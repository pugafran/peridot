import json
import subprocess
import sys


def send(proc: subprocess.Popen, msg: dict) -> dict:
    proc.stdin.write((json.dumps(msg) + "\n").encode("utf-8"))
    proc.stdin.flush()
    line = proc.stdout.readline().decode("utf-8")
    assert line
    return json.loads(line)


def test_mcp_initialize_and_tools_list_and_version():
    proc = subprocess.Popen(
        [sys.executable, "-m", "peridot_mcp"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        resp = send(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"clientInfo": {"name": "pytest", "version": "0"}},
            },
        )
        assert resp["result"]["serverInfo"]["name"] == "peridot-mcp"

        tools = send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        names = {t["name"] for t in tools["result"]["tools"]}
        assert "peridot_version" in names
        assert "peridot_init" in names

        ver = send(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "peridot_version", "arguments": {}},
            },
        )
        content = ver["result"]["content"][0]["text"]
        payload = json.loads(content)
        assert "version" in payload
    finally:
        proc.kill()
