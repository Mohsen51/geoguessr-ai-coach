"""Per-round classification and aggregates over recent duels."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from statistics import median
from typing import Literal

from geocoach.duels import Mode
from geocoach.store import Store

LossType = Literal["won", "lost_on_country", "lost_on_pin", "both_missed"]


@dataclass(frozen=True)
class RoundReview:
    game_id: str
    n: int
    mode: str
    country: str
    guess_country: str
    opp_guess_country: str
    my_score: int
    opp_score: int
    score_diff: int
    distance_m: float
    opp_distance_m: float
    time_to_guess_s: float | None
    damage_taken: int
    multiplier: float
    loss_type: LossType
    pano_id: str
    lat: float
    lng: float
    heading: float
    pitch: float

    @property
    def country_hit(self) -> bool:
        return self.guess_country == self.country

    @property
    def points_lost(self) -> int:
        return max(0, -self.score_diff)

    def as_dict(self) -> dict:
        d = asdict(self)
        d["country_hit"] = self.country_hit
        return d


def classify(my_hit: bool, opp_hit: bool, score_diff: int) -> LossType:
    if score_diff >= 0:
        return "won"
    if not my_hit and opp_hit:
        return "lost_on_country"
    if not my_hit and not opp_hit:
        return "both_missed"
    return "lost_on_pin"


def round_reviews(store: Store, n_games: int, modes: Iterable[Mode]) -> list[RoundReview]:
    reviews: list[RoundReview] = []
    for duel in store.recent_duels(n_games, modes):
        gid = duel["game_id"]
        guesses = defaultdict(dict)
        for g in store.guesses_for(gid):
            guesses[g["n"]]["me" if g["is_me"] else "opp"] = g
        results = {r["n"]: r for r in store.results_for(gid)}
        for r in store.rounds_for(gid):
            me, opp = guesses[r["n"]].get("me"), guesses[r["n"]].get("opp")
            if me is None:
                continue
            my_score = me["score"] or 0
            opp_score = opp["score"] if opp else 0
            my_hit = (me["guess_country"] or "") == r["country"]
            opp_hit = bool(opp) and (opp["guess_country"] or "") == r["country"]
            res = results.get(r["n"])
            damage = (res["my_health_before"] - res["my_health_after"]) if res else 0
            ttg = None
            if me["time_spent_ms"] is not None:
                ttg = round(me["time_spent_ms"] / 1000, 1)
            reviews.append(
                RoundReview(
                    game_id=gid,
                    n=r["n"],
                    mode=duel["mode"],
                    country=r["country"],
                    guess_country=me["guess_country"] or "",
                    opp_guess_country=(opp["guess_country"] if opp else "") or "",
                    my_score=my_score,
                    opp_score=opp_score,
                    score_diff=my_score - opp_score,
                    distance_m=me["distance_m"] or 0.0,
                    opp_distance_m=(opp["distance_m"] if opp else 0.0) or 0.0,
                    time_to_guess_s=ttg,
                    damage_taken=max(0, damage),
                    multiplier=r["multiplier"] or 1.0,
                    loss_type=classify(my_hit, opp_hit, my_score - opp_score),
                    pano_id=r["pano_id"],
                    lat=r["lat"],
                    lng=r["lng"],
                    heading=r["heading"],
                    pitch=r["pitch"],
                )
            )
    return reviews


def weak_countries(reviews: list[RoundReview]) -> list[dict]:
    by: dict[str, list[RoundReview]] = defaultdict(list)
    for rv in reviews:
        by[rv.country].append(rv)
    out = []
    for country, rows in by.items():
        hits = [r for r in rows if r.country_hit]
        out.append(
            {
                "country": country,
                "rounds": len(rows),
                "hit_rate": round(len(hits) / len(rows), 2),
                "points_lost": sum(r.points_lost for r in rows),
                "lost_on_country": sum(r.loss_type == "lost_on_country" for r in rows),
                "lost_on_pin": sum(r.loss_type == "lost_on_pin" for r in rows),
                "median_km_when_hit": round(median(r.distance_m for r in hits) / 1000)
                if hits
                else None,
            }
        )
    return sorted(out, key=lambda d: -d["points_lost"])


def confusions(reviews: list[RoundReview]) -> list[dict]:
    pairs = Counter((r.country, r.guess_country) for r in reviews if not r.country_hit)
    return [{"actual": a, "guessed": g, "count": c} for (a, g), c in pairs.most_common()]


def time_buckets(reviews: list[RoundReview], edges=(5, 10, 15, 30)) -> list[dict]:
    buckets: dict[str, list[int]] = defaultdict(list)
    for r in reviews:
        if r.time_to_guess_s is None:
            continue
        label = next((f"<{e}s" for e in edges if r.time_to_guess_s < e), f">={edges[-1]}s")
        buckets[label].append(r.my_score)
    return [
        {"bucket": k, "rounds": len(v), "avg_score": round(sum(v) / len(v))}
        for k, v in buckets.items()
    ]


def damage_by_round(reviews: list[RoundReview]) -> list[dict]:
    by: dict[int, list[RoundReview]] = defaultdict(list)
    for r in reviews:
        by[r.n].append(r)
    return [
        {
            "round": n,
            "rounds": len(v),
            "avg_damage": round(sum(r.damage_taken for r in v) / len(v)),
            "multiplier_rounds": sum(r.multiplier > 1 for r in v),
        }
        for n, v in sorted(by.items())
    ]


def rating_trend(store: Store, n_games: int, modes: Iterable[Mode]) -> list[dict]:
    rows = store.recent_duels(n_games, modes)
    return [
        {
            "game_id": r["game_id"],
            "played_at_ms": r["played_at_ms"],
            "mode": r["mode"],
            "won": r["won"],
            "my_rating": r["my_rating"],
            "opp_rating": r["opp_rating"],
        }
        for r in reversed(rows)
    ]


def select_rounds_for_review(reviews: list[RoundReview], max_rounds: int = 12):
    lost = [r for r in reviews if r.loss_type != "won"]
    return sorted(lost, key=lambda r: (-r.points_lost * r.multiplier, r.game_id, r.n))[:max_rounds]
