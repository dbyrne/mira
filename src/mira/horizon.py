"""Local horizon profiles — per-azimuth minimum-altitude floors.

The standard observability check uses a single ``min_altitude_deg`` for
the whole sky (e.g. 45° from Jersey City). Real observing locations have
trees, houses, and other structures that block specific directions —
the actual minimum altitude required to see a target depends on which
way you're pointing.

A ``HorizonProfile`` captures that as (azimuth, altitude) silhouette
points. ``evaluate_observability`` interpolates the profile per sample
and uses ``max(global_floor, profile_at_az)`` instead of just the
global floor. Targets whose best moment puts them behind a tree are
correctly rejected.

YAML format (see config/horizon_balcony_jc.yaml for a real example):

    site: "..."
    captured_at: "YYYY-MM-DD"
    points:
      - {az: 0, alt: 8}
      - {az: 30, alt: 25}
      - ...
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class HorizonPoint:
    az_deg: float
    alt_deg: float


@dataclass(frozen=True)
class HorizonProfile:
    """A site's local horizon as a piecewise-linear silhouette. Points
    are stored sorted by azimuth in [0, 360); the curve wraps around
    so points at azimuths 350° and 10° interpolate linearly through 0°."""
    site: str
    captured_at: str
    points: tuple[HorizonPoint, ...]

    def min_altitude_at(self, az_deg: float) -> float:
        """Linear-interpolate the minimum required altitude at the given
        azimuth. Returns 0.0 if the profile is empty (no horizon = clear
        sky to the horizon line)."""
        if not self.points:
            return 0.0
        az = az_deg % 360.0
        # Find the bracketing pair (lower, upper). Profile points are
        # sorted ascending. Wrap from the last point back to the first.
        for i, point in enumerate(self.points):
            if point.az_deg >= az:
                upper = point
                lower = self.points[i - 1] if i > 0 else self.points[-1]
                break
        else:
            # az is greater than all stored azimuths; wrap to the first.
            lower = self.points[-1]
            upper = self.points[0]
        # Handle wrap-around: if lower comes after upper in az terms,
        # adjust by 360° so the interpolation parameter is well-defined.
        lower_az = lower.az_deg
        upper_az = upper.az_deg
        target_az = az
        if upper_az < lower_az:
            upper_az += 360.0
            if target_az < lower_az:
                target_az += 360.0
        span = upper_az - lower_az
        if span <= 0:
            return upper.alt_deg
        t = (target_az - lower_az) / span
        return lower.alt_deg + t * (upper.alt_deg - lower.alt_deg)

    def floor_at(self, az_deg: float, global_floor: float) -> float:
        """Combine the per-azimuth horizon with the site's global
        altitude floor — a target must be above both."""
        return max(global_floor, self.min_altitude_at(az_deg))


def load_horizon_profile(path: Path) -> HorizonProfile:
    """Parse a horizon YAML file. Sorts points by azimuth and validates
    that altitudes are within [0, 90]. Raises ValueError on malformed
    input."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Horizon profile {path} is not a mapping")
    raw_points = data.get("points") or []
    if not raw_points:
        raise ValueError(f"Horizon profile {path} has no 'points'")
    parsed: list[HorizonPoint] = []
    for entry in raw_points:
        try:
            az = float(entry["az"]) % 360.0
            alt = float(entry["alt"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Horizon profile {path}: bad point {entry}: {exc}")
        if not (-1.0 <= alt <= 91.0):  # tolerate tiny float imprecision
            raise ValueError(f"Horizon profile {path}: alt={alt} outside [0, 90]")
        parsed.append(HorizonPoint(az_deg=az, alt_deg=max(0.0, min(90.0, alt))))
    parsed.sort(key=lambda p: p.az_deg)
    return HorizonProfile(
        site=str(data.get("site", "")),
        captured_at=str(data.get("captured_at", "")),
        points=tuple(parsed),
    )
