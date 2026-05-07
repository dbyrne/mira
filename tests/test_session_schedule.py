"""Tests for the schedule writers (md, csv, NINA csv, overflow csv).

We construct ScheduleResult fixtures directly (rather than running the
greedy scheduler) so the writer behavior is decoupled from scheduling
logic. The CSV outputs are the contract that NINA Target Scheduler
imports and the photometry index reads — schema regressions here would
silently break the workflow.
"""
from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from zoneinfo import ZoneInfo

from anomaly_scout.config import load_config
from anomaly_scout.models import Candidate, Observability, VsxTarget
from anomaly_scout.scheduler import ScheduledTarget, ScheduleResult
from anomaly_scout.session_schedule import (
    write_nina_targets_scheduled_csv,
    write_session_overflow_csv,
    write_session_schedule_csv,
    write_session_schedule_md,
    write_session_schedule_outputs,
)

CONFIG = load_config(Path(__file__).resolve().parent.parent / "config" / "s30_pro_jc.yaml")
TZ = ZoneInfo("America/New_York")


def _target(name: str = "RR LYR", oid: int = 1, mag: float = 7.06, period: float | None = 0.5668) -> VsxTarget:
    return VsxTarget(
        oid=oid, name=name, var_type="RRAB",
        bright_mag=mag, faint_mag=mag + 1.0,
        bright_band="V", faint_band="V", faint_is_amplitude=False,
        period_days=period, spectral_type="A",
        ra_deg=291.366, dec_deg=42.785,
    )


def _observability(site: str = "Jersey City", best_local: datetime | None = None) -> Observability:
    return Observability(
        site_name=site,
        max_altitude_deg=70.0,
        minutes_above_minimum=200,
        best_local_time=best_local or datetime(2026, 5, 6, 22, 0, tzinfo=TZ),
        best_night_date=None,
        galactic_latitude_deg=25.0,
    )


def _candidate(name: str = "RR LYR", oid: int = 1, score: float = 80.0) -> Candidate:
    obs = _observability()
    return Candidate(
        target=_target(name, oid),
        observabilities=(obs,),
        score=score,
        reasons=["test"],
        best_site_name="Jersey City",
        site_scores={"Jersey City": score},
        site_reasons={"Jersey City": ["test"]},
    )


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


def _schedule(scheduled: list[ScheduledTarget], overflow: list[Candidate]) -> ScheduleResult:
    return ScheduleResult(
        scheduled=scheduled,
        overflow=overflow,
        window_start=datetime(2026, 5, 6, 22, 0, tzinfo=TZ),
        window_end=datetime(2026, 5, 7, 2, 0, tzinfo=TZ),
    )


class WriteSessionScheduleCsvTests(TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.path = Path(self.tmp.name) / "session_schedule.csv"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_csv_has_expected_columns(self) -> None:
        sched = _scheduled(_candidate("RR LYR"), start_min=0, duration_min=30)
        write_session_schedule_csv(_schedule([sched], []), self.path)
        with self.path.open(encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        self.assertEqual(len(rows), 1)
        expected_cols = {"order", "start_local", "end_local", "name", "ra_deg",
                        "dec_deg", "bright_mag", "var_type", "exposure_seconds",
                        "frame_count", "integration_minutes", "score", "effective_score"}
        self.assertTrue(expected_cols.issubset(reader.fieldnames or []))

    def test_csv_rows_in_schedule_order(self) -> None:
        a = _scheduled(_candidate("RR LYR", oid=1, score=80), start_min=0, duration_min=30)
        b = _scheduled(_candidate("AB AUR", oid=2, score=90), start_min=33, duration_min=30)
        write_session_schedule_csv(_schedule([a, b], []), self.path)
        with self.path.open(encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual([r["name"] for r in rows], ["RR LYR", "AB AUR"])
        self.assertEqual([int(r["order"]) for r in rows], [1, 2])

    def test_empty_schedule_writes_header_only(self) -> None:
        write_session_schedule_csv(_schedule([], []), self.path)
        with self.path.open(encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(rows, [])


class WriteSessionOverflowCsvTests(TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.path = Path(self.tmp.name) / "session_overflow.csv"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_overflow_columns(self) -> None:
        cand = _candidate("FF DRA", oid=99)
        write_session_overflow_csv(_schedule([], [cand]), self.path)
        with self.path.open(encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "FF DRA")
        # best_local_time should be HH:MM formatted
        self.assertRegex(rows[0]["best_local_time"], r"^\d{2}:\d{2}$")

    def test_empty_overflow(self) -> None:
        write_session_overflow_csv(_schedule([], []), self.path)
        with self.path.open(encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(rows, [])


class WriteNinaTargetsScheduledCsvTests(TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.path = Path(self.tmp.name) / "nina_targets.csv"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_nina_csv_has_target_scheduler_schema(self) -> None:
        sched = _scheduled(_candidate("RR LYR"), start_min=0, duration_min=30)
        write_nina_targets_scheduled_csv(_schedule([sched], []), self.path)
        with self.path.open(encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        self.assertEqual(len(rows), 1)
        # NINA Target Scheduler expects these exact columns
        expected_cols = {"Type", "Name", "Ra", "Dec", "Rotation", "ROI"}
        self.assertEqual(set(reader.fieldnames or []), expected_cols)
        self.assertEqual(rows[0]["Type"], "Variable Star")
        self.assertEqual(rows[0]["Name"], "RR LYR")

    def test_excludes_overflow_targets(self) -> None:
        sched = _scheduled(_candidate("RR LYR", oid=1), start_min=0, duration_min=30)
        overflow_cand = _candidate("FF DRA", oid=2)
        write_nina_targets_scheduled_csv(_schedule([sched], [overflow_cand]), self.path)
        with self.path.open(encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        names = [r["Name"] for r in rows]
        self.assertIn("RR LYR", names)
        self.assertNotIn("FF DRA", names)


class WriteSessionScheduleMdTests(TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.path = Path(self.tmp.name) / "session_schedule.md"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_md_contains_quick_glance_and_target_section(self) -> None:
        sched = _scheduled(_candidate("RR LYR"), start_min=0, duration_min=30)
        write_session_schedule_md(_schedule([sched], []), self.path, CONFIG)
        text = self.path.read_text(encoding="utf-8")
        self.assertIn("Quick-glance schedule", text)
        self.assertIn("RR LYR", text)
        self.assertIn("Workflow reminder", text)

    def test_md_renders_no_targets_message_when_empty(self) -> None:
        write_session_schedule_md(_schedule([], []), self.path, CONFIG)
        text = self.path.read_text(encoding="utf-8")
        self.assertIn("No targets scheduled", text)

    def test_md_includes_overflow_section(self) -> None:
        cand = _candidate("FF DRA", oid=2)
        write_session_schedule_md(_schedule([], [cand]), self.path, CONFIG)
        text = self.path.read_text(encoding="utf-8")
        self.assertIn("Unscheduled overflow", text)
        self.assertIn("FF DRA", text)


class WriteSessionScheduleOutputsTests(TestCase):
    def test_writes_all_four_files(self) -> None:
        with TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            sched = _scheduled(_candidate("RR LYR"), start_min=0, duration_min=30)
            cand = _candidate("FF DRA", oid=2)
            write_session_schedule_outputs(_schedule([sched], [cand]), output_dir, CONFIG)
            self.assertTrue((output_dir / "session_schedule.md").exists())
            self.assertTrue((output_dir / "session_schedule.csv").exists())
            self.assertTrue((output_dir / "nina_targets.csv").exists())
            self.assertTrue((output_dir / "session_overflow.csv").exists())
