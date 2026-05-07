"""Tests for the helpers in `tonight_pipeline`. The full pipeline does
network I/O so we don't drive it end-to-end here; the orchestration is
exercised indirectly by the webapp tests via _execute_tonight, and the
CLI's tonight subcommand uses the same code path."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from zoneinfo import ZoneInfo

from mira.models import Candidate, Observability, VsxTarget
from mira.tonight_pipeline import (
    PrintReporter,
    _archive_outputs,
    filter_to_window,
)

TZ = ZoneInfo("America/New_York")


def _candidate(best_local: datetime | None) -> Candidate:
    obs = Observability(
        site_name="Jersey City",
        max_altitude_deg=70.0,
        minutes_above_minimum=200,
        best_local_time=best_local,
        best_night_date=None,
        galactic_latitude_deg=25.0,
    )
    target = VsxTarget(
        oid=1, name="X", var_type="RRAB",
        bright_mag=8.0, faint_mag=9.0, bright_band="V", faint_band="V",
        faint_is_amplitude=False, period_days=0.5, spectral_type="A",
        ra_deg=0.0, dec_deg=0.0,
    )
    return Candidate(
        target=target, observabilities=(obs,), score=50.0, reasons=[],
        best_site_name="Jersey City",
        site_scores={"Jersey City": 50.0},
        site_reasons={"Jersey City": []},
    )


class FilterToWindowTests(TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 5, 6, 22, 0, tzinfo=TZ)
        self.end = self.now + timedelta(hours=4)

    def test_keeps_candidate_in_window(self) -> None:
        cand = _candidate(self.now + timedelta(hours=1))
        result = filter_to_window([cand], self.now, self.end)
        self.assertEqual(result, [cand])

    def test_drops_candidate_after_window_end(self) -> None:
        cand = _candidate(self.now + timedelta(hours=10))
        result = filter_to_window([cand], self.now, self.end)
        self.assertEqual(result, [])

    def test_keeps_candidate_within_one_hour_hindsight(self) -> None:
        # Best moment 30 min ago; the 1h hindsight tolerance keeps it
        cand = _candidate(self.now - timedelta(minutes=30))
        result = filter_to_window([cand], self.now, self.end)
        self.assertEqual(result, [cand])

    def test_drops_candidate_more_than_one_hour_in_past(self) -> None:
        cand = _candidate(self.now - timedelta(hours=2))
        result = filter_to_window([cand], self.now, self.end)
        self.assertEqual(result, [])

    def test_drops_candidate_with_no_best_local_time(self) -> None:
        cand = _candidate(None)
        result = filter_to_window([cand], self.now, self.end)
        self.assertEqual(result, [])


class ArchiveOutputsTests(TestCase):
    def test_copies_files_and_packets_dir(self) -> None:
        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "tonight"
            source.mkdir()
            (source / "session_schedule.html").write_text("hi", encoding="utf-8")
            (source / "session_schedule.csv").write_text("a,b\n", encoding="utf-8")
            packets = source / "candidate_packets"
            packets.mkdir()
            (packets / "RR_LYR.md").write_text("packet", encoding="utf-8")

            archive = Path(tmp) / "archive" / "2026-05-06"
            _archive_outputs(source, archive, PrintReporter())

            self.assertTrue((archive / "session_schedule.html").exists())
            self.assertTrue((archive / "session_schedule.csv").exists())
            self.assertTrue((archive / "candidate_packets" / "RR_LYR.md").exists())

    def test_archive_failure_is_logged_not_raised(self) -> None:
        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "missing"
            archive = Path(tmp) / "archive" / "2026-05-06"
            # source doesn't exist; archive_outputs should swallow OSError
            class _Capture:
                def __init__(self): self.messages = []
                def log(self, m): self.messages.append(m)
                def progress(self, f): pass
            cap = _Capture()
            _archive_outputs(source, archive, cap)
            # At least one log line, indicating non-fatal failure
            self.assertTrue(any("failed" in m.lower() or "non-fatal" in m.lower() for m in cap.messages))
