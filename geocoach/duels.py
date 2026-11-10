"""Parse a GeoGuessr duel result (game-results API) into plain dataclasses."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

Geocoder = Callable[[float, float], str]
PlaceGeocoder = Callable[[float, float], tuple[str, str]]


class Mode(StrEnum):
    MOVING = "moving"
    NM = "nm"
    NMPZ = "nmpz"


MODE_NAMES = {
    "nomovezoompan": Mode.NMPZ,
    "nmpz": Mode.NMPZ,
    "nomove": Mode.NM,
    "standard": Mode.MOVING,
    "moving": Mode.MOVING,
}


@dataclass(frozen=True)
class Round:
    number: int
    pano_id: str
    lat: float
    lng: float
    country: str
    heading: float
    pitch: float
    zoom: float
    multiplier: float
    healing: bool
    region: str = ""


@dataclass(frozen=True)
class Guess:
    round_number: int
    player_id: str
    is_me: bool
    lat: float
    lng: float
    distance_m: float
    score: int
    time_spent_ms: int | None
    country: str = ""
    region: str = ""


@dataclass(frozen=True)
class RoundResult:
    number: int
    my_health_before: int
    my_health_after: int
    opp_health_before: int
    opp_health_after: int


@dataclass(frozen=True)
class Duel:
    game_id: str
    played_at_ms: int | None
    mode: Mode
    rated: bool
    my_team: str
    won: bool | None
    my_rating: int | None
    opp_rating: int | None
    opp_id: str
    map_name: str
    rounds: list[Round] = field(default_factory=list)
    guesses: list[Guess] = field(default_factory=list)
    round_results: list[RoundResult] = field(default_factory=list)


_HEX44 = re.compile(r"^[0-9a-fA-F]{44}$")


def decode_pano_id(value: str) -> str:
    """Pano ids are usually plain 22-char ids; older payloads hex-encode them."""
    if _HEX44.match(value):
        try:
            return bytes.fromhex(value).decode("ascii")
        except ValueError:
            return value
    return value


def classify_mode(options: dict[str, Any]) -> Mode:
    name = str(options.get("mode") or "").lower()
    if name in MODE_NAMES:
        return MODE_NAMES[name]
    comp = str(options.get("competitiveGameMode") or "").lower()
    if "nmpz" in comp:
        return Mode.NMPZ
    if "nomove" in comp:
        return Mode.NM
    movement = options.get("movementOptions") or {}
    if movement.get("forbidMoving") and movement.get("forbidRotating"):
        return Mode.NMPZ
    if movement.get("forbidMoving"):
        return Mode.NM
    return Mode.MOVING


def to_ms(value: Any) -> int | None:
    """Accept epoch ms, epoch seconds, or ISO 8601 strings (any fraction length)."""
    if value is None:
        return None
    if isinstance(value, int | float):
        return int(value if value > 1e11 else value * 1000)
    text = re.sub(r"(\.\d{6})\d+", r"\1", str(value)).replace("Z", "+00:00")
    try:
        return int(datetime.fromisoformat(text).timestamp() * 1000)
    except ValueError:
        return None


def _rating(player: dict[str, Any]) -> int | None:
    raw = player.get("progression")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return None
    if isinstance(raw, dict) and isinstance(raw.get("rating"), int | float):
        return int(raw["rating"])
    comp = player.get("competitive") or {}
    return comp.get("rating")


def _team_of(teams: list[dict[str, Any]], user_id: str) -> dict[str, Any]:
    for t in teams:
        if any(p.get("playerId") == user_id for p in t.get("players", [])):
            return t
    raise ValueError("user not found in duel teams")


def _health_by_round(team: dict[str, Any]) -> dict[int, tuple[int, int]]:
    return {
        int(rr["roundNumber"]): (int(rr["healthBefore"]), int(rr["healthAfter"]))
        for rr in team.get("roundResults", [])
    }


def parse_duel(
    game: dict[str, Any],
    user_id: str,
    geocoder: Geocoder | None = None,
    place_geocoder: PlaceGeocoder | None = None,
) -> Duel:
    """Parse one duel. place_geocoder (country, region) takes precedence over geocoder."""
    if place_geocoder is not None:
        place = place_geocoder
    elif geocoder is not None:
        place = lambda lat, lng: (geocoder(lat, lng), "")  # noqa: E731
    else:
        place = lambda lat, lng: ("", "")  # noqa: E731
    teams = game["teams"]
    mine = _team_of(teams, user_id)
    others = [t for t in teams if t is not mine]
    opp = others[0] if others else {"players": [], "roundResults": []}
    opp_player = (opp.get("players") or [{}])[0]
    my_player = next(p for p in mine["players"] if p.get("playerId") == user_id)

    rounds = []
    for i, r in enumerate(game.get("rounds", [])):
        p = r.get("panorama") or r
        lat, lng = float(p["lat"]), float(p["lng"])
        cc, region = place(lat, lng)
        rounds.append(
            Round(
                number=int(r.get("roundNumber", i + 1)),
                pano_id=decode_pano_id(str(p.get("panoId") or "")),
                lat=lat,
                lng=lng,
                country=(p.get("countryCode") or cc or "").lower(),
                heading=float(p.get("heading", 0)),
                pitch=float(p.get("pitch", 0)),
                zoom=float(p.get("zoom", 0)),
                multiplier=float(r.get("multiplier", 1)),
                healing=bool(r.get("isHealingRound", False)),
                region=region,
            )
        )

    guesses = []
    for team in teams:
        for player in team.get("players", []):
            for g in player.get("guesses", []):
                lat, lng = float(g["lat"]), float(g["lng"])
                cc, region = place(lat, lng)
                guesses.append(
                    Guess(
                        round_number=int(g["roundNumber"]),
                        player_id=player.get("playerId", ""),
                        is_me=player.get("playerId") == user_id,
                        lat=lat,
                        lng=lng,
                        distance_m=float(g.get("distance", 0)),
                        score=int(g.get("score", 0)),
                        time_spent_ms=g.get("timeSpentMs"),
                        country=(cc or "").lower(),
                        region=region,
                    )
                )

    my_h, opp_h = _health_by_round(mine), _health_by_round(opp)
    results = [RoundResult(n, *my_h[n], *opp_h.get(n, (0, 0))) for n in sorted(my_h)]
    won: bool | None = None
    if results:
        my_final, opp_final = results[-1].my_health_after, results[-1].opp_health_after
        won = my_final > opp_final if my_final != opp_final else None

    options = game.get("options", {})
    return Duel(
        game_id=game["gameId"],
        played_at_ms=to_ms(game.get("finishedAt") or game.get("startedAt")),
        mode=classify_mode(options),
        rated=bool(options.get("isRated", False)),
        my_team=mine.get("name", ""),
        won=won,
        my_rating=_rating(my_player),
        opp_rating=_rating(opp_player),
        opp_id=opp_player.get("playerId", ""),
        map_name=options.get("mapName", ""),
        rounds=rounds,
        guesses=guesses,
        round_results=results,
    )
