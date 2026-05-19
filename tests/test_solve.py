"""Tests for the bulk ASTAP solver. No real astap_cli — subprocess.run is
injected via the `runner` kwarg. The properties under test:

  - already-solved frames are skipped (cheap header check)
  - RA/Dec hints are read from mira_capture.json when not passed
  - blind solve falls back to -fov 0 -r 180 if no hint
  - failure modes: timeout, non-zero exit, exit 0 + no WCS-after
  - --force re-solves
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import MagicMock, patch

from astropy.io import fits

from mira.solve import (
    BLIND_RADIUS_DEG,
    SolveResult,
    has_wcs,
    load_hints_from_sidecar,
    run_solve_dir,
    solve_one,
)


def _make_fits(path: Path, *, with_wcs: bool = False) -> None:
    """Write a tiny FITS file (3x3 zero image). Optionally include a
    minimal WCS (CTYPE1+CRVAL1) so has_wcs returns True."""
    hdu = fits.PrimaryHDU(data=[[0, 0, 0], [0, 0, 0], [0, 0, 0]])
    if with_wcs:
        hdu.header["CTYPE1"] = "RA---TAN"
        hdu.header["CTYPE2"] = "DEC--TAN"
        hdu.header["CRVAL1"] = 202.4696
        hdu.header["CRVAL2"] = 47.1952
    hdu.writeto(path, overwrite=True)


def _fake_runner_factory(*, returncode: int = 0,
                          inject_wcs_into_fits: bool = True,
                          stdout: str = "", stderr: str = ""):
    """Build a mock subprocess.run that simulates astap_cli. When
    `inject_wcs_into_fits` is True, the runner writes WCS into the -f
    target so post-solve has_wcs() returns True — matching real ASTAP's
    -update behavior."""
    calls: list[list[str]] = []

    def _runner(args, **kw):
        calls.append(list(args))
        if inject_wcs_into_fits and "-update" in args:
            f_idx = args.index("-f")
            target = Path(args[f_idx + 1])
            if target.exists():
                _make_fits(target, with_wcs=True)
        return subprocess.CompletedProcess(
            args=args, returncode=returncode,
            stdout=stdout, stderr=stderr,
        )

    _runner.calls = calls  # type: ignore[attr-defined]
    return _runner


class TestHasWcs(TestCase):
    def test_detects_wcs(self) -> None:
        with TemporaryDirectory() as d:
            p = Path(d) / "a.fit"
            _make_fits(p, with_wcs=True)
            self.assertTrue(has_wcs(p))

    def test_no_wcs(self) -> None:
        with TemporaryDirectory() as d:
            p = Path(d) / "a.fit"
            _make_fits(p, with_wcs=False)
            self.assertFalse(has_wcs(p))

    def test_unreadable_returns_false(self) -> None:
        self.assertFalse(has_wcs(Path("/nonexistent/x.fit")))


class TestLoadHintsFromSidecar(TestCase):
    def test_reads_ra_dec_from_sidecar(self) -> None:
        with TemporaryDirectory() as d:
            (Path(d) / "mira_capture.json").write_text(
                json.dumps({"ra_deg": 202.47, "dec_deg": 47.20, "filter": "LP"}),
                encoding="utf-8",
            )
            ra, dec = load_hints_from_sidecar(Path(d))
            self.assertEqual((ra, dec), (202.47, 47.20))

    def test_missing_sidecar_returns_none_none(self) -> None:
        with TemporaryDirectory() as d:
            self.assertEqual(load_hints_from_sidecar(Path(d)), (None, None))

    def test_unparseable_sidecar_returns_none_none(self) -> None:
        with TemporaryDirectory() as d:
            (Path(d) / "mira_capture.json").write_text("{not json", encoding="utf-8")
            self.assertEqual(load_hints_from_sidecar(Path(d)), (None, None))


class TestSolveOne(TestCase):
    def test_guided_solve_passes_ra_in_hours_and_spd(self) -> None:
        with TemporaryDirectory() as d:
            f = Path(d) / "x.fit"
            _make_fits(f)
            runner = _fake_runner_factory(returncode=0)
            r = solve_one(
                f, astap_cli="astap", ra_hint_deg=202.47, dec_hint_deg=47.20,
                runner=runner,
            )
            self.assertEqual(r.status, "solved")
            args = runner.calls[0]
            self.assertIn("-update", args)
            # ASTAP wants RA in HOURS, not deg.
            ra_idx = args.index("-ra")
            self.assertAlmostEqual(float(args[ra_idx + 1]),
                                   202.47 / 15.0, places=5)
            # SPD = 90 + dec_deg.
            spd_idx = args.index("-spd")
            self.assertAlmostEqual(float(args[spd_idx + 1]),
                                   90.0 + 47.20, places=5)
            self.assertNotIn("0", args[args.index("-fov") + 1:args.index("-fov") + 2])

    def test_blind_solve_when_no_hints(self) -> None:
        with TemporaryDirectory() as d:
            f = Path(d) / "x.fit"
            _make_fits(f)
            runner = _fake_runner_factory(returncode=0)
            r = solve_one(
                f, astap_cli="astap", ra_hint_deg=None, dec_hint_deg=None,
                runner=runner,
            )
            self.assertEqual(r.status, "solved")
            args = runner.calls[0]
            self.assertNotIn("-ra", args)
            self.assertNotIn("-spd", args)
            # Blind uses fov=0 (auto) and the full-sky radius.
            self.assertEqual(args[args.index("-fov") + 1], "0")
            self.assertEqual(float(args[args.index("-r") + 1]),
                              BLIND_RADIUS_DEG)

    def test_nonzero_exit_is_failure(self) -> None:
        with TemporaryDirectory() as d:
            f = Path(d) / "x.fit"
            _make_fits(f)
            runner = _fake_runner_factory(
                returncode=1, inject_wcs_into_fits=False,
                stderr="no solution",
            )
            r = solve_one(
                f, astap_cli="astap", ra_hint_deg=10.0, dec_hint_deg=20.0,
                runner=runner,
            )
            self.assertEqual(r.status, "failed")
            self.assertIn("exit 1", r.note)

    def test_exit_zero_but_no_wcs_is_failure(self) -> None:
        """ASTAP can exit 0 with 'no solution found' if the star DB is
        missing — verify by reading the post-solve header."""
        with TemporaryDirectory() as d:
            f = Path(d) / "x.fit"
            _make_fits(f)
            runner = _fake_runner_factory(
                returncode=0, inject_wcs_into_fits=False,
            )
            r = solve_one(
                f, astap_cli="astap", ra_hint_deg=10.0, dec_hint_deg=20.0,
                runner=runner,
            )
            self.assertEqual(r.status, "failed")
            self.assertIn("no WCS", r.note)

    def test_timeout_is_failure(self) -> None:
        with TemporaryDirectory() as d:
            f = Path(d) / "x.fit"
            _make_fits(f)
            def _timeout_runner(*a, **kw):
                raise subprocess.TimeoutExpired(cmd=a[0], timeout=kw.get("timeout"))
            r = solve_one(
                f, astap_cli="astap", ra_hint_deg=10.0, dec_hint_deg=20.0,
                timeout_s=5.0, runner=_timeout_runner,
            )
            self.assertEqual(r.status, "failed")
            self.assertIn("timed out", r.note)


class TestRunSolveDir(TestCase):
    def _dir_with_frames(self, d: Path, n: int = 3, already_solved: int = 0,
                          with_sidecar: bool = True) -> Path:
        lights = d / "lights"
        lights.mkdir()
        if with_sidecar:
            (lights / "mira_capture.json").write_text(
                json.dumps({"ra_deg": 202.47, "dec_deg": 47.20}),
                encoding="utf-8",
            )
        for i in range(n):
            _make_fits(lights / f"frame_{i:04d}.fit",
                       with_wcs=(i < already_solved))
        return lights

    def test_skips_already_solved_unless_force(self) -> None:
        with TemporaryDirectory() as d:
            lights = self._dir_with_frames(Path(d), n=5, already_solved=2)
            runner = _fake_runner_factory()
            res = run_solve_dir(
                lights, astap_cli="astap", workers=1, runner=runner,
            )
            self.assertEqual(len(res.already_solved), 2)
            self.assertEqual(len(res.solved), 3)
            self.assertEqual(len(res.failed), 0)
            self.assertEqual(len(runner.calls), 3)   # only the 3 unsolved

    def test_force_resolves_everything(self) -> None:
        with TemporaryDirectory() as d:
            lights = self._dir_with_frames(Path(d), n=5, already_solved=2)
            runner = _fake_runner_factory()
            res = run_solve_dir(
                lights, astap_cli="astap", workers=1, force=True,
                runner=runner,
            )
            self.assertEqual(len(res.solved), 5)
            self.assertEqual(len(res.already_solved), 0)
            self.assertEqual(len(runner.calls), 5)

    def test_uses_sidecar_hints_by_default(self) -> None:
        with TemporaryDirectory() as d:
            lights = self._dir_with_frames(Path(d), n=2)
            runner = _fake_runner_factory()
            run_solve_dir(lights, astap_cli="astap", workers=1, runner=runner)
            # First call should have -ra hint derived from sidecar (202.47/15).
            args = runner.calls[0]
            self.assertIn("-ra", args)
            self.assertAlmostEqual(float(args[args.index("-ra") + 1]),
                                    202.47 / 15.0, places=4)

    def test_explicit_hint_overrides_sidecar(self) -> None:
        with TemporaryDirectory() as d:
            lights = self._dir_with_frames(Path(d), n=1)
            runner = _fake_runner_factory()
            run_solve_dir(
                lights, astap_cli="astap", workers=1,
                ra_hint_deg=10.0, dec_hint_deg=20.0, runner=runner,
            )
            args = runner.calls[0]
            self.assertAlmostEqual(float(args[args.index("-ra") + 1]),
                                    10.0 / 15.0, places=4)

    def test_no_sidecar_no_hint_falls_back_to_blind(self) -> None:
        with TemporaryDirectory() as d:
            lights = self._dir_with_frames(Path(d), n=2, with_sidecar=False)
            runner = _fake_runner_factory()
            run_solve_dir(lights, astap_cli="astap", workers=1, runner=runner)
            args = runner.calls[0]
            self.assertNotIn("-ra", args)
            self.assertEqual(args[args.index("-fov") + 1], "0")
