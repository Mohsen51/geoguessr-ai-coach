"""Paths and secrets. The _ncfa cookie is read from env, .env or the macOS keychain."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
METAS_DIR = ROOT / "metas"
DB_PATH = DATA_DIR / "geocoach.db"
PANOS_DIR = DATA_DIR / "panos"
PAGES_DIR = DATA_DIR / "pages"
REPORTS_DIR = DATA_DIR / "reports"

KEYCHAIN_SERVICE = "geocoach"
KEYCHAIN_ACCOUNT = "ncfa"


class MissingCookieError(RuntimeError):
    pass


def ensure_dirs() -> None:
    for d in (DATA_DIR, PANOS_DIR, PAGES_DIR, REPORTS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def _keychain_cookie() -> str | None:
    cmd = [
        "security",
        "find-generic-password",
        "-s",
        KEYCHAIN_SERVICE,
        "-a",
        KEYCHAIN_ACCOUNT,
        "-w",
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = out.stdout.strip()
    return value if out.returncode == 0 and value else None


def get_cookie() -> str:
    load_dotenv(ROOT / ".env")
    value = os.environ.get("GEOGUESSR_NCFA", "").strip() or _keychain_cookie()
    if not value:
        raise MissingCookieError(
            "No _ncfa cookie found. Put GEOGUESSR_NCFA=... in .env or run: "
            "security add-generic-password -s geocoach -a ncfa -w '<cookie>'"
        )
    return value
