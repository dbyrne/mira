"""Tests for `mira doctor`. Pure helpers (version parse, darkness math,
summarize, formatter) are asserted hard; rig/env-dependent checks are
asserted structurally (status in an allowed set, never raises) so the
suite is deterministic on any machine."""
from __future__ import annotations

from datetime import datetime, timezone
from tempfile import TemporaryDirectory
from unittest import TestCase

from mira.doctor import (
    FAIL,
    PASS,
    WARN,
    Check,
    check_config,
    check_disk_space,
    check_nina,
    check_python,
    check_writable,
    format_report,
    night_darkness_minutes,
    parse_version,
    run_doctor,
    summarize,
)


class TestPureHelpers(TestCase):
    def test_parse_version(self) -> None:
        self.assertEqual(parse_version("siril 1.4.3 for windows"), (1, 4, 3))
        self.assertEqual(parse_version("numpy 2.2.6"), (2, 2, 6))
        self.assertEqual(parse_version("no digits here"), ())
        self.assertEqual(parse_version(""), ())

    def test_darkness_polar_day_is_zero(self) -> None:
        # 80N at northern summer solstice: sun never below -12 -> 0 min.
        mins = night_darkness_minutes(
            80.0, 0.0, -12.0,
            datetime(2026, 6, 21, tzinfo=timezone.utc), hours=24, step_min=30)
        self.assertEqual(mins, 0)

    def test_darkness_midlatitude_has_some(self) -> None:
        # 40N in autumn: a real, partial dark window (0 < x < 24h).
        mins = night_darkness_minutes(
            40.0, -74.0, -12.0,
            datetime(2026, 10, 1, tzinfo=timezone.utc), hours=24, step_min=15)
        self.assertGreater(mins, 0)
        self.assertLess(mins, 24 * 60)

    def test_summarize_precedence(self) -> None:
        self.assertEqual(summarize([Check("a", PASS)]), ("RIG READY", 0))
        v, c = summarize([Check("a", PASS), Check("b", WARN)])
        self.assertIn("warning", v)
        self.assertEqual(c, 0)                      # WARN does not fail exit
        v, c = summarize([Check("a", WARN), Check("b", FAIL)])
        self.assertEqual(c, 1)                      # any FAIL -> exit 1
        self.assertEqual(v, "RIG NOT READY")

    def test_format_report_is_ascii_and_has_verdict(self) -> None:
        rep = format_report([Check("X", PASS, "ok"),
                             Check("Y", FAIL, "bad", "do the thing")])
        self.assertTrue(rep.isascii(), "cp1252 consoles need ASCII-only")
        self.assertIn("[PASS] X", rep)
        self.assertIn("[FAIL] Y", rep)
        self.assertIn("fix: do the thing", rep)
        self.assertIn("RIG NOT READY", rep)

    def test_fix_hidden_on_pass(self) -> None:
        rep = format_report([Check("X", PASS, "ok", "should not show")])
        self.assertNotIn("should not show", rep)


class TestEnvChecks(TestCase):
    def test_python_passes_on_supported_interpreter(self) -> None:
        # The project requires 3.11+, so the test interpreter is >= 3.11.
        self.assertEqual(check_python().status, PASS)

    def test_writable_tmp(self) -> None:
        with TemporaryDirectory() as d:
            self.assertEqual(check_writable((d,)).status, PASS)

    def test_disk_space_structural(self) -> None:
        with TemporaryDirectory() as d:
            c = check_disk_space(d, min_free_gb=0.0)
            self.assertEqual(c.status, PASS)        # 0 GB floor always passes
            c2 = check_disk_space(d, min_free_gb=1e9)  # impossible
            self.assertEqual(c2.status, WARN)

    def test_disk_space_walks_up_to_existing_parent(self) -> None:
        # A not-yet-created captures dir must not crash the check.
        with TemporaryDirectory() as d:
            c = check_disk_space(f"{d}/does/not/exist/yet", min_free_gb=0.0)
            self.assertEqual(c.status, PASS)

    def test_nina_unreachable_is_warn_not_fail(self) -> None:
        chk, url = check_nina("http://localhost:59999")
        self.assertEqual(chk.status, WARN)          # absent NINA != hard fail
        self.assertIsNone(url)
        self.assertIn("not reachable", chk.detail)


class TestConfigAndEndToEnd(TestCase):
    def test_check_config_repo_profile(self) -> None:
        c = check_config("config/s30_pro_jc.yaml")
        self.assertEqual(c.status, PASS)
        self.assertIn("site", c.detail)

    def test_run_doctor_never_raises_and_is_complete(self) -> None:
        # Bogus NINA url keeps it deterministic (NINA -> WARN, not hang).
        checks = run_doctor(
            config_path="config/s30_pro_jc.yaml",
            nina_url="http://localhost:59999",
            captures_root="captures",
            when=datetime(2026, 10, 1, tzinfo=timezone.utc),
        )
        names = {c.name for c in checks}
        for expected in ("Python >= 3.11", "Core dependencies",
                         "numpy GraXpert-compatible", "NINA Advanced API",
                         "Darkness tonight", "Config"):
            self.assertIn(expected, names)
        for c in checks:
            self.assertIn(c.status, (PASS, WARN, FAIL))
        # summarize must produce a usable verdict/code
        verdict, code = summarize(checks)
        self.assertIn(code, (0, 1))
        self.assertTrue(verdict)
