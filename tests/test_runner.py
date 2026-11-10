import json

import pytest

from geocoach import config, runner


@pytest.fixture(autouse=True)
def tmp_dirs(tmp_path, monkeypatch):
    for name in ("DATA_DIR", "PANOS_DIR", "PAGES_DIR", "REPORTS_DIR"):
        monkeypatch.setattr(config, name, tmp_path / name.lower())


def test_write_mcp_config_points_at_repo():
    path = runner.write_mcp_config()
    cfg = json.loads(path.read_text())
    server = cfg["mcpServers"]["geocoach"]
    assert server["command"] == "uv"
    assert server["args"] == ["run", "--directory", str(config.ROOT), "geocoach-mcp"]


def test_build_command_flags(tmp_path):
    cmd = runner.build_command(tmp_path / "mcp.json", model="opus")
    assert cmd[:3] == ["claude", "-p", "--output-format"]
    assert "--strict-mcp-config" in cmd
    assert cmd[cmd.index("--allowedTools") + 1 : cmd.index("--allowedTools") + 3] == [
        "Read",
        "mcp__geocoach__*",
    ]
    assert cmd[-2:] == ["--model", "opus"]


def test_run_claude_streams_and_saves_report():
    seen = []
    report = runner.run_claude("hello prompt", "unit", command=["cat"], echo=seen.append)
    assert "".join(seen) == "hello prompt"
    text = report.read_text()
    assert text.startswith("# unit") and text.endswith("hello prompt")
    assert report.parent == config.REPORTS_DIR


def test_run_claude_raises_on_failure():
    with pytest.raises(RuntimeError, match="exited with 3"):
        runner.run_claude("x", "fail", command=["sh", "-c", "echo boom >&2; exit 3"])


def test_build_command_without_mcp(tmp_path):
    cmd = runner.build_command(None)
    assert "--mcp-config" not in cmd and "--strict-mcp-config" not in cmd
    assert cmd[cmd.index("--allowedTools") + 1] == "Read"
    assert "mcp__geocoach__*" not in cmd
