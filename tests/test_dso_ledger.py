"""Tests for the DSO integration ledger.

Strategy: synthesize mira_capture.json sidecars in a temp dir and walk
them, asserting the aggregation matches what the sidecars said. No real
FITS, no NINA, no network.
"""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from mira.dso.catalog import DsoCatalog, DsoTarget
from mira.dso.ledger import (
    Ledger,
    SessionRecord,
    aggregate_ledger,
    target_completion_fraction,
    target_deficit,
    walk_sidecars,
)


def _write_sidecar(
    dir_path: Path,
    *,
    target_name: str = "NGC 6888",
    filter_name: str | None = "Ha",
    gain: int | None = 100,
    exposure_s: float = 300.0,
    copied: int | None = 60,
    include_result: bool = True,
    started_utc: str | None = "2026-08-15T03:00:00+00:00",
    ended_utc: str | None = "2026-08-15T08:00:00+00:00",
    extra: dict | None = None,
) -> Path:
    """Synthesize one capture session dir with a mira_capture.json sidecar.

    Mirrors the actual shape from `capture.py` — filter/gain/exposure_s at
    top level, plus a `result` block when include_result=True. Drop
    include_result=False to exercise the no-result-block fallback path."""
    dir_path.mkdir(parents=True, exist_ok=True)
    sidecar: dict = {
        "filter": filter_name,
        "gain": gain,
        "exposure_s": exposure_s,
        "target_name": target_name,
    }
    if include_result:
        result: dict = {
            "started_utc": started_utc,
            "ended_utc": ended_utc,
            "stopped_reason": "n_max_reached",
        }
        if copied is not None:
            result["copied"] = copied
        sidecar["result"] = result
    if extra:
        sidecar.update(extra)
    (dir_path / "mira_capture.json").write_text(
        json.dumps(sidecar, indent=2), encoding="utf-8"
    )
    return dir_path


def _make_catalog(*targets: DsoTarget) -> DsoCatalog:
    return DsoCatalog(version="t", defaults={}, targets=tuple(targets))


def _crescent() -> DsoTarget:
    return DsoTarget(
        name="NGC 6888", common_name="Crescent Nebula",
        object_type="WR", ra_deg=303.025, dec_deg=38.35,
        size_arcmin=(18, 13), constellation="Cyg",
        budget_minutes={"Ha": 600, "OIII": 900, "SII": 540},
    )


def _m27() -> DsoTarget:
    return DsoTarget(
        name="M27", common_name="Dumbbell Nebula",
        object_type="PN", ra_deg=299.9, dec_deg=22.72,
        size_arcmin=(8, 6), constellation="Vul",
        budget_minutes={"Ha": 360, "OIII": 540, "SII": 240},
    )


class WalkSidecarsTests(TestCase):
    def test_empty_root_returns_empty_list(self) -> None:
        with TemporaryDirectory() as tmp:
            self.assertEqual(walk_sidecars(Path(tmp)), [])

    def test_nonexistent_root_returns_empty_list(self) -> None:
        # Don't raise on a missing captures dir — fresh installs won't
        # have one yet; `mira dso plan` should still work.
        self.assertEqual(walk_sidecars(Path("/nonexistent/path/xyz")), [])

    def test_single_session_parsed(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_sidecar(root / "ngc6888_20260815", copied=60)
            sessions = walk_sidecars(root)
            self.assertEqual(len(sessions), 1)
            s = sessions[0]
            self.assertEqual(s.target_name, "NGC 6888")
            self.assertEqual(s.filter_name, "Ha")
            self.assertEqual(s.frames_copied, 60)
            self.assertEqual(s.integration_minutes, 60 * 300 / 60)
            self.assertEqual(s.frame_count_source, "result.copied")

    def test_nested_sessions_and_underscore_dirs_skipped(self) -> None:
        """New scheme: sessions nest as <target>/<rig>_<filter>_<date>/.
        The recursive walk finds them; underscore-prefixed derived/non-target
        dirs (_combined_*, _calibration, _rejected) are skipped so a co-stack's
        hardlinks don't double-count their already-counted source sessions."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_sidecar(root / "ngc6888" / "s30_lp_20260530",
                           filter_name="LP", copied=200)
            _write_sidecar(root / "ngc6888" / "esprit80_ha_20260615",
                           filter_name="Ha", copied=36)
            _write_sidecar(root / "ngc6888" / "_combined_s30_lp",
                           filter_name="LP", copied=278)            # skip
            _write_sidecar(root / "_calibration" / "bias_g80",
                           filter_name="LP", copied=25)             # skip
            _write_sidecar(root / "ngc6888" / "s30_lp_20260530" / "_rejected",
                           filter_name="LP", copied=9)              # skip
            sessions = walk_sidecars(root)
            names = sorted(s.sidecar_path.parent.name for s in sessions)
            self.assertEqual(names, ["esprit80_ha_20260615", "s30_lp_20260530"])

    def test_multiple_sessions_walked(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_sidecar(root / "a", target_name="NGC 6888", filter_name="Ha", copied=60)
            _write_sidecar(root / "b", target_name="NGC 6888", filter_name="OIII", copied=36)
            _write_sidecar(root / "c", target_name="M27", filter_name="Ha", copied=80, exposure_s=180.0)
            sessions = walk_sidecars(root)
            self.assertEqual(len(sessions), 3)

    def test_non_dso_capture_skipped(self) -> None:
        # filter is None (variable-star capture) — NOT a DSO ledger entry.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_sidecar(root / "rrlyr", target_name="RR Lyr", filter_name=None)
            self.assertEqual(walk_sidecars(root), [])

    def test_empty_filter_skipped(self) -> None:
        # filter is empty string — same as None.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_sidecar(root / "x", filter_name="")
            self.assertEqual(walk_sidecars(root), [])

    def test_malformed_json_skipped_silently(self) -> None:
        # One bad sidecar can't tank the rest. Best-effort.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bad").mkdir()
            (root / "bad" / "mira_capture.json").write_text("not json {", encoding="utf-8")
            _write_sidecar(root / "good")
            sessions = walk_sidecars(root)
            self.assertEqual(len(sessions), 1)
            self.assertEqual(sessions[0].target_name, "NGC 6888")

    def test_missing_exposure_skipped(self) -> None:
        # Without exposure_s the integration time would be 0 — better to
        # skip than book a misleading "session" with no contribution.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_sidecar(root / "x", exposure_s=0.0)
            self.assertEqual(walk_sidecars(root), [])

    def test_missing_target_name_skipped(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_sidecar(root / "x", target_name="")
            self.assertEqual(walk_sidecars(root), [])


class FrameCountFallbackTests(TestCase):
    def test_no_result_block_falls_back_to_glob(self) -> None:
        # Capture killed before shutdown wrote the result block. Frames are
        # still on disk — fallback path counts the .fit* files in the dir.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            dir_a = root / "interrupted"
            _write_sidecar(dir_a, include_result=False)
            # Drop three pretend FITS files in the dir.
            for i in range(3):
                (dir_a / f"frame_{i}.fits").write_bytes(b"")
            sessions = walk_sidecars(root)
            self.assertEqual(len(sessions), 1)
            self.assertEqual(sessions[0].frames_copied, 3)
            self.assertEqual(sessions[0].frame_count_source, "globbed")

    def test_no_result_no_files_returns_zero(self) -> None:
        # Worst case: sidecar with no result block AND no FITS files. Don't
        # raise; record zero so the session is preserved in the ledger but
        # contributes no minutes.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_sidecar(root / "x", include_result=False)
            sessions = walk_sidecars(root)
            self.assertEqual(len(sessions), 1)
            self.assertEqual(sessions[0].frames_copied, 0)
            self.assertEqual(sessions[0].frame_count_source, "fallback_zero")

    def test_result_with_missing_copied_falls_back(self) -> None:
        # Result block present but no 'copied' key (malformed/old format).
        # Should still try the glob fallback.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            dir_a = root / "weird"
            _write_sidecar(dir_a, copied=None)
            (dir_a / "f.fit").write_bytes(b"")
            sessions = walk_sidecars(root)
            self.assertEqual(sessions[0].frames_copied, 1)
            self.assertEqual(sessions[0].frame_count_source, "globbed")


class AggregateLedgerTests(TestCase):
    def test_aggregation_sums_same_filter_sessions(self) -> None:
        s1 = SessionRecord(
            sidecar_path=Path("a"), target_name="NGC 6888", filter_name="Ha",
            gain=100, exposure_s=300, frames_copied=60,
            started_utc=None, ended_utc=None, stopped_reason="",
            frame_count_source="result.copied",
        )
        s2 = SessionRecord(
            sidecar_path=Path("b"), target_name="NGC 6888", filter_name="Ha",
            gain=100, exposure_s=300, frames_copied=40,
            started_utc=None, ended_utc=None, stopped_reason="",
            frame_count_source="result.copied",
        )
        catalog = _make_catalog(_crescent())
        ledger = aggregate_ledger([s1, s2], catalog=catalog)
        total = ledger.get("NGC 6888", "Ha")
        self.assertIsNotNone(total)
        self.assertEqual(total.session_count, 2)
        self.assertEqual(total.total_minutes, (60 + 40) * 300 / 60)

    def test_orphan_target_not_in_catalog_bucketed(self) -> None:
        s = SessionRecord(
            sidecar_path=Path("x"), target_name="PHANTOM_TARGET",
            filter_name="Ha", gain=100, exposure_s=300, frames_copied=10,
            started_utc=None, ended_utc=None, stopped_reason="",
            frame_count_source="result.copied",
        )
        catalog = _make_catalog(_crescent())
        ledger = aggregate_ledger([s], catalog=catalog)
        self.assertEqual(ledger.orphan_target_names, ("PHANTOM_TARGET",))
        self.assertEqual(ledger.by_target, {})

    def test_canonical_name_match_no_alias_fallback(self) -> None:
        # Per user decision: canonical names only. A capture session that
        # used the common name "Crescent" doesn't match — it's an orphan.
        s = SessionRecord(
            sidecar_path=Path("x"), target_name="Crescent",
            filter_name="Ha", gain=100, exposure_s=300, frames_copied=10,
            started_utc=None, ended_utc=None, stopped_reason="",
            frame_count_source="result.copied",
        )
        catalog = _make_catalog(_crescent())
        ledger = aggregate_ledger([s], catalog=catalog)
        self.assertIn("Crescent", ledger.orphan_target_names)

    def test_no_catalog_passthrough(self) -> None:
        # When catalog=None, targets aren't normalized — common-name or
        # typoed sessions still appear in by_target keyed by their raw name.
        s = SessionRecord(
            sidecar_path=Path("x"), target_name="Crescent",
            filter_name="Ha", gain=100, exposure_s=300, frames_copied=10,
            started_utc=None, ended_utc=None, stopped_reason="",
            frame_count_source="result.copied",
        )
        ledger = aggregate_ledger([s], catalog=None)
        self.assertIn("Crescent", ledger.by_target)
        self.assertEqual(ledger.orphan_target_names, ())

    def test_minutes_helper_zero_for_missing(self) -> None:
        ledger = aggregate_ledger([], catalog=_make_catalog(_crescent()))
        self.assertEqual(ledger.minutes("NGC 6888", "Ha"), 0.0)
        self.assertEqual(ledger.minutes("Nonexistent", "Ha"), 0.0)

    def test_last_capture_picks_latest(self) -> None:
        s1 = SessionRecord(
            sidecar_path=Path("a"), target_name="NGC 6888", filter_name="Ha",
            gain=100, exposure_s=300, frames_copied=60,
            started_utc=None, ended_utc=_iso("2026-08-15T08:00:00+00:00"),
            stopped_reason="", frame_count_source="result.copied",
        )
        s2 = SessionRecord(
            sidecar_path=Path("b"), target_name="NGC 6888", filter_name="Ha",
            gain=100, exposure_s=300, frames_copied=40,
            started_utc=None, ended_utc=_iso("2026-08-22T08:00:00+00:00"),
            stopped_reason="", frame_count_source="result.copied",
        )
        ledger = aggregate_ledger([s1, s2], catalog=_make_catalog(_crescent()))
        last = ledger.get("NGC 6888", "Ha").last_capture
        self.assertEqual(last, _iso("2026-08-22T08:00:00+00:00"))


def _iso(s: str):
    from datetime import datetime
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


class TargetDeficitTests(TestCase):
    def _ledger_for(self, **filter_minutes) -> Ledger:
        """Build a ledger with NGC 6888 having the given per-filter
        captured minutes (one synthetic session per filter)."""
        sessions: list[SessionRecord] = []
        for filter_name, minutes in filter_minutes.items():
            sessions.append(SessionRecord(
                sidecar_path=Path(f"{filter_name}"), target_name="NGC 6888",
                filter_name=filter_name, gain=100, exposure_s=60.0,
                frames_copied=int(minutes),  # exposure 60s → minutes==frames
                started_utc=None, ended_utc=None, stopped_reason="",
                frame_count_source="result.copied",
            ))
        return aggregate_ledger(sessions, catalog=_make_catalog(_crescent()))

    def test_full_deficit_for_never_imaged_target(self) -> None:
        ledger = self._ledger_for()  # empty
        deficit = target_deficit(ledger, _crescent())
        self.assertEqual(deficit["Ha"], 600)
        self.assertEqual(deficit["OIII"], 900)
        self.assertEqual(deficit["SII"], 540)

    def test_partial_deficit(self) -> None:
        ledger = self._ledger_for(Ha=300, OIII=180)
        deficit = target_deficit(ledger, _crescent())
        self.assertEqual(deficit["Ha"], 300)
        self.assertEqual(deficit["OIII"], 720)
        self.assertEqual(deficit["SII"], 540)

    def test_zero_deficit_at_budget(self) -> None:
        ledger = self._ledger_for(Ha=600, OIII=900, SII=540)
        deficit = target_deficit(ledger, _crescent())
        self.assertEqual(deficit["Ha"], 0)
        self.assertEqual(deficit["OIII"], 0)
        self.assertEqual(deficit["SII"], 0)

    def test_zero_deficit_when_over_budget(self) -> None:
        # Imaging past budget doesn't bank negative deficit (which would
        # incorrectly let other filters appear in surplus).
        ledger = self._ledger_for(Ha=1200)
        deficit = target_deficit(ledger, _crescent())
        self.assertEqual(deficit["Ha"], 0)
        self.assertEqual(deficit["OIII"], 900)

    def test_completion_fraction_caps_per_filter(self) -> None:
        # Over-imaging Ha shouldn't drag completion up to "done" while
        # OIII and SII are still empty. Per-filter cap.
        ledger = self._ledger_for(Ha=1200)  # 2x Ha budget, others empty
        frac = target_completion_fraction(ledger, _crescent())
        # Capped contribution: min(1200, 600) = 600 out of 2040 total
        expected = 600 / 2040
        self.assertAlmostEqual(frac, expected, places=4)

    def test_completion_fraction_full_when_all_at_budget(self) -> None:
        ledger = self._ledger_for(Ha=600, OIII=900, SII=540)
        self.assertAlmostEqual(
            target_completion_fraction(ledger, _crescent()),
            1.0, places=4,
        )

    def test_completion_fraction_zero_for_empty_ledger(self) -> None:
        ledger = self._ledger_for()
        self.assertEqual(
            target_completion_fraction(ledger, _crescent()),
            0.0,
        )


class EndToEndWalkTests(TestCase):
    def test_walk_and_aggregate_three_sessions(self) -> None:
        """End-to-end: lay down three real sidecars in temp dirs, walk,
        aggregate against a catalog, assert minute counts match."""
        catalog = _make_catalog(_crescent(), _m27())
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_sidecar(root / "ngc6888_20260815",
                           target_name="NGC 6888", filter_name="Ha", copied=60)
            _write_sidecar(root / "ngc6888_20260817",
                           target_name="NGC 6888", filter_name="OIII", copied=36)
            _write_sidecar(root / "m27_20260815",
                           target_name="M27", filter_name="Ha",
                           copied=80, exposure_s=180.0)
            ledger = aggregate_ledger(walk_sidecars(root), catalog=catalog)
            self.assertEqual(ledger.minutes("NGC 6888", "Ha"), 60 * 300 / 60)
            self.assertEqual(ledger.minutes("NGC 6888", "OIII"), 36 * 300 / 60)
            self.assertEqual(ledger.minutes("M27", "Ha"), 80 * 180 / 60)
            self.assertEqual(ledger.orphan_target_names, ())
