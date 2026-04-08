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
]


def _handle_initialize(params: JSON) -> JSON:
    # Keep this minimal; clients vary.
    client = params.get("clientInfo") or {}
    _ = client.get("name"), client.get("version")

    capabilities = {
        "tools": {"listChanged": False},
    }
    server_info = {
        "name": "peridot-mcp",
        "version": "0.1.0",
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


def _handle_tools_call(params: JSON) -> JSON:
    name = params.get("name")
    arguments = params.get("arguments") or {}

    if name == "peridot_version":
        payload = _tool_peridot_version()
    elif name == "peridot_presets_list":
        payload = _tool_peridot_presets_list()
    elif name == "peridot_init":
        payload = _tool_peridot_init(force=bool(arguments.get("force", False)))
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
