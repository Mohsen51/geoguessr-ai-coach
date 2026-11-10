import pytest
from typer.testing import CliRunner

from geocoach import cli, config
from geocoach.duels import parse_duel
from geocoach.store import Store

run = CliRunner()


@pytest.fixture(autouse=True)
def tmp_env(tmp_path, monkeypatch, duel_page_props):
    for name in ("DATA_DIR", "PANOS_DIR", "PAGES_DIR", "REPORTS_DIR"):
        monkeypatch.setattr(config, name, tmp_path / name.lower())
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "db.sqlite")
    config.ensure_dirs()
    store = Store(config.DB_PATH)
    store.upsert_duel(
        parse_duel(duel_page_props),
        {(1, "me-0001"): "ar", (1, "opp-0002"): "br", (2, "me-0001"): "se", (2, "opp-0002"): "fi"},
    )
    store.close()


def test_stats_prints_tables():
    result = run.invoke(cli.app, ["stats", "--last", "5", "--mode", "nmpz"])
    assert result.exit_code == 0, result.output
    assert "Brazil" in result.output and "Argentina" in result.output
    assert "905" in result.output


def test_stats_rejects_bad_mode():
    result = run.invoke(cli.app, ["stats", "--mode", "moving"])
    assert result.exit_code != 0


def test_training_no_open_lists_urls(monkeypatch):
    maps = [{"mapName": "A Balanced Brazil", "mapId": "a" * 24, "category": "Country",
             "locationCount": 50000, "likes": 1, "plays": 1,
             "countryDistribution": [{"code": "BR", "count": 50000}]}]  # fmt: skip
    monkeypatch.setattr(cli.slashp, "load_maps", lambda: maps)
    result = run.invoke(cli.app, ["training", "--no-open", "--mode", "nmpz"])
    assert result.exit_code == 0, result.output
    assert "A Balanced Brazil" in result.output and "geoguessr.com/maps/" in result.output


def test_analyze_builds_prompt_and_calls_runner(monkeypatch):
    captured = {}

    class FakeFetcher:
        def views_for_round(self, pano_id, heading, mode, pitch=0, full=False):
            return []

        def close(self):
            pass

    monkeypatch.setattr("geocoach.panorama.ViewFetcher", FakeFetcher)
    monkeypatch.setattr(
        cli.runner,
        "run_claude",
        lambda prompt, name, model=None: (
            captured.update(p=prompt, n=name) or config.REPORTS_DIR / "r.md"
        ),
    )
    result = run.invoke(cli.app, ["analyze", "--no-sync", "--mode", "nmpz", "--last", "5"])
    assert result.exit_code == 0, result.output
    assert captured["n"] == "analysis_nmpz_5"
    assert "Actual: Brazil" in captured["p"]


def test_menu_dispatches_via_fzf(monkeypatch):
    answers = iter(["Stats", "5", "nmpz"])
    monkeypatch.setattr(cli, "pick", lambda options, prompt: next(answers))
    result = run.invoke(cli.app, [])
    assert result.exit_code == 0, result.output
    assert "Weak countries" in result.output


def test_sync_without_cookie_fails_cleanly(monkeypatch):
    monkeypatch.delenv("GEOGUESSR_NCFA", raising=False)
    monkeypatch.setattr(config, "_keychain_cookie", lambda: None)
    monkeypatch.setattr(config, "ROOT", config.DATA_DIR)
    result = run.invoke(cli.app, ["sync"])
    assert result.exit_code == 1
    assert "_ncfa" in result.output
