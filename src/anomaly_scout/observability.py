from __future__ import annotations

import math
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from .config import SiteConfig, WindowConfig
from .models import Observability, VsxTarget

J2000 = 2451545.0
RA_NGP_DEG = 192.85948
DEC_NGP_DEG = 27.12825


def evaluate_observability(
    target: VsxTarget,
    site: SiteConfig,
    start_date: date | None = None,
) -> Observability:
    observer = site.observer
    window = site.observing_window
    if start_date is None:
        start_date = datetime.now(ZoneInfo(observer.timezone)).date()

    best_max_altitude = -90.0
    best_local_time: datetime | None = None
    best_night_date: date | None = None
    best_night_minutes = 0

    for night_offset in range(window.nights):
        night_date = start_date + timedelta(days=night_offset)
        samples = _local_window_samples_for_night(night_date, observer.timezone, window)
        dark_samples: list[tuple[datetime, float]] = []
        for sample in samples:
            utc_sample = sample.astimezone(timezone.utc)
            sun_alt = sun_altitude_deg(utc_sample, observer.latitude_deg, observer.longitude_deg)
            if sun_alt > window.max_sun_altitude_deg:
                continue
            moon_alt = moon_altitude_deg(utc_sample, observer.latitude_deg, observer.longitude_deg)
            if moon_alt > window.max_moon_altitude_deg:
                if moon_illumination(utc_sample) > window.max_moon_illumination:
                    continue
            target_alt = altitude_deg(
                target.ra_deg,
                target.dec_deg,
                utc_sample,
                observer.latitude_deg,
                observer.longitude_deg,
            )
            dark_samples.append((sample, target_alt))
        if not dark_samples:
            continue

        night_max_index = max(range(len(dark_samples)), key=lambda index: dark_samples[index][1])
        night_max_altitude = dark_samples[night_max_index][1]
        night_minutes = sum(
            1 for _, alt in dark_samples if alt >= window.min_altitude_deg
        ) * window.sample_minutes
        if (night_minutes, night_max_altitude) > (best_night_minutes, best_max_altitude):
            best_night_minutes = night_minutes
            best_night_date = night_date
            best_max_altitude = night_max_altitude
            best_local_time = dark_samples[night_max_index][0]

    return Observability(
        site_name=site.name,
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


def sun_position(utc_dt: datetime) -> tuple[float, float]:
    jd = julian_date(utc_dt)
    n = jd - J2000
    mean_lon_deg = (280.460 + 0.9856474 * n) % 360.0
    mean_anomaly = math.radians((357.528 + 0.9856003 * n) % 360.0)
    ecliptic_lon = math.radians(
        mean_lon_deg + 1.915 * math.sin(mean_anomaly) + 0.020 * math.sin(2 * mean_anomaly)
    )
    obliquity = math.radians(23.439 - 0.0000004 * n)
    sin_dec = math.sin(obliquity) * math.sin(ecliptic_lon)
    dec_rad = math.asin(max(-1.0, min(1.0, sin_dec)))
    ra_rad = math.atan2(math.cos(obliquity) * math.sin(ecliptic_lon), math.cos(ecliptic_lon))
    if ra_rad < 0:
        ra_rad += 2 * math.pi
    return math.degrees(ra_rad), math.degrees(dec_rad)


def sun_altitude_deg(utc_dt: datetime, latitude_deg: float, longitude_deg: float) -> float:
    ra, dec = sun_position(utc_dt)
    return altitude_deg(ra, dec, utc_dt, latitude_deg, longitude_deg)


def _sun_ecliptic_longitude_deg(utc_dt: datetime) -> float:
    jd = julian_date(utc_dt)
    n = jd - J2000
    mean_lon_deg = (280.460 + 0.9856474 * n) % 360.0
    mean_anomaly = math.radians((357.528 + 0.9856003 * n) % 360.0)
    return mean_lon_deg + 1.915 * math.sin(mean_anomaly) + 0.020 * math.sin(2 * mean_anomaly)


def moon_position(utc_dt: datetime) -> tuple[float, float, float]:
    """Low-precision lunar position. Returns (ra_deg, dec_deg, ecliptic_lon_deg)."""
    jd = julian_date(utc_dt)
    n = jd - J2000
    centuries = n / 36525.0
    mean_lon = (218.3164477 + 481267.88123421 * centuries) % 360.0
    mean_anomaly = math.radians((134.9633964 + 477198.8675055 * centuries) % 360.0)
    arg_latitude = math.radians((93.2720950 + 483202.0175233 * centuries) % 360.0)
    ecliptic_lon = mean_lon + 6.289 * math.sin(mean_anomaly)
    ecliptic_lat = 5.128 * math.sin(arg_latitude)
    obliquity = math.radians(23.439291 - 0.0130042 * centuries)
    lon_rad = math.radians(ecliptic_lon)
    lat_rad = math.radians(ecliptic_lat)
    ra_rad = math.atan2(
        math.sin(lon_rad) * math.cos(obliquity) - math.tan(lat_rad) * math.sin(obliquity),
        math.cos(lon_rad),
    )
    if ra_rad < 0:
        ra_rad += 2 * math.pi
    sin_dec = (
        math.sin(lat_rad) * math.cos(obliquity)
        + math.cos(lat_rad) * math.sin(obliquity) * math.sin(lon_rad)
    )
    dec_rad = math.asin(max(-1.0, min(1.0, sin_dec)))
    return math.degrees(ra_rad), math.degrees(dec_rad), ecliptic_lon % 360.0


def moon_altitude_deg(utc_dt: datetime, latitude_deg: float, longitude_deg: float) -> float:
    ra, dec, _ = moon_position(utc_dt)
    return altitude_deg(ra, dec, utc_dt, latitude_deg, longitude_deg)


def moon_illumination(utc_dt: datetime) -> float:
    _, _, moon_lon = moon_position(utc_dt)
    sun_lon = _sun_ecliptic_longitude_deg(utc_dt) % 360.0
    elongation = abs(moon_lon - sun_lon) % 360.0
    if elongation > 180.0:
        elongation = 360.0 - elongation
    return (1.0 - math.cos(math.radians(elongation))) / 2.0


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
    while current < end_dt:
        samples.append(current)
        current += timedelta(minutes=window.sample_minutes)
    return samples
