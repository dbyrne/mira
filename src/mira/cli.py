from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

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
from .vsx import VsxUnavailableError, fetch_vsx_target_by_name, fetch_vsx_targets
from .ztf import enrich_with_ztf

_run_timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _mira_version() -> str:
    try:
        from importlib.metadata import version

        return version("mira")
    except Exception:
        return "unknown"


def _init_field_log() -> None:
    """Rotating WARN+ log to logs/mira.log so a field failure can be
    diagnosed offline (no internet, no assistant). Best-effort: a logging
    setup problem must never stop a command from running."""
    try:
        import logging
        from logging.handlers import RotatingFileHandler

        Path("logs").mkdir(exist_ok=True)
        root = logging.getLogger()
        if any(isinstance(h, RotatingFileHandler) for h in root.handlers):
            return
        handler = RotatingFileHandler(
            "logs/mira.log", maxBytes=2_000_000, backupCount=3,
            encoding="utf-8")
        handler.setLevel(logging.WARNING)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root.addHandler(handler)
        if root.level == logging.NOTSET or root.level > logging.WARNING:
            root.setLevel(logging.WARNING)
    except Exception:
        pass


def main() -> None:
    # The CLI prints non-ASCII (em-dashes, ≈, ±) in human-readable output.
    # A Windows console defaults to cp1252 and raises UnicodeEncodeError mid-
    # command (it killed `submit` right before the photometry loop). Upgrade
    # the real console to UTF-8, replacing anything truly unencodable rather
    # than crashing. No-op for StringIO in tests (no reconfigure attr).
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    _init_field_log()

    parser = argparse.ArgumentParser(description="Mira — backyard variable-star observing assistant.")
    parser.add_argument(
        "--version", action="version", version=f"mira {_mira_version()}",
        help="Print the installed Mira version and exit.")
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
    submit_parser.add_argument(
        "--siril-calibrate",
        action="store_true",
        help="Calibrate frames with Siril (no register/stack) before photometry. "
        "Off by default. A WCS safety gate aborts if Siril flips the image; "
        "verify recovered magnitudes before submitting to AAVSO.",
    )
    submit_parser.add_argument("--siril-darks", default=None, help="Dir of dark frames for --siril-calibrate.")
    submit_parser.add_argument("--siril-flats", default=None, help="Dir of flat frames for --siril-calibrate.")
    submit_parser.add_argument("--siril-biases", default=None, help="Dir of bias frames for --siril-calibrate.")

    stack_parser = subparsers.add_parser(
        "stack",
        help="Pretty-picture branch: Siril convert/register/stack a lights dir "
        "into a stacked image. Separate from photometry — stacking destroys "
        "the per-frame time series.",
    )
    stack_parser.add_argument("--lights", required=True, help="Directory of light frames (FITS/raw/JPG/TIFF).")
    stack_parser.add_argument("--out", required=True, help="Output image path. The linear stack is written as FITS (.fit) regardless of the extension you give — the .fit preserves the WCS header from the reference frame so the stack is photometry-ready. Optional stretched PNG preview lands alongside.")
    stack_parser.add_argument("--darks", default=None, help="Optional dir of dark frames.")
    stack_parser.add_argument("--flats", default=None, help="Optional dir of raw flat frames (Siril builds the master). Mutually exclusive with --auto-flats.")
    stack_parser.add_argument(
        "--auto-flats", dest="auto_flats", action="store_true",
        help="Auto-resolve the prebuilt master flat for these lights from "
        "their mira_capture.json sidecar (filter+gain) under --flats-root. "
        "Aborts if no match (won't silently stack without the right flat).")
    stack_parser.add_argument("--flats-root", default="data/flats", help="Root searched by --auto-flats (default data/flats).")
    stack_parser.add_argument("--biases", default=None, help="Optional dir of bias frames.")
    stack_parser.add_argument(
        "--cull-low-quality", action="store_true",
        help="Before stacking, move cloud-affected / poorly-focused frames "
        "to <lights>/_rejected/ via NINA's image-history (HFR + star count). "
        "Requires NINA still running with image-history populated from this "
        "session. Fail-soft: a no-history-match no-ops with a warning.",
    )
    stack_parser.add_argument(
        "--auto-solve", action="store_true",
        help="Before stacking, run `mira solve` over any frames in --lights "
        "that don't already carry a WCS. Required if you want the FITS stack "
        "output to inherit WCS from the reference frame (NINA's API captures "
        "save no WCS by default). Skipped when all frames are already solved. "
        "Aborts the stack on any solve failure.",
    )
    stack_parser.add_argument(
        "--debayer",
        dest="debayer",
        action="store_true",
        default=None,
        help="Force debayering (OSC CFA). Default: auto-detect from file type.",
    )
    stack_parser.add_argument(
        "--mono", dest="debayer", action="store_false",
        help="Force no debayering (already-color or true mono data).",
    )
    stack_parser.add_argument(
        "--no-stretch", dest="stretch", action="store_false",
        help="Skip the stretched PNG preview; write only the linear FITS.",
    )

    finish_parser = subparsers.add_parser(
        "finish",
        help="Finishing stage: turn a linear stacked master into a presentable "
        "image — GraXpert background/denoise/deconv (optional) → Siril "
        "autostretch+saturation → edge crop. Reproducible; idempotent on the input.",
    )
    finish_parser.add_argument("--input", required=True, help="Linear stacked master (TIFF/FITS), e.g. a `mira stack` output.")
    finish_parser.add_argument("--out", required=True, help="Output image path (.png or .tif); the other format is written alongside.")
    finish_parser.add_argument("--no-bg", dest="do_bg", action="store_false", help="Skip GraXpert background extraction.")
    finish_parser.add_argument("--no-denoise", dest="do_denoise", action="store_false", help="Skip GraXpert AI denoise.")
    finish_parser.add_argument("--no-deconv", dest="do_deconv", action="store_false", help="Skip GraXpert object deconvolution.")
    finish_parser.add_argument("--saturation", type=float, default=0.20, help="Siril saturation boost after stretch (0 disables). Default 0.20.")
    finish_parser.add_argument(
        "--crop", default="auto",
        help="'auto' (trim under-sampled stack borders), 'none', or a per-side "
        "fraction like 0.06 for a fixed symmetric crop. Default auto.",
    )
    finish_parser.add_argument("--gpu", action="store_true", help="Let GraXpert use the GPU (default CPU).")
    finish_parser.add_argument(
        "--graxpert-path", default=None,
        help="Override GraXpert location (executable path or 'python -m graxpert.main'). "
        "Else $MIRA_GRAXPERT, then PATH, then the installed graxpert module.",
    )
    finish_parser.add_argument(
        "--progress-dir", default=None,
        help="Directory to publish phase-progress JSON to (so the webapp can "
        "show this run live). Default: data/finish_progress.",
    )

    tune_parser = subparsers.add_parser(
        "tune",
        help="Dial in exposure/gain: shoot a test frame per exposure x gain "
        "via NINA, read back HFR/saturation, recommend the longest "
        "non-saturating exposure per gain (flags probable trailing).",
    )
    tune_parser.add_argument("--exposures", default="3,5,8,12", help="Comma list of exposure seconds (default 3,5,8,12).")
    tune_parser.add_argument("--gains", default="120,200", help="Comma list of gains; 'default' = camera default (e.g. 120,200).")
    tune_parser.add_argument("--nina-url", default="http://localhost:1888", help="NINA Advanced API base URL.")
    tune_parser.add_argument("--target-name", default="", help="Label stamped into NINA filenames/targetName (optional).")
    tune_parser.add_argument("--ra", type=float, default=None, help="J2000 RA deg — if given with --dec, plate-solve-center there first.")
    tune_parser.add_argument("--dec", type=float, default=None, help="J2000 Dec deg — see --ra.")
    tune_parser.add_argument("--filter", default=None, help="Filter wheel position to select + confirm before the ramp (aborts if unconfirmed).")

    capture_parser = subparsers.add_parser(
        "capture",
        help="Deep-capture loop with DITHERING + re-centering. Dithers "
        "relative to the fixed nominal coords every sub (breaks walking "
        "noise AND prevents drift); all reposition slews are blind "
        "(center=False, no Center loop). Stops at twilight / low altitude.",
    )
    # Argparse defaults are deliberately None so resolve_capture_config can
    # tell "user didn't pass this flag" from "user explicitly passed the
    # builtin default value". A session profile (--session) fills the gaps;
    # CAPTURE_BUILTIN_DEFAULTS is the final fallback. Precedence:
    # CLI > session > builtin.
    capture_parser.add_argument("--config", default=None, help="Path to a mira site-config YAML (e.g. config/s30_pro_jc.yaml). Its `capture_defaults` section provides rig/site constants (lat, lon, nina_root, alt_floor, ...). Lowest-priority tier of the four (CLI > session > config > builtin).")
    capture_parser.add_argument("--session", default=None, help="Path to a session profile YAML (e.g. targets/m51.yaml). Any flag the user does NOT pass on the CLI is taken from this file. The four required fields (--ra / --dec / --exposure / --dest) can also live there.")
    capture_parser.add_argument("--ra", type=float, default=None, help="J2000 RA deg (nominal target; dithers are relative to this).")
    capture_parser.add_argument("--dec", type=float, default=None, help="J2000 Dec deg.")
    capture_parser.add_argument("--exposure", type=float, default=None, help="Sub exposure seconds.")
    capture_parser.add_argument("--gain", type=int, default=None, help="Gain ('None' = camera default).")
    capture_parser.add_argument("--dest", default=None, help="Directory to incrementally copy captured subs into.")
    capture_parser.add_argument("--dither-arcsec", type=float, default=None, help="Max dither offset per axis (0 disables). Default 30\".")
    capture_parser.add_argument("--dither-every", type=int, default=None, help="Dither every N subs (1 = every sub; best for walking noise).")
    capture_parser.add_argument("--recenter-every", type=int, default=None, help="If NOT dithering, blind re-center to nominal every N subs.")
    capture_parser.add_argument("--n-max", type=int, default=None, help="Hard cap on subs (default 1000; guards usually stop first).")
    capture_parser.add_argument("--alt-floor", type=float, default=None, help="Stop when target drops below this altitude (deg).")
    capture_parser.add_argument("--sun-max", type=float, default=None, help="Stop when Sun rises above this (deg); -15 = astro twilight.")
    capture_parser.add_argument("--lat", type=float, default=None, help="Site latitude (default Jersey City).")
    capture_parser.add_argument("--lon", type=float, default=None, help="Site longitude (default Jersey City).")
    capture_parser.add_argument("--settle", type=float, default=None, help="Seconds to settle after a reposition slew before exposing.")
    capture_parser.add_argument("--nina-url", default=None, help="NINA Advanced API base URL.")
    capture_parser.add_argument(
        "--nina-root", default=None,
        help="Where NINA saves FITS (scanned for new subs to copy out).",
    )
    capture_parser.add_argument("--target-name", default=None, help="Label stamped into NINA filenames.")
    capture_parser.add_argument("--filter", default=None, help="Filter wheel position to select + confirm before the loop. Aborts before any capture if the wheel can't confirm it (won't shoot a multi-hour stack through the wrong/no filter).")
    capture_parser.add_argument("--platesolve-center", action=argparse.BooleanOptionalAction, default=None, help="Before the loop, slew with NINA's plate-solve Center to pin the mount on the requested RA/Dec. Use --no-platesolve-center to override a session profile that enables it. Fails soft: a failed center logs a warning, loop proceeds with the blind anchored-dither.")
    capture_parser.add_argument("--verify-pointing-deg", type=float, default=None, help="After platesolve-center, take one test sub and ASTAP-solve it to verify the mount is actually on target. Abort if solved center is more than this many degrees from nominal. 0 disables. Catches mount-sync drift where NINA reports a wrong position (2026-05-19 M51 disaster).")
    capture_parser.add_argument("--autofocus-every-min", type=int, default=None, help="Run NINA autofocus pre-loop and then every N minutes (wall-clock). 0 disables. Wall-clock — NOT sub-count — because alt-floor/sun guards make session duration dynamic. Fails soft.")
    capture_parser.add_argument("--autofocus-timeout-s", type=float, default=None, help="Per-AF-run timeout. Defaults to 10 min; AF on a fast f/5 typically finishes in 60-120s.")

    flats_parser = subparsers.add_parser(
        "flats",
        help="Per-filter flat calibration. Tape paper over the aperture "
        "once; this drives the filter wheel, auto-brackets exposure "
        "(wide then fine, target ~30k ADU), captures a validated series "
        "per filter, and builds a Siril master flat each. Auto-skips "
        "opaque positions (e.g. a Dark filter). Freshness + 0-stars "
        "guards reject stale/sky frames.",
    )
    # Defaults are None so resolve_flats_config can distinguish user-set from
    # not-set. Final fallback values live in FLATS_BUILTIN_DEFAULTS.
    flats_parser.add_argument("--config", default=None, help="Mira site-config YAML (e.g. config/s30_pro_jc.yaml). Provides nina_url/nina_root/gain from the `capture_defaults` section so flats and capture share the same site truth — no more `--nina-root` per invocation.")
    flats_parser.add_argument(
        "--filters", default=None,
        help="Comma list of filter names (default: every wheel position, "
        "auto-discovered; opaque ones are detected and skipped).")
    flats_parser.add_argument("--gain", type=int, default=None, help="Gain (match your lights' gain; default 120).")
    flats_parser.add_argument("--target-adu", type=float, default=None, help="Target median ADU for the flats (default 30000).")
    flats_parser.add_argument("--frames", type=int, default=None, help="Frames per filter (default 25).")
    flats_parser.add_argument("--min-exp", type=float, default=None, help="Shortest bracket exposure, sec (camera floor; default 0.005).")
    flats_parser.add_argument("--max-exp", type=float, default=None, help="Longest bracket exposure, sec (default 30).")
    flats_parser.add_argument("--out", default=None, help="Root dir for masters (default data/flats; gitignored).")
    flats_parser.add_argument("--nina-url", default=None, help="NINA Advanced API base URL.")
    flats_parser.add_argument(
        "--nina-root", default=None,
        help="Where NINA saves FITS (scanned for new frames to copy out).")

    cull_parser = subparsers.add_parser(
        "cull",
        help="Flag and move low-quality (cloud-affected / trailing / "
        "out-of-focus) frames out of a lights dir. Default mode reads "
        "HFR + Stars from NINA's image-history (NINA must still be up). "
        "`--from-fits` switches to offline mode: pure-Python per-FITS "
        "metrics (stars, HFR, roundness, target-region sky median) with "
        "no NINA dependency — works on historical / external data. In "
        "FITS mode, frames lacking a WCS in an otherwise-solved dir are "
        "flagged as solve-failed. Rejected frames move to "
        "<lights>/_rejected/ — recoverable, not deleted.",
    )
    cull_parser.add_argument("--lights", required=True, help="Directory of FITS frames to cull.")
    cull_parser.add_argument("--nina-url", default="http://localhost:1888", help="NINA Advanced API base URL (default mode only).")
    cull_parser.add_argument("--from-fits", action="store_true", help="Compute quality metrics from FITS pixels directly (no NINA). Adds target-region sky-median + roundness; detects failed-solve frames.")
    cull_parser.add_argument("--target-ra", type=float, default=None, help="Target J2000 RA in degrees (FITS mode). Auto-loaded from mira_capture.json sidecar if absent.")
    cull_parser.add_argument("--target-dec", type=float, default=None, help="Target J2000 Dec in degrees (FITS mode). Auto-loaded from sidecar if absent.")
    cull_parser.add_argument("--central-frac", type=float, default=0.3, help="When no WCS+target, take sky in this central fraction of the frame (default 0.3).")
    cull_parser.add_argument("--min-stars-frac", type=float, default=0.5, help="Keep frames with stars >= this fraction of session median (default 0.5).")
    cull_parser.add_argument("--max-hfr-frac", type=float, default=1.5, help="Keep frames with HFR <= this fraction of session median (default 1.5).")
    cull_parser.add_argument("--max-sky-frac", type=float, default=2.0, help="Keep frames with target-region sky <= this fraction of session median (FITS mode; default 2.0).")
    cull_parser.add_argument("--max-round-frac", type=float, default=2.0, help="Keep frames with |roundness| <= this fraction of session median (FITS mode; default 2.0).")
    cull_parser.add_argument("--dry-run", action="store_true", help="Report what would be moved without touching the filesystem.")

    solve_parser = subparsers.add_parser(
        "solve",
        help="Bulk-inject WCS into a captures directory via offline ASTAP. "
        "NINA's API-driven captures don't save WCS, so photometry "
        "and WCS-aware stacking need this preflight. Reads RA/Dec hints "
        "from mira_capture.json for fast guided solves; falls back to "
        "blind. Idempotent — already-solved frames are skipped.",
    )
    solve_parser.add_argument("--lights", required=True, help="Directory of FITS frames to solve in place.")
    solve_parser.add_argument("--config", default=None, help="Mira site-config YAML; reads fov from capture_defaults if set.")
    solve_parser.add_argument("--force", action="store_true", help="Re-solve frames even if a WCS is already in the header.")
    solve_parser.add_argument("--workers", type=int, default=4, help="Parallel astap_cli invocations (default 4).")
    solve_parser.add_argument("--fov", type=float, default=None, help="Field of view diameter, deg. Defaults to site config; falls back to 4.6 (S30 Pro).")
    solve_parser.add_argument("--radius", type=float, default=5.0, help="Search radius around the RA/Dec hint, deg. Blind solves use 180.")
    solve_parser.add_argument("--ra", type=float, default=None, help="Override RA hint deg (default: read from mira_capture.json).")
    solve_parser.add_argument("--dec", type=float, default=None, help="Override Dec hint deg (default: read from mira_capture.json).")
    solve_parser.add_argument("--astap-cli", default=None, help="Path to astap_cli. Default: MIRA_ASTAP_CLI env / PATH / standard install.")
    solve_parser.add_argument("--timeout-s", type=float, default=120.0, help="Per-frame astap_cli timeout, seconds.")

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Preflight the whole rig: deps, numpy<2.3, Siril, ASTAP, "
        "GraXpert, NINA API (1888/1889), filter wheel, darkness tonight, "
        "disk space, config. Run before a session; exits non-zero on any "
        "hard failure.",
    )
    doctor_parser.add_argument("--config", default="config/s30_pro_jc.yaml", help="YAML config to validate + darkness-check.")
    doctor_parser.add_argument("--nina-url", default="http://localhost:1888", help="NINA Advanced API base URL (also probes :1889).")
    doctor_parser.add_argument("--captures-root", default="captures", help="Capture drive to check free space on (default ./captures).")

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

    rehearsal_parser = subparsers.add_parser(
        "rehearse",
        help="Generate synthetic FITS for a real target and run them through "
        "the full submit pipeline. Smoke test before first light.",
    )
    rehearsal_parser.add_argument("--target", required=True, help="VSX target name (e.g. 'RR Lyr').")
    rehearsal_parser.add_argument(
        "--output-dir", default="captures/_rehearsal",
        help="Where to write synthetic FITS + the AAVSO file (default captures/_rehearsal).",
    )
    rehearsal_parser.add_argument("--frames", type=int, default=20, help="Number of synthetic frames (default 20).")
    rehearsal_parser.add_argument(
        "--observer-code", default="TEST",
        help="Observer code stamped into the synthetic AAVSO file. Default 'TEST' (do NOT submit).",
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
    elif args.command == "stack":
        stack(args)
    elif args.command == "finish":
        finish(args)
    elif args.command == "tune":
        tune(args)
    elif args.command == "capture":
        capture(args)
    elif args.command == "flats":
        flats(args)
    elif args.command == "solve":
        solve(args)
    elif args.command == "cull":
        cull(args)
    elif args.command == "doctor":
        doctor(args)
    elif args.command == "migrate-runs":
        migrate_runs(args)
    elif args.command == "cleanup":
        cleanup(args)
    elif args.command == "rehearse":
        rehearse(args)
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


def rehearse(args: argparse.Namespace) -> None:
    """Smoke-test the full photometry pipeline against synthetic FITS for
    a real target. Catches integration bugs before the gear arrives."""
    from .rehearsal import run_rehearsal

    output_dir = Path(args.output_dir)
    try:
        report = run_rehearsal(
            target_name=args.target,
            output_dir=output_dir,
            n_frames=args.frames,
            observer_code=args.observer_code,
        )
    except Exception as exc:
        print(f"REHEARSAL FAILED: {exc}")
        return

    print()
    print("=== Rehearsal report ===")
    print(f"Target:           {report.target_name}")
    print(f"  RA / Dec:       {report.target_ra_deg:.5f} / {report.target_dec_deg:+.5f}")
    print(f"  Planted mag:    {report.planted_target_mag:.2f}")
    print(f"  Chart:          {report.chart_id} ({report.n_comps_used} comps in {report.comp_band})")
    print(f"Frames:           {report.n_frames}")
    if report.recovered_median_mag is not None:
        residual = report.magnitude_residual
        sign = "+" if residual is not None and residual > 0 else ""
        print(
            f"Recovered mag:    median {report.recovered_median_mag:.2f} "
            f"(range {report.recovered_min_mag:.2f}–{report.recovered_max_mag:.2f}, "
            f"residual {sign}{residual:.2f} mag)"
        )
    else:
        print("Recovered mag:    (no observations)")
    if report.aavso_path:
        print(f"AAVSO file:       {report.aavso_path}")
    if report.issues:
        print()
        print("Issues:")
        for issue in report.issues:
            print(f"  - {issue}")
    else:
        print("No issues. Pipeline looks healthy.")


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
    try:
        targets = fetch_vsx_targets(config.vsx_query)
    except VsxUnavailableError as exc:
        print(f"\nERROR: {exc}\n"
              "(Previous outputs in this dir were already cleared. Restore "
              "connectivity and re-run; nothing else to do here.)")
        raise SystemExit(1)
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

    print("Mira webapp")
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
    """Run photometry on captured FITS files and produce an AAVSO upload file.
    Delegates to submit_pipeline so the math matches the webapp."""
    from .photometry import aavso_filename, write_aavso_extended_file
    from .submit_pipeline import (
        FrameRecord,
        preflight_fits_dir,
        resolve_comps,
        run_photometry_loop,
    )

    captures_dir = Path(args.captures)
    if not captures_dir.exists():
        print(f"Captures directory '{captures_dir}' does not exist.")
        return

    if getattr(args, "siril_calibrate", False):
        from .siril import SirilError, SirilNotFound
        from .siril_pipeline import run_siril_calibrate_for_photometry

        print("Siril calibrate pre-step (no register/stack)...")
        try:
            captures_dir = run_siril_calibrate_for_photometry(
                lights_dir=captures_dir,
                darks_dir=Path(args.siril_darks) if args.siril_darks else None,
                flats_dir=Path(args.siril_flats) if args.siril_flats else None,
                biases_dir=Path(args.siril_biases) if args.siril_biases else None,
            )
        except SirilNotFound as exc:
            print(f"Siril not available: {exc}")
            return
        except SirilError as exc:
            print(f"Siril calibrate aborted: {exc}")
            return
        print(f"WCS safety gate passed. Photometry will run on: {captures_dir}")
        print(
            "WARNING: Siril calibration is opt-in and only spot-checked on one "
            "frame. Eyeball the recovered magnitudes against the raw-frame run "
            "before submitting anything to AAVSO."
        )

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

    comp_path = Path(args.comp_stars) if args.comp_stars else None
    if comp_path is not None and not comp_path.exists():
        print(f"Comparison-star file '{comp_path}' does not exist.")
        return
    try:
        resolution = resolve_comps(
            target_name=args.target,
            target_bright_mag=vsx_target.bright_mag,
            comp_path=comp_path,
            chart_id_override=args.chart_id,
        )
    except Exception as exc:
        print(f"Comp-star resolution failed: {exc}")
        if comp_path is None:
            print("Re-run with --comp-stars <path.json> to use a manual sequence.")
        return

    if resolution.source == "json":
        print(f"Loaded {len(resolution.comps)} comparison stars from {comp_path}.")
    elif resolution.source == "vsp":
        mags = [c.catalog_mag for c in resolution.comps]
        print(
            f"VSP chart {resolution.chart_id}: {resolution.chart_total} candidate comps, "
            f"{len(resolution.comps)} selected (mags {min(mags):.2f}–{max(mags):.2f})."
        )
    elif resolution.source == "vsp-fallback":
        print(
            f"VSP chart {resolution.chart_id} returned "
            f"{resolution.chart_total} comps, none within mag tolerance; "
            f"using brightest {len(resolution.comps)}."
        )

    try:
        fits_files = preflight_fits_dir(captures_dir)
    except ValueError as exc:
        msg = str(exc)
        if "celestial WCS" in msg:
            print(
                f"{msg}\nNINA must plate-solve before saving. Re-run capture "
                "with plate-solve enabled or solve frames manually before retrying."
            )
        else:
            print(msg)
        return
    print(f"WCS pre-flight OK on {fits_files[0].name}.")
    if any(c.catalog_band == "V" for c in resolution.comps):
        print(
            "Note: V-band comps will be reported as TG band per AAVSO OSC convention "
            "(green channel ≈ V but counts as a separate band)."
        )
    print(f"Processing {len(fits_files)} FITS files...")

    def _print_frame(frame: FrameRecord) -> None:
        if frame.skipped_comps:
            preview = "; ".join(frame.skipped_comps[:3])
            print(f"  {frame.filename}: skipped {len(frame.skipped_comps)} comp(s) — {preview}")
        if frame.flag in ("failed", "no-signal"):
            return
        print(
            f"  {frame.filename}: mag {frame.magnitude:.3f} +/- "
            f"{frame.magnitude_error:.3f} via comp {frame.comp_label}"
        )

    result = run_photometry_loop(
        target_name=args.target,
        target_ra_deg=vsx_target.ra_deg,
        target_dec_deg=vsx_target.dec_deg,
        fits_files=fits_files,
        comps=resolution.comps,
        chart_id=resolution.chart_id,
        aperture_arcsec=args.aperture_arcsec,
        on_frame=_print_frame,
    )

    if result.failures:
        print(f"\n{len(result.failures)} files failed:")
        for name, reason in result.failures[:10]:
            print(f"  {name}: {reason}")

    if not result.observations:
        print("\nNo successful observations. Verify FITS files have a celestial WCS (NINA must plate-solve).")
        return

    output_path = captures_dir / aavso_filename(args.target)
    write_aavso_extended_file(
        result.observations,
        output_path,
        observer_code=args.observer_code,
        chart_id=resolution.chart_id,
    )

    mags = [o.magnitude for o in result.observations]
    print(
        f"\n{len(result.observations)} observations submitted, median magnitude "
        f"{result.median_mag:.3f} (range {min(mags):.3f}–{max(mags):.3f})"
    )
    print(f"Wrote {output_path}")
    print("Verify the file, then upload at: https://www.aavso.org/webobs/file")


def stack(args: argparse.Namespace) -> None:
    """Pretty-picture branch. Siril-driven, fully decoupled from the
    photometry/queue path — stacking collapses the time series, so this
    never feeds back into `submit`."""
    from .siril import SirilError, SirilNotFound
    from .siril_pipeline import run_siril_stack

    lights_dir = Path(args.lights)
    if not lights_dir.is_dir():
        print(f"Lights directory '{lights_dir}' does not exist.")
        return

    if getattr(args, "cull_low_quality", False):
        # Cull first, solve second: no point plate-solving frames we're
        # about to discard. Fail-soft on any error — a cull that finds
        # nothing to score (e.g., NINA restarted, history evicted) just
        # logs a warning and the stack proceeds with all frames.
        from .cull import run_cull
        from .webapp.nina_client import NinaClient
        print("--cull-low-quality: querying NINA image-history...")
        try:
            cull_client = NinaClient(base_url="http://localhost:1888")
            cres = run_cull(
                lights_dir,
                history_fetcher=lambda: cull_client.image_history(all_images=True),
                on_step=lambda m: print(m),
            )
            print(
                f"  cull: {len(cres.kept)} kept, {len(cres.rejected)} "
                f"rejected to _rejected/, {len(cres.unscored)} unscored."
            )
        except Exception as exc:  # noqa: BLE001 — fail-soft
            print(f"--cull-low-quality: {exc} (continuing with all frames)")

    if getattr(args, "auto_solve", False):
        # Only solve what needs solving — the cheap header check makes this
        # idempotent on re-runs after a previous solve. A solve failure
        # aborts the stack: better to bail loudly than silently produce a
        # WCS-less FITS that the photometry path will then reject.
        from .solve import AstapNotFound, find_astap_cli, has_wcs, run_solve_dir

        frames = sorted(p for p in lights_dir.glob("*.fit*") if p.is_file())
        unsolved = [f for f in frames if not has_wcs(f)]
        if not unsolved:
            print(f"--auto-solve: all {len(frames)} frames already have WCS, "
                  "skipping ASTAP")
        else:
            print(f"--auto-solve: {len(unsolved)}/{len(frames)} frames "
                  "missing WCS; running ASTAP first...")
            try:
                cli = find_astap_cli()
            except AstapNotFound as exc:
                print(f"--auto-solve: {exc}")
                return
            res = run_solve_dir(
                lights_dir, astap_cli=cli,
                on_step=lambda m: print(m),
            )
            if res.failed:
                print(
                    f"--auto-solve: {len(res.failed)} frame(s) failed to "
                    "solve; aborting stack to prevent a WCS-less output. "
                    "Run `mira solve` manually to investigate."
                )
                return

    flat_master = None
    if args.auto_flats:
        if args.flats:
            print("--auto-flats and --flats are mutually exclusive; pick one.")
            return
        from .flats import resolve_master_for_lights

        master, why = resolve_master_for_lights(lights_dir, Path(args.flats_root))
        if master is None:
            print(f"--auto-flats: {why}\nAborting (refusing to stack without "
                  "the matched flat — pass --flats explicitly to override).")
            return
        flat_master = master
        print(f"--auto-flats: {why} -> {master}")

    print(f"Stacking '{lights_dir}' with Siril...")
    try:
        result = run_siril_stack(
            lights_dir=lights_dir,
            out_path=Path(args.out),
            darks_dir=Path(args.darks) if args.darks else None,
            flats_dir=Path(args.flats) if args.flats else None,
            flat_master=flat_master,
            biases_dir=Path(args.biases) if args.biases else None,
            debayer=args.debayer,
            stretch=args.stretch,
        )
    except SirilNotFound as exc:
        print(f"Siril not available: {exc}")
        return
    except SirilError as exc:
        print(f"Stacking failed: {exc}")
        return

    print(f"\nStacked {result.n_input_frames} frames.")
    print(f"Wrote {result.output_path} (linear)")
    if result.preview_path is not None:
        print(f"Wrote {result.preview_path} (stretched preview)")


def finish(args: argparse.Namespace) -> None:
    """Finishing stage. Decoupled from `stack` on purpose: re-run it with
    different params against the same linear master without re-stacking
    (the iterative workflow). GraXpert is optional — the Siril-only path
    (--no-bg --no-denoise --no-deconv) needs no extra install."""
    from .finish_progress import (
        FinishProgress,
        default_progress_dir,
        plan_phases,
    )
    from .finishing import GraXpertError, GraXpertNotFound, run_finish
    from .siril import SirilError, SirilNotFound

    input_path = Path(args.input)
    if not input_path.is_file():
        print(f"Input '{input_path}' does not exist.")
        return

    progress_dir = Path(args.progress_dir) if args.progress_dir else default_progress_dir()
    fp = FinishProgress.create(
        label=f"finish: {input_path.name} -> {Path(args.out).name}",
        input_path=str(input_path),
        phase_ids=plan_phases(
            do_bg=args.do_bg, do_denoise=args.do_denoise, do_deconv=args.do_deconv
        ),
        progress_dir=progress_dir,
    )
    _advance = fp.make_on_step()

    def _on_step(message: str) -> None:
        print(f"  {message}")
        _advance(message)  # publishes phase progress for the webapp

    print(f"Finishing '{input_path}'... (progress: {progress_dir / (fp.run_id + '.json')})")
    try:
        result = run_finish(
            input_path=input_path,
            out_path=Path(args.out),
            do_bg=args.do_bg,
            do_denoise=args.do_denoise,
            do_deconv=args.do_deconv,
            saturation=args.saturation,
            crop=args.crop,
            gpu=args.gpu,
            graxpert_path=args.graxpert_path,
            on_step=_on_step,
        )
    except GraXpertNotFound as exc:
        fp.fail(str(exc))
        print(f"GraXpert not available: {exc}")
        return
    except (GraXpertError, SirilError, SirilNotFound) as exc:
        fp.fail(str(exc))
        print(f"Finishing failed: {exc}")
        return
    except FileNotFoundError as exc:
        fp.fail(str(exc))
        print(str(exc))
        return

    fp.complete(str(result.output_path))
    print(f"\nSteps: {' -> '.join(result.steps)}")
    print(f"Wrote {result.output_path}")
    if result.preview_path and result.preview_path != result.output_path:
        print(f"Wrote {result.preview_path}")


def tune(args: argparse.Namespace) -> None:
    """Empirical exposure/gain dial-in via NINA test frames. Optional
    plate-solve-center first (only if --ra/--dec given — `tune` deliberately
    does not resolve names; DSOs aren't in VSX)."""
    from .tuning import format_report, recommend, run_tune
    from .webapp.nina_client import NinaClient

    try:
        exposures = [float(x) for x in args.exposures.split(",") if x.strip()]
        gains = [
            None if x.strip().lower() == "default" else int(x)
            for x in args.gains.split(",") if x.strip()
        ]
    except ValueError as exc:
        print(f"Bad --exposures/--gains: {exc}")
        return
    if not exposures or not gains:
        print("Need at least one exposure and one gain.")
        return

    client = NinaClient(base_url=args.nina_url)

    if args.ra is not None and args.dec is not None:
        print(f"Plate-solve-centering on RA {args.ra}, Dec {args.dec} ...")
        res = client.preposition(args.ra, args.dec, center=True, set_sidereal=True)
        print(f"  {res.message}")
        if not res.ok:
            print("  Pointing not confirmed; continuing anyway (frames may be off-target).")

    print(
        f"Tuning: gains={args.gains} exposures={args.exposures}s "
        f"({len(gains) * len(exposures)} test frames). Camera will expose."
    )
    results = run_tune(
        client,
        exposures=exposures,
        gains=gains,
        target_name=args.target_name,
        filter_name=args.filter,
        on_step=lambda m: print(m),
    )
    print()
    print(format_report(results, recommend(results)))


CAPTURE_BUILTIN_DEFAULTS: dict[str, Any] = {
    "gain": None,
    "dither_arcsec": 30.0,
    "dither_every": 1,
    "recenter_every": 0,
    "n_max": 1000,
    "alt_floor": 30.0,
    "sun_max": -15.0,
    "lat": 40.7178,
    "lon": -74.0431,
    "settle": 2.0,
    "nina_url": "http://localhost:1888",
    "nina_root": r"C:\Users\david\OneDrive\Documents\N.I.N.A",
    "target_name": "",
    "filter": None,
    "platesolve_center": False,
    "verify_pointing_deg": 1.0,
    "autofocus_every_min": 0,
    "autofocus_timeout_s": 600.0,
}
CAPTURE_REQUIRED: tuple[str, ...] = ("ra", "dec", "exposure", "dest")


def resolve_capture_config(
    args: argparse.Namespace,
    session: dict[str, Any] | None = None,
    site: dict[str, Any] | None = None,
    builtin: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Four-tier merge for `mira capture` args. Precedence (highest first):
    CLI > session profile > site config > builtin default. Missing values
    stay missing (caller validates required fields). `session` / `site` are
    parsed YAML mappings; `builtin` defaults to CAPTURE_BUILTIN_DEFAULTS.

    Keys are the argparse dest names (underscored, e.g. `dither_arcsec`).
    """
    session = session or {}
    site = site or {}
    builtin = CAPTURE_BUILTIN_DEFAULTS if builtin is None else builtin
    out: dict[str, Any] = {}
    keys = set(CAPTURE_REQUIRED) | set(builtin) | set(session) | set(site)
    for key in keys:
        cli_val = getattr(args, key, None)
        if cli_val is not None:
            out[key] = cli_val
        elif key in session:
            out[key] = session[key]
        elif key in site:
            out[key] = site[key]
        else:
            out[key] = builtin.get(key)
    return out


FLATS_BUILTIN_DEFAULTS: dict[str, Any] = {
    "gain": 120,
    "target_adu": 30000.0,
    "frames": 25,
    "min_exp": 0.005,
    "max_exp": 30.0,
    "out": "data/flats",
    "nina_url": "http://localhost:1888",
    "nina_root": r"C:\Users\david\OneDrive\Documents\N.I.N.A",
    "filters": None,
}


def resolve_flats_config(
    args: argparse.Namespace,
    site: dict[str, Any] | None = None,
    builtin: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Three-tier merge for `mira flats` args: CLI > site config > builtin.
    Reads from the same `capture_defaults` section as `mira capture` —
    nina_url/nina_root/gain are universal NINA-driven defaults, not
    capture-specific."""
    site = site or {}
    builtin = FLATS_BUILTIN_DEFAULTS if builtin is None else builtin
    out: dict[str, Any] = {}
    for key in set(builtin) | set(site):
        cli_val = getattr(args, key, None)
        if cli_val is not None:
            out[key] = cli_val
        elif key in site:
            out[key] = site[key]
        else:
            out[key] = builtin.get(key)
    return out


def _load_site_capture_defaults(path: str | None) -> dict[str, Any]:
    """Read the `capture_defaults` section out of a mira config YAML
    (the same file `mira run --config` uses, e.g. config/s30_pro_jc.yaml).
    Site-level constants (lat/lon, nina_url, nina_root, alt_floor, ...)
    live here so they don't have to be repeated in every session profile
    and every CLI invocation. Missing section -> empty mapping."""
    if not path:
        return {}
    import yaml  # local import keeps mira-cli import cheap when unused
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return {}
    section = raw.get("capture_defaults") or {}
    if not isinstance(section, dict):
        raise SystemExit(
            f"--config {path}: `capture_defaults` must be a mapping, got "
            f"{type(section).__name__}"
        )
    return {str(k).replace("-", "_"): v for k, v in section.items()}


def _load_session_profile(path: str | None) -> dict[str, Any]:
    """Parse a --session YAML to a flat mapping of argparse-dest -> value.
    Accepts hyphenated keys (dither-arcsec) and normalizes to underscores
    so the YAML can mirror either form."""
    if not path:
        return {}
    import yaml  # local import keeps mira-cli import cheap when unused
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise SystemExit(
            f"--session {path}: expected a YAML mapping at top level, got "
            f"{type(raw).__name__}"
        )
    return {str(k).replace("-", "_"): v for k, v in raw.items()}


def capture(args: argparse.Namespace) -> None:
    """Deep-capture loop with dithering + re-centering. Dithers relative to
    the fixed nominal coords (breaks walking noise AND prevents drift);
    blind reposition slews (no Center loop). Stops at twilight / low alt."""
    from .capture import altitude_sun_guard, run_capture
    from .webapp.nina_client import NinaClient

    cfg = resolve_capture_config(
        args,
        session=_load_session_profile(args.session),
        site=_load_site_capture_defaults(args.config),
    )
    missing = [k for k in CAPTURE_REQUIRED if cfg.get(k) is None]
    if missing:
        flags = ", ".join(f"--{m.replace('_', '-')}" for m in missing)
        raise SystemExit(
            f"missing required capture config: {flags}. Provide on the CLI or "
            f"in a --session profile."
        )

    client = NinaClient(base_url=cfg["nina_url"])
    guard = altitude_sun_guard(
        cfg["ra"], cfg["dec"], cfg["lat"], cfg["lon"],
        alt_floor_deg=cfg["alt_floor"], sun_max_deg=cfg["sun_max"],
    )
    print(
        f"Capture loop: RA {cfg['ra']}, Dec {cfg['dec']}, {cfg['exposure']}s "
        f"gain={cfg['gain']} dither={cfg['dither_arcsec']}\" every "
        f"{cfg['dither_every']} filter={cfg['filter'] or '(current)'} "
        f"-> {cfg['dest']}. Stops at <{cfg['alt_floor']} deg alt or sun "
        f">{cfg['sun_max']}."
    )
    if args.session:
        print(f"(session profile: {args.session})")
    res = run_capture(
        client,
        ra_deg=cfg["ra"], dec_deg=cfg["dec"],
        exposure_s=cfg["exposure"], gain=cfg["gain"],
        dest_dir=Path(cfg["dest"]), nina_root=Path(cfg["nina_root"]),
        n_max=cfg["n_max"],
        dither_arcsec=cfg["dither_arcsec"], dither_every=cfg["dither_every"],
        recenter_every=cfg["recenter_every"], settle_s=cfg["settle"],
        target_name=cfg["target_name"],
        filter_name=cfg["filter"],
        platesolve_center=cfg["platesolve_center"],
        verify_pointing_deg=cfg["verify_pointing_deg"],
        autofocus_every_min=cfg["autofocus_every_min"],
        autofocus_timeout_s=cfg["autofocus_timeout_s"],
        # Fields the loop itself doesn't see (they're baked into the
        # altitude_sun_guard closure or the NinaClient base_url) — pipe them
        # into the sidecar's audit block so the run is fully reproducible.
        sidecar_audit={
            "alt_floor_deg": cfg["alt_floor"],
            "sun_max_deg": cfg["sun_max"],
            "lat_deg": cfg["lat"],
            "lon_deg": cfg["lon"],
            "nina_url": cfg["nina_url"],
            "session_profile": args.session,
            "site_config": args.config,
            "dest_dir": str(Path(cfg["dest"]).resolve()),
        },
        should_continue=guard,
        on_step=lambda m: print(m),
    )
    print(
        f"\nDONE: {res.captured} captured, {res.copied} copied to {res.dest_dir}, "
        f"{res.dithers} dithers, {res.recenters} re-centers, "
        f"{res.autofocus_runs} AF runs"
        f"{', plate-solve-centered' if res.platesolve_centered else ''}"
        f"{', filter=' + res.filter_name if res.filter_name else ''}. "
        f"Stopped: {res.stopped_reason}"
    )


def flats(args: argparse.Namespace) -> None:
    """Per-filter flat calibration: drive the wheel, auto-bracket, capture
    a validated series, build a Siril master per filter. Paper stays taped
    over the aperture for the whole run."""
    from .flats import run_flats
    from .webapp.nina_client import NinaClient

    cfg = resolve_flats_config(
        args, site=_load_site_capture_defaults(args.config))
    client = NinaClient(base_url=cfg["nina_url"])
    filters = (
        [s.strip() for s in cfg["filters"].split(",") if s.strip()]
        if cfg["filters"] else None
    )
    discovered = [f.get("Name") for f in client.available_filters()]
    if not discovered:
        print("No filter wheel reported by NINA at "
              f"{cfg['nina_url']}. Is it connected? Aborting.")
        return
    print(
        f"Filter wheel: {discovered}. Flats for "
        f"{filters or 'ALL (opaque auto-skipped)'} @ gain {cfg['gain']}, "
        f"target {cfg['target_adu']:.0f} ADU, {cfg['frames']} frames each.\n"
        "Paper must stay taped over the aperture for the whole run."
    )
    if args.config:
        print(f"(site config: {args.config})")
    res = run_flats(
        client,
        filters=filters, gain=cfg["gain"], target_adu=cfg["target_adu"],
        frames=cfg["frames"], out_root=Path(cfg["out"]),
        nina_root=Path(cfg["nina_root"]),
        min_exp=cfg["min_exp"], max_exp=cfg["max_exp"],
        on_step=lambda m: print(m),
    )
    print("\n=== flats summary ===")
    for r in res.results:
        line = (f"{r.filter_name:>8}: {r.status:<14} "
                f"exp={r.exposure_s:.4g}s med={r.median_adu:.0f} "
                f"good={r.n_good} rej={r.n_rejected}")
        if r.master_path:
            line += f" -> {r.master_path}"
        if r.note:
            line += f"  ({r.note})"
        print(line)


def cull(args: argparse.Namespace) -> None:
    """Cull cloud-affected / low-quality frames in a captures dir.
    Default reads NINA's in-memory image-history for HFR + star counts;
    `--from-fits` reads from FITS pixels directly (works offline)."""
    from .cull import run_cull

    lights = Path(args.lights)
    if not lights.is_dir():
        raise SystemExit(f"--lights: not a directory: {lights}")

    if args.from_fits:
        # Auto-load target coords from the capture sidecar when the user
        # didn't pass --target-ra/--target-dec. Sidecar is written by
        # `mira capture --filter` (see flats.py:write_capture_sidecar).
        tra, tdec = args.target_ra, args.target_dec
        if tra is None or tdec is None:
            from .flats import CAPTURE_SIDECAR
            sc = lights / CAPTURE_SIDECAR
            if sc.exists():
                import json
                try:
                    meta = json.loads(sc.read_text(encoding="utf-8"))
                    if tra is None:
                        tra = meta.get("ra_deg")
                    if tdec is None:
                        tdec = meta.get("dec_deg")
                    if tra is not None and tdec is not None:
                        print(f"target from sidecar: RA={tra} Dec={tdec}")
                except (OSError, ValueError) as exc:
                    print(f"(could not read {CAPTURE_SIDECAR}: {exc})")
        print(f"Culling {lights} (FITS mode)")
        if args.dry_run:
            print("(dry-run — no frames will be moved)")
        res = run_cull(
            lights,
            from_fits=True,
            target_ra=tra, target_dec=tdec,
            central_frac=args.central_frac,
            min_stars_frac=args.min_stars_frac,
            max_hfr_frac=args.max_hfr_frac,
            max_sky_frac=args.max_sky_frac,
            max_round_frac=args.max_round_frac,
            dry_run=args.dry_run,
            on_step=lambda m: print(m),
        )
    else:
        from .webapp.nina_client import NinaClient

        client = NinaClient(base_url=args.nina_url)
        print(f"Culling {lights}")
        if args.dry_run:
            print("(dry-run — no frames will be moved)")
        res = run_cull(
            lights,
            history_fetcher=lambda: client.image_history(all_images=True),
            min_stars_frac=args.min_stars_frac,
            max_hfr_frac=args.max_hfr_frac,
            dry_run=args.dry_run,
            on_step=lambda m: print(m),
        )
    print()
    # Bucket the rejection report: solve-failed (no WCS in a mostly-solved
    # dir) and metric-only (solved, but a pixel-metric threshold fired)
    # are different signals — surfacing them mixed-and-truncated buried
    # the more informative metric bucket on the M51 run.
    verb = "would reject" if args.dry_run else "rejected"
    sf_paths = {s.path for s in res.solve_failed}
    metric_only = [s for s in res.rejected if s.path not in sf_paths]
    SAMPLE = 15

    def _line(s) -> str:
        star_s = "?" if s.stars is None else f"{s.stars:.0f}"
        hfr_s = "?" if s.hfr is None else f"{s.hfr:.2f}"
        extra = f"  [{s.note}]" if s.note else ""
        return f"  {s.path.name}: stars={star_s} HFR={hfr_s}{extra}"

    if res.solve_failed:
        print(f"{verb} — solve-failed ({len(res.solve_failed)}): "
              "no WCS in a mostly-solved dir")
        for s in res.solve_failed[:SAMPLE]:
            print(_line(s))
        if len(res.solve_failed) > SAMPLE:
            print(f"  ... and {len(res.solve_failed) - SAMPLE} more")
        print()
    if metric_only:
        print(f"{verb} — metric thresholds ({len(metric_only)}): "
              "failed stars/HFR/sky/roundness")
        for s in metric_only[:SAMPLE]:
            print(_line(s))
        if len(metric_only) > SAMPLE:
            print(f"  ... and {len(metric_only) - SAMPLE} more")
    if res.rejected and not args.dry_run:
        print(f"  -> {lights / '_rejected'}")
    sf_part = f" ({len(res.solve_failed)} solve-failed + {len(metric_only)} metric)" \
        if res.solve_failed else ""
    print(
        f"\nDONE: {len(res.kept)} kept, {len(res.rejected)} rejected"
        f"{sf_part}, {len(res.unscored)} unscored (of {res.total})."
    )


def solve(args: argparse.Namespace) -> None:
    """Bulk plate-solve a captures directory via ASTAP. WCS goes into each
    FITS in place. Idempotent (skips already-solved unless --force)."""
    from .solve import AstapNotFound, find_astap_cli, run_solve_dir

    # Site config may set fov_deg; CLI --fov wins. Reuses the same
    # `capture_defaults` section as mira capture / mira flats.
    site = _load_site_capture_defaults(args.config)
    fov = args.fov if args.fov is not None else site.get("fov_deg")
    if fov is None:
        from .solve import DEFAULT_FOV_DEG
        fov = DEFAULT_FOV_DEG

    try:
        cli = args.astap_cli or find_astap_cli()
    except AstapNotFound as exc:
        raise SystemExit(str(exc))

    lights = Path(args.lights)
    if not lights.is_dir():
        raise SystemExit(f"--lights: not a directory: {lights}")

    print(f"Solving {lights} with {cli}")
    res = run_solve_dir(
        lights,
        astap_cli=cli,
        force=args.force,
        workers=max(1, args.workers),
        fov_deg=fov,
        radius_deg=args.radius,
        timeout_s=args.timeout_s,
        ra_hint_deg=args.ra,
        dec_hint_deg=args.dec,
        on_step=lambda m: print(m),
    )
    print(
        f"\nDONE: {len(res.solved)} solved, "
        f"{len(res.already_solved)} already solved, "
        f"{len(res.failed)} failed (of {res.total})."
    )
    if res.failed:
        print("Failed frames:")
        for r in res.failed[:20]:
            print(f"  {Path(r.path).name}: {r.note}")
        if len(res.failed) > 20:
            print(f"  ... and {len(res.failed) - 20} more")
        raise SystemExit(2)


def doctor(args: argparse.Namespace) -> None:
    """Preflight the rig. Prints an ASCII report and exits non-zero on any
    hard failure so bootstrap.ps1 / scripts can gate on it."""
    from .doctor import format_report, run_doctor, summarize

    checks = run_doctor(
        config_path=args.config,
        nina_url=args.nina_url,
        captures_root=args.captures_root,
    )
    print(format_report(checks))
    _, code = summarize(checks)
    if code != 0:
        raise SystemExit(code)


def tonight(args: argparse.Namespace) -> None:
    """Drive the shared tonight pipeline; both this and the webapp's
    `/run` POST end up in the same orchestration to avoid drift."""
    from .tonight_pipeline import PrintReporter, TonightOptions, run_tonight_pipeline

    base_output = Path(args.output_dir) if args.output_dir else None
    if base_output is not None:
        # Match the historical CLI behavior: --output-dir is a *base* dir,
        # the pipeline writes into <base>/tonight/. clean_previous_outputs
        # only on this CLI path; the webapp doesn't clean.
        clean_previous_outputs(base_output / "tonight")

    opts = TonightOptions(
        config_path=args.config,
        hours=args.hours,
        mode=args.mode,
        output_dir=base_output,
        top_packets=args.top,
        aavso_top=args.aavso_top,
        simbad_top=args.simbad_top,
        gaia_top=args.gaia_top,
        archive=False,
        extra_metadata={"run_started_utc": _run_timestamp},
    )
    try:
        result = run_tonight_pipeline(opts, PrintReporter())
    except VsxUnavailableError as exc:
        print(f"\nERROR: {exc}\n"
              "(No schedule written. Restore internet/tether and re-run "
              "`mira tonight`.)")
        raise SystemExit(1)
    if result is None:
        print(
            "Nothing in the next window. Try: increase --hours, run later when "
            "stars are higher, or use 'mira run' to see the multi-night queue."
        )
        return

    output_dir = result.output_dir
    print(f"Wrote {output_dir / 'candidate_queue.csv'}")
    print(f"Wrote {output_dir / 'session_plan.md'} (full menu)")
    print(f"Wrote {output_dir / 'session_plan.csv'}")
    print(
        f"Wrote {output_dir / 'session_schedule.md'} "
        f"({result.scheduled} targets scheduled, {result.overflow} overflow)"
    )
    print(f"Wrote {output_dir / 'session_schedule.csv'}")
    print(f"Wrote {output_dir / 'session_schedule.html'} (phone-readable)")
    print(f"Wrote {output_dir / 'nina_targets.csv'} (scheduled targets in execution order)")
    print(f"Wrote {result.packet_count} packets in {output_dir / 'candidate_packets'}")


def _filter_to_window(candidates, now_local: datetime, window_end: datetime) -> list:
    """Backwards-compat shim — delegates to tonight_pipeline.filter_to_window
    so existing callers (and any tests) keep working through the import."""
    from .tonight_pipeline import filter_to_window
    return filter_to_window(candidates, now_local, window_end)


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
