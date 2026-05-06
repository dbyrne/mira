"""Shared orchestration for the `tonight` workflow.

Both `anomaly-scout tonight` (CLI) and the webapp's "Generate tonight's
plan" button (`/run`) execute the same sequence: load config, snap each
site to nights=1, fetch VSX, build candidates, filter to the window,
enrich (AAVSO → SIMBAD → Gaia), then write the schedule + packet outputs.

This module is the single canonical implementation of that sequence so
fixes don't have to be made in two places. Callers supply a :class:`Reporter`
that adapts ``log()`` / ``progress()`` calls onto either ``print`` or
``RunRecord.log`` + ``RunRecord.set_progress``.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace as dc_replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from .aavso import enrich_candidates_with_aavso
from .config import load_config
from .gaia import enrich_candidates_with_gaia
from .nightly_html import write_session_schedule_html
from .report import compute_packet_union_oids, write_outputs
from .scheduler import build_session_schedule
from .scoring import build_candidates, candidate_sort_key
from .session_plan import write_session_plan
from .session_schedule import write_session_schedule_outputs
from .simbad import enrich_candidates_with_simbad
from .vsx import fetch_vsx_targets


@dataclass
class TonightOptions:
    """Inputs to ``run_tonight_pipeline``.

    `output_dir` defaults to ``config.output.directory / "tonight"`` when None.
    The enrich-top knobs default to the corresponding config values.
    """
    config_path: str
    hours: float
    mode: str | None = None
    output_dir: Path | None = None
    top_packets: int | None = None
    aavso_top: int | None = None
    simbad_top: int | None = None
    gaia_top: int | None = None
    archive: bool = False  # also snapshot outputs to <base>/archive/<DATE>/
    extra_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TonightResult:
    """Outputs from a successful ``run_tonight_pipeline``.

    A None return indicates "no candidates were observable in the window";
    callers should treat that as a soft fail (no exception, no schedule)."""
    output_dir: Path
    scheduled: int
    overflow: int
    packet_count: int
    schedule_html_path: Path
    archive_path: Path | None
    session_date: str
    aavso_enriched: int
    simbad_enriched: int
    gaia_enriched: int


class Reporter(Protocol):
    """Adapter for the two I/O patterns: CLI prints and webapp logs progress
    onto a RunRecord. Implementations only need ``log`` and ``progress``."""

    def log(self, message: str) -> None: ...
    def progress(self, fraction: float) -> None: ...


class PrintReporter:
    """Reporter that prints to stdout. Used by the CLI."""

    def log(self, message: str) -> None:
        print(message)

    def progress(self, fraction: float) -> None:  # noqa: ARG002 - no-op for CLI
        return


def run_tonight_pipeline(opts: TonightOptions, reporter: Reporter) -> TonightResult | None:
    """Execute the full tonight workflow. Returns None when nothing in the
    window is observable; otherwise a TonightResult summary."""
    reporter.progress(0.05)
    reporter.log(f"Loading config: {opts.config_path}")
    config = load_config(opts.config_path)

    if opts.mode is not None:
        from .cli import _apply_mode
        config = _apply_mode(config, opts.mode)
        reporter.log(f"Mode: {opts.mode}")

    # Each site is snapped to nights=1 so the standard pipeline runs only
    # against tonight's date.
    new_sites = tuple(
        dc_replace(site, observing_window=dc_replace(site.observing_window, nights=1))
        for site in config.sites
    )
    config = dc_replace(config, sites=new_sites)

    top_packets = opts.top_packets if opts.top_packets is not None else config.output.top_packets
    base_output = opts.output_dir if opts.output_dir is not None else config.output.directory
    output_dir = base_output if (opts.output_dir is not None and opts.output_dir.name == "tonight") else base_output / "tonight"
    output_dir.mkdir(parents=True, exist_ok=True)

    today = date.today()
    primary_tz = ZoneInfo(config.sites[0].observer.timezone)
    now_local = datetime.now(primary_tz)
    window_end = now_local + timedelta(hours=opts.hours)
    reporter.log(
        f"Tonight = {today.isoformat()}; window = {now_local.strftime('%H:%M')}"
        f" -> {window_end.strftime('%H:%M %Z')}"
    )
    reporter.progress(0.1)

    reporter.log(f"Fetching up to {config.vsx_query.row_limit} VSX rows...")
    targets = fetch_vsx_targets(config.vsx_query)
    reporter.log(f"Fetched {len(targets)} catalog rows.")
    reporter.progress(0.25)

    candidates = build_candidates(targets, config, start_date=today)
    reporter.log(f"{len(candidates)} targets passed site filters.")
    candidates = filter_to_window(candidates, now_local, window_end)
    reporter.log(f"{len(candidates)} observable in the next {opts.hours:g}h.")
    reporter.progress(0.35)

    if not candidates:
        reporter.log("Nothing observable in the window; widen --hours or run later.")
        return None

    site_names = [s.name for s in config.sites]
    union_oids = compute_packet_union_oids(candidates, top_packets, site_names)

    aavso_top = config.aavso.enrich_top if opts.aavso_top is None else max(0, int(opts.aavso_top))
    aavso_count = 0
    if config.aavso.enabled and (aavso_top or union_oids):
        aavso_count = enrich_candidates_with_aavso(
            candidates, config, limit=aavso_top, extra_oids=union_oids
        )
        reporter.log(f"AAVSO enriched: {aavso_count}")
    reporter.progress(0.55)

    union_oids = compute_packet_union_oids(candidates, top_packets, site_names)
    simbad_top = config.simbad.enrich_top if opts.simbad_top is None else max(0, int(opts.simbad_top))
    simbad_count = 0
    if config.simbad.enabled and (simbad_top or union_oids):
        simbad_count = enrich_candidates_with_simbad(
            candidates, config, limit=simbad_top, extra_oids=union_oids
        )
        reporter.log(f"SIMBAD enriched: {simbad_count}")
    reporter.progress(0.7)

    gaia_top = config.gaia.enrich_top if opts.gaia_top is None else max(0, int(opts.gaia_top))
    gaia_count = 0
    if config.gaia.enabled and (gaia_top or union_oids):
        gaia_count = enrich_candidates_with_gaia(
            candidates, config, limit=gaia_top, extra_oids=union_oids
        )
        candidates.sort(key=candidate_sort_key)
        reporter.log(f"Gaia enriched: {gaia_count}")
    reporter.progress(0.85)

    metadata: dict[str, Any] = {
        "config_path": opts.config_path,
        "output_dir": str(output_dir),
        "start_date": today.isoformat(),
        "mode": opts.mode or "(yaml defaults)",
        "vsx_row_limit": config.vsx_query.row_limit,
        "candidates_after_filters": len(candidates),
        "aavso_enriched": aavso_count,
        "simbad_enriched": simbad_count,
        "gaia_enriched": gaia_count,
        "ztf_enriched": 0,
        "top_packets_per_view": top_packets,
        "tonight_window_start": now_local.isoformat(),
        "tonight_window_end": window_end.isoformat(),
        "tonight_hours": opts.hours,
    }
    metadata.update(opts.extra_metadata)

    packet_count = write_outputs(candidates, output_dir, top_packets, site_names=site_names, metadata=metadata)
    plan_targets = candidates[:top_packets]
    write_session_plan(plan_targets, output_dir, now_local, window_end, config)
    schedule = build_session_schedule(candidates, window_start=now_local, window_end=window_end)
    write_session_schedule_outputs(schedule, output_dir, config)
    schedule_html_path = write_session_schedule_html(schedule, output_dir, config, metadata=metadata)

    archive_path: Path | None = None
    if opts.archive:
        archive_path = output_dir.parent / "archive" / today.isoformat()
        _archive_outputs(output_dir, archive_path, reporter)

    reporter.log(f"Scheduled {len(schedule.scheduled)} targets, {len(schedule.overflow)} overflow.")
    reporter.log(f"Packets: {packet_count}")
    reporter.progress(1.0)

    return TonightResult(
        output_dir=output_dir,
        scheduled=len(schedule.scheduled),
        overflow=len(schedule.overflow),
        packet_count=packet_count,
        schedule_html_path=schedule_html_path,
        archive_path=archive_path,
        session_date=today.isoformat(),
        aavso_enriched=aavso_count,
        simbad_enriched=simbad_count,
        gaia_enriched=gaia_count,
    )


def filter_to_window(candidates, now_local: datetime, window_end: datetime) -> list:
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


def _archive_outputs(source: Path, archive_dir: Path, reporter: Reporter) -> None:
    """Snapshot tonight's output directory to <base>/archive/<DATE>/. Best-
    effort; failure is logged but doesn't fail the pipeline."""
    import shutil as _shutil

    try:
        archive_dir.mkdir(parents=True, exist_ok=True)
        for entry in source.iterdir():
            dst = archive_dir / entry.name
            if entry.is_file():
                _shutil.copy2(entry, dst)
            elif entry.is_dir() and entry.name == "candidate_packets":
                if dst.exists():
                    _shutil.rmtree(dst)
                _shutil.copytree(entry, dst)
        reporter.log(f"Archived to {archive_dir}")
    except OSError as exc:
        reporter.log(f"Archive copy failed (non-fatal): {exc}")
