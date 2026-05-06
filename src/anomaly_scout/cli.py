from __future__ import annotations

import argparse
from dataclasses import replace as dc_replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

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

_run_timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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

    webapp_parser = subparsers.add_parser(
        "webapp",
        help="Start the Flask web app: kick off plans, monitor progress, run photometry, watch NINA. Tailscale-friendly.",
    )
    webapp_parser.add_argument(
        "--output-dir",
        default="output/s30_pro_jc/tonight",
        help="Directory where tonight's session outputs live (default output/s30_pro_jc/tonight).",
    )
    webapp_parser.add_argument(
        "--captures-root",
        default="captures",
        help="Root directory containing per-target NINA capture subdirectories (default ./captures).",
    )
    webapp_parser.add_argument("--port", type=int, default=8000, help="Port to bind (default 8000).")
    webapp_parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Interface to bind. 0.0.0.0 lets Tailscale peers reach you; 127.0.0.1 is local only.",
    )
    webapp_parser.add_argument(
        "--nina-url",
        default="http://localhost:1888",
        help="NINA Advanced API base URL (default http://localhost:1888).",
    )

    serve_parser = subparsers.add_parser(
        "serve",
        help="[deprecated alias for webapp] Serve the output directory over HTTP. Use 'webapp' instead.",
    )
    serve_parser.add_argument(
        "--output-dir",
        default="output/s30_pro_jc/tonight",
        help="Directory to serve (default output/s30_pro_jc/tonight).",
    )
    serve_parser.add_argument("--port", type=int, default=8000)
    serve_parser.add_argument("--host", default="0.0.0.0")

    submit_parser = subparsers.add_parser(
        "submit",
        help="Run photometry on a captures dir and produce an AAVSO upload file.",
    )
    submit_parser.add_argument("--captures", required=True, help="Directory containing FITS files for one target.")
    submit_parser.add_argument("--target", required=True, help="VSX target name (used to look up RA/Dec).")
    submit_parser.add_argument(
        "--comp-stars",
        default=None,
        help="Optional path to a JSON file listing AAVSO comparison stars. "
        "Format: [{\"label\":\"095\",\"ra_deg\":...,\"dec_deg\":...,\"catalog_mag\":9.5,\"catalog_band\":\"V\"}, ...] "
        "If omitted, comps are auto-fetched from AAVSO VSP for the target.",
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

    migrate_parser = subparsers.add_parser(
        "migrate-runs",
        help="Walk state_dir/<run_id>.json files and (re-)populate the SQLite session store.",
    )
    migrate_parser.add_argument(
        "--state-dir",
        default="data/webapp_runs",
        help="State directory containing run JSON files (default data/webapp_runs).",
    )
    migrate_parser.add_argument(
        "--db-path",
        default=None,
        help="Override path to sessions.db (default <state-dir>/sessions.db).",
    )

    cleanup_parser = subparsers.add_parser(
        "cleanup",
        help="Delete old run records and stale HTTP cache entries. Default is dry-run.",
    )
    cleanup_parser.add_argument(
        "--state-dir", default="data/webapp_runs",
        help="State directory containing run JSON files (default data/webapp_runs).",
    )
    cleanup_parser.add_argument(
        "--cache-dir", default="data/cache",
        help="HTTP cache root (default data/cache).",
    )
    cleanup_parser.add_argument(
        "--older-than", type=int, default=90,
        help="Age threshold in days; entries older than this are eligible for deletion (default 90).",
    )
    cleanup_parser.add_argument(
        "--runs", action="store_true",
        help="Include run records in the cleanup. Submitted sessions are kept regardless of age.",
    )
    cleanup_parser.add_argument(
        "--cache", action="store_true",
        help="Include HTTP cache entries in the cleanup.",
    )
    cleanup_parser.add_argument(
        "--apply", action="store_true",
        help="Actually delete. Without this, the command reports what it would touch but does nothing.",
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
    elif args.command == "migrate-runs":
        migrate_runs(args)
    elif args.command == "cleanup":
        cleanup(args)
    elif args.command == "webapp":
        webapp(args)
    elif args.command == "serve":
        # Backwards-compat alias: route to the new webapp.
        print("[serve] note: 'serve' is deprecated; use 'webapp'. Continuing with default webapp settings.")
        args.captures_root = "captures"
        args.nina_url = "http://localhost:1888"
        webapp(args)
    elif args.command in (None, "run"):
        run(args)


def cleanup(args: argparse.Namespace) -> None:
    """Garbage-collect old run records and HTTP cache entries.

    Default is dry-run: lists what would be removed but doesn't touch
    anything. Pass --apply to actually delete. Submitted sessions
    (those marked with `submitted_at` in the DB or run record) are kept
    regardless of age — they're irreplaceable.
    """
    import json as _json
    import time as _time

    if not (args.runs or args.cache):
        print("Specify at least one of --runs or --cache (and optionally --apply).")
        return

    cutoff = _time.time() - args.older_than * 86400
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode}] Cleanup: --older-than {args.older_than}d (cutoff {datetime.fromtimestamp(cutoff).isoformat()[:19]})")

    if args.runs:
        state_dir = Path(args.state_dir)
        if not state_dir.is_dir():
            print(f"  state-dir does not exist: {state_dir}")
        else:
            kept = 0
            removed = 0
            protected = 0
            for path in sorted(state_dir.glob("*.json")):
                if path.name == "settings.json":
                    continue
                try:
                    mtime = path.stat().st_mtime
                except OSError:
                    continue
                if mtime >= cutoff:
                    kept += 1
                    continue
                # Read the record; keep if it was submitted to AAVSO.
                try:
                    data = _json.loads(path.read_text(encoding="utf-8"))
                    submitted = bool((data.get("result") or {}).get("submitted_at"))
                except (OSError, ValueError):
                    submitted = False
                if submitted:
                    protected += 1
                    print(f"  KEEP  {path.name} (submitted to AAVSO)")
                    continue
                if args.apply:
                    try:
                        path.unlink()
                    except OSError as exc:
                        print(f"  ERROR removing {path.name}: {exc}")
                        continue
                print(f"  {'DEL' if args.apply else 'WOULD DEL'} {path.name}")
                removed += 1
            print(f"  Run records: kept {kept}, would-remove/removed {removed}, protected (submitted) {protected}")

    if args.cache:
        cache_dir = Path(args.cache_dir)
        if not cache_dir.is_dir():
            print(f"  cache-dir does not exist: {cache_dir}")
        else:
            removed = 0
            kept = 0
            for path in cache_dir.rglob("*.json"):
                try:
                    mtime = path.stat().st_mtime
                except OSError:
                    continue
                if mtime >= cutoff:
                    kept += 1
                    continue
                if args.apply:
                    try:
                        path.unlink()
                    except OSError:
                        continue
                removed += 1
            print(f"  Cache entries: kept {kept}, would-remove/removed {removed}")


def migrate_runs(args: argparse.Namespace) -> None:
    """Walk state_dir/<run_id>.json and (re-)populate sessions.db. Idempotent
    via UNIQUE(run_id) — re-running updates rows in place."""
    import json as _json

    from .webapp.db import SessionStore, from_run_record

    state_dir = Path(args.state_dir)
    if not state_dir.is_dir():
        print(f"State directory does not exist: {state_dir}")
        return
    db_path = Path(args.db_path) if args.db_path else state_dir / "sessions.db"
    store = SessionStore(db_path)

    inserted = 0
    skipped = 0
    failed = 0
    for path in sorted(state_dir.glob("*.json")):
        if path.name == "settings.json":
            continue
        try:
            data = _json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"  {path.name}: parse error ({exc})")
            failed += 1
            continue
        kwargs = from_run_record(data)
        if kwargs is None:
            skipped += 1
            continue
        try:
            store.upsert_session(**kwargs)
            inserted += 1
        except Exception as exc:
            print(f"  {path.name}: upsert error ({exc})")
            failed += 1
    print(
        f"Migrated {inserted} sessions to {db_path}. "
        f"Skipped {skipped} (not photometry submits). Failed {failed}."
    )


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


def webapp(args: argparse.Namespace) -> None:
    """Start the Flask webapp."""
    from .webapp import create_app

    output_dir = Path(args.output_dir).resolve()
    captures_root = Path(args.captures_root).resolve()

    output_dir.mkdir(parents=True, exist_ok=True)
    captures_root.mkdir(parents=True, exist_ok=True)

    app = create_app(
        output_dir=output_dir,
        captures_root=captures_root,
        nina_base_url=args.nina_url,
    )

    print("AAVSO Anomaly Scout webapp")
    print(f"  Output dir:    {output_dir}")
    print(f"  Captures root: {captures_root}")
    print(f"  NINA API:      {args.nina_url}")
    print()
    print("Open one of these from any device on your Tailnet:")
    print(f"  Local:        http://localhost:{args.port}/")
    _print_tailscale_urls(args.port)
    print()
    print("Press Ctrl+C to stop.")

    # Use Werkzeug's threaded server so HTMX polling and the long-running
    # background task don't block each other. Single-user, single-machine,
    # so this is fine; not exposing it to the internet.
    app.run(host=args.host, port=args.port, debug=False, use_reloader=False, threaded=True)


def _print_tailscale_urls(port: int) -> None:
    import json as _json
    import subprocess

    try:
        ts_ip = subprocess.run(
            ["tailscale", "ip", "-4"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        for line in ts_ip.stdout.splitlines():
            ip = line.strip()
            if ip:
                print(f"  Tailscale IP: http://{ip}:{port}/")
                break
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    try:
        ts_status = subprocess.run(
            ["tailscale", "status", "--self", "--json"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        if ts_status.returncode == 0:
            data = _json.loads(ts_status.stdout)
            dns_name = (data.get("Self") or {}).get("DNSName", "").rstrip(".")
            if dns_name:
                print(f"  Magic DNS:    http://{dns_name}:{port}/")
    except (FileNotFoundError, subprocess.TimeoutExpired, _json.JSONDecodeError):
        pass


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
        print(
            f"Could not resolve '{args.target}' — either the name doesn't match a VSX "
            "entry or VizieR was unreachable after 3 attempts. Check the spelling and "
            "your network."
        )
        return
    print(
        f"Target: {vsx_target.name} at RA {vsx_target.ra_deg:.5f}, "
        f"Dec {vsx_target.dec_deg:.5f}"
    )

    chart_id = args.chart_id
    if args.comp_stars:
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
        print(f"Loaded {len(comps)} comparison stars from {comp_path}.")
    else:
        from .vsp import fetch_vsp_chart, filter_comps_for_target

        print("Auto-fetching comp stars from AAVSO VSP...")
        try:
            chart = fetch_vsp_chart(args.target)
        except Exception as exc:
            print(f"VSP fetch failed: {exc}")
            print("Re-run with --comp-stars <path.json> to use a manual sequence.")
            return
        target_mag = vsx_target.max_mag if vsx_target.max_mag is not None else None
        comps = filter_comps_for_target(chart.comps, target_mag)
        if not comps:
            print(f"VSP chart {chart.chart_id} returned {len(chart.comps)} comps, none within mag tolerance.")
            comps = chart.comps[:6]
        print(
            f"VSP chart {chart.chart_id}: {len(chart.comps)} candidate comps, "
            f"{len(comps)} selected (mags {min(c.catalog_mag for c in comps):.2f}–"
            f"{max(c.catalog_mag for c in comps):.2f})."
        )
        if not chart_id or chart_id == "na":
            chart_id = chart.chart_id

    fits_files = sorted(list(captures_dir.glob("*.fits")) + list(captures_dir.glob("*.fit")))
    if not fits_files:
        print(f"No FITS files found in {captures_dir}.")
        return

    from .photometry import read_fits_with_wcs

    try:
        read_fits_with_wcs(fits_files[0])
    except ValueError as exc:
        print(
            f"First FITS ({fits_files[0].name}) is missing a celestial WCS: {exc}\n"
            "NINA must plate-solve before saving. Re-run capture with plate-solve "
            "enabled or solve frames manually before retrying."
        )
        return
    print(f"WCS pre-flight OK on {fits_files[0].name}.")
    if any(c.catalog_band == "V" for c in comps):
        print(
            "Note: V-band comps will be reported as TG band per AAVSO OSC convention "
            "(green channel ≈ V but counts as a separate band)."
        )
    print(f"Processing {len(fits_files)} FITS files...")

    observations = []
    failures = []
    for fits_path in fits_files:
        skipped_comps: list[str] = []

        def _skip_log(comp, reason: str, _skipped=skipped_comps) -> None:
            _skipped.append(f"{comp.label}: {reason}")

        try:
            obs = process_capture(
                fits_path,
                args.target,
                vsx_target.ra_deg,
                vsx_target.dec_deg,
                comps,
                aperture_radius_arcsec=args.aperture_arcsec,
                on_comp_skipped=_skip_log,
            )
            if skipped_comps:
                print(f"  {fits_path.name}: skipped {len(skipped_comps)} comp(s) — {'; '.join(skipped_comps[:3])}")
        except Exception as exc:
            failures.append((fits_path.name, str(exc)))
            continue
        if obs is None:
            failures.append((fits_path.name, "no usable signal"))
            continue
        obs.chart_id = chart_id
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
        chart_id=chart_id,
    )

    mags = [o.magnitude for o in observations]
    median_mag = sorted(mags)[len(mags) // 2]
    print(
        f"\n{len(observations)} observations submitted, median magnitude "
        f"{median_mag:.3f} (range {min(mags):.3f}–{max(mags):.3f})"
    )
    print(f"Wrote {output_path}")
    print("Verify the file, then upload at: https://www.aavso.org/webobs/file")


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

    from .nightly_html import write_session_schedule_html
    from .scheduler import build_session_schedule
    from .session_plan import write_session_plan
    from .session_schedule import write_session_schedule_outputs

    plan_targets = candidates[:top_packets]
    write_session_plan(plan_targets, output_dir, now_local, window_end, config)

    schedule = build_session_schedule(
        candidates,
        window_start=now_local,
        window_end=window_end,
    )
    write_session_schedule_outputs(schedule, output_dir, config)
    write_session_schedule_html(schedule, output_dir, config, metadata=metadata)

    print(f"Wrote {output_dir / 'candidate_queue.csv'}")
    print(f"Wrote {output_dir / 'session_plan.md'} (full menu)")
    print(f"Wrote {output_dir / 'session_plan.csv'}")
    print(
        f"Wrote {output_dir / 'session_schedule.md'} "
        f"({len(schedule.scheduled)} targets scheduled, {len(schedule.overflow)} overflow)"
    )
    print(f"Wrote {output_dir / 'session_schedule.csv'}")
    print(f"Wrote {output_dir / 'session_schedule.html'} (phone-readable)")
    print(f"Wrote {output_dir / 'nina_targets.csv'} (scheduled targets in execution order)")
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
