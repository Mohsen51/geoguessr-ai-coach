"""Fetch oriented Street View views for a round via Google's thumbnail endpoint.

Undocumented endpoint, no API key. It refuses non-browser clients, so a fixed
browser-style user agent is sent (the user's explicit choice). Low volume only.
"""

from __future__ import annotations

import time
from pathlib import Path

import httpx

from geocoach import config
from geocoach.duels import Mode

THUMB_URL = "https://streetviewpixels-pa.clients6.google.com/v1/thumbnail"
USER_AGENT = "Mozilla/5.0"
MAX_W, MAX_H = 1024, 768
FOV_NMPZ = 100
FOV_NM = 120


class PanoramaError(RuntimeError):
    pass


def headings_for(mode: Mode | str, heading: float, full: bool = False) -> list[tuple[int, int]]:
    """(yaw, fov) pairs to fetch: one for NMPZ, two for NM, three with full=True."""
    h = round(heading) % 360
    if full:
        return [((h + off) % 360, FOV_NM) for off in (0, 120, 240)]
    if Mode(mode) == Mode.NMPZ:
        return [(h, FOV_NMPZ)]
    return [(h, FOV_NM), ((h + 180) % 360, FOV_NM)]


def view_path(pano_id: str, yaw: int, pitch: int, fov: int, w: int = MAX_W, h: int = MAX_H):
    return config.PANOS_DIR / f"{pano_id}_y{yaw:03d}_p{pitch:+03d}_f{fov}_{w}x{h}.jpg"


class ViewFetcher:
    def __init__(self, min_interval_s: float = 0.3, transport=None):
        self._client = httpx.Client(
            headers={"User-Agent": USER_AGENT}, timeout=30, transport=transport
        )
        self._min_interval = min_interval_s
        self._last = 0.0

    def close(self) -> None:
        self._client.close()

    def fetch_view(
        self, pano_id: str, yaw: int, pitch: int = 0, fov: int = FOV_NMPZ, w=MAX_W, h=MAX_H
    ) -> Path:
        config.ensure_dirs()
        out = view_path(pano_id, yaw, pitch, fov, w, h)
        if out.exists():
            return out
        wait = self._min_interval - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        params = {
            "cb_client": "maps_sv.tactile",
            "panoid": pano_id,
            "w": w,
            "h": h,
            "yaw": yaw,
            "pitch": pitch,
            "thumbfov": fov,
        }
        resp = self._client.get(THUMB_URL, params=params)
        self._last = time.monotonic()
        if resp.status_code != 200 or not resp.headers.get("content-type", "").startswith("image"):
            raise PanoramaError(f"thumbnail fetch failed for {pano_id}: HTTP {resp.status_code}")
        out.write_bytes(resp.content)
        return out

    def views_for_round(
        self, pano_id: str, heading: float, mode: Mode | str, pitch: float = 0, full=False
    ) -> list[Path]:
        return [
            self.fetch_view(pano_id, yaw, round(pitch), fov)
            for yaw, fov in headings_for(mode, heading, full)
        ]
