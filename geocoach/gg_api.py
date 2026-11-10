"""Minimal GeoGuessr client: private feed pagination and duel summaries.

Unofficial endpoints, read-only, authenticated with the user's own _ncfa cookie.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Iterator
from typing import Any

import httpx

BASE = "https://www.geoguessr.com"
FEED_URL = f"{BASE}/api/v4/feed/private"
USER_AGENT = "geocoach/0.1 (personal duel review tool)"
NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S
)


class ApiError(RuntimeError):
    pass


class GeoGuessrClient:
    def __init__(self, ncfa: str, min_interval_s: float = 0.5, transport=None):
        self._client = httpx.Client(
            base_url=BASE,
            cookies={"_ncfa": ncfa},
            headers={"User-Agent": USER_AGENT},
            timeout=20,
            follow_redirects=True,
            transport=transport,
        )
        self._min_interval = min_interval_s
        self._last = 0.0

    def close(self) -> None:
        self._client.close()

    def _get(self, url: str, params: dict[str, str] | None = None) -> httpx.Response:
        for attempt in range(3):
            wait = self._min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            resp = self._client.get(url, params=params)
            self._last = time.monotonic()
            if resp.status_code == 429:
                time.sleep(2 * (attempt + 1))
                continue
            if resp.status_code in (401, 403):
                raise ApiError("GeoGuessr rejected the cookie (expired?). Refresh _ncfa.")
            resp.raise_for_status()
            return resp
        raise ApiError("rate limited three times in a row")

    def iter_feed_items(self) -> Iterator[dict[str, Any]]:
        """Yield flattened feed payload items, newest first, across pages."""
        token: str | None = None
        while True:
            params = {"paginationToken": token} if token else None
            data = self._get(FEED_URL, params).json()
            for entry in data.get("entries", []):
                yield from _flatten_payload(entry.get("payload"))
            token = data.get("paginationToken")
            if not token or not data.get("entries"):
                return

    def iter_duel_ids(self) -> Iterator[str]:
        seen: set[str] = set()
        for item in self.iter_feed_items():
            if item.get("gameMode") != "Duels":
                continue
            game_id = item.get("gameId")
            if game_id and game_id not in seen:
                seen.add(game_id)
                yield game_id

    def duel_summary(self, game_id: str) -> dict[str, Any]:
        """Return pageProps of the duel summary page."""
        html = self._get(f"/duels/{game_id}/summary").text
        return parse_next_data(html)["props"]["pageProps"]


def _flatten_payload(payload: Any) -> Iterator[dict[str, Any]]:
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return
    if isinstance(payload, dict):
        yield payload
    elif isinstance(payload, list):
        for item in payload:
            inner = item.get("payload", item) if isinstance(item, dict) else item
            yield from _flatten_payload(inner)


def parse_next_data(html: str) -> dict[str, Any]:
    m = NEXT_DATA_RE.search(html)
    if not m:
        raise ApiError("no __NEXT_DATA__ in page (login page or layout change)")
    return json.loads(m.group(1))
