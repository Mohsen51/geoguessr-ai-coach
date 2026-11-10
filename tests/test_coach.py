import pytest

from geocoach import coach, config
from geocoach.duels import Mode
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
def store(duel, tmp_path, monkeypatch):
    for name in ("DATA_DIR", "PANOS_DIR", "PAGES_DIR", "REPORTS_DIR"):
        monkeypatch.setattr(config, name, tmp_path / name.lower())
    s = Store()
    s.upsert_duel(duel)
    return s


def test_prepare_analysis_builds_prompt_with_images(store):
    fetcher = FakeFetcher()
    bundle = coach.prepare_analysis(store, fetcher, 5, [Mode.NMPZ], max_rounds=5)
    assert [r.n for r in bundle.rounds] == [1, 5, 4]
    assert fetcher.calls[0] == ("PANO1xxxxxxxxxxxxxxxxx", 116, "nmpz", False)
    p = bundle.prompt
    assert "rating about 862" in p and "plays NMPZ" in p
    assert "Actual: India (in)" in p and "My guess: Bangladesh" in p
    assert "PANO1xxxxxxxxxxxxxxxxx_y116.jpg" in p
    assert "India (3059 pts over 1 rounds)" in p
    assert "Bangladesh at 23.861" in p and "Opponent: India at 22.709" in p


def test_prepare_analysis_includes_clue_cards(store, tmp_path):
    calls = []

    def fetch(cc):
        calls.append(cc)
        return [{"type": "poles", "title": "Ladder poles", "description": "Concrete steps.",
                 "regions": [{"name": "North"}]}]  # fmt: skip

    bundle = coach.prepare_analysis(store, None, 5, [Mode.NMPZ], max_rounds=1, clue_fetch=fetch)
    assert calls == ["in"]
    assert "poles: Ladder poles. Concrete steps. (regions: North)" in bundle.prompt
    bundle = coach.prepare_analysis(store, None, 5, [Mode.NMPZ], max_rounds=1, clue_fetch=fetch)
    assert calls == ["in"]  # second call served from the disk cache


def test_prepare_analysis_survives_image_failure(store):
    logs = []
    fetcher = FakeFetcher(fail_for={"PANO1xxxxxxxxxxxxxxxxx"})
    bundle = coach.prepare_analysis(store, fetcher, 5, [Mode.NMPZ], log=logs.append)
    assert bundle.images[(bundle.rounds[0].game_id, 1)] == []
    assert "No image available" in bundle.prompt
    assert logs and "403" in logs[0]


def test_prepare_encyclopedia_without_docs(store):
    prompt = coach.prepare_encyclopedia(store, "BR")
    assert "meta sheet for Brazil (br)" in prompt
    assert prompt.count("(none)") == 3
