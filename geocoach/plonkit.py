"""Plonkit guides as the base knowledge source.

Plonkit's API only serves the beginners guide and asks scrapers to read the
__PRELOADED_DATA__ script of each guide page instead, which is what this does,
with on-disk caching and pacing so the site is hit at most once per guide per week.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx

from geocoach import config, metas
from geocoach.store import Store

BASE = "https://www.plonkit.net"
USER_AGENT = "geocoach/0.1 (personal GeoGuessr study tool)"
INDEX_TTL_S = 24 * 3600
GUIDE_TTL_S = 7 * 24 * 3600
PRELOADED_RE = re.compile(r'<script[^>]+id="__PRELOADED_DATA__"[^>]*>(.*?)</script>', re.S)
DOC_PREFIX = "plonkit:"


@dataclass(frozen=True)
class Chunk:
    section: str
    subsection: str
    text: str
    image_url: str | None
    step: int


def cache_dir() -> Path:
    config.ensure_dirs()
    d = config.DATA_DIR / "plonkit"
    (d / "guides").mkdir(parents=True, exist_ok=True)
    (d / "images").mkdir(parents=True, exist_ok=True)
    return d


class PlonkitClient:
    def __init__(self, min_interval_s: float = 2.0, transport=None, retry_base_s: float = 15.0):
        self._client = httpx.Client(
            base_url=BASE,
            headers={"User-Agent": USER_AGENT},
            timeout=60,
            follow_redirects=True,
            transport=transport,
        )
        self._min_interval = min_interval_s
        self._retry_base = retry_base_s
        self._last = 0.0

    def close(self) -> None:
        self._client.close()

    def _get(self, path: str) -> httpx.Response:
        """Paced GET; on 429 wait (Retry-After or exponential) and retry up to 4 times."""
        for attempt in range(5):
            wait = self._min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            resp = self._client.get(path)
            self._last = time.monotonic()
            if resp.status_code != 429:
                resp.raise_for_status()
                return resp
            retry_after = resp.headers.get("Retry-After")
            delay = float(retry_after) if retry_after and retry_after.isdigit() else 0.0
            time.sleep(max(delay, self._retry_base * 2**attempt))
        resp.raise_for_status()
        return resp

    def guide_index(self) -> list[dict]:
        """[{slug, title, code, cat, updatedAt}] for every guide, cached one day."""
        path = cache_dir() / "guides.json"
        if path.exists() and time.time() - path.stat().st_mtime < INDEX_TTL_S:
            return json.loads(path.read_text())
        data = self._get("/api/guides").json().get("data", [])
        path.write_text(json.dumps(data))
        return data

    def guide(self, slug: str, max_age_s: int = GUIDE_TTL_S) -> dict:
        """Public guide object from the page's preloaded data, cached one week."""
        path = cache_dir() / "guides" / f"{slug}.json"
        if path.exists() and time.time() - path.stat().st_mtime < max_age_s:
            return json.loads(path.read_text())
        html = self._get(f"/{slug}").text
        guide = parse_preloaded(html)
        path.write_text(json.dumps(guide))
        return guide

    def image(self, image_url: str, slug: str) -> Path:
        """Download one guide image into the cache, return its local path."""
        name = re.sub(r"[^A-Za-z0-9._-]", "_", image_url.rsplit("/", 1)[-1])
        out = cache_dir() / "images" / slug / name
        if out.exists():
            return out
        out.parent.mkdir(parents=True, exist_ok=True)
        resp = self._get(image_url if image_url.startswith("/") else f"/{image_url}")
        out.write_bytes(resp.content)
        return out


def parse_preloaded(html: str) -> dict:
    m = PRELOADED_RE.search(html)
    if not m:
        raise ValueError("no __PRELOADED_DATA__ in page")
    data = json.loads(m.group(1))
    guide = (data.get("data") or {}).get("public")
    if not guide:
        raise ValueError("guide has no public content")
    guide["communityDocs"] = (data.get("data") or {}).get("communityDocs") or []
    return guide


def guide_chunks(guide: dict) -> list[Chunk]:
    """One chunk per tip, with its section and the last divider as context."""
    chunks: list[Chunk] = []
    for i, step in enumerate(guide.get("steps") or []):
        section = step.get("title") or ""
        sub = ""
        for item in step.get("items") or []:
            kind = item.get("kind")
            if kind == "divider":
                sub = item.get("title") or ""
            elif kind == "tip":
                data = item.get("data") or {}
                text = " ".join(t.strip() for t in data.get("text") or [] if t and t.strip())
                image = (data.get("image") or {}).get("imageUrl")
                if text or image:
                    chunks.append(Chunk(section, sub, text, image, i + 1))
        if step.get("kind") == "map" and step.get("text"):
            chunks.append(Chunk(section, "", str(step["text"]), None, i + 1))
    return chunks


def chunk_text(c: Chunk) -> str:
    head = f"[{c.section}{' > ' + c.subsection if c.subsection else ''}] "
    return head + c.text


def ingest_guide(store: Store, slug: str, code: str, guide: dict) -> int:
    doc = DOC_PREFIX + slug
    with store.conn:
        store.conn.execute("DELETE FROM meta_chunks WHERE doc = ?", (doc,))
        store.conn.execute("DELETE FROM meta_docs WHERE doc = ?", (doc,))
        chunks = guide_chunks(guide)
        store.conn.execute(
            "INSERT INTO meta_docs VALUES (?,?,?,?)",
            (
                doc,
                guide.get("updatedAt") or "",
                len(guide.get("steps") or []),
                int(time.time() * 1000),
            ),
        )
        for c in chunks:
            tags = [code.lower()] + [t for t in metas.tag_countries(c.text) if t != code.lower()]
            store.conn.execute(
                "INSERT INTO meta_chunks(doc, page, country_tags, text, kind) VALUES (?,?,?,?,?)",
                (doc, c.step, " ".join(tags), chunk_text(c), "plonkit"),
            )
    return len(chunks)


def guide_for_country(index: list[dict], country: str) -> dict | None:
    country = country.lower()
    for g in index:
        if (g.get("code") or "").lower() == country or g.get("slug") == country:
            return g
    return None


def sync(
    store: Store,
    client: PlonkitClient,
    countries: list[str] | None = None,
    log: Callable[[str], None] = lambda _: None,
) -> int:
    """Fetch and index guides (all, or the given ISO codes). Returns guides indexed."""
    index = [g for g in client.guide_index() if g.get("code")]
    if countries:
        wanted = {c.lower() for c in countries}
        index = [g for g in index if g["code"].lower() in wanted or g["slug"] in wanted]
    done = 0
    for g in index:
        row = store.conn.execute(
            "SELECT sha256 FROM meta_docs WHERE doc = ?", (DOC_PREFIX + g["slug"],)
        ).fetchone()
        if row and row["sha256"] == (g.get("updatedAt") or ""):
            continue
        try:
            guide = client.guide(g["slug"], max_age_s=0 if row else GUIDE_TTL_S)
        except (httpx.HTTPError, ValueError) as exc:
            log(f"{g['slug']}: {exc}")
            continue
        n = ingest_guide(store, g["slug"], g["code"], guide)
        done += 1
        log(f"indexed plonkit {g['slug']} ({n} tips)")
    return done


def sections_for_country(store: Store, country: str) -> list[dict]:
    """Full plonkit text for a country, grouped by section, from the local index."""
    rows = store.conn.execute(
        "SELECT page, text FROM meta_chunks WHERE kind = 'plonkit' AND doc LIKE ? "
        "AND (' ' || country_tags || ' ') LIKE ? ORDER BY page, id",
        (DOC_PREFIX + "%", f"% {country.lower()} %"),
    ).fetchall()
    out: dict[int, dict] = {}
    for r in rows:
        head, _, body = r["text"].partition("] ")
        title = head.lstrip("[").split(" > ")[0]
        out.setdefault(r["page"], {"section": title, "tips": []})["tips"].append(body)
    return list(out.values())


def images_for_guide(client: PlonkitClient, slug: str, guide: dict, limit: int = 12):
    """Download up to `limit` tip images, return [(caption, local path)]."""
    out = []
    for c in guide_chunks(guide):
        if not c.image_url or len(out) >= limit:
            continue
        try:
            out.append((chunk_text(c)[:200], client.image(c.image_url, slug)))
        except httpx.HTTPError:
            continue
    return out
