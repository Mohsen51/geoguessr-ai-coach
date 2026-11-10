import json

import httpx
import respx

from geocoach.slashp import MAPS_URL, load_maps, map_url, recommend

MAPS = [
    {"mapName": "A Balanced Brazil", "mapId": "a" * 24, "category": "Country",
     "locationCount": 50000, "likes": 900, "plays": 1,
     "countryDistribution": [{"code": "BR", "count": 50000, "name": "Brazil"}]},
    {"mapName": "An Arbitrary South America", "mapId": "b" * 24, "category": "Continent",
     "locationCount": 80000, "likes": 500, "plays": 1,
     "countryDistribution": [{"code": "BR", "count": 30000, "name": "Brazil"},
                             {"code": "AR", "count": 20000, "name": "Argentina"},
                             {"code": "CL", "count": 30000, "name": "Chile"}]},
    {"mapName": "Tiny Finland", "mapId": "c" * 24, "category": "Country",
     "locationCount": 800, "likes": 10, "plays": 1,
     "countryDistribution": [{"code": "FI", "count": 800, "name": "Finland"}]},
    {"mapName": "Sao Paulo state", "mapId": "d" * 24, "category": "Subdivision",
     "locationCount": 20000, "likes": 50, "plays": 1,
     "countryDistribution": [{"code": "BR", "count": 20000, "name": "Brazil"}]},
]  # fmt: skip


def test_recommend_single_weak_country_prefers_country_map():
    recs = recommend(MAPS, {"br": 3000})
    assert [r["name"] for r in recs] == ["A Balanced Brazil", "An Arbitrary South America"]
    assert recs[0]["coverage"] == 1.0
    assert recs[0]["url"] == map_url("a" * 24)


def test_recommend_weights_by_points_lost_and_filters():
    recs = recommend(MAPS, {"br": 500, "ar": 4000, "fi": 100})
    assert recs[0]["name"] == "An Arbitrary South America"
    assert recs[0]["weak_countries_covered"] == ["br", "ar"]
    assert all(r["name"] != "Tiny Finland" for r in recs)
    assert all(r["category"] != "Subdivision" for r in recs)
    subs = recommend(MAPS, {"br": 1}, categories=("Subdivision",))
    assert [r["name"] for r in subs] == ["Sao Paulo state"]


@respx.mock
def test_load_maps_caches(tmp_path):
    route = respx.get(MAPS_URL).mock(return_value=httpx.Response(200, json=MAPS))
    cache = tmp_path / "maps.json"
    assert len(load_maps(cache)) == 4
    assert len(load_maps(cache)) == 4
    assert route.call_count == 1
    assert json.loads(cache.read_text())[0]["mapName"] == "A Balanced Brazil"
