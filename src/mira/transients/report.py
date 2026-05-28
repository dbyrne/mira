"""Bright-transient report: Markdown for humans, CSV for ingestion.

Honest funnel: how many transients were fetched, how many are observable
from your site, how many are within the rig's reach. When nothing is
reachable (common on a shallow rig), it says so and still lists the
observable-but-too-faint ones so you know what a deeper rig could grab.
"""
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import Iterable

from .planner import TransientCandidate


def write_transient_report(
    candidates: Iterable[TransientCandidate],
    out_dir: Path,
    *,
    config_path: str,
    start_date: date,
    max_mag: float | None,
    fetched_count: int,
    source_url: str,
) -> tuple[Path, Path]:
    """Write transients.md + transients.csv. Returns both paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / "transients.md"
    csv_path = out_dir / "transients.csv"
    cands = list(candidates)
    md_path.write_text(_render_markdown(
        cands, config_path=config_path, start_date=start_date,
        max_mag=max_mag, fetched_count=fetched_count, source_url=source_url,
    ), encoding="utf-8")
    _write_csv(cands, csv_path)
    return md_path, csv_path


def _hms(ra_deg: float) -> str:
    h = ra_deg / 15.0
    hh = int(h); mm = int((h - hh) * 60); ss = (((h - hh) * 60) - mm) * 60
    return f"{hh:02d}h{mm:02d}m{ss:04.1f}s"


def _dms(dec_deg: float) -> str:
    sign = "+" if dec_deg >= 0 else "-"
    d = abs(dec_deg); dd = int(d); mm = int((d - dd) * 60); ss = (((d - dd) * 60) - mm) * 60
    return f"{sign}{dd:02d}°{mm:02d}'{ss:04.1f}\""


def _render_markdown(
    cands: list[TransientCandidate],
    *,
    config_path: str,
    start_date: date,
    max_mag: float | None,
    fetched_count: int,
    source_url: str,
) -> str:
    reachable = [c for c in cands if c.within_reach]
    beyond = [c for c in cands if not c.within_reach]
    lines: list[str] = []
    lines.append("# Bright transients")
    lines.append("")
    reach_txt = f"mag ≤ {max_mag:.1f}" if max_mag is not None else "no reach limit"
    lines.append(
        f"{start_date.isoformat()} • config: `{config_path}` • "
        f"fetched {fetched_count} active SNe (mag<17) • "
        f"{len(cands)} observable • {len(reachable)} within reach ({reach_txt})"
    )
    lines.append("")
    lines.append(
        "_Transients are point sources — moon-tolerant and AAVSO-submittable. "
        "The ideal urban/bright-moon science target._"
    )
    lines.append("")

    lines.append("## Within reach tonight")
    lines.append("")
    if reachable:
        lines.append(
            "| # | Name | Type | Mag | Host | Best site | Peak alt | Dark min | Flags |"
        )
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for i, c in enumerate(reachable, 1):
            t = c.transient; b = c.best_observability
            flag = "⚠ stale" if t.mag_stale else ""
            lines.append(
                f"| {i} | `{t.name}` | {t.sn_type} | {t.magnitude:.1f} | {t.host} | "
                f"{b.site_name} | {b.max_altitude_deg:.0f}° | {b.minutes_above_minimum} | {flag} |"
            )
    else:
        lines.append(
            "_Nothing within this rig's reach tonight — the brightest "
            "observable transient is below the magnitude limit. See the "
            "deeper-rig list below, or raise the limit with `--max-mag`._"
        )
    lines.append("")

    if beyond:
        lines.append("## Observable, but beyond this rig's reach")
        lines.append("")
        lines.append("_Too faint for the configured rig; a deeper scope (e.g. the Esprit) could reach these._")
        lines.append("")
        lines.append("| Name | Type | Mag | Host | Peak alt | Flags |")
        lines.append("|---|---|---|---|---|---|")
        for c in beyond:
            t = c.transient; b = c.best_observability
            flag = "⚠ stale" if t.mag_stale else ""
            lines.append(
                f"| `{t.name}` | {t.sn_type} | {t.magnitude:.1f} | {t.host} | "
                f"{b.max_altitude_deg:.0f}° | {flag} |"
            )
        lines.append("")

    if reachable:
        lines.append("## Detail (within reach)")
        lines.append("")
        for i, c in enumerate(reachable, 1):
            t = c.transient
            lines.append(f"### {i}. {t.name} — {t.sn_type} in {t.host}")
            lines.append("")
            lines.append(f"- **Magnitude:** {t.magnitude:.1f}"
                         + (" ⚠ (last obs > 1 month old — verify)" if t.mag_stale else "") + "  ")
            lines.append(
                f"- **Coords (J2000):** {_hms(t.ra_deg)} {_dms(t.dec_deg)}  "
                f"(RA {t.ra_deg:.4f}° / Dec {t.dec_deg:+.4f}°)  "
            )
            for r in c.reasons:
                lines.append(f"- {r}")
            lines.append("")

    lines.append("---")
    lines.append(
        "Reduce captures with `mira submit` (OSC → TG band). Generate a comp-star "
        "chart by coordinates at AAVSO VSP (https://app.aavso.org/vsp/). "
        f"Source: {source_url}"
    )
    lines.append("")
    return "\n".join(lines)


def _write_csv(cands: list[TransientCandidate], path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "rank", "name", "type", "magnitude", "mag_stale", "host",
            "ra_deg", "dec_deg", "within_reach", "best_site",
            "peak_alt_deg", "dark_minutes", "best_night",
        ])
        for i, c in enumerate(cands, 1):
            t = c.transient; b = c.best_observability
            writer.writerow([
                i, t.name, t.sn_type, f"{t.magnitude:.1f}",
                "yes" if t.mag_stale else "no", t.host,
                f"{t.ra_deg:.5f}", f"{t.dec_deg:+.5f}",
                "yes" if c.within_reach else "no", b.site_name,
                f"{b.max_altitude_deg:.2f}", b.minutes_above_minimum,
                b.best_night_date.isoformat() if b.best_night_date else "",
            ])
