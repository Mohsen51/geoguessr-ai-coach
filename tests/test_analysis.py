import pytest

from geocoach.analysis import (
    classify,
    confusions,
    damage_by_round,
    round_reviews,
    select_rounds_for_review,
    time_buckets,
    weak_countries,
)
from geocoach.duels import Mode
from geocoach.store import Store


@pytest.fixture
def store(duel):
    s = Store()
    s.upsert_duel(duel)
    return s


def test_classify():
    assert classify(True, True, 100) == "won"
    assert classify(False, True, -100) == "lost_on_country"
    assert classify(True, True, -100) == "lost_on_pin"
    assert classify(False, False, -100) == "both_missed"
    assert classify(True, False, -100) == "lost_on_pin"


def test_round_reviews(store):
    reviews = round_reviews(store, 5, [Mode.NMPZ])
    assert [r.loss_type for r in reviews] == [
        "lost_on_country", "won", "won", "lost_on_country", "lost_on_pin",
    ]  # fmt: skip
    r1 = reviews[0]
    assert r1.country == "in" and r1.guess_country == "bd" and r1.opp_guess_country == "in"
    assert r1.score_diff == -3059 and r1.damage_taken == 3059
    assert r1.time_to_guess_s == 14.3
    assert reviews[4].points_lost == 2679 and reviews[4].country_hit


def test_weak_countries_sorted_by_points_lost(store):
    rows = weak_countries(round_reviews(store, 5, [Mode.NMPZ]))
    assert [r["country"] for r in rows[:3]] == ["in", "br", "fr"]
    assert rows[0]["hit_rate"] == 0.0 and rows[0]["median_km_when_hit"] is None
    assert rows[1]["lost_on_pin"] == 1 and rows[1]["median_km_when_hit"] == 1424


def test_confusions(store):
    assert confusions(round_reviews(store, 5, [Mode.NMPZ])) == [
        {"actual": "in", "guessed": "bd", "count": 1},
        {"actual": "za", "guessed": "sz", "count": 1},
        {"actual": "fr", "guessed": "dk", "count": 1},
    ]


def test_time_and_damage_buckets(store):
    reviews = round_reviews(store, 5, [Mode.NMPZ])
    buckets = {b["bucket"]: b["rounds"] for b in time_buckets(reviews)}
    assert buckets == {"<10s": 2, "<15s": 1, "<30s": 2}
    dmg = damage_by_round(reviews)
    assert dmg[0] == {"round": 1, "rounds": 1, "avg_damage": 3059, "multiplier_rounds": 0}


def test_select_rounds_ranks_by_points_lost(store):
    reviews = round_reviews(store, 5, [Mode.NMPZ])
    picked = select_rounds_for_review(reviews, max_rounds=2)
    assert [r.n for r in picked] == [1, 5]
    assert len(select_rounds_for_review(reviews, max_rounds=9)) == 3
