"""Tests for the dress-rehearsal helpers. We exercise synthesize_frames
directly with hand-crafted comps; run_rehearsal hits the network so we
don't drive it end-to-end here (the real CLI invocation does)."""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from anomaly_scout.photometry import CompStar, read_fits_with_wcs
from anomaly_scout.rehearsal import synthesize_frames


class SynthesizeFramesTests(TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_writes_requested_number_of_frames(self) -> None:
        comps = [
            CompStar(label="100", ra_deg=180.001, dec_deg=0.001,
                     catalog_mag=10.0, catalog_band="V"),
        ]
        paths = synthesize_frames(
            target_ra_deg=180.0, target_dec_deg=0.0, target_mag=11.0,
            comps=comps, output_dir=self.dir, n_frames=5,
        )
        self.assertEqual(len(paths), 5)
        for p in paths:
            self.assertTrue(p.exists())

    def test_each_frame_has_jd_and_wcs(self) -> None:
        comps = [
            CompStar(label="100", ra_deg=180.005, dec_deg=0.005,
                     catalog_mag=10.0, catalog_band="V"),
        ]
        paths = synthesize_frames(
            target_ra_deg=180.0, target_dec_deg=0.0, target_mag=11.0,
            comps=comps, output_dir=self.dir, n_frames=3,
            frame_cadence_seconds=60.0, start_jd=2461165.5,
        )
        jds = []
        for p in paths:
            image, wcs, header = read_fits_with_wcs(p)
            self.assertTrue(wcs.has_celestial)
            self.assertGreaterEqual(image.shape[0], 100)
            self.assertIn("JD", header)
            jds.append(float(header["JD"]))
        # JDs should increase monotonically
        self.assertEqual(jds, sorted(jds))
        self.assertNotEqual(jds[0], jds[-1])

    def test_offframe_comps_are_skipped(self) -> None:
        # A comp 5° away from a 512×512 image at 2"/pix scale is way
        # outside the frame; synthesize_frames should silently skip it.
        far_comp = CompStar(label="far", ra_deg=185.0, dec_deg=0.0,
                            catalog_mag=10.0, catalog_band="V")
        in_comp = CompStar(label="100", ra_deg=180.005, dec_deg=0.005,
                           catalog_mag=10.0, catalog_band="V")
        # Should not raise; should still produce frames
        paths = synthesize_frames(
            target_ra_deg=180.0, target_dec_deg=0.0, target_mag=11.0,
            comps=[far_comp, in_comp], output_dir=self.dir, n_frames=2,
        )
        self.assertEqual(len(paths), 2)
