"""Orchestrate the analysis and encyclopedia modes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from geocoach import analysis, clues, metas, plonkit, prompts
from geocoach.analysis import RoundReview
from geocoach.duels import Mode
from geocoach.panorama import PanoramaError, ViewFetcher
from geocoach.store import Store


@dataclass
class AnalysisBundle:
    prompt: str
    rounds: list[RoundReview]
    images: dict[tuple[str, int], list[str]]


def mode_label(modes: list[Mode]) -> str:
    return " and ".join(m.value.upper() for m in modes)


def prepare_analysis(
    store: Store,
    fetcher: ViewFetcher | None,
    n_games: int,
    modes: list[Mode],
    max_rounds: int = 12,
    full_pano: bool = False,
    log: Callable[[str], None] = lambda _: None,
    clue_fetch: Callable[[str], list[dict]] | None = None,
    focus: analysis.Focus = "region",
    plonkit_client: plonkit.PlonkitClient | None = None,
) -> AnalysisBundle:
    reviews = analysis.round_reviews(store, n_games, modes)
    picked = analysis.select_rounds_for_review(reviews, max_rounds, focus)
    if plonkit_client is not None:
        ensure_plonkit(store, plonkit_client, {r.country for r in picked if r.country}, log)
    images: dict[tuple[str, int], list[str]] = {}
    blocks = []
    for r in picked:
        paths: list[str] = []
        if fetcher is not None and r.pano_id:
            try:
                views = fetcher.views_for_round(r.pano_id, r.heading, r.mode, r.pitch, full_pano)
                paths = [str(p) for p in views]
            except PanoramaError as exc:
                log(f"round {r.n} of {r.game_id[:8]}: {exc}")
        images[(r.game_id, r.n)] = paths
        snippets = [c["text"] for c in pdf_chunks(store, r.country, 2)]
        cards = clue_lines(clue_fetch, r.country)
        meta_pages = [
            str(metas.render_page(d, p)) for d, p in metas.pages_for_country(store, r.country, 1)
        ]
        tips, region_tips, outline = plonkit_context(store, r)
        blocks.append(
            prompts.round_block(r, paths, snippets, cards, meta_pages, tips, outline, region_tips)
        )
    summary = {
        "weak_countries": analysis.weak_countries(reviews),
        "confusions": analysis.confusions(reviews),
        "weak_regions": analysis.weak_regions(reviews),
        "region_confusions": analysis.region_confusions(reviews),
    }
    rating = next((d["my_rating"] for d in store.recent_duels(1, modes)), None)
    prompt = prompts.analysis_prompt(blocks, mode_label(modes), n_games, rating, summary, focus)
    return AnalysisBundle(prompt=prompt, rounds=picked, images=images)


def ensure_plonkit(
    store: Store,
    client: plonkit.PlonkitClient,
    countries: set[str],
    log: Callable[[str], None] = lambda _: None,
) -> None:
    """Fetch the plonkit guides missing from the local index for these countries."""
    missing = [c for c in sorted(countries) if not plonkit.sections_for_country(store, c)]
    if not missing:
        return
    log(f"fetching plonkit guides for {', '.join(missing)}")
    try:
        plonkit.sync(store, client, missing, log)
    except Exception as exc:  # noqa: BLE001 - offline, continue without plonkit
        log(f"plonkit unavailable: {exc}")


def pdf_chunks(store: Store, country: str, limit: int) -> list[dict]:
    return [
        c for c in metas.chunks_for_country(store, country, limit * 4) if c["kind"] != "plonkit"
    ][:limit]


def identifying_tips(store: Store, country: str, limit: int) -> list[str]:
    sections = plonkit.sections_for_country(store, country)
    return sections[0]["tips"][:limit] if sections else []


def plonkit_context(store: Store, r: RoundReview) -> tuple[list[str], list[str], list[str]]:
    """Identifying tips when the country was missed, regional tips always, plus the outline."""
    names = [n for n in (r.region, r.guess_region if r.country_hit else "") if n]
    region_tips = plonkit.regional_tips(store, r.country, names, 6)
    outline = plonkit.regional_outline(store, r.country, 12)
    if r.loss_type == "lost_on_pin" or r.country_hit:
        return [], region_tips, outline
    return identifying_tips(store, r.country, 5), region_tips, outline


def clue_lines(
    clue_fetch: Callable[[str], list[dict]] | None, country: str, limit: int = 12
) -> list[str]:
    if clue_fetch is None or not country:
        return []
    return clues.format_clues(clues.cached_clues(clue_fetch, country), limit)
