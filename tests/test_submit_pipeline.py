"""Tests for the shared submit_pipeline module — comp resolution
(JSON vs VSP), FITS preflight, photometry loop with on-frame streaming,
outlier flagging."""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS

from anomaly_scout.photometry import CompStar
from anomaly_scout.submit_pipeline import (
    FrameRecord,
    PhotometryRunResult,
    flag_outliers,
    preflight_fits_dir,
    resolve_comps,
    run_photometry_loop,
)


def _make_fits(path: Path, with_wcs: bool = True) -> None:
    rng = np.random.default_rng(42)
    image = (100 + rng.normal(0, 5, (256, 256))).astype(float)
    # Plant a Gaussian source at center
    yy, xx = np.mgrid[0:256, 0:256]
    image += 1000 * np.exp(-((xx - 128) ** 2 + (yy - 128) ** 2) / (2 * 2 ** 2))
    image += 2512 * np.exp(-((xx - 158) ** 2 + (yy - 128) ** 2) / (2 * 2 ** 2))
    hdr = fits.Header()
    hdr["JD"] = 2461165.5
    if with_wcs:
        wcs = WCS(naxis=2)
        wcs.wcs.crpix = [128.0, 128.0]
        wcs.wcs.crval = [180.0, 0.0]
        wcs.wcs.cdelt = [-1.0 / 3600, 1.0 / 3600]
        wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
        hdr.update(wcs.to_header())
    hdu = fits.PrimaryHDU(image.astype(np.float32), header=hdr)
    hdu.writeto(path, overwrite=True)


class ResolveCompsTests(TestCase):
    def test_loads_from_json_path(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "comps.json"
            path.write_text(json.dumps([
                {"label": "100", "ra_deg": 180.0, "dec_deg": 0.0,
                 "catalog_mag": 10.0, "catalog_band": "V"},
                {"label": "105", "ra_deg": 180.1, "dec_deg": 0.1,
                 "catalog_mag": 10.5, "catalog_band": "V"},
            ]))
            res = resolve_comps(
                target_name="X", target_bright_mag=10.0,
                comp_path=path, chart_id_override="X12345",
            )
        self.assertEqual(res.source, "json")
        self.assertEqual(res.chart_id, "X12345")
        self.assertEqual(len(res.comps), 2)

    def test_falls_back_to_vsp_when_no_path(self) -> None:
        # `fetch_vsp_chart` is imported lazily inside resolve_comps, so we
        # patch it at its source module rather than the import site.
        from anomaly_scout import vsp
        from anomaly_scout.vsp import VspChart

        chart = VspChart(
            chart_id="X99",
            star_name="RR LYR",
            target_ra_deg=291.366,
            target_dec_deg=42.785,
            comps=[
                CompStar(label="95", ra_deg=291.4, dec_deg=42.8,
                         catalog_mag=9.5, catalog_band="V"),
                CompStar(label="100", ra_deg=291.5, dec_deg=42.9,
                         catalog_mag=10.0, catalog_band="V"),
                CompStar(label="105", ra_deg=291.6, dec_deg=43.0,
                         catalog_mag=10.5, catalog_band="V"),
            ],
        )
        with patch.object(vsp, "fetch_vsp_chart", return_value=chart):
            res = resolve_comps(
                target_name="RR LYR", target_bright_mag=10.0,
                comp_path=None, chart_id_override="na",
            )
        self.assertEqual(res.source, "vsp")
        self.assertEqual(res.chart_id, "X99")
        self.assertEqual(len(res.comps), 3)
        self.assertEqual(res.chart_total, 3)

    def test_vsp_fallback_when_no_comps_in_range(self) -> None:
        from anomaly_scout import vsp
        from anomaly_scout.vsp import VspChart

        chart = VspChart(
            chart_id="X1",
            star_name="X",
            target_ra_deg=0.0,
            target_dec_deg=0.0,
            comps=[
                CompStar(label=str(13 + i), ra_deg=0, dec_deg=0,
                         catalog_mag=13 + i, catalog_band="V")
                for i in range(8)
            ],
        )
        with patch.object(vsp, "fetch_vsp_chart", return_value=chart):
            res = resolve_comps(
                target_name="X", target_bright_mag=10.0,
                comp_path=None, chart_id_override="na",
            )
        self.assertEqual(res.source, "vsp-fallback")
        self.assertEqual(len(res.comps), 6)


class PreflightFitsDirTests(TestCase):
    def test_returns_sorted_fits_files(self) -> None:
        with TemporaryDirectory() as tmp:
            target = Path(tmp)
            _make_fits(target / "b.fits")
            _make_fits(target / "a.fits")
            files = preflight_fits_dir(target)
        self.assertEqual([p.name for p in files], ["a.fits", "b.fits"])

    def test_raises_when_no_fits(self) -> None:
        with TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                preflight_fits_dir(Path(tmp))

    def test_raises_when_first_frame_missing_wcs(self) -> None:
        with TemporaryDirectory() as tmp:
            target = Path(tmp)
            _make_fits(target / "first.fits", with_wcs=False)
            _make_fits(target / "second.fits", with_wcs=True)
            with self.assertRaises(ValueError):
                preflight_fits_dir(target)


class FlagOutliersTests(TestCase):
    def _result(self, mags: list[float]) -> PhotometryRunResult:
        result = PhotometryRunResult()
        for i, mag in enumerate(mags):
            result.frames.append(FrameRecord(
                filename=f"f{i}.fits", magnitude=mag, magnitude_error=0.05,
                flag="pending",
            ))
        return result

    def test_flags_3sigma_outlier(self) -> None:
        # 9 frames with realistic photometric scatter (~0.02 mag) around
        # mag 7.5, plus one frame at 9.5 (well outside 3σ).
        mags = [7.49, 7.50, 7.51, 7.49, 7.52, 7.48, 7.50, 7.51, 7.49, 9.50]
        result = self._result(mags)
        flag_outliers(result)
        flags = [f.flag for f in result.frames]
        self.assertEqual(flags.count("outlier"), 1)
        self.assertEqual(result.frames[-1].flag, "outlier")
        self.assertEqual(flags.count("ok"), 9)

    def test_no_outlier_flagged_when_mad_is_zero(self) -> None:
        # When all values are exactly identical, MAD=0 means we can't
        # estimate sigma; everything stays 'ok' rather than incorrectly
        # flagging the lone different value via division-by-zero math.
        mags = [7.5] * 9 + [9.5]
        result = self._result(mags)
        flag_outliers(result)
        flags = [f.flag for f in result.frames]
        self.assertEqual(flags.count("outlier"), 0)
        self.assertEqual(flags.count("ok"), 10)

    def test_too_few_frames_marks_all_ok(self) -> None:
        mags = [7.5, 7.6, 7.4]  # only 3 frames
        result = self._result(mags)
        flag_outliers(result)
        self.assertTrue(all(f.flag == "ok" for f in result.frames))

    def test_skips_failed_frames(self) -> None:
        result = self._result([7.5, 7.6, 7.5, 7.4, 7.5, 7.55])
        result.frames.append(FrameRecord(filename="bad.fits", flag="failed"))
        flag_outliers(result)
        # The bad frame stays "failed", the rest become "ok"
        self.assertEqual(result.frames[-1].flag, "failed")
        self.assertTrue(all(f.flag == "ok" for f in result.frames[:-1]))


class RunPhotometryLoopTests(TestCase):
    def test_streams_frames_via_callback(self) -> None:
        with TemporaryDirectory() as tmp:
            target_dir = Path(tmp)
            _make_fits(target_dir / "a.fits")
            _make_fits(target_dir / "b.fits")
            from anomaly_scout.photometry import read_fits_with_wcs

            _, wcs, _ = read_fits_with_wcs(target_dir / "a.fits")
            target_sky = wcs.pixel_to_world(128, 128)
            comp_sky = wcs.pixel_to_world(158, 128)
            comps = [CompStar(label="100", ra_deg=comp_sky.ra.deg,
                              dec_deg=comp_sky.dec.deg, catalog_mag=10.0,
                              catalog_band="V")]
            files = preflight_fits_dir(target_dir)
            streamed: list[FrameRecord] = []
            result = run_photometry_loop(
                target_name="TEST",
                target_ra_deg=target_sky.ra.deg,
                target_dec_deg=target_sky.dec.deg,
                fits_files=files,
                comps=comps,
                chart_id="X1",
                on_frame=lambda f: streamed.append(f),
            )
        self.assertEqual(len(streamed), 2)
        self.assertEqual(len(result.observations), 2)
        # All frames started "pending" and were flagged "ok" (3-frame floor)
        # Only 2 frames here, so flag_outliers shouldn't run MAD logic;
        # we expect "ok" via the <5 frames branch.
        self.assertTrue(all(f.flag == "ok" for f in result.frames))
