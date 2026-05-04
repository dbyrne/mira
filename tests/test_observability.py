from __future__ import annotations

from datetime import datetime, timezone
from unittest import TestCase

from anomaly_scout.observability import altitude_deg, galactic_latitude_deg


class ObservabilityTests(TestCase):
    def test_altitude_is_reasonable_for_polaris_from_jersey_city(self) -> None:
        altitude = altitude_deg(
            37.95456067,
            89.26410897,
            datetime(2026, 5, 4, tzinfo=timezone.utc),
            40.7178,
            -74.0431,
        )
        self.assertGreaterEqual(altitude, 39.0)
        self.assertLessEqual(altitude, 42.0)

    def test_galactic_latitude_range(self) -> None:
        latitude = galactic_latitude_deg(0.0, 0.0)
        self.assertGreaterEqual(latitude, -90.0)
        self.assertLessEqual(latitude, 90.0)
