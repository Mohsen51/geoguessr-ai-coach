import json
from pathlib import Path

import pytest

from geocoach.duels import parse_duel

FIXTURES = Path(__file__).parent / "fixtures"

# Rough country lookup for the fixture coordinates, avoids the offline geocoder in tests.
POINTS = [
    (23.1, 72.1, "in"), (23.9, 90.5, "bd"), (22.7, 72.3, "in"),
    (-23.7, 30.3, "za"), (-26.7, 31.5, "sz"), (-27.0, 28.5, "za"),
    (39.9, -5.2, "es"), (41.2, -1.3, "es"), (42.2, 19.9, "al"),
    (49.6, 0.6, "fr"), (55.7, 9.3, "dk"), (47.9, 5.6, "fr"),
    (-13.9, -40.1, "br"), (-23.8, -48.7, "br"), (-13.8, -40.1, "br"),
    (48.9, 2.3, "fr"), (-23.5, -46.6, "br"),
]  # fmt: skip


REGIONS = {"br": {(-13.9, -40.1): "Bahia", (-23.8, -48.7): "Sao Paulo", (-13.8, -40.1): "Bahia"}}


def fake_geocoder(lat: float, lng: float) -> str:
    return min(POINTS, key=lambda p: (p[0] - lat) ** 2 + (p[1] - lng) ** 2)[2]


def fake_place_geocoder(lat: float, lng: float) -> tuple[str, str]:
    p = min(POINTS, key=lambda p: (p[0] - lat) ** 2 + (p[1] - lng) ** 2)
    return p[2], REGIONS.get(p[2], {}).get((p[0], p[1]), "")


@pytest.fixture
def duel_game() -> dict:
    return json.loads((FIXTURES / "duel_result.json").read_text())


@pytest.fixture
def duel(duel_game):
    return parse_duel(duel_game, "me-0001", place_geocoder=fake_place_geocoder)
