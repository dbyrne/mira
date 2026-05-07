"""Tests for the session_schedule.html renderer (timeline, target cards,
day-mode CSS). The output is the user's primary phone-readable view, so
these guard against silent regressions in structure."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from zoneinfo import ZoneInfo

from mira.config import load_config
from mira.models import AavsoStats, Candidate, Observability, VsxTarget
from mira.nightly_html import (
    _render_timeline_html,
    render_schedule_main_html,
    render_schedule_summary_html,
    write_session_schedule_html,
)
from mira.scheduler import ScheduledTarget, ScheduleResult

CONFIG = load_config(Path(__file__).resolve().parent.parent / "config" / "s30_pro_jc.yaml")
TZ = ZoneInfo("America/New_York")


def _target(name: str = "RR LYR", oid: int = 1, mag: float = 7.06) -> VsxTarget:
    return VsxTarget(
        oid=oid, name=name, var_type="RRAB",
        bright_mag=mag, faint_mag=mag + 1.0,
        bright_band="V", faint_band="V", faint_is_amplitude=False,
        period_days=0.5668, spectral_type="A",
        ra_deg=291.366, dec_deg=42.785,
    )


def _observability() -> Observability:
    return Observability(
        site_name="Jersey City",
        max_altitude_deg=70.0,
        minutes_above_minimum=200,
        best_local_time=datetime(2026, 5, 6, 22, 0, tzinfo=TZ),
        best_night_date=None,
        galactic_latitude_deg=25.0,
    )


def _candidate(name: str = "RR LYR", oid: int = 1, with_aavso: bool = False) -> Candidate:
    obs = _observability()
    cand = Candidate(
        target=_target(name, oid),
        observabilities=(obs,),
        score=80.0,
        reasons=["max altitude 70.0 deg", "long nightly window"],
        best_site_name="Jersey City",
        site_scores={"Jersey City": 80.0},
        site_reasons={"Jersey City": ["max altitude 70.0 deg"]},
    )
    if with_aavso:
        cand.aavso = AavsoStats(
            status="ok",
            recent_observations=5,
            recent_median_mag=7.5,
            recent_min_mag=7.2,
            recent_max_mag=7.9,
            recent_samples=[(2461165.5, 7.5, "V"), (2461166.5, 7.6, "V")],
        )
    return cand


def _scheduled(candidate: Candidate, start_min: int, duration_min: int) -> ScheduledTarget:
    start = datetime(2026, 5, 6, 22, 0, tzinfo=TZ) + timedelta(minutes=start_min)
    end = start + timedelta(minutes=duration_min)
    return ScheduledTarget(
        candidate=candidate,
        observability=candidate.observabilities[0],
        start_local=start,
        end_local=end,
        integration_minutes=duration_min - 3,
        slew_minutes=3.0,
        effective_score=candidate.score,
    )


def _schedule(scheduled: list[ScheduledTarget], overflow: list[Candidate] | None = None) -> ScheduleResult:
    return ScheduleResult(
        scheduled=scheduled,
        overflow=overflow or [],
        window_start=datetime(2026, 5, 6, 22, 0, tzinfo=TZ),
        window_end=datetime(2026, 5, 7, 2, 0, tzinfo=TZ),
    )


class TimelineRenderTests(TestCase):
    def test_three_blocks_render_with_anchors(self) -> None:
        s1 = _scheduled(_candidate("RR LYR", 1), start_min=0, duration_min=25)
        s2 = _scheduled(_candidate("AB AUR", 2), start_min=30, duration_min=35)
        s3 = _scheduled(_candidate("TT CYG", 3), start_min=70, duration_min=60)
        html = _render_timeline_html(_schedule([s1, s2, s3]))
        self.assertIn('href="#t1"', html)
        self.assertIn('href="#t2"', html)
        self.assertIn('href="#t3"', html)
        self.assertIn("RR LYR", html)
        self.assertIn("AB AUR", html)
        self.assertIn("TT CYG", html)

    def test_empty_window_returns_empty(self) -> None:
        zero_schedule = ScheduleResult(
            scheduled=[],
            overflow=[],
            window_start=datetime(2026, 5, 6, 22, 0, tzinfo=TZ),
            window_end=datetime(2026, 5, 6, 22, 0, tzinfo=TZ),  # same as start
        )
        self.assertEqual(_render_timeline_html(zero_schedule), "")

    def test_block_widths_proportional(self) -> None:
        # 4-hour window; a 30min block should be 12.5% wide
        s1 = _scheduled(_candidate("RR LYR"), start_min=0, duration_min=30)
        html = _render_timeline_html(_schedule([s1]))
        self.assertIn("width:12.50%", html)

    def test_hour_ticks_present(self) -> None:
        s1 = _scheduled(_candidate("RR LYR"), start_min=0, duration_min=30)
        html = _render_timeline_html(_schedule([s1]))
        # 4-hour window starting at 22:00 → ticks at 22:00, 23:00, 00:00, 01:00, 02:00
        self.assertIn("22:00", html)
        self.assertIn("00:00", html)


class RenderScheduleMainHtmlTests(TestCase):
    def test_quick_glance_table_present_with_targets(self) -> None:
        s = _scheduled(_candidate("RR LYR"), start_min=0, duration_min=30)
        html = render_schedule_main_html(_schedule([s]))
        self.assertIn("Schedule", html)  # quick-glance heading
        self.assertIn("RR LYR", html)
        self.assertIn("VSX details", html)  # action button

    def test_empty_schedule_message(self) -> None:
        html = render_schedule_main_html(_schedule([]))
        self.assertIn("No targets scheduled", html)

    def test_overflow_section_renders(self) -> None:
        cand = _candidate("FF DRA", oid=2)
        html = render_schedule_main_html(_schedule([], overflow=[cand]))
        self.assertIn("Overflow", html)
        self.assertIn("FF DRA", html)

    def test_aavso_section_includes_recent_obs(self) -> None:
        s = _scheduled(_candidate("RR LYR", with_aavso=True), start_min=0, duration_min=30)
        html = render_schedule_main_html(_schedule([s]))
        self.assertIn("AAVSO recent coverage", html)
        # The candidate has recent_observations=5
        self.assertIn(">5<", html)


class RenderScheduleSummaryHtmlTests(TestCase):
    def test_summary_contains_window_and_target_count(self) -> None:
        s = _scheduled(_candidate("RR LYR"), start_min=0, duration_min=30)
        html = render_schedule_summary_html(_schedule([s]), site_name="Jersey City")
        self.assertIn("Jersey City", html)
        self.assertIn("1 targets", html)


class WriteSessionScheduleHtmlTests(TestCase):
    def test_writes_html_file(self) -> None:
        with TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            s = _scheduled(_candidate("RR LYR"), start_min=0, duration_min=30)
            path = write_session_schedule_html(_schedule([s]), output_dir, CONFIG)
            self.assertTrue(path.exists())
            text = path.read_text(encoding="utf-8")
            # Must include the embedded CSS and page structure
            self.assertIn("<!DOCTYPE html>", text)
            self.assertIn("session-header", text)
            self.assertIn("RR LYR", text)
            self.assertIn("day-mode", text)  # day-mode toggle button

    def test_html_contains_dashboard_link(self) -> None:
        with TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            s = _scheduled(_candidate("RR LYR"), start_min=0, duration_min=30)
            path = write_session_schedule_html(_schedule([s]), output_dir, CONFIG)
            text = path.read_text(encoding="utf-8")
            self.assertIn("Dashboard", text)
