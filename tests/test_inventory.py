"""Tests for the capture-data inventory (`mira inventory`)."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from astropy.io import fits

from mira.inventory import (
    SessionInventory,
    build_inventory,
    infer_rig,
    inventory_session,
    split_dirname,
    target_slug,
    write_inventory,
)


def _write_fits(path: Path, *, solved: bool = False, exptime: float | None = 60.0,
                date_obs: str | None = "2026-06-01T03:00:00") -> None:
    hdu = fits.PrimaryHDU(np.zeros((4, 4), dtype=np.uint16))
    if exptime is not None:
        hdu.header["EXPTIME"] = exptime
    if date_obs is not None:
        hdu.header["DATE-OBS"] = date_obs
    if solved:
        hdu.header["CRVAL1"] = 303.0
        hdu.header["CRVAL2"] = 38.35
    hdu.writeto(path, overwrite=True)


class HelperTests(unittest.TestCase):
    def test_infer_rig_known_dims_both_orientations(self):
        self.assertEqual(infer_rig(3840, 2160), "S30 Pro")
        self.assertEqual(infer_rig(2160, 3840), "S30 Pro")
        self.assertEqual(infer_rig(6248, 4176), "ASI2600MM (Esprit 80/120)")

    def test_infer_rig_unknown_is_honest(self):
        self.assertEqual(infer_rig(4, 4), "?")
        self.assertEqual(infer_rig(None, None), "?")

    def test_split_dirname(self):
        self.assertEqual(split_dirname("m51_20260517"), ("m51", "20260517"))
        self.assertEqual(split_dirname("veil_p1_west"), ("veil_p1_west", ""))
        self.assertEqual(split_dirname("bias_g80"), ("bias_g80", ""))

    def test_target_slug_matches_processed_convention(self):
        self.assertEqual(target_slug("NGC 6888"), "ngc6888")
        self.assertEqual(target_slug("M51"), "m51")
        self.assertEqual(target_slug("v_cvn"), "v_cvn")


class InventorySessionTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.captures = self.root / "captures"
        self.processed = self.root / "processed"
        self.captures.mkdir()
        self.processed.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _session(self, name: str) -> Path:
        d = self.captures / name
        d.mkdir()
        return d

    def test_sidecar_session_full_facts(self):
        d = self._session("ngc6888_20260601")
        (d / "mira_capture.json").write_text(json.dumps({
            "target_name": "NGC 6888", "filter": "LP", "gain": 80,
            "exposure_s": 60.0, "result": {"copied": 2},
        }), encoding="utf-8")
        _write_fits(d / "a.fits", solved=True)
        _write_fits(d / "b.fits", solved=False)
        rej = d / "_rejected"; rej.mkdir()
        _write_fits(rej / "bad.fits")
        (self.processed / "ngc6888").mkdir()

        s = inventory_session(d, self.processed)
        self.assertTrue(s.has_sidecar)
        self.assertEqual(s.target, "NGC 6888")
        self.assertEqual(s.filter_name, "LP")
        self.assertEqual(s.gain, 80)
        self.assertEqual(s.exposure_s, 60.0)
        self.assertEqual(s.frames, 2)
        self.assertEqual(s.rejected, 1)
        self.assertEqual(s.solved, 1)
        self.assertEqual(s.date, "20260601")
        self.assertEqual(s.total_minutes, 2.0)
        self.assertTrue(s.processed.endswith("ngc6888"))

    def test_legacy_dir_recovers_from_fits_and_dirname(self):
        d = self._session("m101_20260601")
        _write_fits(d / "a.fits", exptime=120.0)
        s = inventory_session(d, self.processed)
        self.assertFalse(s.has_sidecar)
        self.assertEqual(s.target, "m101")          # dirname stem
        self.assertEqual(s.filter_name, "?")        # never guessed
        self.assertIsNone(s.gain)
        self.assertEqual(s.exposure_s, 120.0)       # FITS EXPTIME fallback
        self.assertEqual(s.date, "20260601")
        self.assertEqual(s.processed, "")           # no processed dir

    def test_legacy_dir_date_falls_back_to_date_obs(self):
        d = self._session("randomname")
        _write_fits(d / "a.fits", date_obs="2026-05-17T04:00:00")
        s = inventory_session(d, self.processed)
        self.assertEqual(s.date, "20260517")

    def test_empty_dir_is_zeroed_not_fatal(self):
        d = self._session("empty_20260101")
        s = inventory_session(d, self.processed)
        self.assertEqual(s.frames, 0)
        self.assertEqual(s.total_minutes, 0.0)
        self.assertIsNone(s.exposure_s)

    def test_corrupt_fits_counts_as_frame_only(self):
        d = self._session("corrupt_20260101")
        (d / "broken.fits").write_bytes(b"not a fits file")
        s = inventory_session(d, self.processed)
        self.assertEqual(s.frames, 1)
        self.assertEqual(s.solved, 0)
        self.assertIsNone(s.exposure_s)

    def test_unstatable_file_skipped_in_size_sum(self):
        # One dangling symlink / locked temp (Syncthing mid-transfer) in a
        # session dir must not abort the whole inventory run — the per-file
        # stat is guarded and the bad file simply contributes no bytes.
        d = self._session("locked_20260101")
        _write_fits(d / "a.fits")
        (d / "locked.tmp").write_bytes(b"x" * 64)
        real_stat = Path.stat

        def fake_stat(path_self, *args, **kwargs):
            if path_self.name == "locked.tmp":
                raise OSError("file is locked by another process")
            return real_stat(path_self, *args, **kwargs)

        with mock.patch.object(Path, "stat", fake_stat):
            s = inventory_session(d, self.processed)
        self.assertEqual(s.frames, 1)
        # Size still counted for the healthy file (a 4x4 FITS > 0 bytes,
        # though it rounds to 0.0 GB) — the point is no exception escaped.
        self.assertGreaterEqual(s.size_gb, 0.0)

    def test_build_inventory_walks_dirs_sorted(self):
        for name in ("b_20260102", "a_20260101"):
            d = self._session(name)
            _write_fits(d / "x.fits")
        inv = build_inventory(self.captures, self.processed)
        self.assertEqual([s.dir_name for s in inv], ["a_20260101", "b_20260102"])

    def test_build_inventory_missing_root_returns_empty(self):
        self.assertEqual(build_inventory(self.root / "nope", self.processed), [])

    def test_write_inventory_emits_md_and_csv(self):
        d = self._session("m51_20260517")
        _write_fits(d / "a.fits")
        inv = build_inventory(self.captures, self.processed)
        out = self.root / "out"
        md, csv_path = write_inventory(inv, out, self.captures)
        self.assertTrue(md.is_file())
        self.assertTrue(csv_path.is_file())
        text = md.read_text(encoding="utf-8")
        self.assertIn("m51_20260517", text)
        self.assertIn("without a sidecar", text)     # legacy section present
        self.assertIn("no processed/ output", text)  # unprocessed section
        header = csv_path.read_text(encoding="utf-8").splitlines()[0]
        self.assertIn("total_minutes", header)


if __name__ == "__main__":
    unittest.main()
