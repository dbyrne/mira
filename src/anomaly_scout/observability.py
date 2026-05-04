from __future__ import annotations

import math
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from .config import ObserverConfig, WindowConfig
from .models import Observability, VsxTarget

J2000 = 2451545.0
RA_NGP_DEG = 192.85948
DEC_NGP_DEG = 27.12825


def evaluate_observability(
    target: VsxTarget,
    observer: ObserverConfig,
    window: WindowConfig,
    start_date: date | None = None,
) -> Observability:
    if start_date is None:
        start_date = datetime.now(ZoneInfo(observer.timezone)).date()

    best_max_altitude = -90.0
    best_local_time: datetime | None = None
    best_night_date: date | None = None
    best_night_minutes = 0

    for night_offset in range(window.nights):
        night_date = start_date + timedelta(days=night_offset)
        samples = _local_window_samples_for_night(night_date, observer.timezone, window)
        altitudes = [
            altitude_deg(
                target.ra_deg,
                target.dec_deg,
                sample.astimezone(timezone.utc),
                observer.latitude_deg,
                observer.longitude_deg,
            )
            for sample in samples
        ]
        if not altitudes:
            continue

        night_max_index = max(range(len(altitudes)), key=lambda index: altitudes[index])
        night_max_altitude = altitudes[night_max_index]
        night_minutes = sum(1 for alt in altitudes if alt >= window.min_altitude_deg) * window.sample_minutes
        if (night_minutes, night_max_altitude) > (best_night_minutes, best_max_altitude):
            best_night_minutes = night_minutes
            best_night_date = night_date
            best_max_altitude = night_max_altitude
            best_local_time = samples[night_max_index]

    return Observability(
        max_altitude_deg=best_max_altitude,
        minutes_above_minimum=best_night_minutes,
        best_local_time=best_local_time,
        best_night_date=best_night_date,
        galactic_latitude_deg=galactic_latitude_deg(target.ra_deg, target.dec_deg),
    )


def altitude_deg(
    ra_deg: float,
    dec_deg: float,
    utc_dt: datetime,
    latitude_deg: float,
    longitude_deg: float,
) -> float:
    lst_hours = local_sidereal_time_hours(utc_dt, longitude_deg)
    hour_angle_deg = ((lst_hours * 15.0 - ra_deg + 180.0) % 360.0) - 180.0

    lat = math.radians(latitude_deg)
    dec = math.radians(dec_deg)
    ha = math.radians(hour_angle_deg)
    sin_alt = math.sin(dec) * math.sin(lat) + math.cos(dec) * math.cos(lat) * math.cos(ha)
    return math.degrees(math.asin(max(-1.0, min(1.0, sin_alt))))


def local_sidereal_time_hours(utc_dt: datetime, longitude_deg: float) -> float:
    jd = julian_date(utc_dt)
    gmst = 18.697374558 + 24.06570982441908 * (jd - J2000)
    return (gmst + longitude_deg / 15.0) % 24.0


def julian_date(utc_dt: datetime) -> float:
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=timezone.utc)
    utc_dt = utc_dt.astimezone(timezone.utc)
    year = utc_dt.year
    month = utc_dt.month
    day_fraction = (
        utc_dt.day
        + (utc_dt.hour + (utc_dt.minute + (utc_dt.second + utc_dt.microsecond / 1_000_000) / 60) / 60) / 24
    )
    if month <= 2:
        year -= 1
        month += 12
    a = math.floor(year / 100)
    b = 2 - a + math.floor(a / 4)
    return (
        math.floor(365.25 * (year + 4716))
        + math.floor(30.6001 * (month + 1))
        + day_fraction
        + b
        - 1524.5
    )


def galactic_latitude_deg(ra_deg: float, dec_deg: float) -> float:
    ra = math.radians(ra_deg)
    dec = math.radians(dec_deg)
    ra_ngp = math.radians(RA_NGP_DEG)
    dec_ngp = math.radians(DEC_NGP_DEG)
    sin_b = math.sin(dec) * math.sin(dec_ngp) + math.cos(dec) * math.cos(dec_ngp) * math.cos(ra - ra_ngp)
    return math.degrees(math.asin(max(-1.0, min(1.0, sin_b))))


def _local_window_samples(start_date: date, tz_name: str, window: WindowConfig) -> list[datetime]:
    samples: list[datetime] = []
    for night_offset in range(window.nights):
        samples.extend(_local_window_samples_for_night(start_date + timedelta(days=night_offset), tz_name, window))
    return samples


def _local_window_samples_for_night(night_date: date, tz_name: str, window: WindowConfig) -> list[datetime]:
    tz = ZoneInfo(tz_name)
    samples: list[datetime] = []
    start_dt = datetime.combine(night_date, time(window.start_hour_local, 0), tzinfo=tz)
    end_date = night_date
    if window.end_hour_local <= window.start_hour_local:
        end_date = night_date + timedelta(days=1)
    end_dt = datetime.combine(end_date, time(window.end_hour_local, 0), tzinfo=tz)
    current = start_dt
    while current <= end_dt:
        samples.append(current)
        current += timedelta(minutes=window.sample_minutes)
    return samples
