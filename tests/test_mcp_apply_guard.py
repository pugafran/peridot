import json
import subprocess
import sys


def send(proc: subprocess.Popen, msg: dict) -> dict:
    proc.stdin.write((json.dumps(msg) + "\n").encode("utf-8"))
    proc.stdin.flush()
    line = proc.stdout.readline().decode("utf-8")
    assert line
    return json.loads(line)


def test_mcp_apply_requires_confirm():
    proc = subprocess.Popen(
        [sys.executable, "-m", "peridot_mcp"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        send(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        resp = send(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "peridot_apply", "arguments": {"package": "x.peridot"}},
            },
        )
        payload = json.loads(resp["result"]["content"][0]["text"])
        assert payload["ok"] is False
        assert "confirm=true" in payload["error"]
    finally:
        proc.kill()
