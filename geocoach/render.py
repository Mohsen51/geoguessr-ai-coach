"""Markdown on the terminal: glow when installed, rich otherwise."""

from __future__ import annotations

import shutil
import subprocess

from rich.console import Console
from rich.markdown import Markdown


def glow_path() -> str | None:
    return shutil.which("glow")


def show_markdown(text: str, console: Console) -> None:
    """Render markdown with glow (no pager, width 100) or fall back to rich."""
    glow = glow_path()
    if glow:
        done = subprocess.run([glow, "-", "-w", "100"], input=text, text=True, check=False)
        if done.returncode == 0:
            return
    console.print(Markdown(text))
