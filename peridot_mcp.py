#!/usr/bin/env python3

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import traceback
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from typing import Any


# Minimal MCP (Model Context Protocol) server over stdio.
#
# We implement a small subset of the JSON-RPC surface that most MCP clients use:
# - initialize
# - tools/list
# - tools/call
#
# The goal is to expose Peridot as a set of high-level tools so an AI agent can
# drive Peridot without the user learning the CLI.


JSON = dict[str, Any]


@dataclass
class Tool:
    name: str
    description: str
    input_schema: JSON


def _jsonrpc_result(id_: Any, result: Any) -> JSON:
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def _jsonrpc_error(id_: Any, code: int, message: str, data: Any | None = None) -> JSON:
    err: JSON = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": id_, "error": err}


def _readline() -> str | None:
    line = sys.stdin.readline()
    if not line:
        return None
    return line


def _write(obj: JSON) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _capture_peridot_main(argv: list[str]) -> tuple[int, str, str]:
    """Run peridot.main(argv) in-process and capture output.

    We prefer in-process execution for speed and portability.
    """

    try:
        import peridot

        out = io.StringIO()
        err = io.StringIO()
        code = 0
        with redirect_stdout(out), redirect_stderr(err):
            try:
                peridot.main(argv)
            except SystemExit as exc:
                code = int(exc.code or 0)
        return code, out.getvalue(), err.getvalue()
    except Exception:
        return 1, "", traceback.format_exc()


def _tool_peridot_version() -> JSON:
    import peridot

    return {
        "version": peridot.APP_VERSION,
        "package_version": getattr(peridot, "PACKAGE_VERSION", None),
    }


def _tool_peridot_presets_list() -> JSON:
    import peridot

    presets = []
    for name, p in peridot.PRESET_LIBRARY.items():
        presets.append(
            {
                "name": name,
                "platform": p.get("platform"),
                "shell": p.get("shell"),
                "description": p.get("description"),
                "paths": list(p.get("paths") or []),
                "tags": list(p.get("tags") or []),
            }
        )
    presets.sort(key=lambda x: x["name"])
    return {"presets": presets}


def _tool_peridot_init(force: bool = False) -> JSON:
    code, out, err = _capture_peridot_main(["init", "--force"] if force else ["init"])
    return {"ok": code == 0, "exitCode": code, "stdout": out, "stderr": err}


TOOLS: list[Tool] = [
    Tool(
        name="peridot_version",
        description="Return Peridot version information.",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    ),
    Tool(
        name="peridot_presets_list",
        description="List available Peridot presets (platform/shell/paths).",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    ),
    Tool(
        name="peridot_init",
        description="Initialize Peridot local state (key + settings). Safe to run multiple times.",
        input_schema={
            "type": "object",
            "properties": {"force": {"type": "boolean", "default": False}},
            "additionalProperties": False,
        },
    ),
    Tool(
        name="peridot_pack",
        description="Create a .peridot bundle. Defaults are safe and script-friendly.",
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "paths": {"type": "array", "items": {"type": "string"}},
                "output": {"type": "string"},
                "preset": {"type": "string"},
                "platform": {"type": "string"},
                "shell": {"type": "string"},
                "arch": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "exclude": {"type": "array", "items": {"type": "string"}},
                "compression_level": {"type": "integer", "minimum": 0, "maximum": 9},
                "jobs": {"type": "integer", "minimum": 1},
                "yes": {"type": "boolean", "default": True},
            },
            "additionalProperties": False,
        },
    ),
    Tool(
        name="peridot_inspect",
        description="Inspect a .peridot bundle (card + optional file list/json).",
        input_schema={
            "type": "object",
            "properties": {
                "package": {"type": "string"},
                "files": {"type": "boolean", "default": True},
                "all": {"type": "boolean", "default": False},
                "json": {"type": "boolean", "default": False},
            },
            "required": ["package"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="peridot_manifest",
        description="Print manifest for a bundle.",
        input_schema={
            "type": "object",
            "properties": {"package": {"type": "string"}},
            "required": ["package"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="peridot_diff",
        description="Diff a bundle against a target directory.",
        input_schema={
            "type": "object",
            "properties": {
                "package": {"type": "string"},
                "target": {"type": "string"},
                "no_hash": {"type": "boolean", "default": False},
                "json": {"type": "boolean", "default": False},
            },
            "required": ["package"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="peridot_verify",
        description="Verify a bundle integrity (optionally deep).",
        input_schema={
            "type": "object",
            "properties": {
                "package": {"type": "string"},
                "deep": {"type": "boolean", "default": True},
                "json": {"type": "boolean", "default": False},
            },
            "required": ["package"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="peridot_bench",
        description="Run pack benchmark.",
        input_schema={
            "type": "object",
            "properties": {
                "files": {"type": "integer", "minimum": 1, "default": 200},
                "size_kb": {"type": "integer", "minimum": 1, "default": 4},
                "runs": {"type": "integer", "minimum": 1, "default": 1},
                "levels": {"type": "string", "default": "0,1,3"},
                "jobs": {"type": "integer", "minimum": 1},
                "json": {"type": "boolean", "default": False},
                "out": {"type": "string"},
            },
            "additionalProperties": False,
        },
    ),
    Tool(
        name="peridot_apply_dry_run",
        description="Dry-run apply: shows what would change without writing.",
        input_schema={
            "type": "object",
            "properties": {
                "package": {"type": "string"},
                "target": {"type": "string"},
                "ignore_platform": {"type": "boolean", "default": False},
                "select": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["package"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="peridot_apply",
        description="Apply a bundle. Requires explicit confirmation and an apply_token from dry-run.",
        input_schema={
            "type": "object",
            "properties": {
                "package": {"type": "string"},
                "target": {"type": "string"},
                "backup_dir": {"type": "string"},
                "ignore_platform": {"type": "boolean", "default": False},
                "select": {"type": "array", "items": {"type": "string"}},
                "apply_token": {"type": "string"},
                "confirm": {"type": "boolean", "default": False},
            },
            "required": ["package"],
            "additionalProperties": False,
        },
    ),
]


def _handle_initialize(params: JSON) -> JSON:
    # Keep this minimal; clients vary.
    client = params.get("clientInfo") or {}
    _ = client.get("name"), client.get("version")

    capabilities = {
        "tools": {"listChanged": False},
    }

    # The description helps MCP hosts/agents understand what this server is for.
    server_info = {
        "name": "peridot-mcp",
        "version": "0.1.0",
        "description": (
            "Peridot MCP exposes Peridot as AI-callable tools to package, inspect, verify, "
            "diff and (optionally) apply encrypted + compressed dotfiles/config bundles "
            "across systems safely."
        ),
    }
    return {"capabilities": capabilities, "serverInfo": server_info}


def _handle_tools_list() -> JSON:
    return {
        "tools": [
            {
                "name": t.name,
                "description": t.description,
                "inputSchema": t.input_schema,
            }
            for t in TOOLS
        ]
    }


def _tool_run_cli(argv: list[str]) -> JSON:
    code, out, err = _capture_peridot_main(argv)
    payload: JSON = {"ok": code == 0, "exitCode": code, "stdout": out, "stderr": err, "argv": argv}

    # Best-effort: if stdout is pure JSON, parse it for structured consumption.
    out_stripped = out.strip()
    if out_stripped.startswith("{") or out_stripped.startswith("["):
        try:
            payload["data"] = json.loads(out_stripped)
        except Exception:
            pass

    return payload


def _handle_tools_call(params: JSON) -> JSON:
    name = params.get("name")
    arguments = params.get("arguments") or {}

    if name == "peridot_version":
        payload = _tool_peridot_version()
    elif name == "peridot_presets_list":
        payload = _tool_peridot_presets_list()
    elif name == "peridot_init":
        payload = _tool_peridot_init(force=bool(arguments.get("force", False)))

    elif name == "peridot_pack":
        # NOTE: argparse in Peridot expects pack paths before optional flags.
        argv = ["pack"]
        if arguments.get("name"):
            argv.append(str(arguments["name"]))
        for p in arguments.get("paths") or []:
            argv.append(str(p))
        argv.append("--json")
        if arguments.get("preset"):
            argv.extend(["--preset", str(arguments["preset"])])
        if arguments.get("output"):
            argv.extend(["--output", str(arguments["output"])])
        if arguments.get("platform"):
            argv.extend(["--platform", str(arguments["platform"])])
        if arguments.get("shell"):
            argv.extend(["--shell", str(arguments["shell"])])
        if arguments.get("arch"):
            argv.extend(["--arch", str(arguments["arch"])])
        for tag in arguments.get("tags") or []:
            argv.extend(["--tag", str(tag)])
        for ex in arguments.get("exclude") or []:
            argv.extend(["--exclude", str(ex)])
        if arguments.get("compression_level") is not None:
            argv.extend(["--compression-level", str(int(arguments["compression_level"]))])
        if arguments.get("jobs") is not None:
            argv.extend(["--jobs", str(int(arguments["jobs"]))])
        if arguments.get("yes", True):
            argv.append("--yes")
        payload = _tool_run_cli(argv)

    elif name == "peridot_inspect":
        # Prefer JSON for machine consumption.
        argv = ["inspect", str(arguments["package"]), "--json"]
        payload = _tool_run_cli(argv)

    elif name == "peridot_manifest":
        payload = _tool_run_cli(["manifest", str(arguments["package"])])

    elif name == "peridot_diff":
        argv = ["diff", str(arguments["package"]), "--json"]
        if arguments.get("target"):
            argv.extend(["--target", str(arguments["target"])])
        if arguments.get("no_hash", False):
            argv.append("--no-hash")
        payload = _tool_run_cli(argv)

    elif name == "peridot_verify":
        argv = ["verify", str(arguments["package"]), "--json"]
        if arguments.get("deep", True):
            argv.append("--deep")
        payload = _tool_run_cli(argv)

    elif name == "peridot_bench":
        argv = [
            "bench",
            "--files",
            str(int(arguments.get("files", 200))),
            "--size-kb",
            str(int(arguments.get("size_kb", 4))),
            "--runs",
            str(int(arguments.get("runs", 1))),
            "--levels",
            str(arguments.get("levels", "0,1,3")),
            "--json",
        ]
        if arguments.get("jobs") is not None:
            argv.extend(["--jobs", str(int(arguments["jobs"]))])
        if arguments.get("out"):
            argv.extend(["--out", str(arguments["out"])])
        payload = _tool_run_cli(argv)

    elif name == "peridot_apply_dry_run":
        argv = ["apply", str(arguments["package"]), "--dry-run", "--json"]
        if arguments.get("target"):
            argv.extend(["--target", str(arguments["target"])])
        if arguments.get("ignore_platform", False):
            argv.append("--ignore-platform")
        for p in arguments.get("select") or []:
            argv.extend(["--select", str(p)])
        argv.append("--yes")
        payload = _tool_run_cli(argv)

    elif name == "peridot_apply":
        if not bool(arguments.get("confirm", False)):
            payload = {
                "ok": False,
                "exitCode": 1,
                "error": "Refusing to apply without confirm=true. Use peridot_apply_dry_run first.",
            }
        elif not str(arguments.get("apply_token") or ""):
            payload = {
                "ok": False,
                "exitCode": 1,
                "error": "Missing apply_token. Call peridot_apply_dry_run and pass its apply_token.",
            }
        else:
            argv = [
                "apply",
                str(arguments["package"]),
                "--json",
                "--apply-token",
                str(arguments.get("apply_token")),
            ]
            if arguments.get("target"):
                argv.extend(["--target", str(arguments["target"])])
            if arguments.get("backup_dir"):
                argv.extend(["--backup-dir", str(arguments["backup_dir"])])
            if arguments.get("ignore_platform", False):
                argv.append("--ignore-platform")
            for p in arguments.get("select") or []:
                argv.extend(["--select", str(p)])
            argv.append("--yes")
            payload = _tool_run_cli(argv)

    else:
        raise ValueError(f"Unknown tool: {name}")

    # MCP tool call result: an array of content blocks.
    return {
        "content": [
            {"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)}
        ]
    }


def main() -> None:
    # Stdio server loop.
    while True:
        line = _readline()
        if line is None:
            return
        line = line.strip()
        if not line:
            continue

        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            # Ignore junk.
            continue

        id_ = req.get("id")
        method = req.get("method")
        params = req.get("params") or {}

        try:
            if method == "initialize":
                result = _handle_initialize(params)
                _write(_jsonrpc_result(id_, result))
            elif method == "tools/list":
                _write(_jsonrpc_result(id_, _handle_tools_list()))
            elif method == "tools/call":
                _write(_jsonrpc_result(id_, _handle_tools_call(params)))
            else:
                _write(_jsonrpc_error(id_, -32601, f"Method not found: {method}"))
        except Exception as exc:
            _write(
                _jsonrpc_error(
                    id_,
                    -32603,
                    f"Internal error: {exc}",
                    data={"traceback": traceback.format_exc()},
                )
            )


if __name__ == "__main__":
    main()
