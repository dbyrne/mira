from __future__ import annotations

import argparse
from dataclasses import replace as dc_replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

_run_timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

from .aavso import apply_aavso_score, enrich_candidates_with_aavso, fetch_recent_observation_count
from .config import load_config
from .gaia import apply_gaia_score, enrich_candidates_with_gaia, fetch_gaia_match
from .report import (
    clean_previous_outputs,
    compute_packet_union_oids,
    write_candidate_packet,
    write_outputs,
)
from .scoring import apply_ztf_score, build_candidates, build_single_candidate, candidate_sort_key
from .simbad import enrich_candidates_with_simbad, fetch_simbad_match
from .vsx import fetch_vsx_target_by_name, fetch_vsx_targets
from .ztf import enrich_with_ztf


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a Jersey City AAVSO anomaly observing queue.")
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="Fetch VSX targets and generate candidate packets.")
    run_parser.add_argument("--config", default="config/jersey_city.yaml", help="YAML config path.")
    run_parser.add_argument("--limit", type=int, default=None, help="Override VSX row limit.")
    run_parser.add_argument("--top", type=int, default=None, help="Override number of packets.")
    run_parser.add_argument("--start-date", default=None, help="Local observing start date, YYYY-MM-DD.")
    run_parser.add_argument("--output-dir", default=None, help="Override output directory (lets you write practice and novelty passes side by side without editing the YAML).")
    run_parser.add_argument("--aavso-top", type=int, default=None, help="Check AAVSO recent coverage for top N candidates.")
    run_parser.add_argument("--simbad-top", type=int, default=None, help="Fetch SIMBAD context for top N candidates.")
    run_parser.add_argument("--gaia-top", type=int, default=None, help="Fetch Gaia DR3 context for top N candidates.")
    run_parser.add_argument("--ztf-top", type=int, default=0, help="Fetch ZTF light curves for the top N candidates.")
    run_parser.add_argument(
        "--mode",
        choices=["novelty", "practice", "mixed"],
        default=None,
        help="Scoring profile. novelty: survey-discovery bonus only. practice: classical-GCVS bonus only. mixed: balanced. Overrides scoring.survey_name_bonus and scoring.classical_name_bonus.",
    )

    target_parser = subparsers.add_parser(
        "target",
        help="Fetch and enrich one named VSX target without rerunning the full queue.",
    )
    target_parser.add_argument("name", help="VSX target name (e.g. 'RR Lyr', 'ASASSN-V J160002.35+453848.8').")
    target_parser.add_argument("--config", default="config/jersey_city.yaml", help="YAML config path.")
    target_parser.add_argument("--start-date", default=None, help="Local observing start date, YYYY-MM-DD.")
    target_parser.add_argument("--ztf", action="store_true", help="Fetch ZTF light curve and run period analysis.")
    target_parser.add_argument(
        "--mode",
        choices=["novelty", "practice", "mixed"],
        default=None,
        help="Scoring profile (see run --mode).",
    )

    submit_parser = subparsers.add_parser(
        "submit",
        help="Run photometry on a captures dir and produce an AAVSO upload file.",
    )
    submit_parser.add_argument("--captures", required=True, help="Directory containing FITS files for one target.")
    submit_parser.add_argument("--target", required=True, help="VSX target name (used to look up RA/Dec).")
    submit_parser.add_argument(
        "--comp-stars",
        required=True,
        help="Path to a JSON file listing AAVSO comparison stars: "
        "[{\"label\":\"095\",\"ra_deg\":...,\"dec_deg\":...,\"catalog_mag\":9.5,\"catalog_band\":\"V\"}, ...]",
    )
    submit_parser.add_argument(
        "--observer-code",
        required=True,
        help="Your AAVSO observer code (assigned when you register on aavso.org).",
    )
    submit_parser.add_argument("--config", default="config/s30_pro_jc.yaml", help="YAML config (used to resolve target RA/Dec via VSX).")
    submit_parser.add_argument("--chart-id", default="na", help="AAVSO chart sequence ID (e.g. X12345AAB), if known.")
    submit_parser.add_argument(
        "--aperture-arcsec",
        type=float,
        default=6.0,
        help="Photometric aperture radius in arcsec (default 6).",
    )

    tonight_parser = subparsers.add_parser(
        "tonight",
        help="Show the queue and session plan for what's observable in the next N hours from now.",
    )
    tonight_parser.add_argument("--config", default="config/s30_pro_jc.yaml", help="YAML config path.")
    tonight_parser.add_argument("--hours", type=float, default=4.0, help="Look-ahead window in hours (default 4).")
    tonight_parser.add_argument("--top", type=int, default=None, help="Override number of packets.")
    tonight_parser.add_argument("--output-dir", default=None, help="Override output directory.")
    tonight_parser.add_argument("--aavso-top", type=int, default=None)
    tonight_parser.add_argument("--simbad-top", type=int, default=None)
    tonight_parser.add_argument("--gaia-top", type=int, default=None)
    tonight_parser.add_argument(
        "--mode",
        choices=["novelty", "practice", "mixed"],
        default=None,
        help="Scoring profile (see run --mode).",
    )

    args = parser.parse_args()
    if args.command == "target":
        target(args)
    elif args.command == "tonight":
        tonight(args)
    elif args.command == "submit":
        submit(args)
    elif args.command in (None, "run"):
        run(args)


def run(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    if args.limit is not None:
        config = _replace_vsx_limit(config, args.limit)
    if args.mode is not None:
        config = _apply_mode(config, args.mode)
        print(f"Mode: {args.mode}")
    top_packets = args.top if args.top is not None else config.output.top_packets
    output_dir = Path(args.output_dir) if args.output_dir else config.output.directory
    packet_dir = output_dir / "candidate_packets"
    clean_previous_outputs(Path(output_dir))

    print(f"Fetching up to {config.vsx_query.row_limit} VSX rows from VizieR...")
    targets = fetch_vsx_targets(config.vsx_query)
    print(f"Fetched {len(targets)} candidate catalog rows.")

    start_date = date.fromisoformat(args.start_date) if args.start_date else None
    candidates = build_candidates(targets, config, start_date=start_date)
    print(f"{len(candidates)} targets passed site filters.")

    site_names = [site.name for site in config.sites]
    union_oids = compute_packet_union_oids(candidates, top_packets, site_names)

    aavso_top = config.aavso.enrich_top if args.aavso_top is None else max(0, int(args.aavso_top))
    aavso_count = 0
    if config.aavso.enabled and (aavso_top or union_oids):
        aavso_count = enrich_candidates_with_aavso(candidates, config, limit=aavso_top, extra_oids=union_oids)
        print(f"Checked AAVSO recent coverage for {aavso_count} candidates (top {aavso_top} + {len(union_oids)} packet-view extras)")

    union_oids = compute_packet_union_oids(candidates, top_packets, site_names)

    simbad_top = config.simbad.enrich_top if args.simbad_top is None else max(0, int(args.simbad_top))
    simbad_count = 0
    if config.simbad.enabled and (simbad_top or union_oids):
        simbad_count = enrich_candidates_with_simbad(candidates, config, limit=simbad_top, extra_oids=union_oids)
        print(f"Fetched SIMBAD context for {simbad_count} candidates")

    gaia_top = config.gaia.enrich_top if args.gaia_top is None else max(0, int(args.gaia_top))
    gaia_count = 0
    if config.gaia.enabled and (gaia_top or union_oids):
        gaia_count = enrich_candidates_with_gaia(candidates, config, limit=gaia_top, extra_oids=union_oids)
        candidates.sort(key=candidate_sort_key)
        print(f"Fetched Gaia DR3 context for {gaia_count} candidates")

    gaia_top = config.gaia.enrich_top if args.gaia_top is None else max(0, int(args.gaia_top))
    if config.gaia.enabled and gaia_top:
        checked = min(gaia_top, len(candidates))
        print(f"Fetching Gaia DR3 context for top {checked} candidates...")
        enrich_candidates_with_gaia(candidates, config, limit=gaia_top)

    ztf_top = max(0, int(args.ztf_top or 0))
    ztf_count = 0
    if config.ztf.enabled and ztf_top:
        # ZTF stays strictly top-N (no union extras) since IRSA is slow and
        # rate-limited; users opt in via --ztf-top.
        for index, candidate in enumerate(candidates[:ztf_top], start=1):
            print(f"Fetching ZTF light curve {index}/{ztf_top}: {candidate.target.name}")
            candidate.ztf = enrich_with_ztf(candidate, config.ztf, packet_dir)
            apply_ztf_score(candidate, config)
        candidates.sort(key=candidate_sort_key)
        ztf_count = ztf_top

    metadata = {
        "config_path": args.config,
        "output_dir": str(output_dir),
        "start_date": args.start_date or "today",
        "mode": args.mode or "(yaml defaults)",
        "vsx_row_limit": config.vsx_query.row_limit,
        "candidates_after_filters": len(candidates),
        "aavso_enriched": aavso_count,
        "simbad_enriched": simbad_count,
        "gaia_enriched": gaia_count,
        "ztf_enriched": ztf_count,
        "top_packets_per_view": top_packets,
        "run_started_utc": _run_timestamp,
    }
    packet_count = write_outputs(
        candidates,
        Path(output_dir),
        top_packets,
        site_names=site_names,
        metadata=metadata,
    )
    print(f"Wrote {Path(output_dir) / 'candidate_queue.csv'}")
    if len(site_names) > 1:
        for name in site_names:
            print(f"Wrote {Path(output_dir) / f'best_{_site_slug(name)}.csv'}")
        print(f"Wrote {Path(output_dir) / 'shared_targets.csv'}")
    print(f"Wrote {packet_count} packets in {packet_dir}")


def _site_slug(name: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in name).strip("_")
    return cleaned or "site"


def submit(args: argparse.Namespace) -> None:
    """Run photometry on captured FITS files and produce an AAVSO upload file."""
    import json as _json

    from .photometry import (
        CompStar,
        process_capture,
        write_aavso_extended_file,
    )

    captures_dir = Path(args.captures)
    if not captures_dir.exists():
        print(f"Captures directory '{captures_dir}' does not exist.")
        return

    print(f"Looking up '{args.target}' in VSX...")
    vsx_target = fetch_vsx_target_by_name(args.target)
    if vsx_target is None:
        print(f"Target '{args.target}' not found in VSX. Cannot proceed without RA/Dec.")
        return
    print(
        f"Target: {vsx_target.name} at RA {vsx_target.ra_deg:.5f}, "
        f"Dec {vsx_target.dec_deg:.5f}"
    )

    comp_path = Path(args.comp_stars)
    if not comp_path.exists():
        print(f"Comparison-star file '{comp_path}' does not exist.")
        return
    with comp_path.open(encoding="utf-8") as handle:
        comp_data = _json.load(handle)
    comps = [
        CompStar(
            label=str(item["label"]),
            ra_deg=float(item["ra_deg"]),
            dec_deg=float(item["dec_deg"]),
            catalog_mag=float(item["catalog_mag"]),
            catalog_band=str(item.get("catalog_band", "V")),
        )
        for item in comp_data
    ]
    print(f"Loaded {len(comps)} comparison stars.")

    fits_files = sorted(list(captures_dir.glob("*.fits")) + list(captures_dir.glob("*.fit")))
    if not fits_files:
        print(f"No FITS files found in {captures_dir}.")
        return
    print(f"Processing {len(fits_files)} FITS files...")

    observations = []
    failures = []
    for fits_path in fits_files:
        try:
            obs = process_capture(
                fits_path,
                args.target,
                vsx_target.ra_deg,
                vsx_target.dec_deg,
                comps,
                aperture_radius_arcsec=args.aperture_arcsec,
            )
        except Exception as exc:
            failures.append((fits_path.name, str(exc)))
            continue
        if obs is None:
            failures.append((fits_path.name, "no usable signal"))
            continue
        obs.chart_id = args.chart_id
        observations.append(obs)
        print(f"  {fits_path.name}: mag {obs.magnitude:.3f} +/- {obs.magnitude_error:.3f} via comp {obs.comp_star_label}")

    if failures:
        print(f"\n{len(failures)} files failed:")
        for name, reason in failures[:10]:
            print(f"  {name}: {reason}")

    if not observations:
        print("\nNo successful observations. Verify FITS files have a celestial WCS (NINA must plate-solve).")
        return

    output_path = captures_dir / f"aavso_{args.target.replace(' ', '_').replace('/', '_')}.txt"
    write_aavso_extended_file(
        observations,
        output_path,
        observer_code=args.observer_code,
        chart_id=args.chart_id,
    )

    mags = [o.magnitude for o in observations]
    median_mag = sorted(mags)[len(mags) // 2]
    print(
        f"\n{len(observations)} observations submitted, median magnitude "
        f"{median_mag:.3f} (range {min(mags):.3f}–{max(mags):.3f})"
    )
    print(f"Wrote {output_path}")
    print(f"Verify the file, then upload at: https://www.aavso.org/webobs/file")


def tonight(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    if args.mode is not None:
        config = _apply_mode(config, args.mode)
        print(f"Mode: {args.mode}")

    # Override each site to look at tonight only.
    new_sites = tuple(
        dc_replace(site, observing_window=dc_replace(site.observing_window, nights=1))
        for site in config.sites
    )
    config = dc_replace(config, sites=new_sites)

    top_packets = args.top if args.top is not None else config.output.top_packets
    base_output = Path(args.output_dir) if args.output_dir else config.output.directory
    output_dir = base_output / "tonight"
    packet_dir = output_dir / "candidate_packets"
    clean_previous_outputs(output_dir)

    today = date.today()
    primary_tz = ZoneInfo(config.sites[0].observer.timezone)
    now_local = datetime.now(primary_tz)
    window_end = now_local + timedelta(hours=args.hours)

    print(
        f"Tonight: {today.isoformat()}, looking ahead {args.hours:g}h "
        f"({now_local.strftime('%H:%M')} -> {window_end.strftime('%H:%M %Z')})"
    )

    print(f"Fetching up to {config.vsx_query.row_limit} VSX rows from VizieR...")
    targets = fetch_vsx_targets(config.vsx_query)
    candidates = build_candidates(targets, config, start_date=today)
    print(f"{len(candidates)} targets passed site filters for tonight")

    candidates = _filter_to_window(candidates, now_local, window_end)
    print(f"{len(candidates)} targets observable in the next {args.hours:g}h")

    if not candidates:
        print(
            "Nothing in the next window. Try: increase --hours, run later when "
            "stars are higher, or use 'anomaly-scout run' to see the multi-night queue."
        )
        return

    site_names = [site.name for site in config.sites]
    union_oids = compute_packet_union_oids(candidates, top_packets, site_names)

    aavso_top = config.aavso.enrich_top if args.aavso_top is None else max(0, int(args.aavso_top))
    aavso_count = 0
    if config.aavso.enabled and (aavso_top or union_oids):
        aavso_count = enrich_candidates_with_aavso(candidates, config, limit=aavso_top, extra_oids=union_oids)
        print(f"AAVSO enriched: {aavso_count}")

    union_oids = compute_packet_union_oids(candidates, top_packets, site_names)
    simbad_top = config.simbad.enrich_top if args.simbad_top is None else max(0, int(args.simbad_top))
    simbad_count = 0
    if config.simbad.enabled and (simbad_top or union_oids):
        simbad_count = enrich_candidates_with_simbad(candidates, config, limit=simbad_top, extra_oids=union_oids)
        print(f"SIMBAD enriched: {simbad_count}")

    gaia_top = config.gaia.enrich_top if args.gaia_top is None else max(0, int(args.gaia_top))
    gaia_count = 0
    if config.gaia.enabled and (gaia_top or union_oids):
        gaia_count = enrich_candidates_with_gaia(candidates, config, limit=gaia_top, extra_oids=union_oids)
        candidates.sort(key=candidate_sort_key)
        print(f"Gaia enriched: {gaia_count}")

    metadata = {
        "config_path": args.config,
        "output_dir": str(output_dir),
        "start_date": today.isoformat(),
        "mode": args.mode or "(yaml defaults)",
        "vsx_row_limit": config.vsx_query.row_limit,
        "candidates_after_filters": len(candidates),
        "aavso_enriched": aavso_count,
        "simbad_enriched": simbad_count,
        "gaia_enriched": gaia_count,
        "ztf_enriched": 0,
        "top_packets_per_view": top_packets,
        "run_started_utc": _run_timestamp,
        "tonight_window_start": now_local.isoformat(),
        "tonight_window_end": window_end.isoformat(),
        "tonight_hours": args.hours,
    }

    packet_count = write_outputs(
        candidates,
        output_dir,
        top_packets,
        site_names=site_names,
        metadata=metadata,
    )
    from .session_plan import write_session_plan

    plan_targets = candidates[:top_packets]
    write_session_plan(plan_targets, output_dir, now_local, window_end, config)
    print(f"Wrote {output_dir / 'candidate_queue.csv'}")
    print(f"Wrote {output_dir / 'session_plan.md'}")
    print(f"Wrote {output_dir / 'session_plan.csv'}")
    print(f"Wrote {output_dir / 'nina_targets.csv'} (NINA Target Scheduler import)")
    print(f"Wrote {packet_count} packets in {packet_dir}")


def _filter_to_window(candidates, now_local: datetime, window_end: datetime) -> list:
    """Keep candidates with at least one observability whose best_local_time
    falls in [now-1h, window_end]. The 1h hindsight tolerance accounts for
    'best moment is just past, target is still observable.'
    """
    earliest = now_local - timedelta(hours=1)
    return [
        c for c in candidates
        if any(
            obs.best_local_time and earliest <= obs.best_local_time <= window_end
            for obs in c.observabilities
        )
    ]


def target(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    if args.mode is not None:
        config = _apply_mode(config, args.mode)
        print(f"Mode: {args.mode}")

    print(f"Looking up '{args.name}' in VSX...")
    vsx_target = fetch_vsx_target_by_name(args.name)
    if vsx_target is None:
        print(f"Target '{args.name}' not found in VSX.")
        return
    print(f"Found: {vsx_target.name} (OID {vsx_target.oid}, type '{vsx_target.var_type or 'blank'}')")

    start_date = date.fromisoformat(args.start_date) if args.start_date else None
    candidate = build_single_candidate(vsx_target, config, start_date=start_date)

    print("Fetching AAVSO recent coverage...")
    candidate.aavso = fetch_recent_observation_count(
        vsx_target.name,
        config.aavso,
        catalog_period=vsx_target.period_days,
    )
    apply_aavso_score(candidate, config)

    print("Fetching SIMBAD context...")
    candidate.simbad = fetch_simbad_match(vsx_target.ra_deg, vsx_target.dec_deg, config.simbad)

    print("Fetching Gaia DR3 context...")
    candidate.gaia = fetch_gaia_match(
        vsx_target.ra_deg,
        vsx_target.dec_deg,
        config.gaia,
        target_name=vsx_target.name,
    )
    apply_gaia_score(candidate, config)

    packet_dir = Path(config.output.directory) / "candidate_packets"
    packet_dir.mkdir(parents=True, exist_ok=True)

    if args.ztf:
        print("Fetching ZTF light curve...")
        candidate.ztf = enrich_with_ztf(candidate, config.ztf, packet_dir)
        apply_ztf_score(candidate, config)

    path = write_candidate_packet(candidate, packet_dir)
    print(f"Wrote {path}")


def _replace_vsx_limit(config, limit: int):
    from dataclasses import replace

    return replace(config, vsx_query=replace(config.vsx_query, row_limit=limit))


_MODE_PRESETS = {
    "novelty": {"survey_name_bonus": 12, "classical_name_bonus": 0},
    "practice": {"survey_name_bonus": 0, "classical_name_bonus": 12},
    "mixed": {"survey_name_bonus": 6, "classical_name_bonus": 6},
}


def _apply_mode(config, mode: str):
    from dataclasses import replace

    return replace(config, scoring=replace(config.scoring, **_MODE_PRESETS[mode]))
