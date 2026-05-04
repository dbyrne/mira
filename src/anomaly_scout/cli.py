from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
from pathlib import Path

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

    args = parser.parse_args()
    if args.command == "target":
        target(args)
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
