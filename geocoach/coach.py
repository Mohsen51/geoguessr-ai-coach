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
) -> AnalysisBundle:
    reviews = analysis.round_reviews(store, n_games, modes)
    picked = analysis.select_rounds_for_review(reviews, max_rounds)
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
        tips = identifying_tips(store, r.country, 5)
        blocks.append(prompts.round_block(r, paths, snippets, cards, meta_pages, tips))
    summary = {
        "weak_countries": analysis.weak_countries(reviews),
        "confusions": analysis.confusions(reviews),
    }
    rating = next((d["my_rating"] for d in store.recent_duels(1, modes)), None)
    prompt = prompts.analysis_prompt(blocks, mode_label(modes), n_games, rating, summary)
    return AnalysisBundle(prompt=prompt, rounds=picked, images=images)


def pdf_chunks(store: Store, country: str, limit: int) -> list[dict]:
    return [
        c for c in metas.chunks_for_country(store, country, limit * 4) if c["kind"] != "plonkit"
    ][:limit]


def identifying_tips(store: Store, country: str, limit: int) -> list[str]:
    sections = plonkit.sections_for_country(store, country)
    return sections[0]["tips"][:limit] if sections else []


def clue_lines(
    clue_fetch: Callable[[str], list[dict]] | None, country: str, limit: int = 12
) -> list[str]:
    if clue_fetch is None or not country:
        return []
    return clues.format_clues(clues.cached_clues(clue_fetch, country), limit)


def prepare_encyclopedia(
    store: Store,
    country: str,
    max_pages: int = 6,
    clue_fetch: Callable[[str], list[dict]] | None = None,
    plonkit_client: plonkit.PlonkitClient | None = None,
    max_plonkit_images: int = 0,
    log: Callable[[str], None] = lambda _: None,
) -> str:
    country = country.lower()
    sections = plonkit.sections_for_country(store, country)
    images: list[tuple[str, str]] = []
    if plonkit_client is not None:
        entry = plonkit.guide_for_country(plonkit_client.guide_index(), country)
        if entry:
            if not sections:
                log(f"fetching plonkit guide for {entry['slug']}")
                plonkit.sync(store, plonkit_client, [country])
                sections = plonkit.sections_for_country(store, country)
            if max_plonkit_images:
                guide = plonkit_client.guide(entry["slug"])
                images = [
                    (cap, str(p))
                    for cap, p in plonkit.images_for_guide(
                        plonkit_client, entry["slug"], guide, max_plonkit_images
                    )
                ]
    chunks = pdf_chunks(store, country, 30)
    page_refs = metas.pages_for_country(store, country, max_pages)
    if page_refs:
        log(f"rendering {len(page_refs)} PDF pages")
    pages = [str(metas.render_page(d, p)) for d, p in page_refs]
    cards = clue_lines(clue_fetch, country, 20)
    return prompts.encyclopedia_prompt(country, chunks, pages, cards, sections, images)
