"""Recommend training maps from slashP's directory based on weak countries."""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx

from geocoach import config

MAPS_URL = (
    "https://raw.githubusercontent.com/slashpeekbot/slashpeekbot.github.io/main/maps/maps.json"
)
CACHE_TTL_S = 24 * 3600
DEFAULT_CATEGORIES = ("Country", "Region", "Continent", "World")


def map_url(map_id: str) -> str:
    return f"https://www.geoguessr.com/maps/{map_id}"


def load_maps(cache: Path | None = None, ttl_s: int = CACHE_TTL_S, transport=None) -> list[dict]:
    config.ensure_dirs()
    cache = cache or config.DATA_DIR / "slashp_maps.json"
    if cache.exists() and time.time() - cache.stat().st_mtime < ttl_s:
        return json.loads(cache.read_text())
    with httpx.Client(timeout=60, transport=transport) as client:
        resp = client.get(MAPS_URL)
        resp.raise_for_status()
    cache.write_bytes(resp.content)
    return resp.json()


def recommend(
    maps: list[dict],
    weak: dict[str, float],
    min_locations: int = 5000,
    categories: tuple[str, ...] = DEFAULT_CATEGORIES,
    limit: int = 10,
) -> list[dict]:
    """Rank maps by the share of their locations in weak countries, weighted by points lost."""
    weights = {code.lower(): max(w, 1.0) for code, w in weak.items()}
    total_w = sum(weights.values()) or 1.0
    out = []
    for m in maps:
        n = m.get("locationCount") or 0
        if n < min_locations or m.get("category") not in categories:
            continue
        dist = {d["code"].lower(): d["count"] for d in m.get("countryDistribution", [])}
        covered = {c: dist[c] for c in weights if c in dist}
        if not covered:
            continue
        coverage = sum(covered.values()) / n
        score = sum(dist[c] / n * weights[c] / total_w for c in covered)
        out.append(
            {
                "name": m["mapName"],
                "url": map_url(m["mapId"]),
                "category": m["category"],
                "locations": n,
                "likes": m.get("likes") or 0,
                "coverage": round(coverage, 2),
                "score": round(score, 4),
                "weak_countries_covered": sorted(covered, key=lambda c: -covered[c]),
            }
        )
    out.sort(key=lambda d: (-d["score"], -d["likes"]))
    return out[:limit]
