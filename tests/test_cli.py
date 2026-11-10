import pytest
from typer.testing import CliRunner

from geocoach import cli, config
from geocoach.store import Store

run = CliRunner()


@pytest.fixture(autouse=True)
def tmp_env(tmp_path, monkeypatch, duel):
    for name in ("DATA_DIR", "PANOS_DIR", "PAGES_DIR", "REPORTS_DIR", "SHEETS_DIR"):
        monkeypatch.setattr(config, name, tmp_path / name.lower())
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "db.sqlite")
    config.ensure_dirs()
    store = Store(config.DB_PATH)
    store.upsert_duel(duel)
    store.close()


def test_stats_prints_tables():
    result = run.invoke(cli.app, ["stats", "--last", "5", "--mode", "nmpz"])
    assert result.exit_code == 0, result.output
    assert "India" in result.output and "Bangladesh" in result.output
    assert "862" in result.output


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
    assert "Actual: India" in captured["p"]


def test_menu_dispatches_via_fzf(monkeypatch):
    answers = iter(["Stats", "5", "nmpz", "Quit"])
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


def test_menu_analyze_passes_plain_defaults(monkeypatch):
    """Regression: menu entries used to call typer commands with Option objects as defaults."""
    captured = {}

    class FakeFetcher:
        def views_for_round(self, *a, **k):
            return []

        def close(self):
            pass

    monkeypatch.setattr("geocoach.panorama.ViewFetcher", FakeFetcher)
    monkeypatch.setattr(cli, "make_client", lambda required=True: None)
    monkeypatch.setattr(cli, "do_sync", lambda store, last, modes: captured.update(synced=last))
    monkeypatch.setattr(
        cli.runner,
        "run_claude",
        lambda prompt, name, model=None: captured.update(n=name) or config.REPORTS_DIR / "r.md",
    )
    answers = iter(["Analyze recent duels", "5", "nmpz", "Quit"])
    monkeypatch.setattr(cli, "pick", lambda options, prompt: next(answers))
    result = run.invoke(cli.app, [])
    assert result.exit_code == 0, result.output
    assert captured["n"] == "analysis_nmpz_5" and captured["synced"] == 5


def test_menu_training_and_ingest_use_plain_defaults(monkeypatch, tmp_path):
    maps = [{"mapName": "A Balanced India", "mapId": "a" * 24, "category": "Country",
             "locationCount": 50000, "likes": 1, "plays": 1,
             "countryDistribution": [{"code": "IN", "count": 50000}]}]  # fmt: skip
    monkeypatch.setattr(cli.slashp, "load_maps", lambda: maps)
    monkeypatch.setattr(cli.webbrowser, "open", lambda url: None)
    answers = iter(["Training map", "5", "nmpz", None, "Quit"])
    monkeypatch.setattr(cli, "pick", lambda options, prompt: next(answers))
    assert run.invoke(cli.app, []).exit_code == 0
    monkeypatch.setattr(config, "METAS_DIR", tmp_path)
    answers2 = iter(["Ingest meta PDFs", "Quit"])
    monkeypatch.setattr(cli, "pick", lambda options, prompt: next(answers2))
    result = run.invoke(cli.app, [])
    assert result.exit_code == 0 and "0 documents indexed" in result.output


def test_menu_loops_until_quit(monkeypatch):
    answers = iter(["Stats", "5", "nmpz", "Stats", "5", "nmpz", "Quit"])
    monkeypatch.setattr(cli, "pick", lambda options, prompt: next(answers))
    result = run.invoke(cli.app, [])
    assert result.exit_code == 0, result.output
    assert result.output.count("Weak countries") == 2


def test_menu_survives_task_error(monkeypatch):
    answers = iter(["Sync plonkit guides", None])

    def boom(*a, **k):
        raise RuntimeError("offline")

    monkeypatch.setattr(cli, "run_plonkit", boom)
    monkeypatch.setattr(cli, "pick", lambda options, prompt: next(answers))
    result = run.invoke(cli.app, [])
    assert result.exit_code == 0 and "RuntimeError: offline" in result.output


def test_encyclopedia_uses_saved_sheet_unless_refresh(monkeypatch):
    calls = []

    def fake_run(prompt, name, model=None):
        calls.append(name)
        report = config.REPORTS_DIR / "r.md"
        report.write_text(
            f"# x\n\nPrompt:\n\n{prompt}{cli.runner.ANSWER_SEPARATOR}# Sheet {len(calls)}\n"
        )
        return report

    monkeypatch.setattr(cli.runner, "run_claude", fake_run)
    monkeypatch.setattr(cli, "make_client", lambda required=True: None)
    monkeypatch.setattr(
        cli.plonkit,
        "PlonkitClient",
        lambda: type("C", (), {"close": lambda self: None, "guide_index": lambda self: []})(),
    )
    assert run.invoke(cli.app, ["encyclopedia", "in"]).exit_code == 0
    assert cli.sheet_path("in").read_text().startswith("# Sheet 1")
    result = run.invoke(cli.app, ["encyclopedia", "IN"])
    assert result.exit_code == 0 and "Sheet 1" in result.output and len(calls) == 1
    assert run.invoke(cli.app, ["encyclopedia", "in", "--refresh"]).exit_code == 0
    assert len(calls) == 2 and cli.sheet_path("in").read_text().startswith("# Sheet 2")
