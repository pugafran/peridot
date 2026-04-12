import peridot_mcp


def test_tool_run_cli_parses_json_from_last_line(monkeypatch):
    def fake_capture(argv):
        return (
            0,
            "INFO: something before JSON\n{\"ok\": true, \"n\": 1}\n",
            "",
        )

    monkeypatch.setattr(peridot_mcp, "_capture_peridot_main", fake_capture)

    payload = peridot_mcp._tool_run_cli(["version", "--json"])
    assert payload["ok"] is True
    assert payload["data"] == {"ok": True, "n": 1}
