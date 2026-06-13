"""Research-oriented Markdown rendering of the DSO catalog.

Different audience from ``report.write_dso_plan``: this is for *offline*
planning — pre-reading on targets before a session, comparing against
Astrobin examples, deciding which to prioritize. It shows every catalog
entry (not just observable ones), groups by best-observing season,
includes sexagesimal coordinates, expected emission-line behavior by
object type, and per-target links to SIMBAD / NED / Wikipedia /
Telescopius / Astrobin / Aladin.
"""
from __future__ import annotations

from urllib.parse import quote_plus

from .catalog import DsoCatalog, DsoTarget


# Seasons keyed off the RA hour at which the target transits at local
# midnight. Picked the conventional Northern-Hemisphere observing seasons.
SEASONS_ORDER = (
    "Winter (Dec–Feb)",
    "Spring (Mar–May)",
    "Summer (Jun–Aug)",
    "Autumn (Sep–Nov)",
)


# Per-object-type narrowband emission cheat sheet. Drives the
# "expected emission" line so the research notes don't require reading
# the catalog notes for every target to know what to expect from each
# filter. These are rules of thumb; reality varies per target.
EMISSION_BY_TYPE: dict[str, str] = {
    "HII": "Ha-dominant; OIII varies (often faint, sometimes strong as in M16/M17 cores); SII for SHO palette",
    "PN":  "OIII typically dominant; Ha bright in core, often a faint outer halo worth long subs",
    "SNR": "OIII strong in shocked filaments; Ha & SII trace remnant outer shells",
    "WR":  "OIII shell is the headline; Ha shows surrounding ISM; SII weaker",
    "DARK": "No narrowband emission — silhouette target; broadband L+RGB",
    "REF": "No narrowband emission — pure reflection; broadband L+RGB. Ha sometimes useful for embedded HII",
    "OPEN": "Stars — narrowband not useful unless surrounded by HII",
    "GLOB": "Stars — narrowband not useful",
}


def render_research_notes(catalog: DsoCatalog) -> str:
    """Render the full catalog as a research-oriented Markdown document.

    Output structure:
      1. Header + counts + table-of-contents (one row per target with the
         most useful at-a-glance facts)
      2. Per-season sections, alphabetized within season by RA, each
         target getting a detail block with coords + budget + emission
         hint + external research links + catalog notes.
    """
    lines: list[str] = []
    lines.append("# DSO catalog — research notes")
    lines.append("")
    lines.append(
        f"Catalog v{catalog.version} • {len(catalog.targets)} targets • "
        "regenerate with `mira dso research`."
    )
    lines.append("")
    lines.append(
        "This is the offline-research view of the catalog — every target, "
        "grouped by best-observing season, with external links for "
        "deeper reading. For *which targets are observable tonight*, run "
        "`mira dso plan` instead."
    )
    lines.append("")

    # Group targets by season; sort each season by RA ascending so the
    # reader walks the sky west-to-east within their imaging window.
    by_season: dict[str, list[DsoTarget]] = {s: [] for s in SEASONS_ORDER}
    for target in catalog.targets:
        by_season[_season_for(target)].append(target)
    for season in SEASONS_ORDER:
        by_season[season].sort(key=lambda t: t.ra_deg)

    # Table of contents — all targets in one scannable table.
    lines.append("## Index")
    lines.append("")
    lines.append(
        "| Target | Common | Type | Const | RA (J2000) | Dec | Size | Mosaic |"
    )
    lines.append("|---|---|---|---|---|---|---|---|")
    for season in SEASONS_ORDER:
        if not by_season[season]:
            continue
        for target in by_season[season]:
            mosaic = "yes" if target.mosaic else ""
            size = f"{target.size_arcmin[0]:.0f}' × {target.size_arcmin[1]:.0f}'"
            # Anchor must slug the FULL detail-heading text ("name — common"),
            # not just the name — GitHub-style renderers derive the anchor
            # from the whole heading, so a name-only slug is a dead link.
            anchor = _slug(_heading_text(target))
            lines.append(
                f"| [`{target.name}`](#{anchor}) | {target.common_name} | "
                f"{target.object_type} | {target.constellation} | "
                f"{_ra_hms(target.ra_deg)} | {_dec_dms(target.dec_deg)} | "
                f"{size} | {mosaic} |"
            )
    lines.append("")

    # Per-season detail sections.
    for season in SEASONS_ORDER:
        targets = by_season[season]
        if not targets:
            continue
        lines.append(f"## {season}")
        lines.append("")
        lines.append(
            f"_{len(targets)} target(s). "
            "RA range listed first; suggested observing months in parentheses._"
        )
        lines.append("")
        for target in targets:
            lines.extend(_render_target(target))
    return "\n".join(lines) + "\n"


def _render_target(target: DsoTarget) -> list[str]:
    lines: list[str] = []
    lines.append(f"### {_heading_text(target)}")
    lines.append("")
    # Header line: quick orient
    type_full = _type_long_name(target.object_type)
    fov_note = "single frame" if not target.mosaic else "**mosaic candidate**"
    size = f"{target.size_arcmin[0]:.0f}' × {target.size_arcmin[1]:.0f}'"
    lines.append(
        f"**{type_full}** in **{target.constellation}** • "
        f"{size} • {fov_note}"
    )
    lines.append("")
    # Coordinates
    lines.append(
        f"- **Coords (J2000):** RA `{_ra_hms(target.ra_deg)}` "
        f"({target.ra_deg:.4f}°) / Dec `{_dec_dms(target.dec_deg)}` "
        f"({target.dec_deg:+.4f}°)"
    )
    # Budget
    budget_str = " • ".join(
        f"{f} {m}m" for f, m in target.budget_minutes.items()
    )
    total_h = target.total_budget_minutes / 60.0
    lines.append(
        f"- **Recommended budget:** {budget_str} "
        f"(total {total_h:.1f}h)"
    )
    # Emission hint
    emission = EMISSION_BY_TYPE.get(target.object_type, "")
    if emission:
        lines.append(f"- **Expected emission:** {emission}")
    # Catalog notes
    if target.notes:
        lines.append(f"- **Catalog notes:** {target.notes}")
    # Research links
    lines.append(f"- **Research:** {_research_links(target)}")
    lines.append("")
    return lines


def _research_links(target: DsoTarget) -> str:
    """One-line set of external links per target. Most useful for offline
    research: SIMBAD for catalog data, Telescopius for FOV preview, Astrobin
    for community examples, Aladin for quick sky-position visual.

    Wikipedia is linked by common_name when present — won't always resolve
    but is high-value when it does (Crab/Helix/Ring/Veil all have great
    Wikipedia pages)."""
    name_q = quote_plus(target.name)
    common_q = quote_plus(target.common_name) if target.common_name else name_q
    parts = [
        f"[SIMBAD](https://simbad.cds.unistra.fr/simbad/sim-id?Ident={name_q})",
        f"[Aladin](https://aladin.u-strasbg.fr/AladinLite/?target={name_q}&fov=2)",
        f"[NED](https://ned.ipac.caltech.edu/byname?objname={name_q})",
        f"[Telescopius](https://telescopius.com/deep-sky-targets?searched={common_q})",
        f"[Astrobin](https://www.astrobin.com/search/?q={common_q})",
    ]
    if target.common_name and target.common_name != target.name:
        # Wikipedia is best-effort: the URL with the common name often works.
        wiki_slug = target.common_name.replace(" ", "_")
        wiki_url = f"https://en.wikipedia.org/wiki/{quote_plus(wiki_slug, safe='_')}"
        parts.append(f"[Wikipedia]({wiki_url})")
    return " • ".join(parts)


def _ra_hms(ra_deg: float) -> str:
    """RA in degrees → 'HHh MMm SS.Ss' sexagesimal. RA is hours since the
    prime meridian, so deg/15."""
    hours_total = (ra_deg % 360.0) / 15.0
    h = int(hours_total)
    m_total = (hours_total - h) * 60
    m = int(m_total)
    s = (m_total - m) * 60
    return f"{h:02d}h {m:02d}m {s:04.1f}s"


def _dec_dms(dec_deg: float) -> str:
    """Dec in degrees → '±DD° MM\\' SS.S\"' sexagesimal."""
    sign = "+" if dec_deg >= 0 else "-"
    abs_dec = abs(dec_deg)
    d = int(abs_dec)
    m_total = (abs_dec - d) * 60
    m = int(m_total)
    s = (m_total - m) * 60
    return f"{sign}{d:02d}° {m:02d}' {s:04.1f}\""


def _season_for(target: DsoTarget) -> str:
    """Best-transit-at-midnight season for a target's RA. Northern-hemisphere
    convention (RA hour 0 transits at midnight in autumn equinox)."""
    ra_hours = target.ra_deg / 15.0
    if 4 <= ra_hours < 10:
        return "Winter (Dec–Feb)"
    if 10 <= ra_hours < 16:
        return "Spring (Mar–May)"
    if 16 <= ra_hours < 22:
        return "Summer (Jun–Aug)"
    return "Autumn (Sep–Nov)"


_TYPE_LONG_NAMES = {
    "HII": "Emission nebula (HII region)",
    "PN": "Planetary nebula",
    "SNR": "Supernova remnant",
    "WR": "Wolf-Rayet bubble",
    "DARK": "Dark nebula",
    "REF": "Reflection nebula / galaxy",
    "OPEN": "Open cluster",
    "GLOB": "Globular cluster",
}


def _type_long_name(code: str) -> str:
    return _TYPE_LONG_NAMES.get(code, code)


def _heading_text(target: DsoTarget) -> str:
    """The exact per-target detail heading. The index anchors slug THIS
    string — heading and anchor must be built from the same text or every
    TOC link goes dead."""
    return f"{target.name} — {target.common_name}"


def _slug(heading: str) -> str:
    """Markdown anchor slug — what GitHub-style renderers turn a heading
    into: lowercase; keep word chars (alnum + underscore) and hyphens; turn
    spaces into hyphens; drop all other punctuation. The em-dash in our
    "name — common" headings is itself dropped but both flanking spaces
    survive as hyphens, so the anchor carries a double hyphen — verified by
    hand against GitHub: "NGC 6888 — Crescent Nebula" →
    "ngc-6888--crescent-nebula"."""
    out: list[str] = []
    for ch in heading.lower():
        if ch.isalnum() or ch in ("_", "-"):
            out.append(ch)
        elif ch == " ":
            out.append("-")
        # other punctuation dropped
    return "".join(out)
