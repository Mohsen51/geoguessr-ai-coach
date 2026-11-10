"""GeoGuessr's own clue cards per country, cached on disk."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path

from geocoach import config

TTL_S = 7 * 24 * 3600


def cached_clues(fetch: Callable[[str], list[dict]], country: str) -> list[dict]:
    config.ensure_dirs()
    cache_dir = config.DATA_DIR / "clues"
    cache_dir.mkdir(exist_ok=True)
    path: Path = cache_dir / f"{country.lower()}.json"
    if path.exists() and time.time() - path.stat().st_mtime < TTL_S:
        return json.loads(path.read_text())
    try:
        clues = fetch(country)
    except Exception:
        return json.loads(path.read_text()) if path.exists() else []
    path.write_text(json.dumps(clues))
    return clues


def format_clues(clues: list[dict], limit: int = 12) -> list[str]:
    out = []
    for c in clues[:limit]:
        regions = ", ".join(r.get("name", str(r)) for r in c.get("regions") or [])
        suffix = f" (regions: {regions})" if regions else ""
        out.append(f"{c.get('type', '')}: {c.get('title', '')}. {c.get('description', '')}{suffix}")
    return out
