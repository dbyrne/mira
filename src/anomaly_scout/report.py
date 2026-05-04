from __future__ import annotations

import csv
from pathlib import Path
from urllib.parse import urlencode

from .models import Candidate
from .ztf import safe_file_stem


def clean_previous_outputs(output_dir: Path) -> None:
    packet_dir = output_dir / "candidate_packets"
    for path in (output_dir / "candidate_queue.csv", output_dir / "research_notes.md"):
        if path.exists():
            path.unlink()
    if packet_dir.exists():
        for pattern in ("*.md", "*.png"):
            for path in packet_dir.glob(pattern):
                path.unlink()


def write_outputs(candidates: list[Candidate], output_dir: Path, top_packets: int) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    packet_dir = output_dir / "candidate_packets"
    packet_dir.mkdir(parents=True, exist_ok=True)
    write_queue_csv(candidates, output_dir / "candidate_queue.csv")
    write_research_notes(candidates[:top_packets], output_dir / "research_notes.md")
    for candidate in candidates[:top_packets]:
        write_candidate_packet(candidate, packet_dir)


def write_queue_csv(candidates: list[Candidate], path: Path) -> None:
    fields = [
        "rank",
        "score",
        "name",
        "type",
        "ra_deg",
        "dec_deg",
        "max_mag",
        "min_mag_or_amplitude",
        "min_is_amplitude",
        "amplitude_mag",
        "period_days",
        "max_altitude_deg",
        "minutes_above_minimum",
        "best_night_date",
        "best_local_time",
        "galactic_latitude_deg",
        "aavso_status",
        "aavso_recent_observations",
        "simbad_status",
        "simbad_main_id",
        "simbad_object_type",
        "simbad_separation_arcsec",
        "ztf_status",
        "ztf_observations",
        "ztf_amplitude_mag",
        "vsx_url",
        "reasons",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for rank, candidate in enumerate(candidates, start=1):
            target = candidate.target
            obs = candidate.observability
            aavso = candidate.aavso
            simbad = candidate.simbad
            ztf = candidate.ztf
            writer.writerow(
                {
                    "rank": rank,
                    "score": f"{candidate.score:.1f}",
                    "name": target.name,
                    "type": target.var_type,
                    "ra_deg": f"{target.ra_deg:.5f}",
                    "dec_deg": f"{target.dec_deg:.5f}",
                    "max_mag": _format_optional(target.max_mag),
                    "min_mag_or_amplitude": _format_optional(target.min_mag),
                    "min_is_amplitude": target.min_is_amplitude,
                    "amplitude_mag": _format_optional(target.catalog_amplitude),
                    "period_days": _format_optional(target.period_days, digits=8),
                    "max_altitude_deg": f"{obs.max_altitude_deg:.1f}",
                    "minutes_above_minimum": obs.minutes_above_minimum,
                    "best_night_date": obs.best_night_date.isoformat() if obs.best_night_date else "",
                    "best_local_time": obs.best_local_time.isoformat() if obs.best_local_time else "",
                    "galactic_latitude_deg": f"{obs.galactic_latitude_deg:.1f}",
                    "aavso_status": aavso.status if aavso else "",
                    "aavso_recent_observations": aavso.recent_observations if aavso else "",
                    "simbad_status": simbad.status if simbad else "",
                    "simbad_main_id": simbad.main_id if simbad else "",
                    "simbad_object_type": simbad.object_type if simbad else "",
                    "simbad_separation_arcsec": _format_optional(simbad.separation_arcsec if simbad else None),
                    "ztf_status": ztf.status if ztf else "",
                    "ztf_observations": ztf.observations if ztf else "",
                    "ztf_amplitude_mag": _format_optional(ztf.amplitude_mag if ztf else None),
                    "vsx_url": target.vsx_url,
                    "reasons": "; ".join(candidate.reasons),
                }
            )


def write_research_notes(candidates: list[Candidate], path: Path) -> None:
    lines = [
        "# AAVSO Anomaly Scout Research Notes",
        "",
        "These notes summarize the current ranked queue. They are triage notes for human review, not discovery claims.",
        "",
        "## Best First Targets",
        "",
    ]
    for rank, candidate in enumerate(candidates[:10], start=1):
        target = candidate.target
        obs = candidate.observability
        aavso = candidate.aavso
        simbad = candidate.simbad
        lines.extend(
            [
                f"### {rank}. {target.name}",
                "",
                f"- Score: `{candidate.score:.1f}`",
                f"- VSX/SIMBAD type: `{target.var_type or 'blank'}` / `{simbad.object_type if simbad else 'not checked'}`",
                f"- SIMBAD main ID: `{simbad.main_id if simbad else 'not checked'}`",
                f"- Recent AAVSO observations: `{aavso.recent_observations if aavso else 'not checked'}`",
                f"- Best Jersey City window: `{obs.best_night_date.isoformat() if obs.best_night_date else 'n/a'}`, "
                f"`{obs.minutes_above_minimum} min` above altitude floor",
                f"- Observing plan: {_observing_strategy_text(target)}",
                f"- Why it matters: {_research_value_text(candidate)}",
                f"- VSX: {target.vsx_url}",
                f"- AAVSO finder chart: {_vsp_chart_url(target.name)}",
            ]
        )
        if simbad and simbad.url:
            lines.append(f"- SIMBAD: {simbad.url}")
        lines.append("")

    lines.extend(
        [
            "## Triage Rules",
            "",
            "- Prefer sparse AAVSO coverage plus a clean SIMBAD match.",
            "- Prefer long-period SR/L candidates for nightly/weekly urban follow-up.",
            "- Prefer EW/EB/RR candidates only when you can commit to a continuous time-series run.",
            "- Treat popular objects with many recent AAVSO observations as calibration/practice targets, not novelty targets.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def write_candidate_packet(candidate: Candidate, packet_dir: Path) -> Path:
    target = candidate.target
    obs = candidate.observability
    aavso = candidate.aavso
    simbad = candidate.simbad
    ztf = candidate.ztf
    path = packet_dir / f"{safe_file_stem(target.name)}.md"
    lines = [
        f"# {target.name}",
        "",
        f"Score: **{candidate.score:.1f}**",
        "",
        "## Catalog",
        "",
        f"- VSX type: `{target.var_type or 'blank'}`",
        f"- Coordinates: RA `{target.ra_deg:.5f}`, Dec `{target.dec_deg:.5f}`",
        f"- Catalog photometry: {_catalog_photometry_text(target)}",
        f"- Catalog amplitude: `{_format_optional(target.catalog_amplitude)}` mag",
        f"- Period: `{_format_optional(target.period_days, digits=8)}` days",
        f"- Spectral type: `{target.spectral_type or 'blank'}`",
        f"- VSX: {target.vsx_url}",
        f"- AAVSO finder chart: {_vsp_chart_url(target.name)}",
        "",
        "## Jersey City Observability",
        "",
        f"- Max altitude in configured window: `{obs.max_altitude_deg:.1f} deg`",
        f"- Best single-night time above altitude floor: `{obs.minutes_above_minimum} min`",
        f"- Best window date: `{obs.best_night_date.isoformat() if obs.best_night_date else 'n/a'}`",
        f"- Best sampled local time: `{obs.best_local_time.isoformat() if obs.best_local_time else 'n/a'}`",
        f"- Galactic latitude: `{obs.galactic_latitude_deg:.1f} deg`",
        "",
        "## Observing Strategy",
        "",
        f"- {_observing_strategy_text(target)}",
        "",
        "## Why It Was Flagged",
        "",
    ]
    lines.extend(f"- {reason}" for reason in candidate.reasons)

    lines.extend(["", "## AAVSO Recent Coverage", ""])
    if aavso is None:
        lines.append("- Not requested for this run.")
    else:
        lines.extend(
            [
                f"- Status: `{aavso.status}`",
                f"- Recent observations: `{aavso.recent_observations}`",
                f"- JD range: `{_format_optional(aavso.from_jd, digits=2)}-{_format_optional(aavso.to_jd, digits=2)}`",
            ]
        )
        if aavso.note:
            lines.append(f"- Note: {aavso.note}")

    lines.extend(["", "## SIMBAD Context", ""])
    if simbad is None:
        lines.append("- Not requested for this run.")
    else:
        lines.extend(
            [
                f"- Status: `{simbad.status}`",
                f"- Main ID: `{simbad.main_id or 'n/a'}`",
                f"- Object type: `{simbad.object_type or 'n/a'}`",
                f"- Match separation: `{_format_optional(simbad.separation_arcsec)}` arcsec",
                f"- Search: {simbad.url}",
            ]
        )
        if simbad.identifiers:
            lines.append(f"- Other IDs: {', '.join(f'`{identifier}`' for identifier in simbad.identifiers)}")
        if simbad.note:
            lines.append(f"- Note: {simbad.note}")

    lines.extend(["", "## ZTF Enrichment", ""])
    if ztf is None:
        lines.append("- Not requested for this run.")
    else:
        lines.extend(
            [
                f"- Status: `{ztf.status}`",
                f"- Observations parsed: `{ztf.observations}`",
                f"- Bands: `{', '.join(ztf.bands) if ztf.bands else 'n/a'}`",
                f"- Median magnitude: `{_format_optional(ztf.median_mag)}`",
                f"- 5-95 percentile amplitude: `{_format_optional(ztf.amplitude_mag)}` mag",
            ]
        )
        if ztf.note:
            lines.append(f"- Note: {ztf.note}")
        if ztf.plot_path:
            plot_name = Path(ztf.plot_path).name
            lines.extend(["", f"![ZTF light curve]({plot_name})"])

    lines.extend(
        [
            "",
            "## Human Review Checklist",
            "",
            "- Check VSX and SIMBAD for newer notes or duplicate names.",
            "- Inspect DSS/Pan-STARRS imagery for crowding and bright nearby stars.",
            "- Verify AAVSO comparison stars are available in the field.",
            "- Decide cadence: single nightly point, weekly monitoring, or continuous time-series.",
            "- Treat this as a follow-up candidate, not a discovery claim.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _format_optional(value: float | None, digits: int = 3) -> str:
    if value is None:
        return ""
    return f"{value:.{digits}f}"


def _catalog_photometry_text(target) -> str:
    if target.min_is_amplitude:
        return (
            f"bright `{_format_optional(target.max_mag)}` {target.max_band or ''}; "
            f"amplitude `{_format_optional(target.min_mag)}` mag {target.min_band or ''}"
        )
    return (
        f"range `{_format_optional(target.max_mag)}-{_format_optional(target.min_mag)}` "
        f"({target.max_band}/{target.min_band})"
    )


def _vsp_chart_url(star_name: str) -> str:
    params = urlencode(
        {
            "star": star_name,
            "type": "chart",
            "fov": "900",
            "maglimit": "15",
            "resolution": "150",
            "north": "up",
            "east": "left",
        }
    )
    return f"https://apps.aavso.org/vsp/photometry/?{params}"


def _observing_strategy_text(target) -> str:
    var_type = (target.var_type or "").upper()
    period = target.period_days
    if any(token in var_type for token in ("EA", "EB", "EW", "RR", "DSCT")) or (period is not None and period <= 2):
        return (
            "Time-series follow-up: run continuously for 2-4 hours when the target is high, "
            "then compare the folded light curve against the VSX period."
        )
    if any(token in var_type for token in ("M", "SR", "SRS", "L", "LB")) or (period is not None and period >= 10):
        return (
            "Long-cadence follow-up: one calibrated point every clear night or two is useful; "
            "weekly cadence is still worthwhile for slow red variables."
        )
    return "Start with one calibrated point on several clear nights, then switch to time-series if short-term changes appear."


def _research_value_text(candidate: Candidate) -> str:
    target = candidate.target
    aavso = candidate.aavso
    simbad = candidate.simbad
    pieces: list[str] = []
    if aavso and aavso.status == "ok" and aavso.recent_observations <= 5:
        pieces.append("sparse recent AAVSO coverage")
    if simbad and simbad.status == "ok" and simbad.object_type.endswith("?"):
        pieces.append(f"SIMBAD object type is uncertain ({simbad.object_type})")
    if "|" in (target.var_type or "") or ":" in (target.var_type or ""):
        pieces.append(f"VSX classification is ambiguous ({target.var_type})")
    if target.period_days is None:
        pieces.append("no VSX period listed")
    if target.catalog_amplitude and target.catalog_amplitude >= 0.25:
        pieces.append(f"amplitude is large enough to measure from an urban site ({target.catalog_amplitude:.2f} mag)")
    return "; ".join(pieces) if pieces else "good observability, but lower novelty signal in current metadata"
