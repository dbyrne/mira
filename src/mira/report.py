from __future__ import annotations

import csv
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from .models import Candidate, Observability
from .scoring import candidate_sort_key, is_uncertain_type
from .vsx import tokenize_var_type
from .ztf import safe_file_stem


_SHORT_PERIOD_EXACT = {"EA", "EB", "EW", "DSCT"}
_SHORT_PERIOD_PREFIXES = ("RR",)
_LONG_PERIOD_EXACT = {"M"}
_LONG_PERIOD_PREFIXES = ("SR", "L")


def _has_short_period_type(var_type: str) -> bool:
    tokens = tokenize_var_type(var_type)
    return any(
        token in _SHORT_PERIOD_EXACT or any(token.startswith(p) for p in _SHORT_PERIOD_PREFIXES)
        for token in tokens
    )


def _has_long_period_type(var_type: str) -> bool:
    tokens = tokenize_var_type(var_type)
    return any(
        token in _LONG_PERIOD_EXACT or any(token.startswith(p) for p in _LONG_PERIOD_PREFIXES)
        for token in tokens
    )


def clean_previous_outputs(output_dir: Path) -> None:
    packet_dir = output_dir / "candidate_packets"
    if output_dir.exists():
        for pattern in ("candidate_queue*.csv", "best_*.csv", "shared_targets.csv"):
            for path in output_dir.glob(pattern):
                path.unlink()
        notes = output_dir / "research_notes.md"
        if notes.exists():
            notes.unlink()
    if packet_dir.exists():
        for pattern in ("*.md", "*.png"):
            for path in packet_dir.glob(pattern):
                path.unlink()


def compute_packet_union_oids(
    candidates: list[Candidate],
    top_packets: int,
    site_names: list[str],
) -> set[int]:
    """Returns the OIDs that will appear in any top-N view (global, per-site, shared).
    Used to drive enrichment so that targets surfaced only by the per-site or
    shared queues still get AAVSO/SIMBAD/Gaia/ZTF treatment.
    """
    oids: set[int] = set()
    for c in candidates[:top_packets]:
        oids.add(c.target.oid)
    if len(site_names) <= 1:
        return oids
    for site_name in site_names:
        site_filtered = sorted(
            [c for c in candidates if site_name in c.observable_site_names],
            key=lambda c: _per_site_sort_key(c, site_name),
        )
        for c in site_filtered[:top_packets]:
            oids.add(c.target.oid)
    shared = sorted(
        [c for c in candidates if len(c.observabilities) >= 2],
        key=candidate_sort_key,
    )
    for c in shared[:top_packets]:
        oids.add(c.target.oid)
    return oids


def write_outputs(
    candidates: list[Candidate],
    output_dir: Path,
    top_packets: int,
    site_names: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    packet_dir = output_dir / "candidate_packets"
    packet_dir.mkdir(parents=True, exist_ok=True)

    if site_names is None:
        site_names = sorted({obs.site_name for c in candidates for obs in c.observabilities})

    write_queue_csv(candidates, output_dir / "candidate_queue.csv")

    packet_oids: set[int] = set()
    for c in candidates[:top_packets]:
        packet_oids.add(c.target.oid)

    if len(site_names) > 1:
        for site_name in site_names:
            site_candidates = sorted(
                [c for c in candidates if site_name in c.observable_site_names],
                key=lambda c: _per_site_sort_key(c, site_name),
            )
            slug = _site_slug(site_name)
            write_queue_csv(
                site_candidates,
                output_dir / f"best_{slug}.csv",
                primary_site_name=site_name,
            )
            for c in site_candidates[:top_packets]:
                packet_oids.add(c.target.oid)

        collaboration = [c for c in candidates if len(c.observabilities) >= 2]
        collaboration.sort(key=candidate_sort_key)
        write_queue_csv(collaboration, output_dir / "shared_targets.csv")
        for c in collaboration[:top_packets]:
            packet_oids.add(c.target.oid)

    write_research_notes(candidates, output_dir / "research_notes.md", site_names, metadata=metadata)

    packet_count = 0
    for candidate in candidates:
        if candidate.target.oid in packet_oids:
            write_candidate_packet(candidate, packet_dir)
            packet_count += 1
    return packet_count


def _per_site_sort_key(candidate: Candidate, site_name: str) -> tuple:
    obs = next(
        (o for o in candidate.observabilities if o.site_name == site_name),
        None,
    )
    if obs is None:
        # Should never happen - caller filters first - but be defensive.
        return candidate_sort_key(candidate)
    aavso = candidate.aavso
    if aavso is not None and aavso.status in ("ok", "ok-cached"):
        aavso_known = True
        aavso_recent = aavso.recent_observations
    else:
        aavso_known = False
        aavso_recent = 10**9
    amplitude = candidate.target.catalog_amplitude
    site_score = candidate.site_scores.get(site_name, candidate.score)
    return (
        -site_score,
        not aavso_known,
        aavso_recent,
        -obs.minutes_above_minimum,
        -obs.max_altitude_deg,
        amplitude is None,
        -(amplitude or 0.0),
    )


def _site_slug(site_name: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in site_name).strip("_")
    return cleaned or "site"


def _observability_for(candidate: Candidate, site_name: str | None) -> Observability:
    if site_name is None:
        return candidate.best_observability
    for obs in candidate.observabilities:
        if obs.site_name == site_name:
            return obs
    return candidate.best_observability


def write_queue_csv(
    candidates: list[Candidate],
    path: Path,
    primary_site_name: str | None = None,
) -> None:
    fields = [
        "rank",
        "score",
        "global_score",
        "name",
        "type",
        "ra_deg",
        "dec_deg",
        "bright_mag",
        "faint_mag_or_amplitude",
        "faint_is_amplitude",
        "amplitude_mag",
        "period_days",
        "primary_site",
        "observable_sites",
        "max_altitude_deg",
        "minutes_above_minimum",
        "best_night_date",
        "best_local_time",
        "galactic_latitude_deg",
        "aavso_status",
        "aavso_recent_observations",
        "aavso_derived_period_days",
        "aavso_period_disagrees",
        "simbad_status",
        "simbad_main_id",
        "simbad_object_type",
        "simbad_separation_arcsec",
        "gaia_status",
        "gaia_source_id",
        "gaia_bp_rp",
        "gaia_color_anomaly",
        "ztf_status",
        "ztf_observations",
        "ztf_amplitude_mag",
        "ztf_derived_period_days",
        "ztf_period_disagrees",
        "vsx_url",
        "reasons",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for rank, candidate in enumerate(candidates, start=1):
            target = candidate.target
            obs = _observability_for(candidate, primary_site_name)
            aavso = candidate.aavso
            simbad = candidate.simbad
            gaia = candidate.gaia
            ztf = candidate.ztf
            row_score = candidate.score
            row_reasons = candidate.reasons
            if primary_site_name is not None and primary_site_name in candidate.site_scores:
                row_score = candidate.site_scores[primary_site_name]
                row_reasons = candidate.site_reasons.get(primary_site_name, candidate.reasons)
            writer.writerow(
                {
                    "rank": rank,
                    "score": f"{row_score:.1f}",
                    "global_score": f"{candidate.score:.1f}",
                    "name": target.name,
                    "type": target.var_type,
                    "ra_deg": f"{target.ra_deg:.5f}",
                    "dec_deg": f"{target.dec_deg:.5f}",
                    "bright_mag": _format_optional(target.bright_mag),
                    "faint_mag_or_amplitude": _format_optional(target.faint_mag),
                    "faint_is_amplitude": target.faint_is_amplitude,
                    "amplitude_mag": _format_optional(target.catalog_amplitude),
                    "period_days": _format_optional(target.period_days, digits=8),
                    "primary_site": obs.site_name,
                    "observable_sites": "|".join(candidate.observable_site_names),
                    "max_altitude_deg": f"{obs.max_altitude_deg:.1f}",
                    "minutes_above_minimum": obs.minutes_above_minimum,
                    "best_night_date": obs.best_night_date.isoformat() if obs.best_night_date else "",
                    "best_local_time": obs.best_local_time.isoformat() if obs.best_local_time else "",
                    "galactic_latitude_deg": f"{obs.galactic_latitude_deg:.1f}",
                    "aavso_status": aavso.status if aavso else "",
                    "aavso_recent_observations": (
                        aavso.recent_observations
                        if aavso and aavso.status in ("ok", "ok-cached")
                        else ""
                    ),
                    "aavso_derived_period_days": _format_optional(
                        aavso.derived_period_days if aavso else None, digits=4
                    ),
                    "aavso_period_disagrees": (
                        aavso.period_disagrees if aavso and aavso.period_disagrees is not None else ""
                    ),
                    "simbad_status": simbad.status if simbad else "",
                    "simbad_main_id": simbad.main_id if simbad else "",
                    "simbad_object_type": simbad.object_type if simbad else "",
                    "simbad_separation_arcsec": _format_optional(simbad.separation_arcsec if simbad else None),
                    "gaia_status": gaia.status if gaia else "",
                    "gaia_source_id": gaia.source_id if gaia else "",
                    "gaia_bp_rp": _format_optional(gaia.bp_rp if gaia else None),
                    "gaia_color_anomaly": gaia.color_anomaly if gaia else "",
                    "ztf_status": ztf.status if ztf else "",
                    "ztf_observations": ztf.observations if ztf else "",
                    "ztf_amplitude_mag": _format_optional(ztf.amplitude_mag if ztf else None),
                    "ztf_derived_period_days": _format_optional(ztf.derived_period_days if ztf else None, digits=4),
                    "ztf_period_disagrees": ztf.period_disagrees if ztf and ztf.period_disagrees is not None else "",
                    "vsx_url": target.vsx_url,
                    "reasons": "; ".join(row_reasons),
                }
            )


_QUEUE_TITLES = {
    "novelty": "Anomaly / Novelty Discovery Queue (preliminary)",
    "practice": "Practice Queue",
    "mixed": "Practice / Collaboration Queue",
}

_QUEUE_INTROS = {
    "novelty": (
        "Novelty mode: survey-discovery bonus on, classical bonus off. "
        "These are triage candidates, not confirmed anomalies - period mismatches "
        "and color anomalies may have benign causes (blending, alias detections, "
        "bad matches). Verify before submitting anything to VSX/AAVSO."
    ),
    "practice": (
        "Practice mode: classical-GCVS bonus on, survey bonus off. "
        "These are well-known variables that AAVSO is currently under-observing - "
        "good targets for resuming long-term photometric monitoring."
    ),
    "mixed": (
        "Mixed mode: balanced classical/survey bonus. "
        "These are useful follow-up candidates - lapsed-coverage classical variables "
        "and lightly-characterized survey discoveries side by side. Treat as a "
        "practice/collaboration list, not a vetted anomaly queue."
    ),
}


def write_research_notes(
    candidates: list[Candidate],
    path: Path,
    site_names: list[str],
    metadata: dict[str, Any] | None = None,
) -> None:
    metadata = metadata or {}
    raw_mode = (metadata.get("mode") or "mixed").lower()
    if raw_mode.startswith("(yaml"):
        title_key = "mixed"
    else:
        title_key = raw_mode if raw_mode in _QUEUE_TITLES else "mixed"
    title = _QUEUE_TITLES[title_key]
    intro = _QUEUE_INTROS[title_key]

    lines = [
        f"# Mira - {title}",
        "",
        intro,
        "",
    ]

    if metadata:
        lines.append("## Run Metadata")
        lines.append("")
        for label, key in [
            ("Run started (UTC)", "run_started_utc"),
            ("Config", "config_path"),
            ("Output directory", "output_dir"),
            ("Start date", "start_date"),
            ("Mode", "mode"),
            ("VSX row limit", "vsx_row_limit"),
            ("Candidates after filters", "candidates_after_filters"),
            ("AAVSO enriched", "aavso_enriched"),
            ("SIMBAD enriched", "simbad_enriched"),
            ("Gaia DR3 enriched", "gaia_enriched"),
            ("ZTF enriched", "ztf_enriched"),
            ("Top N per view", "top_packets_per_view"),
        ]:
            value = metadata.get(key)
            if value is not None:
                lines.append(f"- {label}: `{value}`")
        lines.append("")

    lines.extend(_notes_section("Best Targets Across All Sites", candidates[:10]))

    if len(site_names) > 1:
        for site_name in site_names:
            site_candidates = sorted(
                [c for c in candidates if site_name in c.observable_site_names],
                key=lambda c: _per_site_sort_key(c, site_name),
            )
            lines.extend(
                _notes_section(
                    f"Best from {site_name}",
                    site_candidates[:10],
                    primary_site_name=site_name,
                )
            )

        collaboration = [c for c in candidates if len(c.observabilities) >= 2]
        collaboration.sort(key=candidate_sort_key)
        lines.extend(
            _notes_section(
                "Collaboration Targets (observable from 2+ sites)",
                collaboration[:10],
            )
        )

    lines.extend(
        [
            "## Triage Rules",
            "",
            "- Prefer sparse AAVSO coverage plus a clean SIMBAD match.",
            "- Prefer long-period SR/L candidates for nightly/weekly urban follow-up.",
            "- Prefer EW/EB/RR candidates only when you can commit to a continuous time-series run.",
            "- Treat popular objects with many recent AAVSO observations as calibration/practice targets, not novelty targets.",
            "- A target listed as observable from a darker site is usually the better choice when both sites can see it.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def _notes_section(
    heading: str,
    candidates: list[Candidate],
    primary_site_name: str | None = None,
) -> list[str]:
    lines = [f"## {heading}", ""]
    if not candidates:
        lines.append("- (no candidates in this view)")
        lines.append("")
        return lines

    for rank, candidate in enumerate(candidates, start=1):
        target = candidate.target
        obs = _observability_for(candidate, primary_site_name)
        aavso = candidate.aavso
        simbad = candidate.simbad
        sites_text = " + ".join(candidate.observable_site_names)
        if primary_site_name is not None and primary_site_name in candidate.site_scores:
            score_label = f"`{candidate.site_scores[primary_site_name]:.1f}` (global `{candidate.score:.1f}`)"
        else:
            score_label = f"`{candidate.score:.1f}`"
        lines.extend(
            [
                f"### {rank}. {target.name}",
                "",
                f"- Score: {score_label}",
                f"- Observable from: `{sites_text}`",
                f"- VSX/SIMBAD type: `{target.var_type or 'blank'}` / `{simbad.object_type if simbad else 'not checked'}`",
                f"- SIMBAD main ID: `{simbad.main_id if simbad else 'not checked'}`",
                f"- Recent AAVSO observations: `{_format_aavso_count(aavso)}`",
                f"- Best window ({obs.site_name}): `{obs.best_night_date.isoformat() if obs.best_night_date else 'n/a'}`, "
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
    return lines


def write_candidate_packet(candidate: Candidate, packet_dir: Path) -> Path:
    target = candidate.target
    aavso = candidate.aavso
    simbad = candidate.simbad
    gaia = candidate.gaia
    ztf = candidate.ztf
    path = packet_dir / f"{safe_file_stem(target.name)}.md"
    sites_text = " + ".join(candidate.observable_site_names)
    lines = [
        f"# {target.name}",
        "",
        f"Score: **{candidate.score:.1f}**  ",
        f"Observable from: **{sites_text}**",
        "",
        "## Catalog",
        "",
        f"- VSX type: `{target.var_type or 'blank'}`",
        f"- Coordinates: RA `{target.ra_deg:.5f}`, Dec `{target.dec_deg:.5f}`",
        f"- Catalog photometry: {_catalog_photometry_text(target)}",
        f"- Catalog amplitude: `{_format_optional(target.catalog_amplitude)}` mag",
        f"- Period: `{_format_optional(target.period_days, digits=8)}` days",
        f"- Spectral type: `{target.spectral_type or 'blank'}`",
        f"- Galactic latitude: `{candidate.best_observability.galactic_latitude_deg:.1f} deg`",
        f"- VSX: {target.vsx_url}",
        f"- AAVSO finder chart: {_vsp_chart_url(target.name)}",
        "",
    ]

    for index, obs in enumerate(candidate.observabilities):
        heading_suffix = " (best)" if index == 0 else ""
        lines.extend(
            [
                f"## Observability from {obs.site_name}{heading_suffix}",
                "",
                f"- Max altitude in dark window: `{obs.max_altitude_deg:.1f} deg`",
                f"- Best single-night dark time above altitude floor: `{obs.minutes_above_minimum} min`",
                f"- Best window date: `{obs.best_night_date.isoformat() if obs.best_night_date else 'n/a'}`",
                f"- Best sampled local time: `{obs.best_local_time.isoformat() if obs.best_local_time else 'n/a'}`",
                "",
            ]
        )

    lines.extend(
        [
            "## Observing Strategy",
            "",
            f"- {_observing_strategy_text(target)}",
            "",
            "## Why It Was Flagged",
            "",
        ]
    )
    lines.extend(f"- {reason}" for reason in candidate.reasons)

    lines.extend(["", "## AAVSO Recent Coverage", ""])
    if aavso is None:
        lines.append("- Not requested for this run.")
    else:
        lines.append(f"- Status: `{aavso.status}`")
        if aavso.status in ("ok", "ok-cached"):
            lines.extend(
                [
                    f"- Recent observations: `{aavso.recent_observations}`",
                    f"- JD range: `{_format_optional(aavso.from_jd, digits=2)}-"
                    f"{_format_optional(aavso.to_jd, digits=2)}`",
                ]
            )
            last_iso = _format_jd_as_iso(aavso.last_observation_jd)
            if last_iso:
                lines.append(f"- Most recent observation: `{last_iso}` (JD `{aavso.last_observation_jd:.2f}`)")
            elif aavso.recent_observations == 0:
                lines.append("- Most recent observation: `none in the configured window`")
            if aavso.derived_period_days is not None:
                lines.append(
                    f"- Lomb-Scargle period: `{aavso.derived_period_days:.4f}` d "
                    f"(peak power `{_format_optional(aavso.period_power, digits=3)}`)"
                )
            if aavso.period_disagrees is True:
                lines.append("- **AAVSO period disagrees with VSX catalog** - flagged as a real anomaly signal.")
            elif aavso.period_disagrees is False:
                lines.append("- AAVSO period agrees with VSX catalog within tolerance.")
            elif aavso.period_note:
                lines.append(f"- Period agreement: not assessable ({aavso.period_note})")
        else:
            lines.append("- Recent observations: not available (status above).")
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

    lines.extend(["", "## Gaia DR3 Context", ""])
    if gaia is None:
        lines.append("- Not requested for this run.")
    else:
        lines.append(f"- Status: `{gaia.status}`")
        if gaia.status == "ok":
            lines.extend(
                [
                    f"- Source ID: `{gaia.source_id or 'n/a'}`",
                    f"- G magnitude: `{_format_optional(gaia.g_mag)}`",
                    f"- BP-RP color: `{_format_optional(gaia.bp_rp)}`",
                    f"- Parallax: `{_format_optional(gaia.parallax_mas)}` +/- "
                    f"`{_format_optional(gaia.parallax_error_mas)}` mas",
                    f"- RUWE: `{_format_optional(gaia.ruwe)}`",
                    f"- Gaia photometric variability flag: `{'VARIABLE' if gaia.photometric_variable else 'not flagged'}`",
                    f"- Match separation: `{_format_optional(gaia.separation_arcsec)}` arcsec",
                ]
            )
            if gaia.ipd_frac_multi_peak is not None:
                crowding_note = (
                    " (PSF appears blended/contaminated)"
                    if gaia.ipd_frac_multi_peak > 0.1
                    else ""
                )
                lines.append(
                    f"- IPD multi-peak fraction: `{gaia.ipd_frac_multi_peak:.3f}`{crowding_note}"
                )
            if gaia.color_anomaly:
                lines.append(f"- **Color anomaly**: {gaia.color_anomaly}")
        if gaia.note:
            lines.append(f"- Note: {gaia.note}")

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
        if ztf.derived_period_days is not None:
            lines.append(
                f"- Lomb-Scargle period: `{ztf.derived_period_days:.4f}` d "
                f"(peak power `{_format_optional(ztf.period_power, digits=3)}`)"
            )
        if ztf.period_disagrees is True:
            lines.append("- **Period disagrees with VSX catalog** - flagged as a real anomaly signal.")
        elif ztf.period_disagrees is False:
            lines.append("- ZTF period agrees with VSX catalog within tolerance.")
        elif ztf.derived_period_days is not None and target.period_days is None:
            lines.append("- ZTF period derived; no VSX catalog period to compare against.")
        elif ztf.note:
            lines.append(f"- Period agreement: not assessable ({ztf.note})")
        plot_blocks: list[str] = []
        if ztf.plot_path:
            plot_blocks.append(f"![ZTF light curve]({Path(ztf.plot_path).name})")
        if ztf.folded_plot_path:
            plot_blocks.append(f"![ZTF folded light curve]({Path(ztf.folded_plot_path).name})")
        if plot_blocks:
            lines.append("")
            lines.extend(plot_blocks)

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


def _format_aavso_count(aavso) -> str:
    if aavso is None:
        return "not checked"
    if aavso.status not in ("ok", "ok-cached"):
        return f"unavailable ({aavso.status})"
    suffix = " (cached)" if aavso.status == "ok-cached" else ""
    return f"{aavso.recent_observations}{suffix}"


def _format_jd_as_iso(jd: float | None) -> str | None:
    if jd is None:
        return None
    from datetime import datetime, timezone

    unix_secs = (jd - 2440587.5) * 86400
    try:
        return datetime.fromtimestamp(unix_secs, tz=timezone.utc).date().isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _catalog_photometry_text(target) -> str:
    if target.faint_is_amplitude:
        return (
            f"bright `{_format_optional(target.bright_mag)}` {target.bright_band or ''}; "
            f"amplitude `{_format_optional(target.faint_mag)}` mag {target.faint_band or ''}"
        )
    return (
        f"range `{_format_optional(target.bright_mag)}-{_format_optional(target.faint_mag)}` "
        f"({target.bright_band}/{target.faint_band})"
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
    period = target.period_days
    if _has_short_period_type(target.var_type) or (period is not None and period <= 2):
        return (
            "Time-series follow-up: run continuously for 2-4 hours when the target is high, "
            "then compare the folded light curve against the VSX period."
        )
    if _has_long_period_type(target.var_type) or (period is not None and period >= 10):
        return (
            "Long-cadence follow-up: one calibrated point every clear night or two is useful; "
            "weekly cadence is still worthwhile for slow red variables."
        )
    return "Start with one calibrated point on several clear nights, then switch to time-series if short-term changes appear."


def _research_value_text(candidate: Candidate) -> str:
    target = candidate.target
    aavso = candidate.aavso
    simbad = candidate.simbad
    gaia = candidate.gaia
    pieces: list[str] = []
    if aavso and aavso.status.startswith("ok") and aavso.recent_observations <= 5:
        pieces.append("sparse recent AAVSO coverage")
    if simbad and simbad.status == "ok" and simbad.object_type.endswith("?"):
        pieces.append(f"SIMBAD object type is uncertain ({simbad.object_type})")
    if is_uncertain_type(target.var_type):
        pieces.append(f"VSX classification is uncertain or broad ({target.var_type or 'blank'})")
    if target.period_days is None:
        pieces.append("no VSX period listed")
    if target.catalog_amplitude and target.catalog_amplitude >= 0.25:
        pieces.append(f"amplitude is large enough to measure from an urban site ({target.catalog_amplitude:.2f} mag)")
    if gaia and gaia.bp_rp is not None and gaia.bp_rp >= 2.0:
        pieces.append(f"Gaia color is very red (BP-RP={gaia.bp_rp:.2f})")
    if gaia and gaia.ruwe is not None and gaia.ruwe >= 1.4:
        pieces.append(f"Gaia RUWE is elevated ({gaia.ruwe:.2f})")
    return "; ".join(pieces) if pieces else "good observability, but lower novelty signal in current metadata"


def _gaia_summary_text(gaia) -> str:
    if gaia is None:
        return "not checked"
    if gaia.status != "ok":
        return gaia.status
    parts = [f"source `{gaia.source_id}`"]
    if gaia.g_mag is not None:
        parts.append(f"G={gaia.g_mag:.2f}")
    if gaia.bp_rp is not None:
        parts.append(f"BP-RP={gaia.bp_rp:.2f}")
    if gaia.parallax_mas is not None:
        parts.append(f"plx={gaia.parallax_mas:.3f} mas")
    if gaia.ruwe is not None:
        parts.append(f"RUWE={gaia.ruwe:.2f}")
    return ", ".join(parts)


def _aavso_recent_text(aavso) -> str:
    if aavso is None:
        return "not checked"
    if not aavso.status.startswith("ok"):
        return aavso.status
    return str(aavso.recent_observations)
