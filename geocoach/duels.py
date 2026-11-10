"""Parse a GeoGuessr duel summary (Next.js pageProps) into plain dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class Mode(StrEnum):
    MOVING = "moving"
    NM = "nm"
    NMPZ = "nmpz"


@dataclass(frozen=True)
class Round:
    number: int
    pano_id: str
    pano_hex: str
    lat: float
    lng: float
    country: str
    heading: float
    pitch: float
    zoom: float
    multiplier: float
    damage_multiplier: float
    healing: bool
    start_ms: int | None
    end_ms: int | None


@dataclass(frozen=True)
class Guess:
    round_number: int
    player_id: str
    is_me: bool
    lat: float
    lng: float
    distance_m: float
    score: int
    created_ms: int | None


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
    opp_nick: str
    rounds: list[Round] = field(default_factory=list)
    guesses: list[Guess] = field(default_factory=list)
    round_results: list[RoundResult] = field(default_factory=list)


def decode_pano_id(hex_id: str) -> str:
    """GeoGuessr stores Google pano ids hex-encoded; return the ASCII id."""
    try:
        return bytes.fromhex(hex_id).decode("ascii")
    except ValueError:
        return hex_id


def classify_mode(movement: dict[str, Any]) -> Mode:
    moving = movement.get("forbidMoving", False)
    zooming = movement.get("forbidZooming", False)
    rotating = movement.get("forbidRotating", False)
    if moving and zooming and rotating:
        return Mode.NMPZ
    if moving and not rotating:
        return Mode.NM
    return Mode.MOVING


def to_ms(value: Any) -> int | None:
    """Accept epoch ms, epoch seconds, or ISO 8601 strings."""
    if value is None:
        return None
    if isinstance(value, int | float):
        return int(value if value > 1e11 else value * 1000)
    try:
        return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None


def _parse_rounds(game: dict[str, Any]) -> list[Round]:
    rounds = []
    for r in game.get("rounds", []):
        p = r.get("panorama", {})
        rounds.append(
            Round(
                number=int(r["roundNumber"]),
                pano_id=decode_pano_id(p.get("panoId", "")),
                pano_hex=p.get("panoId", ""),
                lat=float(p["lat"]),
                lng=float(p["lng"]),
                country=(p.get("countryCode") or "").lower(),
                heading=float(p.get("heading", 0)),
                pitch=float(p.get("pitch", 0)),
                zoom=float(p.get("zoom", 0)),
                multiplier=float(r.get("multiplier", 1)),
                damage_multiplier=float(r.get("damageMultiplier", 1)),
                healing=bool(r.get("isHealingRound", False)),
                start_ms=to_ms(r.get("startTime")),
                end_ms=to_ms(r.get("endTime")),
            )
        )
    return rounds


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


def parse_duel(page_props: dict[str, Any]) -> Duel:
    game = page_props["game"]
    user_id = page_props["userId"]
    teams = game["teams"]
    mine = _team_of(teams, user_id)
    others = [t for t in teams if t is not mine]
    opp = others[0] if others else {"players": [], "roundResults": []}
    opp_player = (opp.get("players") or [{}])[0]
    my_player = next(p for p in mine["players"] if p.get("playerId") == user_id)

    guesses = []
    for team in teams:
        for player in team.get("players", []):
            for g in player.get("guesses", []):
                guesses.append(
                    Guess(
                        round_number=int(g["roundNumber"]),
                        player_id=player.get("playerId", ""),
                        is_me=player.get("playerId") == user_id,
                        lat=float(g["lat"]),
                        lng=float(g["lng"]),
                        distance_m=float(g.get("distance", 0)),
                        score=int(g.get("score", 0)),
                        created_ms=to_ms(g.get("created")),
                    )
                )

    my_h, opp_h = _health_by_round(mine), _health_by_round(opp)
    results = [RoundResult(n, *my_h[n], *opp_h.get(n, (0, 0))) for n in sorted(my_h)]

    result = game.get("result") or {}
    won: bool | None = None
    if result.get("isDraw"):
        won = None
    elif result.get("winningTeamId") is not None:
        won = result["winningTeamId"] == mine.get("id")

    rounds = _parse_rounds(game)
    options = game.get("options", {})
    movement = options.get("movementOptions") or game.get("movementOptions") or {}
    return Duel(
        game_id=game["gameId"],
        played_at_ms=rounds[0].start_ms if rounds else None,
        mode=classify_mode(movement),
        rated=bool(options.get("isRated", False)),
        my_team=mine.get("name", ""),
        won=won,
        my_rating=(my_player.get("competitive") or {}).get("rating"),
        opp_rating=(opp_player.get("competitive") or {}).get("rating"),
        opp_nick=opp_player.get("nick", ""),
        rounds=rounds,
        guesses=guesses,
        round_results=results,
    )
