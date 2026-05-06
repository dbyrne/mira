from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from anomaly_scout.webapp.db import SessionStore, from_run_record


class SessionStoreTests(TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "sessions.db"
        self.store = SessionStore(self.db_path)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_init_creates_db_file(self) -> None:
        self.assertTrue(self.db_path.exists())

    def test_upsert_and_list(self) -> None:
        self.store.upsert_session(
            run_id="r1",
            target_name="RR LYR",
            target_slug="RR_LYR",
            session_date="2026-05-06",
            observer_code="ABC",
            chart_id="X1",
            observation_count=20,
            median_mag=7.65,
            anomaly_level="info",
            submitted_at=None,
            created_at="2026-05-06T22:00:00+00:00",
            observations=[
                {"filename": "f1.fits", "julian_date": 2461165.5, "magnitude": 7.6,
                 "magnitude_error": 0.05, "band": "TG", "comp_star_label": "97",
                 "comp_star_mag": 9.7, "flag": "ok"},
                {"filename": "f2.fits", "julian_date": 2461165.55, "magnitude": 7.7,
                 "magnitude_error": 0.05, "band": "TG", "comp_star_label": "97",
                 "comp_star_mag": 9.7, "flag": "ok"},
            ],
        )
        sessions = self.store.list_sessions()
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["target_slug"], "RR_LYR")
        self.assertEqual(sessions[0]["observation_count"], 20)
        observations = self.store.get_observations("RR_LYR")
        self.assertEqual(len(observations), 2)

    def test_upsert_replaces_observations(self) -> None:
        common = {
            "target_name": "RR LYR",
            "target_slug": "RR_LYR",
            "session_date": "2026-05-06",
            "observer_code": "ABC",
            "chart_id": "X1",
            "anomaly_level": "info",
            "submitted_at": None,
            "created_at": "2026-05-06T22:00:00+00:00",
        }
        # First write: 3 observations
        self.store.upsert_session(
            run_id="r1", observation_count=3, median_mag=7.6, **common,
            observations=[{"filename": f"f{i}.fits", "julian_date": 2461000.0 + i,
                          "magnitude": 7.5 + i * 0.01, "magnitude_error": 0.05,
                          "band": "TG", "comp_star_label": "97", "comp_star_mag": 9.7,
                          "flag": "ok"} for i in range(3)],
        )
        self.assertEqual(len(self.store.get_observations("RR_LYR")), 3)
        # Re-upsert with 1 observation: rows replaced not appended
        self.store.upsert_session(
            run_id="r1", observation_count=1, median_mag=7.55, **common,
            observations=[{"filename": "f0.fits", "julian_date": 2461000.0,
                          "magnitude": 7.55, "magnitude_error": 0.05,
                          "band": "TG", "comp_star_label": "97", "comp_star_mag": 9.7,
                          "flag": "ok"}],
        )
        observations = self.store.get_observations("RR_LYR")
        self.assertEqual(len(observations), 1)
        sessions = self.store.list_sessions()
        self.assertEqual(len(sessions), 1)  # not duplicated
        self.assertEqual(sessions[0]["observation_count"], 1)

    def test_filter_by_target_and_anomaly(self) -> None:
        common = {
            "observer_code": "ABC", "chart_id": "X1", "submitted_at": None,
            "created_at": "2026-05-06T22:00:00+00:00", "observations": [],
        }
        self.store.upsert_session(run_id="a", target_name="RR LYR", target_slug="RR_LYR",
                                  session_date="2026-05-06", observation_count=10,
                                  median_mag=7.6, anomaly_level="info", **common)
        self.store.upsert_session(run_id="b", target_name="AB AUR", target_slug="AB_AUR",
                                  session_date="2026-05-07", observation_count=12,
                                  median_mag=9.5, anomaly_level="anomaly", **common)
        all_sessions = self.store.list_sessions()
        self.assertEqual(len(all_sessions), 2)
        # Anomaly only
        anomalies = self.store.list_sessions(anomaly_only=True)
        self.assertEqual(len(anomalies), 1)
        self.assertEqual(anomalies[0]["target_slug"], "AB_AUR")
        # By target
        rr = self.store.list_sessions(target_slug="RR_LYR")
        self.assertEqual(len(rr), 1)
        self.assertEqual(rr[0]["run_id"], "a")

    def test_upsert_update_path_returns_correct_session_id(self) -> None:
        """Regression: cur.lastrowid is unreliable on the ON CONFLICT
        UPDATE path of sqlite3 — the post-Y fix re-resolves session_id
        from run_id every time. If the resolution is wrong, observations
        are written with session_id=0 (orphaned). Verify both INSERT
        and UPDATE attach observations to the same session row."""
        common = {
            "target_name": "RR LYR", "target_slug": "RR_LYR",
            "session_date": "2026-05-06", "observer_code": "ABC", "chart_id": "X1",
            "anomaly_level": "info", "submitted_at": None,
            "created_at": "2026-05-06T22:00:00+00:00",
        }
        # First write: 2 observations
        self.store.upsert_session(
            run_id="r1", observation_count=2, median_mag=7.6, **common,
            observations=[
                {"filename": "f1.fits", "julian_date": 2461165.5, "magnitude": 7.6,
                 "magnitude_error": 0.05, "band": "TG", "comp_star_label": "97",
                 "comp_star_mag": 9.7, "flag": "ok"},
                {"filename": "f2.fits", "julian_date": 2461165.6, "magnitude": 7.65,
                 "magnitude_error": 0.05, "band": "TG", "comp_star_label": "97",
                 "comp_star_mag": 9.7, "flag": "ok"},
            ],
        )
        first_obs = self.store.get_observations("RR_LYR")
        self.assertEqual(len(first_obs), 2)
        # All observations must reference an actual sessions row, not session_id=0.
        sessions = self.store.list_sessions()
        self.assertEqual(len(sessions), 1)
        # Re-upsert with different observations (UPDATE path).
        self.store.upsert_session(
            run_id="r1", observation_count=3, median_mag=7.7, **common,
            observations=[
                {"filename": f"updated{i}.fits", "julian_date": 2461165.5 + i*0.01,
                 "magnitude": 7.7, "magnitude_error": 0.05, "band": "TG",
                 "comp_star_label": "97", "comp_star_mag": 9.7, "flag": "ok"}
                for i in range(3)
            ],
        )
        # Sessions table still has exactly 1 row (UPDATE not INSERT).
        sessions = self.store.list_sessions()
        self.assertEqual(len(sessions), 1)
        # New observations attached, old observations replaced (not appended).
        new_obs = self.store.get_observations("RR_LYR")
        self.assertEqual(len(new_obs), 3)
        self.assertTrue(all("updated" in o["filename"] for o in new_obs))

    def test_mark_submitted(self) -> None:
        self.store.upsert_session(
            run_id="r1", target_name="RR LYR", target_slug="RR_LYR",
            session_date="2026-05-06", observer_code="ABC", chart_id="X1",
            observation_count=10, median_mag=7.6, anomaly_level=None,
            submitted_at=None, created_at="2026-05-06T22:00:00+00:00",
            observations=[],
        )
        self.store.mark_submitted("r1", "2026-05-07T10:00:00+00:00")
        session = self.store.list_sessions()[0]
        self.assertEqual(session["submitted_at"], "2026-05-07T10:00:00+00:00")


class FromRunRecordTests(TestCase):
    def test_extracts_kwargs_from_full_record(self) -> None:
        record = {
            "run_id": "abc",
            "kind": "submit:RR_LYR:2026-05-06",
            "status": "done",
            "created_at": "2026-05-06T22:00:00+00:00",
            "result": {
                "target_name": "RR LYR",
                "target_slug": "RR_LYR",
                "session_date": "2026-05-06",
                "observer_code": "ABC",
                "chart_id": "X1",
                "observation_count": 12,
                "median_mag": 7.6,
                "anomaly": {"level": "info"},
                "submitted_at": None,
                "observations": [{"filename": "f.fits", "magnitude": 7.6}],
            },
        }
        kwargs = from_run_record(record)
        self.assertIsNotNone(kwargs)
        self.assertEqual(kwargs["run_id"], "abc")
        self.assertEqual(kwargs["target_slug"], "RR_LYR")
        self.assertEqual(kwargs["session_date"], "2026-05-06")
        self.assertEqual(kwargs["anomaly_level"], "info")
        self.assertEqual(len(kwargs["observations"]), 1)

    def test_skips_non_submit_runs(self) -> None:
        self.assertIsNone(from_run_record({"kind": "tonight", "status": "done"}))

    def test_skips_unfinished_runs(self) -> None:
        self.assertIsNone(from_run_record({"kind": "submit:RR_LYR", "status": "running"}))

    def test_recovers_slug_from_kind_when_missing(self) -> None:
        record = {
            "run_id": "old",
            "kind": "submit:RR_LYR",
            "status": "done",
            "created_at": "2026-05-06T22:00:00+00:00",
            "result": {"observation_count": 5},
        }
        kwargs = from_run_record(record)
        self.assertEqual(kwargs["target_slug"], "RR_LYR")
