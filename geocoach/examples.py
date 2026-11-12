"""Street View example locations: plonkit map links and my own rounds, rendered and verified."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx

from geocoach import config, runner
from geocoach.geocode import country_name
from geocoach.panorama import PanoramaError, ViewFetcher
from geocoach.store import Store

LINK_RE = re.compile(
    r"https://(?:maps\.app\.goo\.gl|goo\.gl/maps|www\.google\.com/maps)/[^\s)\]>]+"
)
PANO_RE = re.compile(r"!1s([A-Za-z0-9_-]{22})(?=!|$|\?)")
VIEW_RE = re.compile(r"/@-?[0-9.]+,-?[0-9.]+,\d+a,[0-9.]+y,([0-9.]+)h,([0-9.]+)t")
FOV = 100


@dataclass
class Example:
    tip: str
    url: str
    pano_id: str
    heading: float
    pitch: float
    image: str = ""
    verified: bool | None = None
    note: str = ""


def links_in(text: str) -> list[str]:
    return [m.rstrip(".,") for m in LINK_RE.findall(text)]


def parse_streetview_url(url: str) -> tuple[str, float, float] | None:
    """(pano id, heading, pitch) from a Google Maps Street View URL, None if not a panorama."""
    parts = urlsplit(url)
    q = parse_qs(parts.query)
    if q.get("pano") and len(q["pano"][0]) == 22:
        return q["pano"][0], float(q.get("heading", ["0"])[0]), float(q.get("pitch", ["0"])[0])
    m = PANO_RE.search(url)
    if not m:
        return None
    view = VIEW_RE.search(parts.path)
    heading, tilt = (float(view.group(1)), float(view.group(2))) if view else (0.0, 90.0)
    return m.group(1), heading, 90.0 - tilt


class LinkResolver:
    """Follows Google Maps short links, caching the final URL on disk."""

    def __init__(self, cache_path: Path | None = None, transport=None, min_interval_s=0.5):
        self.cache_path = cache_path or config.DATA_DIR / "examples" / "links.json"
        self.cache: dict[str, str] = {}
        if self.cache_path.exists():
            self.cache = json.loads(self.cache_path.read_text())
        self._client = httpx.Client(
            headers={"User-Agent": "Mozilla/5.0"},
            follow_redirects=True,
            timeout=20,
            transport=transport,
        )
        self._min_interval = min_interval_s
        self._last = 0.0

    def close(self) -> None:
        self._client.close()
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(self.cache, indent=0, sort_keys=True))

    def resolve(self, url: str) -> str:
        if "google.com/maps" in url:
            return url
        if url in self.cache:
            return self.cache[url]
        wait = self._min_interval - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        try:
            final = str(self._client.head(url).url)
        except httpx.HTTPError:
            final = ""
        self._last = time.monotonic()
        self.cache[url] = final
        return final


def examples_from_tips(tips: list[str], resolver: LinkResolver, limit: int = 8) -> list[Example]:
    """One example per Street View link found in the tips, in tip order."""
    out: list[Example] = []
    seen: set[str] = set()
    for tip in tips:
        for url in links_in(tip):
            parsed = parse_streetview_url(resolver.resolve(url))
            if parsed and parsed[0] not in seen:
                seen.add(parsed[0])
                out.append(Example(_plain(tip), url, *parsed))
            if len(out) >= limit:
                return out
    return out


def _plain(tip: str) -> str:
    """Tip text without markdown links and emphasis, for captions."""
    tip = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", tip)
    return re.sub(r"\*\*|__", "", tip).strip()


def own_round_examples(store: Store, country: str, limit: int = 4) -> list[Example]:
    """Rounds I played in this country, most recent first, labelled with their region."""
    rows = store.conn.execute(
        "SELECT r.pano_id, r.heading, r.pitch, r.region, r.lat, r.lng FROM rounds r "
        "JOIN duels d USING (game_id) WHERE r.country = ? AND r.pano_id != '' "
        "ORDER BY d.played_at_ms DESC LIMIT ?",
        (country.lower(), limit),
    ).fetchall()
    name = country_name(country) or country
    return [
        Example(
            f"A round I played in {name}{', ' + r['region'] if r['region'] else ''}",
            f"https://www.google.com/maps/@?api=1&map_action=pano&pano={r['pano_id']}"
            f"&heading={r['heading']:.0f}&pitch={r['pitch']:.0f}",
            r["pano_id"],
            r["heading"] or 0.0,
            r["pitch"] or 0.0,
        )
        for r in rows
    ]


def fetch_images(
    examples: list[Example], fetcher: ViewFetcher, log: Callable[[str], None] = lambda _: None
) -> list[Example]:
    kept = []
    for ex in examples:
        try:
            ex.image = str(
                fetcher.fetch_view(ex.pano_id, round(ex.heading) % 360, round(ex.pitch), FOV)
            )
            kept.append(ex)
        except PanoramaError as exc:
            log(f"example skipped: {exc}")
    return kept


VERIFY_PROMPT = """You check Street View images for a GeoGuessr study page. For each image below,
Read it and decide whether the claim is visible in the picture (the clue itself, not just the
country). Be strict: a claim about a pole, sign, plate or vegetation must be clearly visible.

Answer with JSON only, no prose and no code fence: a list of objects with keys "image" (the
path exactly as given), "ok" (true or false) and "note" (one short sentence on what is seen).

Images:
"""


def parse_verification(text: str) -> dict[str, tuple[bool, str]]:
    body = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    start, end = body.find("["), body.rfind("]")
    if start < 0 or end < 0:
        return {}
    try:
        items = json.loads(body[start : end + 1])
    except json.JSONDecodeError:
        return {}
    return {
        str(i.get("image", "")): (bool(i.get("ok")), str(i.get("note", "")).strip())
        for i in items
        if isinstance(i, dict)
    }


def verify(
    examples: list[Example],
    model: str | None = runner.DIGEST_MODEL,
    run: Callable[..., Path] = runner.run_claude,
) -> list[Example]:
    """Ask Claude to confirm each image shows its claim; keep the confirmed ones."""
    with_images = [e for e in examples if e.image]
    if not with_images:
        return []
    prompt = VERIFY_PROMPT + "\n".join(f"- {e.image}\n  claim: {e.tip}" for e in with_images)
    collected: list[str] = []
    run(prompt, "verify_examples", model, echo=collected.append, use_mcp=False)
    verdicts = parse_verification("".join(collected))
    for e in with_images:
        e.verified, e.note = verdicts.get(e.image, (False, "no verdict"))
    return [e for e in with_images if e.verified]


SEARCH_URL = (
    "https://maps.googleapis.com/$rpc/google.internal.maps.mapsjs.v1.MapsJsInternalService/"
    "SingleImageSearch"
)


def nearest_panorama(
    lat: float, lng: float, radius_m: int = 500, client: httpx.Client | None = None
) -> tuple[str, float, float, float] | None:
    """(pano id, lat, lng, heading) of the official coverage closest to a point, or None."""
    body = [
        ["apiv3", None, None, None, "US"],
        [[None, None, lat, lng], float(radius_m)],
        [None, ["en", "en"], None, None, None, None, None, None, [2], None, [[[2, True, 2]]]],
        [[1, 2, 3, 4, 6, 8, 12], None, None, None, [], []],
    ]
    own = client or httpx.Client(timeout=20)
    try:
        resp = own.post(
            SEARCH_URL,
            content=json.dumps(body),
            headers={"content-type": "application/json+protobuf", "User-Agent": "Mozilla/5.0"},
        )
    finally:
        if client is None:
            own.close()
    if resp.status_code != 200:
        raise PanoramaError(f"panorama search failed: HTTP {resp.status_code}")
    data = resp.json()
    if not data or data[0][0] != 0:
        return None
    msg = data[1]
    try:
        pano_id = msg[1][1]
        place = msg[5][0][1]
        return pano_id, place[0][2], place[0][3], float(place[2][0])
    except (IndexError, TypeError, KeyError):
        return None


PROPOSE_PROMPT = """You are helping build a GeoGuessr study page. No plonkit example exists for the
clue below, so propose up to {n} precise road locations with official Google Street View
coverage where the clue is clearly visible from the road, in {country}. Prefer well-known
roads and towns you are confident about; the coordinates must be on a road, not a landmark.

Answer with JSON only, no prose and no code fence: a list of objects with keys "lat", "lng"
(decimal degrees), "heading" (degrees, direction to look) and "claim" (one sentence naming the
clue and the place, e.g. "white pole sticker on a concrete pole near Sibu, Sarawak").

Clue: {clue}
"""


def parse_proposals(text: str) -> list[dict]:
    body = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    start, end = body.find("["), body.rfind("]")
    if start < 0 or end < 0:
        return []
    try:
        items = json.loads(body[start : end + 1])
    except json.JSONDecodeError:
        return []
    out = []
    for i in items:
        try:
            out.append(
                {
                    "lat": float(i["lat"]),
                    "lng": float(i["lng"]),
                    "heading": float(i.get("heading") or 0),
                    "claim": str(i.get("claim") or "").strip(),
                }
            )
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
    return out


def propose_examples(
    clue: str,
    country: str,
    n: int = 4,
    model: str | None = runner.ANALYSIS_MODEL,
    run: Callable[..., Path] = runner.run_claude,
    search: Callable[..., tuple | None] = nearest_panorama,
    log: Callable[[str], None] = lambda _: None,
) -> list[Example]:
    """Last resort: Claude proposes coordinates, the nearest official panorama is used."""
    prompt = PROPOSE_PROMPT.format(n=n, country=country_name(country) or country, clue=clue)
    collected: list[str] = []
    run(prompt, "propose_examples", model, echo=collected.append, use_mcp=False)
    out: list[Example] = []
    for p in parse_proposals("".join(collected)):
        try:
            found = search(p["lat"], p["lng"])
        except PanoramaError as exc:
            log(str(exc))
            continue
        if not found:
            log(f"no coverage within 500 m of {p['lat']:.4f}, {p['lng']:.4f}")
            continue
        pano_id, lat, lng, _ = found
        url = (
            f"https://www.google.com/maps/@?api=1&map_action=pano&pano={pano_id}"
            f"&heading={p['heading']:.0f}&pitch=0"
        )
        out.append(Example(f"{p['claim']} (proposed by Claude)", url, pano_id, p["heading"], 0.0))
    return out
