from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from .aavso import enrich_candidates_with_aavso
from .config import load_config
from .report import clean_previous_outputs, write_outputs
from .scoring import build_candidates
from .simbad import enrich_candidates_with_simbad
from .vsx import fetch_vsx_targets
from .ztf import enrich_with_ztf


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a Jersey City AAVSO anomaly observing queue.")
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="Fetch VSX targets and generate candidate packets.")
    run_parser.add_argument("--config", default="config/jersey_city.yaml", help="YAML config path.")
    run_parser.add_argument("--limit", type=int, default=None, help="Override VSX row limit.")
    run_parser.add_argument("--top", type=int, default=None, help="Override number of packets.")
    run_parser.add_argument("--start-date", default=None, help="Local observing start date, YYYY-MM-DD.")
    run_parser.add_argument("--aavso-top", type=int, default=None, help="Check AAVSO recent coverage for top N candidates.")
    run_parser.add_argument("--simbad-top", type=int, default=None, help="Fetch SIMBAD context for top N candidates.")
    run_parser.add_argument("--ztf-top", type=int, default=0, help="Fetch ZTF light curves for the top N candidates.")

    args = parser.parse_args()
    if args.command in (None, "run"):
        run(args)


def run(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    if args.limit is not None:
        config = _replace_vsx_limit(config, args.limit)
    top_packets = args.top if args.top is not None else config.output.top_packets
    output_dir = config.output.directory
    packet_dir = output_dir / "candidate_packets"
    clean_previous_outputs(Path(output_dir))

    print(f"Fetching up to {config.vsx_query.row_limit} VSX rows from VizieR...")
    targets = fetch_vsx_targets(config.vsx_query)
    print(f"Fetched {len(targets)} candidate catalog rows.")

    start_date = date.fromisoformat(args.start_date) if args.start_date else None
    candidates = build_candidates(targets, config, start_date=start_date)
    print(f"{len(candidates)} targets passed Jersey City filters.")

    aavso_top = config.aavso.enrich_top if args.aavso_top is None else max(0, int(args.aavso_top))
    if config.aavso.enabled and aavso_top:
        checked = min(aavso_top, len(candidates))
        print(f"Checking AAVSO recent coverage for top {checked} candidates...")
        enrich_candidates_with_aavso(candidates, config, limit=aavso_top)

    simbad_top = config.simbad.enrich_top if args.simbad_top is None else max(0, int(args.simbad_top))
    if config.simbad.enabled and simbad_top:
        checked = min(simbad_top, len(candidates))
        print(f"Fetching SIMBAD context for top {checked} candidates...")
        enrich_candidates_with_simbad(candidates, config, limit=simbad_top)

    ztf_top = max(0, int(args.ztf_top or 0))
    if config.ztf.enabled and ztf_top:
        for index, candidate in enumerate(candidates[:ztf_top], start=1):
            print(f"Fetching ZTF light curve {index}/{ztf_top}: {candidate.target.name}")
            candidate.ztf = enrich_with_ztf(candidate, config.ztf, packet_dir)

    write_outputs(candidates, Path(output_dir), top_packets)
    print(f"Wrote {Path(output_dir) / 'candidate_queue.csv'}")
    print(f"Wrote packets in {packet_dir}")


def _replace_vsx_limit(config, limit: int):
    from dataclasses import replace

    return replace(config, vsx_query=replace(config.vsx_query, row_limit=limit))
