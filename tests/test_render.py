import io
import subprocess

from rich.console import Console

from geocoach import render


def test_show_markdown_uses_glow_when_installed(monkeypatch):
    calls = []
    monkeypatch.setattr(render, "glow_path", lambda: "/opt/glow")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda cmd, **kw: calls.append((cmd, kw)) or subprocess.CompletedProcess(cmd, 0),
    )
    render.show_markdown("# hi", Console(file=io.StringIO()))
    assert calls[0][0] == ["/opt/glow", "-", "-w", "100"] and calls[0][1]["input"] == "# hi"


def test_show_markdown_falls_back_to_rich(monkeypatch):
    monkeypatch.setattr(render, "glow_path", lambda: None)
    console = Console(record=True, file=io.StringIO())
    render.show_markdown("# hi", console)
    assert "hi" in console.export_text()
    monkeypatch.setattr(render, "glow_path", lambda: "/opt/glow")
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1))
    console = Console(record=True, file=io.StringIO())
    render.show_markdown("# again", console)
    assert "again" in console.export_text()
