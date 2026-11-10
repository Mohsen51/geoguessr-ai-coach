"""Orchestrate the analysis and encyclopedia modes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from geocoach import analysis, metas, prompts
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
        snippets = [c["text"] for c in metas.chunks_for_country(store, r.country, limit=2)]
        blocks.append(prompts.round_block(r, paths, snippets))
    summary = {
        "weak_countries": analysis.weak_countries(reviews),
        "confusions": analysis.confusions(reviews),
    }
    rating = next((d["my_rating"] for d in store.recent_duels(1, modes)), None)
    prompt = prompts.analysis_prompt(blocks, mode_label(modes), n_games, rating, summary)
    return AnalysisBundle(prompt=prompt, rounds=picked, images=images)


def prepare_encyclopedia(store: Store, country: str, max_pages: int = 6) -> str:
    country = country.lower()
    chunks = metas.chunks_for_country(store, country, limit=30)
    pages = [
        str(metas.render_page(d, p)) for d, p in metas.pages_for_country(store, country, max_pages)
    ]
    return prompts.encyclopedia_prompt(country, chunks, pages)
