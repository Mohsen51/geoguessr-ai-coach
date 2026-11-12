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
    plonkit_outline: list[str] = (),
    plonkit_region_tips: list[str] = (),
) -> str:
    timing = f", answered in {r.time_to_guess_s:.0f}s" if r.time_to_guess_s else ""
    region = f", {r.region}" if r.region else ""
    my_region = f", {r.guess_region}" if r.guess_region else ""
    opp_region = f", {r.opp_guess_region}" if r.opp_guess_region else ""
    lines = [
        f"### Round {r.n} of duel {r.game_id[:8]} ({r.mode.upper()}, x{r.multiplier:g})",
        f"- Actual: {country_name(r.country)} ({r.country}){region} at {r.lat:.4f}, {r.lng:.4f}",
        f"- My guess: {country_name(r.guess_country) or 'none'}{my_region} at {r.guess_lat:.3f}, "
        f"{r.guess_lng:.3f}, {_km(r.distance_m)} off, {r.my_score} pts{timing}",
        f"- Opponent: {country_name(r.opp_guess_country) or 'none'}{opp_region} at "
        f"{r.opp_guess_lat:.3f}, {r.opp_guess_lng:.3f}, {_km(r.opp_distance_m)} off, "
        f"{r.opp_score} pts",
        f"- Outcome: {r.loss_type.replace('_', ' ')}, {r.damage_taken} damage taken",
    ]
    if images:
        lines.append("- Images to Read (what I saw, heading as shown in-game):")
        lines += [f"  - {p}" for p in images]
    else:
        lines.append("- No image available for this round.")
    if plonkit_tips:
        lines.append(f"- Plonkit, identifying {country_name(r.country)}:")
        lines += [f"  * {t[:500]}" for t in plonkit_tips]
    if plonkit_region_tips:
        where = f" (actual region {r.region})" if r.region else ""
        lines.append(f"- Plonkit regional clues for {country_name(r.country)}{where}:")
        lines += [f"  * {t[:500]}" for t in plonkit_region_tips]
    if plonkit_outline:
        lines.append(
            f"- More Plonkit sections for {country_name(r.country)}, call "
            f"get_plonkit('{r.country}', query) when a clue you see is not covered above: "
            + "; ".join(plonkit_outline)
        )
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


FOCUS_TEXT = {
    "region": (
        "My priority is regional guessing: I usually get the country, I lose points on the pin. "
        "Spend most of the answer on which regional clues (landscape, soil, vegetation, road "
        "style, poles, plates, architecture, language variants) narrow the location inside the "
        "country, and where the pin should have gone. Country identification only when I missed it."
    ),
    "country": "My priority is country identification; regional narrowing is secondary.",
    "all": "Cover country identification and regional narrowing with equal weight.",
}


def analysis_prompt(
    blocks: list[str],
    mode_label: str,
    n_games: int,
    rating: int | None,
    summary: dict,
    focus: str = "region",
) -> str:
    weak = ", ".join(
        f"{country_name(w['country'])} ({w['points_lost']} pts over {w['rounds']} rounds)"
        for w in summary.get("weak_countries", [])[:6]
    )
    conf = ", ".join(
        f"{country_name(c['actual'])} guessed as {country_name(c['guessed'])} x{c['count']}"
        for c in summary.get("confusions", [])[:6]
    )
    weak_regions = ", ".join(
        f"{w['region']} ({country_name(w['country'])}, {w['points_lost']} pts, "
        f"median {w['median_km']} km)"
        for w in summary.get("weak_regions", [])[:6]
    )
    region_conf = ", ".join(
        f"{c['actual']} guessed as {c['guessed']} ({country_name(c['country'])}) x{c['count']}"
        for c in summary.get("region_confusions", [])[:6]
    )
    header = f"""You are coaching a GeoGuessr duel player (rating about {rating or "unknown"})
who plays {mode_label}. {FOCUS_TEXT.get(focus, FOCUS_TEXT["all"])}
I lost points on the rounds below, taken from my last {n_games} rated duels. For each round,
Read the image(s), then tell me:
1. The visible clues that place the location inside the country (and the country itself when
   I missed it). Be specific about what is in the picture, do not list generic meta that is
   not visible.
2. Why I likely guessed the region I guessed, and the single clue that should have moved the pin.
3. Where the pin should have gone, named as a region or city, and how far that is from my pin.

Format: one section per round whose heading repeats the round heading below exactly
("### Round N of duel XXXXXXXX"), then a final "## Summary" section with a cross-round summary:
recurring confusions, whether I answer too fast or too slow, and a study list of at most 5
items (country or region plus the exact clue to learn). Plonkit is the
base knowledge: the relevant tips are quoted under each round, use them, and call
get_plonkit(country, query) when a clue you see is not covered. My PDF notes are a bonus on
top; call get_meta_pages for a country if they look relevant. End the Summary with one line
naming the Plonkit tips and tools you actually used. Keep it concrete.

Aggregates: weakest countries: {weak or "n/a"}. Country confusions: {conf or "n/a"}.
Weakest regions (country right, pin wrong): {weak_regions or "n/a"}.
Region confusions: {region_conf or "n/a"}.
Answer in your response only, do not write any file.
"""
    return header + "\n\n" + "\n\n".join(blocks) + "\n"


def hits_block(title: str, hits: list[dict]) -> str:
    lines = [f"### {title}"]
    lines += [f"- [{h['doc']} p{h['page']}] {h['text'].strip()[:500]}" for h in hits]
    return "\n".join(lines) if hits else f"### {title}\n- nothing indexed matches"


def country_knowledge_block(
    code: str,
    identifying: list[str],
    matched: list[str],
    regional: list[str],
    notes: list[str],
) -> str:
    name = country_name(code) or code
    lines = [f"### {name} ({code})"]
    if identifying:
        lines.append("- Plonkit, identifying the country:")
        lines += [f"  * {t[:500]}" for t in identifying]
    if matched:
        lines.append("- Plonkit tips matching the question:")
        lines += [f"  * {t[:500]}" for t in matched]
    if regional:
        lines.append("- Plonkit regional clues:")
        lines += [f"  * {t[:500]}" for t in regional]
    if notes:
        lines.append("- Notes from my community PDFs:")
        lines += [f"  > {n.strip()[:600]}" for n in notes]
    if len(lines) == 1:
        lines.append(f"- No plonkit guide indexed for {name}, call get_plonkit('{code}').")
    return "\n".join(lines)


def ask_prompt(question: str, blocks: list[str], pages: list[str] = (), examples: list = ()) -> str:
    header = f"""You are a GeoGuessr coach for a duel player (NM and NMPZ, rating about 900).
Answer the question below from the plonkit tips and PDF notes quoted after it, which were
pre-fetched for the countries named in the question. Call get_plonkit(country, query) or
search_metas(query) for anything the quotes do not cover, and get_meta_pages(country) when my
PDF notes look relevant. Say when a claim comes from your own knowledge rather than from the
sources, and cite the source section inline. Prefer clues visible in NM and NMPZ (no moving).
Keep it concrete: a short answer, then a checklist of the clues to look for, most reliable
first, and the confusions to avoid. End with one line naming the sources and tools you used.
Answer in your response only, do not write any file.

Question: {question}
"""
    if pages:
        header += (
            "\nPDF pages you may Read if useful:\n" + "\n".join(f"- {p}" for p in pages) + "\n"
        )
    if examples:
        listed = "\n".join(f"{i}. {e.image} ({e.tip[:160]})" for i, e in enumerate(examples, 1))
        header += (
            "\nVerified Street View examples, Read each one and refer to it by number where the "
            f"clue is visible:\n{listed}\n"
        )
    return header + "\n" + "\n\n".join(blocks) + "\n"
