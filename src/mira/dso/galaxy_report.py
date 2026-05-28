"""Galaxy plan output: Markdown for humans, CSV for ingestion.

The galaxy path (`mira galaxies`) shares the DSO planner engine but wants a
different presentation than the narrowband ``dso_plan`` — surface
brightness and integrated magnitude are the headline numbers, and the
mosaic/per-line-budget framing of narrowband targets is irrelevant. So
this is a dedicated writer rather than a branch inside
``report.write_dso_plan``.

Two files per run:
- ``galaxy_plan.md`` — ranked queue + per-target detail. Phone-readable.
- ``galaxy_plan.csv`` — flat rows for spreadsheet triage / NINA import.
"""
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import Iterable

from .ledger import Ledger
from .planner import DsoCandidate


def write_galaxy_plan(
    candidates: Iterable[DsoCandidate],
    out_dir: Path,
    *,
    config_path: str,
    catalog_version: str,
    start_date: date,
    window_nights: int,
    sb_limit_mag_arcsec2: float | None = None,
    ledger: Ledger | None = None,
) -> tuple[Path, Path]:
    """Write galaxy_plan.md and galaxy_plan.csv to ``out_dir``. Returns both."""
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / "galaxy_plan.md"
    csv_path = out_dir / "galaxy_plan.csv"
    md_path.write_text(_render_markdown(
        candidates,
        config_path=config_path,
        catalog_version=catalog_version,
        start_date=start_date,
        window_nights=window_nights,
        sb_limit_mag_arcsec2=sb_limit_mag_arcsec2,
        ledger=ledger,
    ), encoding="utf-8")
    _write_csv(candidates, csv_path)
    return md_path, csv_path


def _flags(cand: DsoCandidate) -> str:
    """Short, glanceable flags for the ranked table."""
    parts: list[str] = []
    if cand.dark_site_only:
        parts.append("🌑 dark-site")
    if cand.under_sampled:
        parts.append("🔬 small")
    return " ".join(parts)


def _render_markdown(
    candidates: Iterable[DsoCandidate],
    *,
    config_path: str,
    catalog_version: str,
    start_date: date,
    window_nights: int,
    sb_limit_mag_arcsec2: float | None,
    ledger: Ledger | None,
) -> str:
    cands = list(candidates)
    lines: list[str] = []
    lines.append("# Galaxy plan")
    lines.append("")
    ledger_note = ""
    if ledger is not None:
        ledger_note = (
            f" • ledger: {len(ledger.sessions)} session(s) over "
            f"{len(ledger.by_target)} target(s)"
        )
    sb_note = (
        f" • dark-site SB floor {sb_limit_mag_arcsec2:.1f} mag/arcsec²"
        if sb_limit_mag_arcsec2 is not None else ""
    )
    lines.append(
        f"Generated for {window_nights} night(s) starting "
        f"{start_date.isoformat()} • config: `{config_path}` • "
        f"catalog v{catalog_version} • {len(cands)} viable galaxies"
        f"{sb_note}{ledger_note}"
    )
    lines.append("")
    lines.append(
        "_Ranked by observability × surface brightness "
        "(× integration deficit when a ledger is present). Surface "
        "brightness — not integrated magnitude — drives the ranking: it's "
        "what survives urban light pollution on a small OSC scope._"
    )
    lines.append("")
    lines.append("## Ranked queue")
    lines.append("")
    if not cands:
        lines.append("_No catalog galaxies are observable in this window._")
        lines.append("")
        return "\n".join(lines)
    ledger_active = ledger is not None
    cols = [
        "#", "Target", "Common", "Const", "Mag", "SB", "Size (arcmin)",
        "Best site", "Dark min", "Peak alt", "Best night", "Flags",
    ]
    if ledger_active:
        cols += ["Captured", "Budget", "% Done"]
    cols += ["Score"]
    lines.append("| " + " | ".join(cols) + " |")
    lines.append("|" + "|".join("---" for _ in cols) + "|")
    for index, cand in enumerate(cands, 1):
        target = cand.target
        best = cand.best_observability
        size = f"{target.size_arcmin[0]:.0f} × {target.size_arcmin[1]:.0f}"
        night = best.best_night_date.isoformat() if best.best_night_date else "—"
        mag = f"{target.magnitude:.1f}" if target.magnitude is not None else "—"
        sb = (
            f"{cand.surface_brightness:.1f}"
            if cand.surface_brightness is not None else "—"
        )
        row = (
            f"| {index} | `{target.name}` | {target.common_name} | "
            f"{target.constellation} | {mag} | {sb} | {size} | "
            f"{best.site_name} | {best.minutes_above_minimum} | "
            f"{best.max_altitude_deg:.1f}° | {night} | {_flags(cand)} |"
        )
        if ledger_active:
            pct = cand.completion_fraction * 100.0
            done_tag = " ✓" if pct >= 100 else ""
            row += (
                f" {cand.captured_minutes:.0f}m | {cand.budget_minutes:.0f}m | "
                f"{pct:.0f}%{done_tag} | {cand.score:.1f} |"
            )
        else:
            row += f" {cand.score:.1f} |"
        lines.append(row)
    lines.append("")
    lines.append("## Per-target detail")
    lines.append("")
    for index, cand in enumerate(cands, 1):
        target = cand.target
        lines.append(f"### {index}. {target.name} — {target.common_name}")
        lines.append("")
        lines.append(f"- **Type:** galaxy in {target.constellation}  ")
        lines.append(
            f"- **Coords (J2000):** RA {target.ra_deg:.4f}° / "
            f"Dec {target.dec_deg:+.4f}°  "
        )
        if target.magnitude is not None:
            sb_txt = (
                f", mean SB {cand.surface_brightness:.1f} mag/arcsec²"
                if cand.surface_brightness is not None else ""
            )
            lines.append(f"- **Brightness:** mag {target.magnitude:.1f}{sb_txt}  ")
        lines.append(
            f"- **Size:** {target.size_arcmin[0]:.0f}' × "
            f"{target.size_arcmin[1]:.0f}'  "
        )
        budgets = ", ".join(f"{f}: {m}m" for f, m in target.budget_minutes.items())
        lines.append(f"- **Suggested integration:** {budgets}  ")
        lines.append("- **Why this rank:**  ")
        for reason in cand.reasons:
            lines.append(f"  - {reason}")
        if ledger is not None and cand.budget_minutes > 0:
            lines.append("- **Captured so far (per filter):**  ")
            for filter_name, budget in target.budget_minutes.items():
                captured = ledger.minutes(target.name, filter_name)
                pct = (captured / budget * 100.0) if budget else 0.0
                done_tag = " ✓" if captured >= budget else ""
                lines.append(
                    f"  - {filter_name}: {captured:.0f} / {budget} min "
                    f"({pct:.0f}%){done_tag}"
                )
        if target.notes:
            lines.append(f"- **Notes:** {target.notes}")
        lines.append("")
    return "\n".join(lines)


def _write_csv(candidates: Iterable[DsoCandidate], path: Path) -> None:
    cands = list(candidates)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "rank", "name", "common_name", "constellation",
            "ra_deg", "dec_deg", "magnitude", "surface_brightness",
            "size_major_arcmin", "size_minor_arcmin",
            "best_site", "dark_minutes", "peak_alt_deg", "best_night",
            "dark_site_only", "under_sampled", "score",
            # Ledger fields — zero when no ledger was passed; columns always
            # present so downstream tooling has a stable schema.
            "captured_minutes", "budget_minutes", "completion_pct",
            "deficit_minutes", "notes",
        ])
        for index, cand in enumerate(cands, 1):
            target = cand.target
            best = cand.best_observability
            writer.writerow([
                index,
                target.name,
                target.common_name,
                target.constellation,
                f"{target.ra_deg:.5f}",
                f"{target.dec_deg:+.5f}",
                f"{target.magnitude:.2f}" if target.magnitude is not None else "",
                f"{cand.surface_brightness:.2f}"
                if cand.surface_brightness is not None else "",
                f"{target.size_arcmin[0]:.1f}",
                f"{target.size_arcmin[1]:.1f}",
                best.site_name,
                best.minutes_above_minimum,
                f"{best.max_altitude_deg:.2f}",
                best.best_night_date.isoformat() if best.best_night_date else "",
                "yes" if cand.dark_site_only else "no",
                "yes" if cand.under_sampled else "no",
                f"{cand.score:.2f}",
                f"{cand.captured_minutes:.1f}",
                f"{cand.budget_minutes:.1f}",
                f"{cand.completion_fraction * 100.0:.1f}",
                f"{cand.deficit_minutes:.1f}",
                target.notes.replace("\n", " "),
            ])
