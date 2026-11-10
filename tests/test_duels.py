from conftest import fake_geocoder

from geocoach.duels import Mode, classify_mode, decode_pano_id, parse_duel, to_ms

HEX_ID = "525053344542684272524343795031544A744B567577"


def test_decode_pano_id():
    assert decode_pano_id(HEX_ID) == "RPS4EBhBrRCCyP1TJtKVuw"
    assert decode_pano_id("3tTgWfI_cPLdbqoGaa1zZA") == "3tTgWfI_cPLdbqoGaa1zZA"
    assert decode_pano_id("abcdef0123456789abcdef") == "abcdef0123456789abcdef"


def test_classify_mode_from_mode_name_then_fallbacks():
    assert classify_mode({"mode": "NoMoveZoomPan"}) == Mode.NMPZ
    assert classify_mode({"mode": "NoMove"}) == Mode.NM
    assert classify_mode({"mode": "Standard"}) == Mode.MOVING
    assert classify_mode({"competitiveGameMode": "NmpzDuels"}) == Mode.NMPZ
    assert classify_mode({"competitiveGameMode": "NoMoveDuels"}) == Mode.NM
    assert classify_mode({"movementOptions": {"forbidMoving": True}}) == Mode.NM
    assert classify_mode({}) == Mode.MOVING


def test_to_ms_formats():
    assert to_ms("2026-11-09T12:32:53.3764038Z") == 1794227573376
    assert to_ms("2026-11-09T18:00:00.000Z") == 1794247200000
    assert to_ms(1794247200000) == 1794247200000
    assert to_ms(1794247200) == 1794247200000
    assert to_ms(None) is None
    assert to_ms("garbage") is None


def test_parse_duel_header(duel):
    assert duel.game_id == "game-0001"
    assert duel.mode == Mode.NMPZ and duel.rated is True
    assert duel.my_team == "red" and duel.won is False
    assert duel.my_rating == 862 and duel.opp_rating == 941
    assert duel.opp_id == "opp-0002" and duel.map_name == "Test Map"
    assert duel.played_at_ms == 1794227573376


def test_parse_duel_rounds_and_countries(duel):
    assert [r.number for r in duel.rounds] == [1, 2, 3, 4, 5]
    assert [r.country for r in duel.rounds] == ["in", "za", "es", "fr", "br"]
    assert duel.rounds[0].heading == 116 and duel.rounds[0].pano_id.startswith("PANO1")


def test_parse_duel_guesses_and_results(duel):
    mine = [g for g in duel.guesses if g.is_me]
    assert [g.score for g in mine] == [1815, 4135, 4121, 3077, 2315]
    assert [g.country for g in mine] == ["bd", "sz", "es", "dk", "br"]
    assert mine[0].time_spent_ms == 14281
    assert duel.round_results[0].my_health_after == 2941
    assert duel.round_results[-1].opp_health_after == 2101


def test_parse_duel_draw_and_summary_shape(duel_game):
    for t in duel_game["teams"]:
        t["roundResults"][-1]["healthAfter"] = 100
    assert parse_duel(duel_game, "me-0001", fake_geocoder).won is None
    # summary page shape: panorama nested, hex pano id, countryCode present
    r = duel_game["rounds"][0]
    duel_game["rounds"][0] = {
        "roundNumber": 1, "multiplier": 1,
        "panorama": {"panoId": "525053344542684272524343795031544A744B567577",
                     "lat": r["lat"], "lng": r["lng"], "countryCode": "IN", "heading": 1},
    }  # fmt: skip
    d = parse_duel(duel_game, "me-0001")
    assert d.rounds[0].pano_id == "RPS4EBhBrRCCyP1TJtKVuw" and d.rounds[0].country == "in"
    assert d.rounds[1].country == ""
