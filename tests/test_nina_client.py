"""Tests for the NINA client — route prefix, slew unit contract, and the
read-back safety logic in preposition(). No NINA is contacted; requests
is mocked. The point of these tests is that a regression which sends a
telescope to the wrong place fails CI, not the sky."""
from __future__ import annotations

from unittest import TestCase
from unittest.mock import MagicMock, patch

from mira.webapp.nina_client import (
    NinaClient,
    SlewResult,
    angular_separation_deg,
)


def _resp(json_body, status=200):
    m = MagicMock()
    m.status_code = status
    m.json.return_value = json_body
    m.raise_for_status.side_effect = None
    return m


class TestSeparation(TestCase):
    def test_zero_and_known(self) -> None:
        self.assertAlmostEqual(angular_separation_deg(10, 20, 10, 20), 0.0, places=6)
        # 1h RA at dec 0 = 15 deg.
        self.assertAlmostEqual(
            angular_separation_deg(0, 0, 15, 0), 15.0, places=4
        )

    def test_ra_wrap_and_high_dec(self) -> None:
        # Across the 0/360 wrap it must be small, not ~360.
        self.assertAlmostEqual(
            angular_separation_deg(359.9, 80, 0.1, 80),
            angular_separation_deg(359.9, 80, 0.1, 80),
        )
        self.assertLess(angular_separation_deg(359.0, 0, 1.0, 0), 2.1)


class TestPrefixAndSlewContract(TestCase):
    def test_prefix_is_v2_api(self) -> None:
        c = NinaClient(base_url="http://localhost:1888")
        with patch("mira.webapp.nina_client.requests.get", return_value=_resp({"Response": {}})) as g:
            c.mount_info()
        url = g.call_args[0][0]
        self.assertEqual(url, "http://localhost:1888/v2/api/equipment/mount/info")

    def test_slew_sends_degrees_and_lower_bools(self) -> None:
        c = NinaClient()
        with patch("mira.webapp.nina_client.requests.get", return_value=_resp({"Response": "Slew finished"})) as g:
            c.slew(199.86571, 45.52714, center=True, wait=True)
        _, kwargs = g.call_args
        params = kwargs["params"]
        self.assertEqual(params["ra"], 199.86571)   # degrees, NOT hours
        self.assertEqual(params["dec"], 45.52714)
        self.assertEqual(params["center"], "true")
        self.assertEqual(params["waitForResult"], "true")
        self.assertGreaterEqual(kwargs["timeout"], 60)  # wait=True needs a long timeout

    def test_tracking_mode_sidereal_is_zero(self) -> None:
        c = NinaClient()
        with patch("mira.webapp.nina_client.requests.get", return_value=_resp({"Response": "ok"})) as g:
            c.set_tracking()
        self.assertEqual(g.call_args[1]["params"], {"mode": 0})


class TestPreposition(TestCase):
    def _client(self):
        return NinaClient(base_url="http://x:1888")

    def test_success_confirmed_by_readback(self) -> None:
        c = self._client()
        # info(connected, not parked) -> slew -> tracking -> info(on target)
        seq = [
            _resp({"Response": {"Connected": True, "AtPark": False,
                                 "RightAscension": 13.0, "Declination": 40.0}}),
            _resp({"Response": "Slew finished"}),
            _resp({"Response": "Tracking mode changed"}),
            _resp({"Response": {"Connected": True, "AtPark": False,
                                 "RightAscension": 199.86571 / 15.0,
                                 "Declination": 45.52714}}),
        ]
        with patch("mira.webapp.nina_client.requests.get", side_effect=seq):
            r = c.preposition(199.86571, 45.52714, tolerance_deg=0.5)
        self.assertIsInstance(r, SlewResult)
        self.assertTrue(r.ok, r.message)
        self.assertLess(r.separation_deg, 0.01)

    def test_offtarget_readback_fails_without_retry(self) -> None:
        c = self._client()
        seq = [
            _resp({"Response": {"Connected": True, "AtPark": False,
                                 "RightAscension": 13.0, "Declination": 40.0}}),
            _resp({"Response": "Slew finished"}),
            _resp({"Response": "Tracking mode changed"}),
            # Mount ended up 30 deg off.
            _resp({"Response": {"Connected": True, "AtPark": False,
                                 "RightAscension": 13.0, "Declination": 40.0}}),
        ]
        with patch("mira.webapp.nina_client.requests.get", side_effect=seq) as g:
            r = c.preposition(199.86571, 45.52714, tolerance_deg=1.0)
        self.assertFalse(r.ok)
        self.assertIn("NOT retrying", r.message)
        # 4 calls only: info, slew, tracking, info. No second slew.
        self.assertEqual(g.call_count, 4)

    def test_not_connected_aborts_before_slew(self) -> None:
        c = self._client()
        with patch(
            "mira.webapp.nina_client.requests.get",
            return_value=_resp({"Response": {"Connected": False}}),
        ) as g:
            r = c.preposition(199.86571, 45.52714)
        self.assertFalse(r.ok)
        self.assertIn("not connected", r.message)
        self.assertEqual(g.call_count, 1)  # only the pre-check; no slew issued


class TestPrepositionMalformedReply(TestCase):
    """Regression: a non-JSON / non-numeric mount reply must NOT raise out
    of preposition() — that would break the abort-safely-no-slew guarantee
    for hardware control."""

    def test_non_json_body_aborts_no_slew(self) -> None:
        bad = MagicMock()
        bad.status_code = 200
        bad.raise_for_status.side_effect = None
        bad.json.side_effect = ValueError("Expecting value: line 1")
        c = NinaClient(base_url="http://x:1888")
        with patch("mira.webapp.nina_client.requests.get", return_value=bad) as g:
            r = c.preposition(199.86571, 45.52714)  # must not raise
        self.assertFalse(r.ok)
        self.assertIn("bad reply", r.message)
        self.assertEqual(g.call_count, 1)  # pre-check only; no slew issued

    def test_non_numeric_radec_does_not_crash(self) -> None:
        c = NinaClient(base_url="http://x:1888")
        # connected, not parked, but RA/Dec are "N/A"/null
        seq = [
            _resp({"Response": {"Connected": True, "AtPark": False,
                                 "RightAscension": "N/A", "Declination": None}}),
            _resp({"Response": "Slew started"}),
            _resp({"Response": "ok"}),
            _resp({"Response": {"Connected": True, "AtPark": False,
                                 "RightAscension": "N/A", "Declination": None}}),
        ]
        with patch("mira.webapp.nina_client.requests.get", side_effect=seq):
            r = c.preposition(199.86571, 45.52714)  # must not raise
        self.assertFalse(r.ok)
        self.assertIn("did not report a position", r.message)


class TestCaptureImaging(TestCase):
    def test_capture_param_contract(self) -> None:
        c = NinaClient(base_url="http://x:1888")
        with patch("mira.webapp.nina_client.requests.get",
                   return_value=_resp({"Response": "ok"})) as g:
            c.capture(duration=12, gain=120, save=True, solve=False,
                      target_name="M94", timeout_s=99)
        url = g.call_args[0][0]
        p = g.call_args[1]["params"]
        self.assertEqual(url, "http://x:1888/v2/api/equipment/camera/capture")
        self.assertEqual(p["duration"], 12)
        self.assertEqual(p["gain"], 120)            # int, not hours/str
        self.assertEqual(p["save"], "true")
        self.assertEqual(p["solve"], "false")
        self.assertEqual(p["waitForResult"], "true")
        self.assertEqual(p["omitImage"], "true")
        self.assertEqual(p["targetName"], "M94")
        self.assertGreaterEqual(g.call_args[1]["timeout"], 60)

    def test_capture_omits_gain_when_none(self) -> None:
        c = NinaClient()
        with patch("mira.webapp.nina_client.requests.get",
                   return_value=_resp({"Response": "ok"})) as g:
            c.capture(duration=5)
        self.assertNotIn("gain", g.call_args[1]["params"])
        self.assertNotIn("targetName", g.call_args[1]["params"])

    def test_image_history_filters_and_tolerates_errors(self) -> None:
        c = NinaClient()
        with patch("mira.webapp.nina_client.requests.get",
                   return_value=_resp({"Response": [{"Max": 1}, "garbage", {"Max": 2}]})):
            self.assertEqual(c.image_history(), [{"Max": 1}, {"Max": 2}])
            self.assertEqual(c.latest_image_stats(), {"Max": 2})

        bad = MagicMock()
        bad.status_code = 200
        bad.raise_for_status.side_effect = None
        bad.json.side_effect = ValueError("no json")
        with patch("mira.webapp.nina_client.requests.get", return_value=bad):
            self.assertEqual(c.image_history(), [])
            self.assertIsNone(c.latest_image_stats())

    def test_camera_state_and_idle_wait(self) -> None:
        c = NinaClient()
        with patch("mira.webapp.nina_client.requests.get",
                   return_value=_resp({"Response": {"CameraState": "Idle"}})):
            self.assertEqual(c.camera_state(), "Idle")
            self.assertTrue(c.wait_camera_idle(timeout_s=0.0))
        with patch("mira.webapp.nina_client.requests.get",
                   return_value=_resp({"Response": {"CameraState": "Exposing"}})):
            self.assertFalse(c.wait_camera_idle(timeout_s=0.0))  # fast: no sleep loop


class TestStatus(TestCase):
    def test_reachable_via_version(self) -> None:
        c = NinaClient()

        def _route(url, params=None, timeout=None):
            if url.endswith("/version"):
                return _resp({"Response": "2.2.15.1"})
            raise __import__("requests").RequestException("no")

        with patch("mira.webapp.nina_client.requests.get", side_effect=_route):
            st = c.status()
        self.assertTrue(st.reachable)
