"""DSO plan output: Markdown for humans, CSV for ingestion.

Two files written per run:

- ``dso_plan.md`` — chronological-ish Markdown plan. Top section is the
  ranked queue; per-target sections list filter budgets, observability,
  notes. Phone-readable.
- ``dso_plan.csv`` — flat rows (one per candidate) suitable for spreadsheet
  triage. Columns chosen to be NINA Target Scheduler-friendly so a
  follow-up step can transform to a true import CSV when Phase 3 lands.
"""
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import Iterable

from .ledger import Ledger
from .planner import DsoCandidate


def write_dso_plan(
    candidates: Iterable[DsoCandidate],
    out_dir: Path,
    *,
    config_path: str,
    catalog_version: str,
    start_date: date,
    window_nights: int,
    ledger: Ledger | None = None,
) -> tuple[Path, Path]:
    """Write dso_plan.md and dso_plan.csv to ``out_dir``. Returns both paths.

    When ``ledger`` is provided, the per-target detail section shows
    per-filter captured-vs-budget rows from the ledger so the user can
    see *which* filter is behind, not just that the target is N% done."""
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / "dso_plan.md"
    csv_path = out_dir / "dso_plan.csv"
    md_path.write_text(_render_markdown(
        candidates,
        config_path=config_path,
        catalog_version=catalog_version,
        start_date=start_date,
        window_nights=window_nights,
        ledger=ledger,
    ), encoding="utf-8")
    _write_csv(candidates, csv_path)
    return md_path, csv_path


def _render_markdown(
    candidates: Iterable[DsoCandidate],
    *,
    config_path: str,
    catalog_version: str,
    start_date: date,
    window_nights: int,
    ledger: Ledger | None = None,
) -> str:
    cands = list(candidates)
    lines: list[str] = []
    lines.append("# DSO / narrowband plan")
    lines.append("")
    ledger_note = ""
    if ledger is not None:
        ledger_note = (
            f" • ledger: {len(ledger.sessions)} session(s) over "
            f"{len(ledger.by_target)} target(s)"
        )
        if ledger.orphan_target_names:
            ledger_note += (
                f", {len(ledger.orphan_target_names)} orphan(s)"
            )
    lines.append(
        f"Generated for {window_nights} night(s) starting "
        f"{start_date.isoformat()} • config: `{config_path}` • "
        f"catalog v{catalog_version} • {len(cands)} viable targets"
        f"{ledger_note}"
    )
    lines.append("")
    lines.append("## Ranked queue")
    lines.append("")
    if not cands:
        lines.append("_No catalog targets are observable in this window._")
        lines.append("")
        return "\n".join(lines)
    ledger_active = ledger is not None
    if ledger_active:
        # Add Captured / Budget / % Done columns. Completed targets stay
        # in the table — they're just demoted by score.
        lines.append(
            "| # | Target | Common | Type | Const | Size (arcmin) | Best site | "
            "Dark min | Peak alt | Best night | Mosaic | Captured | Budget | "
            "% Done | Score |"
        )
        lines.append(
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"
        )
    else:
        lines.append(
            "| # | Target | Common | Type | Const | Size (arcmin) | Best site | "
            "Dark min | Peak alt | Best night | Mosaic | Score |"
        )
        lines.append(
            "|---|---|---|---|---|---|---|---|---|---|---|---|"
        )
    for index, cand in enumerate(cands, 1):
        target = cand.target
        best = cand.best_observability
        size = f"{target.size_arcmin[0]:.0f} × {target.size_arcmin[1]:.0f}"
        night = best.best_night_date.isoformat() if best.best_night_date else "—"
        mosaic = "yes" if not cand.fits_fov else ""
        if ledger_active:
            pct = cand.completion_fraction * 100.0
            done_tag = " ✓" if pct >= 100 else ""
            lines.append(
                f"| {index} | `{target.name}` | {target.common_name} | "
                f"{target.object_type} | {target.constellation} | {size} | "
                f"{best.site_name} | {best.minutes_above_minimum} | "
                f"{best.max_altitude_deg:.1f}° | {night} | {mosaic} | "
                f"{cand.captured_minutes:.0f}m | {cand.budget_minutes:.0f}m | "
                f"{pct:.0f}%{done_tag} | {cand.score:.1f} |"
            )
        else:
            lines.append(
                f"| {index} | `{target.name}` | {target.common_name} | "
                f"{target.object_type} | {target.constellation} | {size} | "
                f"{best.site_name} | {best.minutes_above_minimum} | "
                f"{best.max_altitude_deg:.1f}° | {night} | {mosaic} | "
                f"{cand.score:.1f} |"
            )
    lines.append("")
    lines.append("## Per-target detail")
    lines.append("")
    for index, cand in enumerate(cands, 1):
        target = cand.target
        best = cand.best_observability
        lines.append(f"### {index}. {target.name} — {target.common_name}")
        lines.append("")
        lines.append(
            f"- **Type:** {target.object_type} in {target.constellation}  "
        )
        lines.append(
            f"- **Coords (J2000):** RA {target.ra_deg:.4f}° / "
            f"Dec {target.dec_deg:+.4f}°  "
        )
        lines.append(
            f"- **Size:** {target.size_arcmin[0]:.0f}' × "
            f"{target.size_arcmin[1]:.0f}'  "
        )
        lines.append(
            f"- **FOV fit:** "
            f"{'single frame' if cand.fits_fov else 'mosaic candidate'} "
            f"(rig FOV {cand.fov_deg[0]:.2f}° × {cand.fov_deg[1]:.2f}°)  "
        )
        if ledger_active and cand.budget_minutes > 0:
            # Per-filter ledger breakdown: which filter is behind, which is done.
            lines.append("- **Per-filter status (captured / budget):**  ")
            for filter_name, budget in target.budget_minutes.items():
                captured = ledger.minutes(target.name, filter_name)
                pct = (captured / budget * 100.0) if budget else 0.0
                done_tag = " ✓" if captured >= budget else ""
                deficit = max(0, budget - captured)
                lines.append(
                    f"  - {filter_name}: {captured:.0f} / {budget} min "
                    f"({pct:.0f}% — {deficit:.0f}m to go){done_tag}"
                )
        else:
            budgets = ", ".join(
                f"{f}: {m}m" for f, m in target.budget_minutes.items()
            )
            lines.append(f"- **Budget:** {budgets}  ")
        lines.append("- **Observability per site:**  ")
        for obs in cand.observabilities:
            night = obs.best_night_date.isoformat() if obs.best_night_date else "—"
            lines.append(
                f"  - {obs.site_name}: "
                f"{obs.minutes_above_minimum} min above floor, "
                f"peak {obs.max_altitude_deg:.1f}° on {night}"
            )
        if target.notes:
            lines.append(f"- **Notes:** {target.notes}")
        lines.append("")
    if ledger_active and ledger.orphan_target_names:
        lines.append("## Orphan sessions")
        lines.append("")
        lines.append(
            "_These captures' `target_name` doesn't match any catalog "
            "entry. Could be a typo or a one-off non-catalog target._"
        )
        lines.append("")
        for name in ledger.orphan_target_names:
            sessions = [s for s in ledger.sessions if s.target_name == name]
            mins = sum(s.integration_minutes for s in sessions)
            lines.append(
                f"- `{name}` — {len(sessions)} session(s), "
                f"{mins:.0f} total min"
            )
        lines.append("")
    return "\n".join(lines)


def _write_csv(candidates: Iterable[DsoCandidate], path: Path) -> None:
    cands = list(candidates)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "rank", "name", "common_name", "object_type", "constellation",
            "ra_deg", "dec_deg", "size_major_arcmin", "size_minor_arcmin",
            "best_site", "dark_minutes", "peak_alt_deg", "best_night",
            "fits_fov", "mosaic", "score",
            # Ledger fields — populated when planner was passed a ledger;
            # zero when ledger was None. Columns are always present so
            # downstream tooling has a stable schema regardless of ledger
            # state.
            "captured_minutes", "budget_minutes", "completion_pct",
            "deficit_minutes",
            "budget_minutes_json",  # filter→minutes as JSON for round-trip
            "notes",
        ])
        import json
        for index, cand in enumerate(cands, 1):
            target = cand.target
            best = cand.best_observability
            writer.writerow([
                index,
                target.name,
                target.common_name,
                target.object_type,
                target.constellation,
                f"{target.ra_deg:.5f}",
                f"{target.dec_deg:+.5f}",
                f"{target.size_arcmin[0]:.1f}",
                f"{target.size_arcmin[1]:.1f}",
                best.site_name,
                best.minutes_above_minimum,
                f"{best.max_altitude_deg:.2f}",
                best.best_night_date.isoformat() if best.best_night_date else "",
                "yes" if cand.fits_fov else "no",
                "yes" if not cand.fits_fov else "no",
                f"{cand.score:.2f}",
                f"{cand.captured_minutes:.1f}",
                f"{cand.budget_minutes:.1f}",
                f"{cand.completion_fraction * 100.0:.1f}",
                f"{cand.deficit_minutes:.1f}",
                json.dumps(target.budget_minutes),
                target.notes.replace("\n", " "),
            ])
