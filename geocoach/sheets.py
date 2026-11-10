"""Deterministic encyclopedia sheets built from cached plonkit guides.

One markdown file per country under encyclopedia/, committed to the repo by the
sheets workflow. Content is plonkit's, licensed CC BY-NC-SA 4.0 (see the folder README).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from geocoach import config, plonkit

SHEETS_DIR = config.ROOT / "encyclopedia"
LICENSE_LINE = (
    "Source: [Plonk It](https://www.plonkit.net/{slug}), licensed "
    "[CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/). "
    "Text only; open the page for the pictures."
)
IMAGE_MD_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
REGIONAL_RE = re.compile(r"region|province|state|area|subdivision", re.I)


def render_sheet(guide: dict) -> str:
    """Markdown sheet for one guide: every section, divider and tip, no images."""
    slug, title = guide.get("slug", ""), guide.get("title", "")
    code = (guide.get("code") or "").lower()
    updated = (guide.get("updatedAt") or "")[:10]
    lines = [f"# {title} ({code})", "", LICENSE_LINE.format(slug=slug)]
    if updated:
        lines.append(f"Guide updated on plonkit: {updated}.")
    for note in guide.get("headerNotes") or []:
        lines += ["", f"> {note}"]
    steps = list(guide.get("steps") or [])
    steps.sort(key=lambda st: not REGIONAL_RE.search(st.get("title") or ""))
    for step in steps:
        section = step.get("title") or "Section"
        if step.get("kind") == "map":
            if step.get("text"):
                lines += ["", f"## {section}", "", str(step["text"]).strip()]
            continue
        items = step.get("items") or []
        body: list[str] = []
        for item in items:
            kind = item.get("kind")
            if kind == "divider" and item.get("title"):
                body += ["", f"### {item['title']}", ""]
            elif kind == "tip":
                text = " ".join(
                    t.strip() for t in (item.get("data") or {}).get("text") or [] if t and t.strip()
                )
                text = IMAGE_MD_RE.sub("", text).strip()
                if text:
                    body.append(f"- {text}")
        if body:
            lines += ["", f"## {section}", ""] + body
    docs = guide.get("communityDocs") or []
    if docs:
        lines += ["", "## Community documents", ""] + [f"- {d}" for d in docs]
    return "\n".join(lines).rstrip() + "\n"


def sheet_path(code: str, out_dir: Path | None = None) -> Path:
    return (out_dir or SHEETS_DIR) / f"{code.lower()}.md"


def build_all(out_dir: Path | None = None, guides_dir: Path | None = None) -> list[Path]:
    """Render every cached guide that has a country code. Returns the written paths."""
    out_dir = out_dir or SHEETS_DIR
    guides_dir = guides_dir or plonkit.cache_dir() / "guides"
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for path in sorted(guides_dir.glob("*.json")):
        guide = json.loads(path.read_text())
        code = (guide.get("code") or "").lower()
        if not code:
            continue
        target = sheet_path(code, out_dir)
        content = render_sheet(guide)
        if not target.exists() or target.read_text() != content:
            target.write_text(content)
        written.append(target)
    return written


def read_sheet(code: str, out_dir: Path | None = None) -> str | None:
    path = sheet_path(code, out_dir)
    return path.read_text() if path.exists() else None


def available_codes(out_dir: Path | None = None) -> list[str]:
    out_dir = out_dir or SHEETS_DIR
    if not out_dir.exists():
        return []
    return sorted(p.stem for p in out_dir.glob("*.md") if p.stem != "README")
