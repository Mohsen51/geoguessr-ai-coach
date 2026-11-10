import pytest

from geocoach import coach, config
from geocoach.duels import Mode, parse_duel
from geocoach.panorama import PanoramaError
from geocoach.store import Store


class FakeFetcher:
    def __init__(self, fail_for: set[str] = frozenset()):
        self.fail_for = fail_for
        self.calls = []

    def views_for_round(self, pano_id, heading, mode, pitch=0, full=False):
        self.calls.append((pano_id, round(heading), mode, full))
        if pano_id in self.fail_for:
            raise PanoramaError("HTTP 403")
        return [config.PANOS_DIR / f"{pano_id}_y{round(heading):03d}.jpg"]


@pytest.fixture
def store(duel_page_props, tmp_path, monkeypatch):
    for name in ("DATA_DIR", "PANOS_DIR", "PAGES_DIR", "REPORTS_DIR"):
        monkeypatch.setattr(config, name, tmp_path / name.lower())
    s = Store()
    s.upsert_duel(
        parse_duel(duel_page_props),
        {(1, "me-0001"): "ar", (1, "opp-0002"): "br", (2, "me-0001"): "se", (2, "opp-0002"): "fi"},
    )
    return s


def test_prepare_analysis_builds_prompt_with_images(store):
    fetcher = FakeFetcher()
    bundle = coach.prepare_analysis(store, fetcher, 5, [Mode.NMPZ], max_rounds=5)
    assert [r.n for r in bundle.rounds] == [1, 2]
    assert fetcher.calls[0] == ("RPS4EBhBrRCCyP1TJtKVuw", 172, "nmpz", False)
    p = bundle.prompt
    assert "rating about 905" in p and "plays NMPZ" in p
    assert "Actual: Brazil (br)" in p and "My guess: Argentina" in p
    assert "RPS4EBhBrRCCyP1TJtKVuw_y172.jpg" in p
    assert "Brazil (1500 pts over 1 rounds)" in p


def test_prepare_analysis_survives_image_failure(store):
    logs = []
    fetcher = FakeFetcher(fail_for={"RPS4EBhBrRCCyP1TJtKVuw"})
    bundle = coach.prepare_analysis(store, fetcher, 5, [Mode.NMPZ], log=logs.append)
    assert bundle.images[(bundle.rounds[0].game_id, 1)] == []
    assert "No image available" in bundle.prompt
    assert logs and "403" in logs[0]


def test_prepare_encyclopedia_without_docs(store):
    prompt = coach.prepare_encyclopedia(store, "BR")
    assert "meta sheet for Brazil (br)" in prompt
    assert "(none)" in prompt
