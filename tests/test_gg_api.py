import json
from pathlib import Path

import httpx
import pytest
import respx

from geocoach.gg_api import FEED_URL, ApiError, GeoGuessrClient, parse_next_data

FIXTURES = Path(__file__).parent / "fixtures"


def summary_html(page_props: dict) -> str:
    data = json.dumps({"props": {"pageProps": page_props}})
    return f'<html><script id="__NEXT_DATA__" type="application/json">{data}</script></html>'


@pytest.fixture
def client():
    c = GeoGuessrClient("secret-cookie", min_interval_s=0)
    yield c
    c.close()


@respx.mock
def test_iter_duel_ids_pages_and_dedups(client):
    p1 = json.loads((FIXTURES / "feed_page1.json").read_text())
    p2 = json.loads((FIXTURES / "feed_page2.json").read_text())
    route = respx.get(FEED_URL)
    route.side_effect = [httpx.Response(200, json=p1), httpx.Response(200, json=p2)]

    ids = list(client.iter_duel_ids())

    assert ids == [
        "11111111-2222-3333-4444-555555555555",
        "aaaaaaaa-0000-0000-0000-000000000002",
        "bbbbbbbb-0000-0000-0000-000000000003",
    ]
    assert route.calls[1].request.url.params["paginationToken"] == "page2"
    assert route.calls[0].request.headers["cookie"] == "_ncfa=secret-cookie"


@respx.mock
def test_duel_summary_parses_next_data(client):
    respx.get("https://www.geoguessr.com/duels/abc/summary").mock(
        return_value=httpx.Response(200, text=summary_html({"userId": "me-0001"}))
    )
    assert client.duel_summary("abc")["userId"] == "me-0001"


@respx.mock
def test_duel_results_batches_ids(client, duel_game):
    route = respx.post("https://www.geoguessr.com/api/v4/game-results/duels/by-game-ids").mock(
        return_value=httpx.Response(200, json=[duel_game])
    )
    out = client.duel_results([f"g{i}" for i in range(45)], batch=20)
    assert len(out) == 3 and route.call_count == 3
    assert json.loads(route.calls[0].request.content)["gameIds"] == [f"g{i}" for i in range(20)]


@respx.mock
def test_user_id_and_ranked_progress(client):
    respx.get("https://www.geoguessr.com/api/v3/profiles").mock(
        return_value=httpx.Response(200, json={"user": {"id": "me-0001"}})
    )
    respx.get("https://www.geoguessr.com/api/v4/ranked-system/progress/me-0001").mock(
        return_value=httpx.Response(
            200, json={"rating": 850, "gameModeRatings": {"nmpzDuels": 725}}
        )
    )
    uid = client.user_id()
    assert uid == "me-0001"
    assert client.ranked_progress(uid)["gameModeRatings"]["nmpzDuels"] == 725


@respx.mock
def test_expired_cookie_raises(client):
    respx.get(FEED_URL).mock(return_value=httpx.Response(401))
    with pytest.raises(ApiError, match="cookie"):
        list(client.iter_duel_ids())


@respx.mock
def test_retries_on_429(client):
    route = respx.get("https://www.geoguessr.com/duels/abc/summary")
    route.side_effect = [
        httpx.Response(429),
        httpx.Response(200, text=summary_html({"userId": "me-0001"})),
    ]
    client.duel_summary("abc")
    assert route.call_count == 2


def test_parse_next_data_rejects_login_page():
    with pytest.raises(ApiError):
        parse_next_data("<html>Log in</html>")
