import pytest
from typer.testing import CliRunner

from geocoach import cli, config
from geocoach.store import Store

run = CliRunner()


def fake_report(captured):
    """Stand-in for runner.run_claude that writes a minimal report file."""

    def run_claude(prompt, name, model=None):
        captured.update(p=prompt, n=name)
        config.ensure_dirs()
        path = config.REPORTS_DIR / "r.md"
        path.write_text(f"# x\n\nPrompt:\n\n{prompt}{cli.runner.ANSWER_SEPARATOR}## Summary\nok\n")
        return path

    return run_claude


@pytest.fixture(autouse=True)
def tmp_env(tmp_path, monkeypatch, duel):
    for name in ("DATA_DIR", "PANOS_DIR", "PAGES_DIR", "REPORTS_DIR"):
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
    monkeypatch.setattr(cli.runner, "run_claude", fake_report(captured))
    opened = []
    monkeypatch.setattr(cli.webbrowser, "open", opened.append)
    result = run.invoke(cli.app, ["analyze", "--no-sync", "--mode", "nmpz", "--last", "5"])
    assert result.exit_code == 0, result.output
    assert captured["n"] == "analysis_nmpz_5"
    assert "Actual: India" in captured["p"]
    assert len(opened) == 1 and opened[0].endswith(".html")
    assert run.invoke(cli.app, ["analyze", "--no-sync", "--no-open"]).exit_code == 0
    assert len(opened) == 1


ORIGINAL_PAUSE = cli.pause
ORIGINAL_MAKE_CLIENT = cli.make_client


@pytest.fixture(autouse=True)
def no_pause(monkeypatch):
    monkeypatch.setattr(cli, "pause", lambda: None)
    monkeypatch.setattr(cli, "make_client", lambda required=True: None)

    class OfflinePlonkit:
        def guide_index(self):
            return []

        def close(self):
            pass

    monkeypatch.setattr(cli.plonkit, "PlonkitClient", OfflinePlonkit)


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
    monkeypatch.setattr(cli, "make_client", ORIGINAL_MAKE_CLIENT)
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
    monkeypatch.setattr(cli.runner, "run_claude", fake_report(captured))
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
    result = run.invoke(cli.app, ["ingest"])
    assert result.exit_code == 0 and "0 documents indexed" in result.output


def test_menu_loops_until_quit(monkeypatch):
    answers = iter(["Stats", "5", "nmpz", "Stats", "5", "nmpz", "Quit"])
    monkeypatch.setattr(cli, "pick", lambda options, prompt: next(answers))
    result = run.invoke(cli.app, [])
    assert result.exit_code == 0, result.output
    assert result.output.count("Weak countries") == 2


def test_menu_survives_task_error(monkeypatch):
    answers = iter(["Stats", None])

    def boom(*a, **k):
        raise RuntimeError("offline")

    monkeypatch.setattr(cli, "_menu_stats", boom)
    monkeypatch.setattr(cli, "pick", lambda options, prompt: next(answers))
    result = run.invoke(cli.app, [])
    assert result.exit_code == 0 and "RuntimeError: offline" in result.output


def test_encyclopedia_shows_repo_sheet(monkeypatch, tmp_path):
    monkeypatch.setattr(cli.sheets, "SHEETS_DIR", tmp_path)
    (tmp_path / "in.md").write_text("# India (in)\n\n## Identifying India\n\n- Ladder poles.\n")
    result = run.invoke(cli.app, ["encyclopedia", "IN"])
    assert result.exit_code == 0 and "Ladder poles" in result.output
    assert run.invoke(cli.app, ["encyclopedia", "zz"]).exit_code == 1
    answers = iter(["Encyclopedia", "in  India", "Quit"])
    monkeypatch.setattr(cli, "pick", lambda options, prompt: next(answers))
    assert "Ladder poles" in run.invoke(cli.app, []).output


def test_menu_pauses_after_each_task(monkeypatch):
    pauses = []
    monkeypatch.setattr(cli, "pause", lambda: pauses.append(1))
    answers = iter(["Stats", "5", "nmpz", "Quit"])
    monkeypatch.setattr(cli, "pick", lambda options, prompt: next(answers))
    assert run.invoke(cli.app, []).exit_code == 0
    assert pauses == [1]


def test_pause_exits_cleanly_on_eof(monkeypatch):
    monkeypatch.setattr(cli.console, "input", lambda *a, **k: (_ for _ in ()).throw(EOFError()))
    with pytest.raises(cli.typer.Exit):
        ORIGINAL_PAUSE()


def test_menu_help_lists_every_entry(monkeypatch):
    answers = iter(["Help", "Quit"])
    monkeypatch.setattr(cli, "pick", lambda options, prompt: next(answers))
    out = run.invoke(cli.app, []).output
    for entry in (
        "Analyze recent duels",
        "Training map",
        "Encyclopedia",
        "Ask a question",
        "Stats",
        "Index meta PDFs",
    ):
        assert entry in out


def test_menu_has_only_user_facing_entries(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        cli, "pick", lambda options, prompt: seen.setdefault("options", options) and None
    )
    run.invoke(cli.app, [])
    assert seen["options"] == [
        "Analyze recent duels", "Training map", "Encyclopedia", "Ask a question", "Stats",
        "Index meta PDFs", "Help", "Quit",
    ]  # fmt: skip


def test_stats_and_training_auto_sync(monkeypatch):
    synced = []
    monkeypatch.setattr(cli, "auto_sync", lambda store, last, modes: synced.append(last))
    assert run.invoke(cli.app, ["stats", "--last", "5", "--mode", "nmpz"]).exit_code == 0
    maps = [{"mapName": "A Balanced India", "mapId": "a" * 24, "category": "Country",
             "locationCount": 50000, "likes": 1, "plays": 1,
             "countryDistribution": [{"code": "IN", "count": 50000}]}]  # fmt: skip
    monkeypatch.setattr(cli.slashp, "load_maps", lambda: maps)
    assert run.invoke(cli.app, ["training", "--no-open", "--last", "7"]).exit_code == 0
    assert synced == [5, 7]


def test_auto_sync_without_cookie_is_silent():
    cli.auto_sync(cli.open_store(), 5, [cli.Mode.NMPZ])


def test_index_metas_runs_ingest_then_digest(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "run_ingest", lambda force=False: calls.append("ingest"))
    monkeypatch.setattr(cli, "run_digest", lambda *a, **k: calls.append("digest"))
    answers = iter(["Index meta PDFs", "Quit"])
    monkeypatch.setattr(cli, "pick", lambda options, prompt: next(answers))
    assert run.invoke(cli.app, []).exit_code == 0
    assert calls == ["ingest", "digest"]


def test_menu_custom_last_number(monkeypatch):
    captured = {}
    monkeypatch.setattr(cli, "run_stats", lambda last, mode: captured.update(last=last, mode=mode))
    answers = iter(["Stats", cli.CUSTOM_LAST, "nm", "Quit"])
    monkeypatch.setattr(cli, "pick", lambda options, prompt: next(answers))
    typed = iter(["abc", "0", "42"])
    monkeypatch.setattr(cli.console, "input", lambda *a, **k: next(typed))
    result = run.invoke(cli.app, [])
    assert result.exit_code == 0, result.output
    assert captured == {"last": 42, "mode": "nm"}
    assert "whole number" in result.output


def test_ask_number_returns_none_on_empty_or_eof(monkeypatch):
    monkeypatch.setattr(cli.console, "input", lambda *a, **k: "")
    assert cli.ask_number("n") is None
    monkeypatch.setattr(cli.console, "input", lambda *a, **k: (_ for _ in ()).throw(EOFError()))
    assert cli.ask_number("n") is None


def test_ask_builds_prompt_and_calls_runner(monkeypatch):
    captured = {}
    monkeypatch.setattr(cli.runner, "run_claude", fake_report(captured))
    monkeypatch.setattr(cli.plonkit, "PlonkitClient", lambda: None)
    result = run.invoke(cli.app, ["ask", "How do I recognise Spain?"])
    assert result.exit_code == 0, result.output
    assert captured["n"] == "ask"
    assert "Question: How do I recognise Spain?" in captured["p"]
    assert "### Spain (es)" in captured["p"]


def test_menu_ask_reads_question_from_console(monkeypatch):
    captured = {}
    answers = iter(["Ask a question", "Quit"])
    monkeypatch.setattr(cli, "pick", lambda options, prompt: next(answers))
    monkeypatch.setattr(
        cli.console, "input", lambda prompt: "Spain plates?" if "question" in prompt else ""
    )
    monkeypatch.setattr(cli, "run_ask", lambda q, model=None: captured.setdefault("q", q))
    assert run.invoke(cli.app, []).exit_code == 0
    assert captured["q"] == "Spain plates?"
