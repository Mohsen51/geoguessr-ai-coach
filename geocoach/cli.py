"""geocoach CLI: fzf menus plus scriptable subcommands."""

from __future__ import annotations

import subprocess
import sys
import webbrowser
from collections.abc import Sequence

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table

from geocoach import analysis, coach, config, metas, plonkit, runner, sheets, slashp, sync
from geocoach.duels import Mode
from geocoach.geocode import country_name
from geocoach.store import Store

app = typer.Typer(add_completion=False, no_args_is_help=False, invoke_without_command=True)
console = Console()
err = Console(stderr=True)

MODE_CHOICES = {"nm": [Mode.NM], "nmpz": [Mode.NMPZ], "both": [Mode.NM, Mode.NMPZ]}
LAST_CHOICES = (5, 10, 15)


def pick(options: Sequence[str], prompt: str) -> str | None:
    """Let the user choose one option with fzf. Returns None if cancelled."""
    try:
        proc = subprocess.run(
            ["fzf", "--prompt", f"{prompt} > ", "--height", "40%", "--reverse"],
            input="\n".join(options),
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        err.print("[red]fzf not found. Install it (brew install fzf) or use subcommands.[/red]")
        raise typer.Exit(1) from None
    choice = proc.stdout.strip()
    return choice or None


def modes_of(mode: str) -> list[Mode]:
    try:
        return MODE_CHOICES[mode.lower()]
    except KeyError:
        raise typer.BadParameter("mode must be nm, nmpz or both") from None


def open_store() -> Store:
    config.ensure_dirs()
    return Store(config.DB_PATH)


def make_client(required: bool = True):
    from geocoach.gg_api import GeoGuessrClient

    try:
        return GeoGuessrClient(config.get_cookie())
    except config.MissingCookieError as exc:
        if not required:
            return None
        err.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from None


def do_sync(store: Store, last: int, modes: list[Mode]) -> int:
    client = make_client()
    try:
        return sync.sync(store, client, last, modes, log=lambda m: err.print(f"[dim]{m}[/dim]"))
    finally:
        client.close()


@app.callback()
def main(ctx: typer.Context) -> None:
    """GeoGuessr duel coach. Run without arguments for the menu."""
    if ctx.invoked_subcommand is not None:
        return
    menu = {
        "Analyze recent duels": _menu_analyze,
        "Training map": _menu_training,
        "Encyclopedia": _menu_encyclopedia,
        "Stats": _menu_stats,
        "Sync duels": _menu_sync,
        "Sync plonkit guides": run_plonkit,
        "Build encyclopedia sheets": run_build_sheets,
        "Ingest meta PDFs": run_ingest,
        "Digest PDF images with Claude": run_digest,
        "Help": show_help,
        "Quit": None,
    }
    while True:
        choice = pick(list(menu), "geocoach")
        if not choice or menu[choice] is None:
            return
        try:
            menu[choice]()
        except typer.Exit:
            pass
        except Exception as exc:  # noqa: BLE001 - keep the menu alive, show the error
            err.print(f"[red]{type(exc).__name__}: {exc}[/red]")
        pause()


MENU_HELP = """\
# geocoach menu

Every entry asks its inputs with fzf, runs, then waits for Enter before the menu comes back.
Esc or Ctrl-C at any prompt returns to the menu or quits. Each entry has a subcommand twin.

- **Analyze recent duels** (`geocoach analyze --last N --mode nm|nmpz|both`, options
  `--focus region|country|all`, `--model opus`):
  syncs new rated duels, picks the lost rounds with the most points lost (pin losses first),
  fetches the Street View views, and asks Claude (Sonnet by default) to read them against
  plonkit's regional clues, your PDF notes and the GeoGuessr clue cards. Report in `data/reports/`.
  One to three minutes.
- **Training map** (`geocoach training`): ranks slashP maps by how much they cover your weak
  countries, lets you pick one and opens it. No Claude.
- **Encyclopedia** (`geocoach encyclopedia <cc>`): shows the plonkit-based sheet from
  `encyclopedia/`, regional sections first. Instant, no Claude.
- **Stats** (`geocoach stats`): weak countries and regions, region and country confusions,
  time-to-guess buckets, rating trend. Local only.
- **Sync duels** (`geocoach sync`): fetches rated duels and geocodes every location and guess.
  Analyze does this itself; use it before Stats or Training.
- **Sync plonkit guides** (`geocoach plonkit`): refreshes the local plonkit index used by Analyze.
  Paced, with backoff. Rarely needed.
- **Build encyclopedia sheets** (`geocoach build-sheets`): renders the sheets from the cached
  guides. The monthly workflow does this for the repo.
- **Ingest meta PDFs** (`geocoach ingest [--force]`): indexes new or changed PDFs from `metas/`.
- **Digest PDF images with Claude** (`geocoach digest`): describes image-only PDF pages with
  Haiku so maps and photos become searchable. Incremental.

Secrets: `GEOGUESSR_NCFA` in `.envrc` or `.env`. Data and caches live in `data/`.
"""


def show_help() -> None:
    console.print(Markdown(MENU_HELP))


def pause() -> None:
    """Wait for Enter before showing the menu again, so output stays readable."""
    try:
        console.input("\n[dim]Press Enter to return to the menu...[/dim]")
    except (EOFError, KeyboardInterrupt):
        raise typer.Exit(0) from None


def _ask_last_and_mode() -> tuple[int, str]:
    last = pick([str(n) for n in LAST_CHOICES], "last N duels")
    mode = pick(list(MODE_CHOICES), "mode") if last else None
    if not last or not mode:
        raise typer.Exit(0)
    return int(last), mode


def _menu_analyze() -> None:
    last, mode = _ask_last_and_mode()
    run_analyze(last, mode)


def _menu_training() -> None:
    last, mode = _ask_last_and_mode()
    run_training(last, mode)


def _menu_stats() -> None:
    last, mode = _ask_last_and_mode()
    run_stats(last, mode)


def _menu_sync() -> None:
    last, mode = _ask_last_and_mode()
    run_sync(last, mode)


def _menu_encyclopedia() -> None:
    codes = sheets.available_codes()
    options = [f"{c}  {country_name(c)}" for c in codes] or [
        "(no sheets, run: geocoach build-sheets)"
    ]
    choice = pick(options, "country")
    if not choice or choice.startswith("("):
        raise typer.Exit(0)
    run_encyclopedia(choice.split()[0])


def run_analyze(
    last: int = 10,
    mode: str = "both",
    max_rounds: int = 12,
    full: bool = False,
    model: str = runner.ANALYSIS_MODEL,
    no_sync: bool = False,
    focus: str = "region",
) -> None:
    from geocoach.panorama import ViewFetcher

    if focus not in ("region", "country", "all"):
        raise typer.BadParameter("focus must be region, country or all")
    modes = modes_of(mode)
    store = open_store()
    if not no_sync:
        do_sync(store, last, modes)
    fetcher = ViewFetcher()
    client = make_client(required=False)
    try:
        bundle = coach.prepare_analysis(
            store,
            fetcher,
            last,
            modes,
            max_rounds,
            full,
            log=lambda m: err.print(f"[dim]{m}[/dim]"),
            clue_fetch=client.country_clues if client else None,
            focus=focus,  # type: ignore[arg-type]
        )
    finally:
        fetcher.close()
        if client:
            client.close()
    if not bundle.rounds:
        console.print("No lost rounds found in the selected duels.")
        raise typer.Exit(0)
    err.print(
        f"[dim]reviewing {len(bundle.rounds)} rounds, asking Claude, "
        "this usually takes one to three minutes...[/dim]"
    )
    report = runner.run_claude(bundle.prompt, f"analysis_{mode}_{last}", model)
    err.print(f"[green]report saved to {report}[/green]")


@app.command()
def analyze(
    last: int = typer.Option(10, "--last", help="number of rated duels"),
    mode: str = typer.Option("both", "--mode", help="nm, nmpz or both"),
    max_rounds: int = typer.Option(12, help="max rounds to review"),
    full: bool = typer.Option(False, "--full", help="three views per round"),
    model: str = typer.Option(runner.ANALYSIS_MODEL, help="claude model: sonnet, opus, fable"),
    no_sync: bool = typer.Option(False, "--no-sync", help="skip fetching new duels"),
    focus: str = typer.Option("region", help="region (default), country or all"),
) -> None:
    """Review the rounds where you lost the most points with Claude."""
    run_analyze(last, mode, max_rounds, full, model, no_sync, focus)


def run_training(
    last: int = 10,
    mode: str = "both",
    min_locations: int = 5000,
    subdivisions: bool = False,
    no_open: bool = False,
) -> None:
    store = open_store()
    reviews = analysis.round_reviews(store, last, modes_of(mode))
    weak = {w["country"]: float(w["points_lost"]) for w in analysis.weak_countries(reviews)}
    if not weak:
        console.print("No duels stored yet. Run: geocoach sync")
        raise typer.Exit(0)
    cats = slashp.DEFAULT_CATEGORIES + (("Subdivision",) if subdivisions else ())
    recs = slashp.recommend(slashp.load_maps(), weak, min_locations, cats)
    if not recs:
        console.print("No matching map found.")
        raise typer.Exit(0)
    labels = [
        f"{r['name']}  [{r['category']}, {r['locations']} locs, {r['coverage']:.0%} weak, "
        f"{', '.join(r['weak_countries_covered'][:4])}]"
        for r in recs
    ]
    if no_open:
        for lbl, r in zip(labels, recs, strict=True):
            console.print(f"{lbl}\n  {r['url']}")
        return
    choice = pick(labels, "map")
    if choice:
        url = recs[labels.index(choice)]["url"]
        console.print(url)
        webbrowser.open(url)


@app.command()
def training(
    last: int = typer.Option(10, "--last"),
    mode: str = typer.Option("both", "--mode"),
    min_locations: int = typer.Option(5000),
    subdivisions: bool = typer.Option(False, help="include subdivision maps"),
    no_open: bool = typer.Option(False, "--no-open", help="do not open the chosen map"),
) -> None:
    """Suggest slashP maps covering your weak countries."""
    run_training(last, mode, min_locations, subdivisions, no_open)


def run_encyclopedia(country: str) -> None:
    text = sheets.read_sheet(country)
    if text is None:
        console.print(
            f"No sheet for {country!r}. Sheets live in encyclopedia/ and are built from plonkit "
            "by the monthly workflow; run `geocoach build-sheets` after `geocoach plonkit`."
        )
        raise typer.Exit(1)
    console.print(Markdown(text))


@app.command()
def encyclopedia(country: str = typer.Argument(..., help="ISO code, e.g. br")) -> None:
    """Show the plonkit-based sheet for one country (encyclopedia/<cc>.md)."""
    run_encyclopedia(country)


def run_build_sheets() -> None:
    written = sheets.build_all()
    console.print(f"{len(written)} sheets in {sheets.SHEETS_DIR}")


@app.command("build-sheets")
def build_sheets_cmd() -> None:
    """Render encyclopedia/<cc>.md for every cached plonkit guide."""
    run_build_sheets()


def run_stats(last: int = 10, mode: str = "both") -> None:
    store = open_store()
    modes = modes_of(mode)
    reviews = analysis.round_reviews(store, last, modes)
    if not reviews:
        console.print("No duels stored yet. Run: geocoach sync")
        raise typer.Exit(0)
    t = Table(title=f"Weak countries, last {last} duels ({mode})")
    for col in ("country", "rounds", "hit rate", "pts lost", "on country", "on pin", "km when hit"):
        t.add_column(col)
    for w in analysis.weak_countries(reviews)[:15]:
        t.add_row(
            country_name(w["country"]), str(w["rounds"]), f"{w['hit_rate']:.0%}",
            str(w["points_lost"]), str(w["lost_on_country"]), str(w["lost_on_pin"]),
            "" if w["median_km_when_hit"] is None else str(w["median_km_when_hit"]),
        )  # fmt: skip
    console.print(t)
    wr = Table(title="Weak regions (country right, pin wrong)")
    for col in ("country", "region", "rounds", "region hit", "pts lost", "median km"):
        wr.add_column(col)
    for w in analysis.weak_regions(reviews)[:15]:
        wr.add_row(
            country_name(w["country"]), w["region"], str(w["rounds"]),
            f"{w['region_hit_rate']:.0%}", str(w["points_lost"]), str(w["median_km"]),
        )  # fmt: skip
    console.print(wr)
    rc = Table(title="Region confusions")
    rc.add_column("country"), rc.add_column("actual"), rc.add_column("guessed"), rc.add_column("n")
    for row in analysis.region_confusions(reviews)[:10]:
        rc.add_row(country_name(row["country"]), row["actual"], row["guessed"], str(row["count"]))
    console.print(rc)
    c = Table(title="Country confusions")
    c.add_column("actual"), c.add_column("guessed"), c.add_column("n")
    for row in analysis.confusions(reviews)[:10]:
        c.add_row(country_name(row["actual"]), country_name(row["guessed"]), str(row["count"]))
    console.print(c)
    tb = Table(title="Time to guess")
    tb.add_column("bucket"), tb.add_column("rounds"), tb.add_column("avg score")
    for b in analysis.time_buckets(reviews):
        tb.add_row(b["bucket"], str(b["rounds"]), str(b["avg_score"]))
    console.print(tb)
    tr = analysis.rating_trend(store, last, modes)
    ratings = [str(d["my_rating"]) for d in tr if d["my_rating"] is not None]
    console.print(f"Rating trend (oldest to newest): {' -> '.join(ratings) or 'n/a'}")


@app.command()
def stats(
    last: int = typer.Option(10, "--last"),
    mode: str = typer.Option("both", "--mode"),
) -> None:
    """Local tables: weak countries, confusions, timing, damage, rating."""
    run_stats(last, mode)


def run_sync(last: int = 15, mode: str = "both") -> None:
    added = do_sync(open_store(), last, modes_of(mode))
    console.print(f"{added} new duels stored")


@app.command("sync")
def sync_cmd(
    last: int = typer.Option(15, "--last"),
    mode: str = typer.Option("both", "--mode"),
) -> None:
    """Fetch recent rated duels into the local database."""
    run_sync(last, mode)


def run_plonkit(countries: list[str] | None = None) -> None:
    client = plonkit.PlonkitClient()
    try:
        n = plonkit.sync(
            open_store(), client, countries, log=lambda m: err.print(f"[dim]{m}[/dim]")
        )
    finally:
        client.close()
    console.print(f"{n} plonkit guides indexed")


COUNTRY_OPTION = typer.Option(None, "--country", help="ISO codes, default all guides")


@app.command("plonkit")
def plonkit_cmd(country: list[str] = COUNTRY_OPTION) -> None:
    """Fetch and index plonkit guides (base knowledge for every mode)."""
    run_plonkit(country or None)


def run_ingest(force: bool = False) -> None:
    n = metas.ingest(open_store(), log=lambda m: err.print(f"[dim]{m}[/dim]"), force=force)
    console.print(f"{n} documents indexed")


@app.command()
def ingest(force: bool = typer.Option(False, "--force", help="re-index unchanged PDFs")) -> None:
    """Index the PDFs in metas/."""
    run_ingest(force)


def run_digest(batch: int = 8, doc: str | None = None, model: str = runner.DIGEST_MODEL) -> None:
    from geocoach import digest as digest_mod

    n = digest_mod.digest(
        open_store(), batch=batch, doc_filter=doc, model=model,
        log=lambda m: err.print(f"[dim]{m}[/dim]"),
    )  # fmt: skip
    console.print(f"{n} pages digested")


@app.command()
def digest(
    batch: int = typer.Option(8, help="page images per Claude call"),
    doc: str | None = typer.Option(None, help="only PDFs whose name contains this"),
    model: str = typer.Option(runner.DIGEST_MODEL, help="claude model, haiku is enough here"),
) -> None:
    """Describe image-heavy PDF pages with Claude so maps and photos become searchable."""
    run_digest(batch, doc, model)


if __name__ == "__main__":
    sys.exit(app())
