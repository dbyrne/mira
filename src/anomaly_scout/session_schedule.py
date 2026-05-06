"""Session schedule writers - the prescriptive 'do this, in this order' view.

session_plan.py produces the menu (all viable targets, chronological).
This module produces the *schedule* (the picked subset with time slots
and embedded per-target detail). Two outputs are intentional: the menu
remains useful when you want to override the auto-pick.
"""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Any

from .scheduler import ScheduledTarget, ScheduleResult
from .session_plan import (
    dec_to_dms,
    dec_to_target_scheduler_dms,
    expected_magnitude_summary,
    ra_to_hms,
    ra_to_target_scheduler_hms,
    recommended_exposure_plan,
    vsp_chart_url,
)


def write_session_schedule_outputs(
    schedule: ScheduleResult,
    output_dir: Path,
    config: Any,
) -> tuple[Path, Path, Path]:
    """Write all three schedule files. Returns (md_path, csv_path, nina_path).
    Also writes session_overflow.csv (deferred candidates) when overflow is
    non-empty; that file is consumed by the photometry index UI."""
    output_dir.mkdir(parents=True, exist_ok=True)
    md_path = output_dir / "session_schedule.md"
    csv_path = output_dir / "session_schedule.csv"
    nina_path = output_dir / "nina_targets.csv"
    overflow_path = output_dir / "session_overflow.csv"

    write_session_schedule_md(schedule, md_path, config)
    write_session_schedule_csv(schedule, csv_path)
    write_nina_targets_scheduled_csv(schedule, nina_path)
    write_session_overflow_csv(schedule, overflow_path)
    return md_path, csv_path, nina_path


def write_session_overflow_csv(schedule: ScheduleResult, path: Path) -> None:
    """Viable candidates that didn't fit the schedule. The webapp reads this
    so the user can see deferred options (e.g. if conditions or timing
    change, they can still image one)."""
    fields = ["name", "ra_deg", "dec_deg", "max_mag", "var_type", "score", "best_local_time"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for candidate in schedule.overflow:
            target = candidate.target
            best = candidate.best_observability
            best_time = ""
            if best and best.best_local_time:
                best_time = best.best_local_time.strftime("%H:%M")
            writer.writerow(
                {
                    "name": target.name,
                    "ra_deg": f"{target.ra_deg:.6f}",
                    "dec_deg": f"{target.dec_deg:.6f}",
                    "max_mag": f"{target.bright_mag:.2f}" if target.bright_mag is not None else "",
                    "var_type": target.var_type or "",
                    "score": f"{candidate.score:.1f}",
                    "best_local_time": best_time,
                }
            )


def write_session_schedule_md(schedule: ScheduleResult, path: Path, config: Any) -> None:
    site = config.sites[0]
    duration = (schedule.window_end - schedule.window_start).total_seconds() / 3600.0
    total_integration = sum(t.integration_minutes for t in schedule.scheduled)
    total_slew = sum(t.slew_minutes for t in schedule.scheduled[:-1]) if len(schedule.scheduled) > 1 else 0.0

    lines: list[str] = [
        f"# Session Schedule: {schedule.window_start.strftime('%Y-%m-%d')} from {site.name}",
        "",
        f"Window: **{schedule.window_start.strftime('%H:%M %Z')}** to "
        f"**{schedule.window_end.strftime('%H:%M %Z')}** ({duration:.1f} hours)",
        "",
        f"Scheduled: **{len(schedule.scheduled)} targets**, "
        f"{total_integration} min integration + {total_slew:.0f} min slewing.",
        "",
        f"Overflow (viable but unscheduled): **{len(schedule.overflow)} targets** "
        "(listed at the end).",
        "",
    ]

    if schedule.scheduled:
        lines.extend(_quick_glance_table(schedule))
        lines.extend(["", "---", ""])
        for index, scheduled in enumerate(schedule.scheduled, start=1):
            lines.extend(_target_section(index, scheduled))
            lines.append("---")
            lines.append("")
    else:
        lines.extend(
            [
                "## No targets scheduled",
                "",
                "The window contains no candidates whose required integration time "
                "fits within their observable window. Try a wider --hours window, "
                "a different start time, or a more permissive config.",
                "",
            ]
        )

    if schedule.overflow:
        lines.extend(_overflow_section(schedule))

    lines.extend(_footer_workflow_reminder())
    path.write_text("\n".join(lines), encoding="utf-8")


def _quick_glance_table(schedule: ScheduleResult) -> list[str]:
    lines = [
        "## Quick-glance schedule",
        "",
        "| Time slot       | Target | Mag | Type | Exposure |",
        "|-----------------|--------|-----|------|----------|",
    ]
    for scheduled in schedule.scheduled:
        target = scheduled.candidate.target
        slot = (
            f"{scheduled.start_local.strftime('%H:%M')}"
            f"–{scheduled.end_local.strftime('%H:%M')}"
        )
        plan = recommended_exposure_plan(target.bright_mag)
        mag = f"{target.bright_mag:.2f}" if target.bright_mag is not None else "n/a"
        var_type = (target.var_type or "blank").replace("|", "\\|")
        name = target.name.replace("|", "\\|")
        lines.append(
            f"| {slot} | {name} | {mag} | {var_type} | "
            f"{plan['frames']}×{plan['exposure_s']}s |"
        )
    return lines


def _target_section(index: int, scheduled: ScheduledTarget) -> list[str]:
    candidate = scheduled.candidate
    target = candidate.target
    obs = scheduled.observability
    plan = recommended_exposure_plan(target.bright_mag)
    slot = (
        f"{scheduled.start_local.strftime('%H:%M')}"
        f"–{scheduled.end_local.strftime('%H:%M')}"
    )
    slew_at = (scheduled.start_local).strftime("%H:%M")

    aavso = candidate.aavso
    mag_summary = expected_magnitude_summary(target, aavso)

    lines = [
        f"## {index}. {slot} — {target.name}",
        "",
        f"**Slew at {slew_at}, capture {scheduled.start_local.strftime('%H:%M')}–"
        f"{scheduled.end_local.strftime('%H:%M')}** "
        f"({plan['frames']}×{plan['exposure_s']}s = {plan['total_min']} min integration).",
        "",
    ]

    summary_bits = [f"**Score:** `{candidate.score:.1f}`"]
    if mag_summary.expected_mag is not None:
        bracket = ""
        if mag_summary.range_min is not None and mag_summary.range_max is not None:
            bracket = f" (range `{mag_summary.range_min:.2f}`–`{mag_summary.range_max:.2f}`, source: {mag_summary.source})"
        summary_bits.append(f"**Expected mag:** `~{mag_summary.expected_mag:.2f}`{bracket}")
    summary_bits.append(f"**Type:** `{target.var_type or 'blank'}`")
    if target.period_days is not None:
        summary_bits.append(f"**Period:** `{target.period_days:.3f} d`")
    summary_bits.append(f"**Max alt tonight:** `{obs.max_altitude_deg:.1f}°`")
    lines.append("  |  ".join(summary_bits))
    lines.append("")

    if mag_summary.sparkline:
        lines.append(
            f"Brightness today vs recent range: `{mag_summary.sparkline}` "
            f"(brighter ←  → fainter)"
        )
        lines.append("")
    if mag_summary.comp_low_label and mag_summary.comp_high_label:
        lines.append(
            f"**At the chart, bracket your estimate against comp stars near "
            f"mag {mag_summary.comp_low_label} and mag {mag_summary.comp_high_label}.**"
        )
        lines.append("")

    lines.extend(
        [
            "### Catalog",
            "",
            f"- VSX type: `{target.var_type or 'blank'}`",
            f"- Coordinates (J2000): RA `{ra_to_hms(target.ra_deg)}` / Dec `{dec_to_dms(target.dec_deg)}`",
            f"- Catalog photometry range: `{_format_optional(target.max_mag)}` to "
            f"`{_format_optional(target.min_mag)}` mag",
            f"- Catalog amplitude: `{_format_optional(target.catalog_amplitude)}` mag",
            f"- Spectral type: `{target.spectral_type or 'blank'}`",
            f"- Galactic latitude: `{obs.galactic_latitude_deg:.1f}°`",
            f"- VSX detail page: {target.vsx_url}",
            f"- AAVSO finder chart: {vsp_chart_url(target.name)}",
            "",
        ]
    )

    lines.extend(
        [
            f"### Tonight's observability ({obs.site_name})",
            "",
            f"- Best moment: `{obs.best_local_time.isoformat() if obs.best_local_time else 'n/a'}`",
            f"- Max altitude in dark window: `{obs.max_altitude_deg:.1f}°`",
            f"- Total dark minutes above floor: `{obs.minutes_above_minimum}` "
            "(approximate observable span)",
            "",
        ]
    )

    if candidate.reasons:
        lines.append("### Why it's on the queue")
        lines.append("")
        for reason in candidate.reasons:
            lines.append(f"- {reason}")
        lines.append("")

    lines.extend(_aavso_block(aavso))
    lines.extend(_simbad_block(candidate.simbad))
    lines.extend(_gaia_block(candidate.gaia))
    lines.extend(_ztf_block(candidate.ztf, target))

    return lines


def _aavso_block(aavso) -> list[str]:
    lines = ["### AAVSO recent coverage", ""]
    if aavso is None:
        lines.append("- Not requested for this run.")
        lines.append("")
        return lines
    if aavso.status not in ("ok", "ok-cached"):
        lines.append(f"- Status: `{aavso.status}` (no usable data)")
        if aavso.note:
            lines.append(f"- Note: {aavso.note}")
        lines.append("")
        return lines
    lines.append(f"- Status: `{aavso.status}`")
    lines.append(f"- Recent observations: `{aavso.recent_observations}`")
    if aavso.recent_median_mag is not None:
        range_text = ""
        if aavso.recent_min_mag is not None and aavso.recent_max_mag is not None:
            range_text = (
                f" (range `{aavso.recent_min_mag:.2f}`–`{aavso.recent_max_mag:.2f}`)"
            )
        lines.append(f"- Recent median magnitude: `{aavso.recent_median_mag:.2f}`{range_text}")
    if aavso.last_observation_jd is not None:
        last_iso = _jd_to_iso(aavso.last_observation_jd)
        if last_iso:
            lines.append(f"- Last observed: `{last_iso}` (JD `{aavso.last_observation_jd:.2f}`)")
    if aavso.derived_period_days is not None:
        lines.append(
            f"- Lomb-Scargle period from AAVSO data: `{aavso.derived_period_days:.4f}` d "
            f"(peak power `{_format_optional(aavso.period_power, digits=3)}`)"
        )
    if aavso.period_disagrees is True:
        lines.append("- **Period disagrees with VSX catalog** — flagged anomaly signal.")
    elif aavso.period_disagrees is False:
        lines.append("- AAVSO period agrees with the catalog within tolerance.")
    elif aavso.period_note:
        lines.append(f"- Period agreement: not assessable ({aavso.period_note})")

    if aavso.recent_samples:
        lines.append("")
        lines.append("Most recent AAVSO observations:")
        lines.append("")
        lines.append("| JD | Date | Mag | Band |")
        lines.append("|----|------|-----|------|")
        for jd, mag, band in aavso.recent_samples:
            iso = _jd_to_iso(jd) or ""
            lines.append(f"| {jd:.4f} | {iso} | {mag:.2f} | {band or 'V'} |")

    lines.append("")
    return lines


def _simbad_block(simbad) -> list[str]:
    lines = ["### SIMBAD context", ""]
    if simbad is None:
        lines.append("- Not requested for this run.")
        lines.append("")
        return lines
    lines.append(f"- Status: `{simbad.status}`")
    if simbad.status == "ok":
        lines.extend(
            [
                f"- Main ID: `{simbad.main_id or 'n/a'}`",
                f"- Object type: `{simbad.object_type or 'n/a'}`",
                f"- Match separation: `{_format_optional(simbad.separation_arcsec)}` arcsec",
                f"- Search: {simbad.url}",
            ]
        )
        if simbad.identifiers:
            lines.append(
                f"- Other IDs: {', '.join(f'`{ident}`' for ident in simbad.identifiers)}"
            )
    if simbad.note:
        lines.append(f"- Note: {simbad.note}")
    lines.append("")
    return lines


def _gaia_block(gaia) -> list[str]:
    lines = ["### Gaia DR3 context", ""]
    if gaia is None:
        lines.append("- Not requested for this run.")
        lines.append("")
        return lines
    lines.append(f"- Status: `{gaia.status}`")
    if gaia.status == "ok":
        lines.extend(
            [
                f"- Source ID: `{gaia.source_id or 'n/a'}`",
                f"- G mag: `{_format_optional(gaia.g_mag)}`  |  "
                f"BP-RP: `{_format_optional(gaia.bp_rp)}`",
                f"- Parallax: `{_format_optional(gaia.parallax_mas)}` mas  |  "
                f"RUWE: `{_format_optional(gaia.ruwe)}`",
                f"- Photometric variability flag: `{'VARIABLE' if gaia.photometric_variable else 'not flagged'}`",
            ]
        )
        if gaia.ipd_frac_multi_peak is not None:
            blend = " (PSF appears blended)" if gaia.ipd_frac_multi_peak > 0.1 else ""
            lines.append(f"- IPD multi-peak fraction: `{gaia.ipd_frac_multi_peak:.3f}`{blend}")
        if gaia.color_anomaly:
            lines.append(f"- **Color anomaly:** {gaia.color_anomaly}")
    if gaia.note:
        lines.append(f"- Note: {gaia.note}")
    lines.append("")
    return lines


def _ztf_block(ztf, target) -> list[str]:
    if ztf is None:
        return []
    lines = ["### ZTF light curve", ""]
    lines.append(f"- Status: `{ztf.status}`")
    if ztf.status == "ok":
        lines.extend(
            [
                f"- Observations parsed: `{ztf.observations}`",
                f"- Median mag: `{_format_optional(ztf.median_mag)}`  |  "
                f"5–95 percentile amplitude: `{_format_optional(ztf.amplitude_mag)}` mag",
            ]
        )
        if ztf.derived_period_days is not None:
            lines.append(
                f"- Lomb-Scargle period: `{ztf.derived_period_days:.4f}` d "
                f"(peak power `{_format_optional(ztf.period_power, digits=3)}`)"
            )
        if ztf.period_disagrees is True:
            lines.append("- **ZTF period disagrees with catalog** — flagged anomaly.")
        elif ztf.period_disagrees is False:
            lines.append("- ZTF period agrees with the catalog within tolerance.")
    if ztf.note:
        lines.append(f"- Note: {ztf.note}")
    if ztf.plot_path:
        lines.extend(["", f"![ZTF light curve]({Path(ztf.plot_path).name})"])
    if ztf.folded_plot_path:
        lines.append(f"![ZTF folded]({Path(ztf.folded_plot_path).name})")
    lines.append("")
    return lines


def _overflow_section(schedule: ScheduleResult) -> list[str]:
    lines = ["## Unscheduled overflow", "", "Viable candidates that didn't fit tonight's window:", ""]
    for candidate in schedule.overflow:
        target = candidate.target
        obs = candidate.best_observability
        best_time = obs.best_local_time.strftime("%H:%M") if obs.best_local_time else "n/a"
        mag = f"{target.bright_mag:.2f}" if target.bright_mag is not None else "n/a"
        lines.append(
            f"- **{target.name}** (score `{candidate.score:.1f}`, type "
            f"`{target.var_type or 'blank'}`, mag `{mag}`, peaks `{best_time}`)"
        )
    lines.append("")
    return lines


def _footer_workflow_reminder() -> list[str]:
    return [
        "## Workflow reminder",
        "",
        "1. Polar-align the wedge using the Seestar app's PA routine.",
        "2. Import `nina_targets.csv` into NINA Target Scheduler (the rows are "
        "in execution order).",
        "3. For each scheduled slot: slew → plate-solve → run the exposure plan.",
        "4. After capture, run `anomaly-scout submit ...` per target with the "
        "comp-star JSON to produce the AAVSO upload file.",
        "5. Inspect the upload file, then submit at "
        "https://www.aavso.org/webobs/file.",
        "",
    ]


def write_session_schedule_csv(schedule: ScheduleResult, path: Path) -> None:
    fields = [
        "order",
        "start_local",
        "end_local",
        "name",
        "ra_deg",
        "dec_deg",
        "max_mag",
        "var_type",
        "exposure_seconds",
        "frame_count",
        "integration_minutes",
        "score",
        "effective_score",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for index, scheduled in enumerate(schedule.scheduled, start=1):
            target = scheduled.candidate.target
            plan = recommended_exposure_plan(target.bright_mag)
            writer.writerow(
                {
                    "order": index,
                    "start_local": scheduled.start_local.isoformat(),
                    "end_local": scheduled.end_local.isoformat(),
                    "name": target.name,
                    "ra_deg": f"{target.ra_deg:.6f}",
                    "dec_deg": f"{target.dec_deg:.6f}",
                    "max_mag": f"{target.bright_mag:.2f}" if target.bright_mag is not None else "",
                    "var_type": target.var_type,
                    "exposure_seconds": plan["exposure_s"],
                    "frame_count": plan["frames"],
                    "integration_minutes": scheduled.integration_minutes,
                    "score": f"{scheduled.candidate.score:.1f}",
                    "effective_score": f"{scheduled.effective_score:.1f}",
                }
            )


def write_nina_targets_scheduled_csv(schedule: ScheduleResult, path: Path) -> None:
    """NINA Target Scheduler-compatible CSV containing only scheduled targets,
    in execution order."""
    fields = ["Type", "Name", "Ra", "Dec", "Rotation", "ROI"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for scheduled in schedule.scheduled:
            target = scheduled.candidate.target
            writer.writerow(
                {
                    "Type": "Variable Star",
                    "Name": target.name,
                    "Ra": ra_to_target_scheduler_hms(target.ra_deg),
                    "Dec": dec_to_target_scheduler_dms(target.dec_deg),
                    "Rotation": 0,
                    "ROI": 100,
                }
            )


def _format_optional(value: float | None, digits: int = 3) -> str:
    if value is None:
        return ""
    return f"{value:.{digits}f}"


def _jd_to_iso(jd: float | None) -> str | None:
    if jd is None:
        return None
    from datetime import timezone

    unix_secs = (jd - 2440587.5) * 86400
    try:
        return datetime.fromtimestamp(unix_secs, tz=timezone.utc).date().isoformat()
    except (OverflowError, OSError, ValueError):
        return None
