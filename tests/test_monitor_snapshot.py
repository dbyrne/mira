"""Tests for the MonitorSnapshot aggregator.

A small FakeNinaClient stands in for the real one so these tests don't
need a running NINA. The point of these tests is to pin the
shape-and-resilience of the aggregator: every getter is wrapped so that
a missing/blank/exception-raising endpoint produces a sensible default
rather than crashing the /monitor page.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from mira.monitor.demo import demo_catalog, demo_snapshot
from mira.monitor.snapshot import (
    Anomaly,
    CameraState,
    FilterWheelState,
    FocuserState,
    FrameStat,
    GuiderState,
    MonitorSnapshot,
    MountState,
    SessionState,
    build_snapshot,
)


class FakeStatus:
    """Quack-types the NinaStatus returned by ``NinaClient.status()``."""

    def __init__(self, **kw) -> None:
        self.reachable = kw.get("reachable", True)
        self.error = kw.get("error", "")
        self.sequence_running = kw.get("sequence_running", True)
        self.current_target = kw.get("current_target", "")
        self.target_progress = kw.get("target_progress", "")
        self.last_image_hfr = kw.get("last_image_hfr", None)
        self.equipment = kw.get("equipment", {})
        self.raw_payloads = kw.get("raw_payloads", {})


class FakeNinaClient:
    """Minimal stub: each method returns whatever was passed at init time.

    Methods raise nothing — we want to verify the aggregator's degrade
    paths separately by setting individual returns to None or {} or
    raising a sentinel exception."""

    def __init__(
        self, *,
        status=None,
        mount_info=None,
        camera_info=None,
        filter_wheel_info=None,
        focuser_info=None,
        last_af=None,
        guider_info=None,
        image_history=None,
        raise_on=None,
    ) -> None:
        self._status = status if status is not None else FakeStatus()
        self._mount = mount_info if mount_info is not None else {}
        self._camera = camera_info if camera_info is not None else {}
        self._wheel = filter_wheel_info if filter_wheel_info is not None else {}
        self._focuser = focuser_info if focuser_info is not None else {}
        self._last_af = last_af if last_af is not None else {}
        self._guider = guider_info if guider_info is not None else {}
        self._history = image_history if image_history is not None else []
        self._raise_on = raise_on or set()

    def status(self):
        return self._status

    def mount_info(self):
        if "mount_info" in self._raise_on:
            raise RuntimeError("mount fake-raised")
        return dict(self._mount)

    def filter_wheel_info(self):
        if "filter_wheel_info" in self._raise_on:
            raise RuntimeError("wheel fake-raised")
        return dict(self._wheel)

    def focuser_info(self):
        if "focuser_info" in self._raise_on:
            raise RuntimeError("focuser fake-raised")
        return dict(self._focuser)

    def last_af(self):
        return dict(self._last_af)

    def guider_info(self):
        return dict(self._guider)

    def image_history(self, all_images: bool = True):
        return list(self._history)

    # Snapshot module's helpers fall back to ``client._get`` for the
    # camera endpoint and for any method we didn't add yet — wire it up.
    def _get(self, path, *args, **kwargs):
        if path == "/equipment/camera/info":
            return {"Response": dict(self._camera)}
        return {"Response": {}}


class BuildSnapshotTests(TestCase):
    def test_unreachable_nina_yields_stale_mode(self) -> None:
        client = FakeNinaClient(status=FakeStatus(
            reachable=False, error="no answer",
        ))
        snap = build_snapshot(client)
        self.assertFalse(snap.nina_reachable)
        self.assertEqual(snap.mode, "stale")
        self.assertIn("no answer", snap.nina_error)

    def test_partial_state_doesnt_crash(self) -> None:
        # Mount info present but missing every interesting field.
        # Everything else absent. Aggregator must not raise.
        client = FakeNinaClient(
            mount_info={"Connected": True},
            camera_info={"Connected": True, "CameraState": "Idle"},
        )
        snap = build_snapshot(client)
        self.assertTrue(snap.mount.connected)
        self.assertIsNone(snap.mount.ra_deg)
        self.assertEqual(snap.camera.state, "Idle")
        self.assertIsNone(snap.camera.temp_c)

    def test_raising_method_is_swallowed(self) -> None:
        # A getter that raises must not crash the aggregator.
        client = FakeNinaClient(raise_on={"mount_info"})
        snap = build_snapshot(client)
        self.assertFalse(snap.mount.connected)  # default

    def test_image_history_parsed_newest_first(self) -> None:
        # NINA gives oldest-first; aggregator returns newest-first.
        client = FakeNinaClient(image_history=[
            {"Filename": "f1.fit", "Filter": "Ha", "ExposureTime": 300,
             "HFR": 2.4, "Stars": 410, "Mean": 1340, "Median": 1330,
             "Date": "2026-05-26T03:00:00Z"},
            {"Filename": "f2.fit", "Filter": "Ha", "ExposureTime": 300,
             "HFR": 2.5, "Stars": 405, "Date": "2026-05-26T03:05:00Z"},
            {"Filename": "f3.fit", "Filter": "Ha", "ExposureTime": 300,
             "HFR": 2.6, "Stars": 400, "Date": "2026-05-26T03:10:00Z"},
        ])
        snap = build_snapshot(client)
        names = [f.filename for f in snap.recent_frames]
        self.assertEqual(names, ["f3.fit", "f2.fit", "f1.fit"])

    def test_image_history_skips_entries_without_filename(self) -> None:
        # The plugin occasionally emits placeholder entries during errors;
        # they have no Filename. Drop those silently.
        client = FakeNinaClient(image_history=[
            {"Filename": "real.fit", "ExposureTime": 300},
            {"HFR": 99},  # placeholder
            {"Filename": "", "ExposureTime": 300},  # blank
        ])
        snap = build_snapshot(client)
        self.assertEqual(len(snap.recent_frames), 1)
        self.assertEqual(snap.recent_frames[0].filename, "real.fit")

    def test_cooler_power_normalized(self) -> None:
        # Some drivers return 0-100, others 0-1. Aggregator normalizes
        # everything to 0-1.
        client = FakeNinaClient(camera_info={
            "Connected": True, "CoolerPower": 41.0,
        })
        snap = build_snapshot(client)
        self.assertAlmostEqual(snap.camera.cooler_power, 0.41, places=2)

        client_pct = FakeNinaClient(camera_info={
            "Connected": True, "CoolerPower": 0.41,
        })
        snap2 = build_snapshot(client_pct)
        self.assertAlmostEqual(snap2.camera.cooler_power, 0.41, places=2)

    def test_mount_ra_converted_from_hours_to_deg(self) -> None:
        # NINA gives RA in hours. Aggregator returns degrees so the UI
        # doesn't have to know the convention.
        client = FakeNinaClient(mount_info={
            "Connected": True, "RightAscension": 20.0, "Declination": 38.35,
        })
        snap = build_snapshot(client)
        self.assertAlmostEqual(snap.mount.ra_deg, 300.0, places=3)

    def test_selected_filter_nested_or_string(self) -> None:
        # Variant A: {"SelectedFilter": {"Name": "Ha"}}
        c1 = FakeNinaClient(filter_wheel_info={
            "Connected": True,
            "SelectedFilter": {"Name": "Ha"},
            "AvailableFilters": [{"Name": "L"}, {"Name": "Ha"}],
        })
        self.assertEqual(build_snapshot(c1).filter_wheel.selected_name, "Ha")

        # Variant B: {"SelectedFilter": "OIII"}
        c2 = FakeNinaClient(filter_wheel_info={
            "Connected": True, "SelectedFilter": "OIII",
        })
        self.assertEqual(build_snapshot(c2).filter_wheel.selected_name, "OIII")

        # Variant C: index-based — Position 1 in AvailableFilters
        c3 = FakeNinaClient(filter_wheel_info={
            "Connected": True, "Position": 1,
            "AvailableFilters": [{"Name": "L"}, {"Name": "R"}],
        })
        self.assertEqual(build_snapshot(c3).filter_wheel.selected_name, "R")

    def test_catalog_canonicalizes_target_name(self) -> None:
        # status.current_target arrives as "ngc 6888"; catalog normalizes.
        client = FakeNinaClient(status=FakeStatus(
            sequence_running=True, current_target="ngc 6888",
        ))
        catalog = demo_catalog()
        snap = build_snapshot(client, catalog=catalog)
        self.assertEqual(snap.session.current_target, "NGC 6888")
        self.assertEqual(snap.session.current_target_common, "Crescent Nebula")

    def test_ledger_view_aggregates_when_catalog_and_captures_root_set(self) -> None:
        # Synthesize a sidecar that books 60 min of Ha against NGC 6888.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = root / "ngc6888_20260601"
            session_dir.mkdir()
            import json as _json
            (session_dir / "mira_capture.json").write_text(_json.dumps({
                "target_name": "NGC 6888",
                "filter": "Ha",
                "exposure_s": 300.0,
                "gain": 100,
                "result": {"copied": 12, "started_utc": "2026-06-01T03:00:00+00:00",
                           "ended_utc": "2026-06-01T04:00:00+00:00"},
            }), encoding="utf-8")
            client = FakeNinaClient(status=FakeStatus(
                sequence_running=True, current_target="NGC 6888",
            ))
            snap = build_snapshot(
                client, catalog=demo_catalog(), captures_root=root,
            )
            self.assertIsNotNone(snap.ledger_view)
            ha_row = next(r for r in snap.ledger_view.per_filter if r[0] == "Ha")
            # 12 frames × 300s = 60 min
            self.assertAlmostEqual(ha_row[1], 60.0, places=2)
            self.assertEqual(ha_row[2], 600)

    def test_no_catalog_means_no_ledger_view(self) -> None:
        client = FakeNinaClient()
        snap = build_snapshot(client)
        self.assertIsNone(snap.ledger_view)


class DemoSnapshotTests(TestCase):
    def test_demo_snapshot_is_well_formed(self) -> None:
        snap = demo_snapshot()
        self.assertEqual(snap.mode, "demo")
        self.assertTrue(snap.nina_reachable)
        self.assertEqual(snap.session.current_target, "NGC 6888")
        self.assertEqual(snap.filter_wheel.selected_name, "Ha")
        self.assertGreater(len(snap.recent_frames), 0)
        # The demo should fire at least one anomaly so the console
        # actually demonstrates the alert path — what severity it lands
        # on can shift with threshold tuning; the existence of a badge
        # is the contract.
        self.assertGreater(
            len(snap.anomalies), 0,
            "demo should produce at least one anomaly so the badge styling renders",
        )
        self.assertTrue(
            any(a.severity in ("amber", "red") for a in snap.anomalies),
        )

    def test_demo_events_newest_first(self) -> None:
        snap = demo_snapshot()
        prev = None
        for evt in snap.recent_events:
            if prev is not None:
                self.assertGreaterEqual(prev, evt.timestamp_utc)
            prev = evt.timestamp_utc

    def test_demo_deterministic(self) -> None:
        # Same now → same frames, same anomalies. Reproducible screenshots.
        now = datetime(2026, 5, 26, 3, 0, tzinfo=timezone.utc)
        a = demo_snapshot(now_utc=now)
        b = demo_snapshot(now_utc=now)
        self.assertEqual(
            [f.filename for f in a.recent_frames],
            [f.filename for f in b.recent_frames],
        )
        self.assertEqual(
            [(an.section, an.message) for an in a.anomalies],
            [(an.section, an.message) for an in b.anomalies],
        )
