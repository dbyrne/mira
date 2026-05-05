"""Session-plan generator: produces a phone-readable session_plan.md and a
NINA-importable session_plan.csv for the targets selected by `tonight`."""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode


def write_session_plan(
    candidates: list,
    output_dir: Path,
    window_start: datetime,
    window_end: datetime,
    config,
) -> tuple[Path, Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    md_path = output_dir / "session_plan.md"
    csv_path = output_dir / "session_plan.csv"
    nina_path = output_dir / "nina_targets.csv"

    # Sort by best_local_time ascending so the plan reads in chronological order
    sorted_candidates = sorted(
        candidates,
        key=lambda c: c.best_observability.best_local_time or datetime.max.replace(tzinfo=window_start.tzinfo),
    )

    write_session_plan_md(sorted_candidates, md_path, window_start, window_end, config)
    write_session_plan_csv(sorted_candidates, csv_path)
    write_nina_target_scheduler_csv(sorted_candidates, nina_path)
    return md_path, csv_path, nina_path


def write_session_plan_md(candidates, path: Path, window_start, window_end, config) -> None:
    site = config.sites[0]
    lines = [
        f"# Session Plan: {window_start.strftime('%Y-%m-%d')} from {site.name}",
        "",
        f"Window: **{window_start.strftime('%H:%M %Z')}** to **{window_end.strftime('%H:%M %Z')}** "
        f"({(window_end - window_start).total_seconds() / 3600:.1f} hours)",
        "",
        f"Site: {site.name} (lat {site.observer.latitude_deg:.3f}, lon {site.observer.longitude_deg:.3f})",
        "",
        "Targets ranked chronologically. For each target, the recommended exposure "
        "plan assumes a Seestar S30 Pro in EQ mode; adjust for your actual gear.",
        "",
        "---",
        "",
    ]
    for index, candidate in enumerate(candidates, start=1):
        target = candidate.target
        obs = candidate.best_observability
        plan = recommended_exposure_plan(target.bright_mag)
        ra_hms = ra_to_hms(target.ra_deg)
        dec_dms = dec_to_dms(target.dec_deg)
        best_time = obs.best_local_time.strftime("%H:%M") if obs.best_local_time else "n/a"
        chart_url = vsp_chart_url(target.name)
        catalog_period = f"{target.period_days:.3f} d" if target.period_days is not None else "n/a"
        catalog_amplitude = f"{target.catalog_amplitude:.2f} mag" if target.catalog_amplitude is not None else "n/a"
        aavso_count = "n/a"
        if candidate.aavso and candidate.aavso.status == "ok":
            aavso_count = str(candidate.aavso.recent_observations)

        lines.extend(
            [
                f"## {index}. {target.name}",
                "",
                f"- **Best time tonight:** `{best_time}` (local), max alt **{obs.max_altitude_deg:.1f}°**",
                f"- **Score:** `{candidate.score:.1f}`  |  **Type:** `{target.var_type or 'blank'}`  |  **Mag:** `{target.bright_mag:.2f}`",
                f"- **Period:** {catalog_period}  |  **Amplitude:** {catalog_amplitude}  |  **AAVSO recent:** {aavso_count}",
                f"- **RA / Dec:** `{ra_hms}` / `{dec_dms}` (J2000)",
                f"- **Exposure plan:** {plan['frames']} × {plan['exposure_s']:g}s = **{plan['total_min']:g} min** integration",
                f"- **AAVSO chart:** {chart_url}",
            ]
        )
        if candidate.simbad and candidate.simbad.status == "ok":
            simbad_url = candidate.simbad.url
            lines.append(f"- **SIMBAD:** {simbad_url}")
        if candidate.gaia and candidate.gaia.status == "ok" and candidate.gaia.color_anomaly:
            lines.append(f"- **Gaia color anomaly:** {candidate.gaia.color_anomaly}")
        lines.append("")

    lines.extend(
        [
            "---",
            "",
            "## Workflow reminder",
            "",
            "1. Polar-align the wedge using the Seestar app's PA routine.",
            "2. Slew to target, plate-solve, autofocus.",
            "3. Run the exposure plan above. Dither every ~10 frames if NINA is driving.",
            "4. After capture: open AAVSO chart, identify two comparison stars bracketing target brightness.",
            "5. Submit estimate at https://www.aavso.org/webobs/file with band code `TG` (transformed green from OSC).",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def write_session_plan_csv(candidates, path: Path) -> None:
    fields = [
        "order",
        "name",
        "ra_hms",
        "dec_dms",
        "ra_deg",
        "dec_deg",
        "max_mag",
        "var_type",
        "catalog_period_days",
        "catalog_amplitude_mag",
        "best_local_time",
        "best_max_altitude_deg",
        "exposure_seconds",
        "frame_count",
        "total_minutes",
        "score",
        "aavso_chart_url",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for index, candidate in enumerate(candidates, start=1):
            target = candidate.target
            obs = candidate.best_observability
            plan = recommended_exposure_plan(target.bright_mag)
            writer.writerow(
                {
                    "order": index,
                    "name": target.name,
                    "ra_hms": ra_to_hms(target.ra_deg),
                    "dec_dms": dec_to_dms(target.dec_deg),
                    "ra_deg": f"{target.ra_deg:.6f}",
                    "dec_deg": f"{target.dec_deg:.6f}",
                    "max_mag": f"{target.bright_mag:.2f}" if target.bright_mag is not None else "",
                    "var_type": target.var_type,
                    "catalog_period_days": (
                        f"{target.period_days:.6f}" if target.period_days is not None else ""
                    ),
                    "catalog_amplitude_mag": (
                        f"{target.catalog_amplitude:.3f}" if target.catalog_amplitude is not None else ""
                    ),
                    "best_local_time": obs.best_local_time.isoformat() if obs.best_local_time else "",
                    "best_max_altitude_deg": f"{obs.max_altitude_deg:.1f}",
                    "exposure_seconds": plan["exposure_s"],
                    "frame_count": plan["frames"],
                    "total_minutes": plan["total_min"],
                    "score": f"{candidate.score:.1f}",
                    "aavso_chart_url": vsp_chart_url(target.name),
                }
            )


def write_nina_target_scheduler_csv(candidates, path: Path) -> None:
    """Emit a CSV in NINA Target Scheduler plugin's documented import format.

    Columns: Type, Name, Ra, Dec, Rotation, ROI
      - Ra:  HMS string like "10h 08m 19s"
      - Dec: DMS string like "+20° 00' 13\""
      - Rotation: degrees (0 = native)
      - ROI: percentage of full sensor (100 = full frame)

    Reference: https://tcpalmer.github.io/nina-scheduler/target-management/targets.html
    """
    fields = ["Type", "Name", "Ra", "Dec", "Rotation", "ROI"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for candidate in candidates:
            target = candidate.target
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


def ra_to_target_scheduler_hms(ra_deg: float) -> str:
    """Format RA as 'HHh MMm SSs' for NINA Target Scheduler."""
    hours_total = ra_deg / 15.0
    h = int(hours_total)
    minutes_total = (hours_total - h) * 60.0
    m = int(minutes_total)
    s = (minutes_total - m) * 60.0
    return f"{h:02d}h {m:02d}m {s:02.0f}s"


def dec_to_target_scheduler_dms(dec_deg: float) -> str:
    """Format Dec as '±DD° MM\\' SS\"' for NINA Target Scheduler."""
    sign = "+" if dec_deg >= 0 else "-"
    abs_dec = abs(dec_deg)
    d = int(abs_dec)
    minutes_total = (abs_dec - d) * 60.0
    m = int(minutes_total)
    s = (minutes_total - m) * 60.0
    return f"{sign}{d:02d}° {m:02d}' {s:02.0f}\""


def recommended_exposure_plan(bright_mag: float | None) -> dict:
    """Return a recommended (exposure_s, frames, total_min) plan for the S30 Pro
    in EQ mode at the given target magnitude. Conservative defaults; adjust per
    your actual sky conditions."""
    if bright_mag is None:
        return {"exposure_s": 30, "frames": 60, "total_min": 30}
    if bright_mag <= 8.0:
        return {"exposure_s": 5, "frames": 60, "total_min": 5}
    if bright_mag <= 10.0:
        return {"exposure_s": 15, "frames": 60, "total_min": 15}
    if bright_mag <= 12.0:
        return {"exposure_s": 30, "frames": 60, "total_min": 30}
    return {"exposure_s": 60, "frames": 30, "total_min": 30}


def ra_to_hms(ra_deg: float) -> str:
    hours_total = ra_deg / 15.0
    h = int(hours_total)
    minutes_total = (hours_total - h) * 60.0
    m = int(minutes_total)
    s = (minutes_total - m) * 60.0
    return f"{h:02d}:{m:02d}:{s:05.2f}"


def dec_to_dms(dec_deg: float) -> str:
    sign = "+" if dec_deg >= 0 else "-"
    abs_dec = abs(dec_deg)
    d = int(abs_dec)
    minutes_total = (abs_dec - d) * 60.0
    m = int(minutes_total)
    s = (minutes_total - m) * 60.0
    return f"{sign}{d:02d}:{m:02d}:{s:04.1f}"


def vsp_chart_url(star_name: str) -> str:
    params = urlencode(
        {
            "star": star_name,
            "type": "chart",
            "fov": "120",
            "maglimit": "14.5",
            "resolution": "150",
            "north": "up",
            "east": "left",
        }
    )
    return f"https://apps.aavso.org/vsp/photometry/?{params}"
