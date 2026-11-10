"""Prompt templates for the Claude-backed modes."""

from __future__ import annotations

from geocoach.analysis import RoundReview
from geocoach.geocode import country_name


def _km(m: float) -> str:
    return f"{m / 1000:.0f} km"


def round_block(
    r: RoundReview,
    images: list[str],
    meta_snippets: list[str],
    clues: list[str] = (),
    meta_pages: list[str] = (),
    plonkit_tips: list[str] = (),
) -> str:
    timing = f", answered in {r.time_to_guess_s:.0f}s" if r.time_to_guess_s else ""
    lines = [
        f"### Round {r.n} of duel {r.game_id[:8]} ({r.mode.upper()}, x{r.multiplier:g})",
        f"- Actual: {country_name(r.country)} ({r.country}) at {r.lat:.4f}, {r.lng:.4f}",
        f"- My guess: {country_name(r.guess_country) or 'none'} at {r.guess_lat:.3f}, "
        f"{r.guess_lng:.3f}, {_km(r.distance_m)} off, {r.my_score} pts{timing}",
        f"- Opponent: {country_name(r.opp_guess_country) or 'none'} at {r.opp_guess_lat:.3f}, "
        f"{r.opp_guess_lng:.3f}, {_km(r.opp_distance_m)} off, {r.opp_score} pts",
        f"- Outcome: {r.loss_type.replace('_', ' ')}, {r.damage_taken} damage taken",
    ]
    if images:
        lines.append("- Images to Read (what I saw, heading as shown in-game):")
        lines += [f"  - {p}" for p in images]
    else:
        lines.append("- No image available for this round.")
    if plonkit_tips:
        lines.append(
            f"- Plonkit, identifying {country_name(r.country)} (call get_plonkit for more):"
        )
        lines += [f"  * {t[:500]}" for t in plonkit_tips]
    if meta_snippets:
        lines.append("- Bonus notes from my community PDFs:")
        lines += [f"  > {s.strip()[:600]}" for s in meta_snippets]
    if clues:
        lines.append(f"- GeoGuessr clue cards for {country_name(r.country)}:")
        lines += [f"  * {c}" for c in clues]
    if meta_pages:
        lines.append("- Meta PDF page(s) about this country, Read if relevant:")
        lines += [f"  - {p}" for p in meta_pages]
    return "\n".join(lines)


def analysis_prompt(
    blocks: list[str], mode_label: str, n_games: int, rating: int | None, summary: dict
) -> str:
    weak = ", ".join(
        f"{country_name(w['country'])} ({w['points_lost']} pts over {w['rounds']} rounds)"
        for w in summary.get("weak_countries", [])[:6]
    )
    conf = ", ".join(
        f"{country_name(c['actual'])} guessed as {country_name(c['guessed'])} x{c['count']}"
        for c in summary.get("confusions", [])[:6]
    )
    header = f"""You are coaching a GeoGuessr duel player (rating about {rating or "unknown"})
who plays {mode_label}. I lost points on the rounds below, taken from my last {n_games} rated
duels. For each round, Read the image(s), then tell me:
1. The visible clues that point to the actual country and region (camera generation, car,
   road lines, bollards, poles, signs, plates, vegetation, soil, architecture, language).
   Be specific about what is in the picture, do not list generic meta that is not visible.
2. Why I likely guessed what I guessed, and the single clue that should have separated the two.
3. For rounds where I had the country but lost on pin: which regional clue narrows the location.

Then a cross-round summary: recurring confusions, whether I answer too fast or too slow, and a
study list of at most 5 items (country or region plus the exact clue to learn). Plonkit is the
base knowledge: call get_plonkit(country, query) to check a clue you see in the image. My PDF
notes are a bonus on top; call get_meta_pages for a country if they look relevant. Keep it concrete.

Aggregates: weakest countries: {weak or "n/a"}. Confusions: {conf or "n/a"}.
Answer in your response only, do not write any file.
"""
    return header + "\n\n" + "\n\n".join(blocks) + "\n"


def encyclopedia_prompt(
    country: str,
    chunks: list[dict],
    page_images: list[str],
    clues: list[str] = (),
    plonkit_sections: list[dict] = (),
    plonkit_images: list[tuple[str, str]] = (),
) -> str:
    notes = "\n\n".join(f"[{c['doc']} p.{c['page']}]\n{c['text']}" for c in chunks)
    pages = "\n".join(f"- {p}" for p in page_images)
    cards = "\n".join(f"- {c}" for c in clues)
    plonkit = "\n\n".join(
        f"## {sec['section']}\n" + "\n".join(f"- {t}" for t in sec["tips"])
        for sec in plonkit_sections
    )
    plonkit_imgs = "\n".join(f"- {path}: {caption}" for caption, path in plonkit_images)
    return f"""Build a GeoGuessr No Move / NMPZ meta sheet for {country_name(country)} ({country}).
Sections: camera generation and car meta, roads and road lines, bollards and poles, signs and
plates, language and domains, landscape and vegetation, regional splits (how to tell north from
south etc.), and the countries it is most confused with and how to separate them.
Plonkit is the base knowledge: structure the sheet from it. My PDF notes are a bonus with
more specific or regional detail. Mark each fact as [plonkit], [doc] (my PDF notes), [gg]
(GeoGuessr clue cards) or [memory] (your own knowledge), and flag anything you are unsure
about. Read the PDF page images for the visual clues. Answer in your response only, do not
write any file.

Plonkit guide:
{plonkit or "(not synced, run: geocoach plonkit)"}

Plonkit images to Read (path: caption):
{plonkit_imgs or "(none)"}

GeoGuessr clue cards:
{cards or "(none)"}

My PDF notes (bonus):
{notes or "(none)"}

Page images to Read:
{pages or "(none)"}
"""
