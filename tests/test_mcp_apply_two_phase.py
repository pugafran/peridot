import json
import subprocess
import sys
from pathlib import Path

import peridot


def send(proc: subprocess.Popen, msg: dict) -> dict:
    proc.stdin.write((json.dumps(msg) + "\n").encode("utf-8"))
    proc.stdin.flush()
    line = proc.stdout.readline().decode("utf-8")
    assert line
    return json.loads(line)


def test_mcp_apply_two_phase(tmp_path: Path):
    # Ensure key exists
    peridot.main(["init", "--force"])

    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.mkdir()
    dst.mkdir()

    (src / "hello.txt").write_text("hello", encoding="utf-8")

    bundle = tmp_path / "bundle.peridot"
    peridot.main(["pack", "test-bundle", str(src / "hello.txt"), "--yes", "--output", str(bundle)])
    manifest = peridot.manifest_from_zip(bundle)
    rel_path = manifest["files"][0]["path"]

    proc = subprocess.Popen(
        [sys.executable, "-m", "peridot_mcp"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        send(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})

        # Dry-run: get token
        dry = send(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "peridot_apply_dry_run",
                    "arguments": {"package": str(bundle), "target": str(dst)},
                },
            },
        )
        dry_payload = json.loads(dry["result"]["content"][0]["text"])
        assert dry_payload["ok"] is True
        token = dry_payload["data"]["apply_token"]
        assert isinstance(token, str) and len(token) > 10

        # Apply without token should be rejected by MCP wrapper.
        bad = send(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "peridot_apply",
                    "arguments": {"package": str(bundle), "target": str(dst), "confirm": True},
                },
            },
        )
        bad_payload = json.loads(bad["result"]["content"][0]["text"])
        assert bad_payload["ok"] is False
        assert "apply_token" in bad_payload["error"]

        # Apply with token should write the file.
        ok = send(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "peridot_apply",
                    "arguments": {
                        "package": str(bundle),
                        "target": str(dst),
                        "confirm": True,
                        "apply_token": token,
                    },
                },
            },
        )
        ok_payload = json.loads(ok["result"]["content"][0]["text"])
        assert ok_payload["ok"] is True
        assert ok_payload["data"]["restored"] == 1

        written = dst / rel_path
        assert written.exists()
        assert written.read_text(encoding="utf-8") == "hello"

    finally:
        proc.kill()
