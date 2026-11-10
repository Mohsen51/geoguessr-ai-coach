from geocoach.duels import Mode, classify_mode, decode_pano_id, parse_duel, to_ms


def test_decode_pano_id_hex_to_ascii():
    assert (
        decode_pano_id("525053344542684272524343795031544A744B567577") == "RPS4EBhBrRCCyP1TJtKVuw"
    )


def test_decode_pano_id_passthrough_on_invalid_hex():
    assert decode_pano_id("not-hex") == "not-hex"


def test_classify_mode():
    assert (
        classify_mode({"forbidMoving": True, "forbidZooming": True, "forbidRotating": True})
        == Mode.NMPZ
    )
    assert (
        classify_mode({"forbidMoving": True, "forbidZooming": False, "forbidRotating": False})
        == Mode.NM
    )
    assert (
        classify_mode({"forbidMoving": True, "forbidZooming": True, "forbidRotating": False})
        == Mode.NM
    )
    assert classify_mode({"forbidMoving": False}) == Mode.MOVING
    assert classify_mode({}) == Mode.MOVING


def test_to_ms_accepts_iso_epoch_ms_and_seconds():
    assert to_ms("2026-11-09T18:00:00.000Z") == 1794247200000
    assert to_ms(1794247200000) == 1794247200000
    assert to_ms(1794247200) == 1794247200000
    assert to_ms(None) is None
    assert to_ms("garbage") is None


def test_parse_duel_header(duel_page_props):
    duel = parse_duel(duel_page_props)
    assert duel.game_id == "11111111-2222-3333-4444-555555555555"
    assert duel.mode == Mode.NMPZ
    assert duel.rated is True
    assert duel.my_team == "blue"
    assert duel.won is False
    assert duel.my_rating == 905
    assert duel.opp_rating == 930
    assert duel.opp_nick == "opponent"
    assert duel.played_at_ms == 1794247200000


def test_parse_duel_rounds(duel_page_props):
    duel = parse_duel(duel_page_props)
    assert [r.number for r in duel.rounds] == [1, 2]
    r1 = duel.rounds[0]
    assert r1.pano_id == "RPS4EBhBrRCCyP1TJtKVuw"
    assert r1.country == "br"
    assert r1.heading == 172
    assert duel.rounds[1].multiplier == 1.5


def test_parse_duel_guesses_and_results(duel_page_props):
    duel = parse_duel(duel_page_props)
    mine = [g for g in duel.guesses if g.is_me]
    opp = [g for g in duel.guesses if not g.is_me]
    assert [g.score for g in mine] == [2500, 4200]
    assert [g.score for g in opp] == [4000, 4600]
    assert duel.round_results[0].my_health_after == 4500
    assert duel.round_results[0].opp_health_after == 6000


def test_parse_duel_draw_sets_won_none(duel_page_props):
    duel_page_props["game"]["result"] = {"isDraw": True}
    assert parse_duel(duel_page_props).won is None
