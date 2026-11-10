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
from geocoach.duels import Mode, parse_duel
from geocoach.store import Store


@pytest.fixture
def store(duel_page_props):
    s = Store()
    duel = parse_duel(duel_page_props)
    countries = {
        (1, "me-0001"): "ar",
        (1, "opp-0002"): "br",
        (2, "me-0001"): "se",
        (2, "opp-0002"): "fi",
    }
    s.upsert_duel(duel, countries)
    return s


def test_classify():
    assert classify(True, True, 100) == "won"
    assert classify(False, True, -100) == "lost_on_country"
    assert classify(True, True, -100) == "lost_on_pin"
    assert classify(False, False, -100) == "both_missed"
    assert classify(True, False, -100) == "lost_on_pin"


def test_round_reviews(store):
    reviews = round_reviews(store, 5, [Mode.NMPZ])
    assert len(reviews) == 2
    r1, r2 = reviews
    assert r1.country == "br" and r1.guess_country == "ar"
    assert r1.loss_type == "lost_on_country"
    assert r1.score_diff == -1500
    assert r1.damage_taken == 1500
    assert r1.time_to_guess_s == 10.0
    assert r2.loss_type == "lost_on_country"
    assert r2.multiplier == 1.5
    assert r2.points_lost == 400


def test_weak_countries_sorted_by_points_lost(store):
    rows = weak_countries(round_reviews(store, 5, [Mode.NMPZ]))
    assert [r["country"] for r in rows] == ["br", "fi"]
    assert rows[0]["hit_rate"] == 0.0
    assert rows[0]["median_km_when_hit"] is None


def test_confusions(store):
    assert confusions(round_reviews(store, 5, [Mode.NMPZ])) == [
        {"actual": "br", "guessed": "ar", "count": 1},
        {"actual": "fi", "guessed": "se", "count": 1},
    ]


def test_time_and_damage_buckets(store):
    reviews = round_reviews(store, 5, [Mode.NMPZ])
    assert time_buckets(reviews) == [{"bucket": "<15s", "rounds": 2, "avg_score": 3350}]
    dmg = damage_by_round(reviews)
    assert dmg[0] == {"round": 1, "rounds": 1, "avg_damage": 1500, "multiplier_rounds": 0}
    assert dmg[1]["multiplier_rounds"] == 1


def test_select_rounds_weights_by_multiplier(store):
    reviews = round_reviews(store, 5, [Mode.NMPZ])
    picked = select_rounds_for_review(reviews, max_rounds=1)
    assert picked[0].n == 1
    assert len(select_rounds_for_review(reviews, max_rounds=5)) == 2
