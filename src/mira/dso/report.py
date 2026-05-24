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

from .planner import DsoCandidate


def write_dso_plan(
    candidates: Iterable[DsoCandidate],
    out_dir: Path,
    *,
    config_path: str,
    catalog_version: str,
    start_date: date,
    window_nights: int,
) -> tuple[Path, Path]:
    """Write dso_plan.md and dso_plan.csv to ``out_dir``. Returns both paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / "dso_plan.md"
    csv_path = out_dir / "dso_plan.csv"
    md_path.write_text(_render_markdown(
        candidates,
        config_path=config_path,
        catalog_version=catalog_version,
        start_date=start_date,
        window_nights=window_nights,
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
) -> str:
    cands = list(candidates)
    lines: list[str] = []
    lines.append("# DSO / narrowband plan")
    lines.append("")
    lines.append(
        f"Generated for {window_nights} night(s) starting "
        f"{start_date.isoformat()} • config: `{config_path}` • "
        f"catalog v{catalog_version} • {len(cands)} viable targets"
    )
    lines.append("")
    lines.append("## Ranked queue")
    lines.append("")
    if not cands:
        lines.append("_No catalog targets are observable in this window._")
        lines.append("")
        return "\n".join(lines)
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
                json.dumps(target.budget_minutes),
                target.notes.replace("\n", " "),
            ])
