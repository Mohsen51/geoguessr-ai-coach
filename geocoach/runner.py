"""Run headless Claude Code with the geocoach MCP server attached."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from geocoach import config

ALLOWED_TOOLS = ("Read", "mcp__geocoach__*")


def write_mcp_config(path: Path | None = None) -> Path:
    config.ensure_dirs()
    path = path or config.DATA_DIR / "mcp.json"
    cfg = {
        "mcpServers": {
            "geocoach": {
                "command": "uv",
                "args": ["run", "--directory", str(config.ROOT), "geocoach-mcp"],
            }
        }
    }
    path.write_text(json.dumps(cfg, indent=2))
    return path


def build_command(mcp_config: Path, model: str | None = None) -> list[str]:
    cmd = [
        "claude",
        "-p",
        "--output-format",
        "text",
        "--mcp-config",
        str(mcp_config),
        "--strict-mcp-config",
        "--permission-mode",
        "dontAsk",
        "--allowedTools",
        *ALLOWED_TOOLS,
        "--add-dir",
        str(config.DATA_DIR),
    ]
    if model:
        cmd += ["--model", model]
    return cmd


def run_claude(
    prompt: str,
    report_name: str,
    model: str | None = None,
    echo: Callable[[str], None] = lambda s: sys.stdout.write(s),
    command: list[str] | None = None,
) -> Path:
    """Stream Claude's answer to the terminal and save it under data/reports."""
    config.ensure_dirs()
    cmd = command or build_command(write_mcp_config(), model)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    report = config.REPORTS_DIR / f"{stamp}_{report_name}.md"
    proc = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    assert proc.stdin and proc.stdout and proc.stderr
    proc.stdin.write(prompt)
    proc.stdin.close()
    chunks: list[str] = []
    for line in proc.stdout:
        echo(line)
        chunks.append(line)
    proc.wait()
    err = proc.stderr.read()
    if proc.returncode != 0:
        raise RuntimeError(f"claude exited with {proc.returncode}: {err.strip()[:500]}")
    report.write_text(f"# {report_name}\n\nPrompt:\n\n{prompt}\n\n---\n\n{''.join(chunks)}")
    return report
