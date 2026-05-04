from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass
class VsxTarget:
    oid: int
    name: str
    var_type: str
    max_mag: float | None
    min_mag: float | None
    max_band: str
    min_band: str
    min_is_amplitude: bool
    period_days: float | None
    spectral_type: str
    ra_deg: float
    dec_deg: float

    @property
    def catalog_amplitude(self) -> float | None:
        if self.min_mag is None or self.max_mag is None:
            return None
        if self.min_is_amplitude:
            return self.min_mag
        if self.min_mag >= self.max_mag:
            return self.min_mag - self.max_mag
        return None

    @property
    def bright_mag(self) -> float | None:
        return self.max_mag

    @property
    def vsx_url(self) -> str:
        return f"https://www.aavso.org/vsx/index.php?view=detail.top&oid={self.oid}"


@dataclass
class Observability:
    max_altitude_deg: float
    minutes_above_minimum: int
    best_local_time: datetime | None
    best_night_date: date | None
    galactic_latitude_deg: float


@dataclass
class ZtfStats:
    status: str
    observations: int = 0
    bands: tuple[str, ...] = ()
    median_mag: float | None = None
    amplitude_mag: float | None = None
    plot_path: str | None = None
    note: str = ""


@dataclass
class AavsoStats:
    status: str
    recent_observations: int = 0
    from_jd: float | None = None
    to_jd: float | None = None
    note: str = ""


@dataclass
class SimbadStats:
    status: str
    main_id: str = ""
    object_type: str = ""
    ra_deg: float | None = None
    dec_deg: float | None = None
    separation_arcsec: float | None = None
    identifiers: tuple[str, ...] = ()
    url: str = ""
    note: str = ""


@dataclass
class Candidate:
    target: VsxTarget
    observability: Observability
    score: float
    reasons: list[str] = field(default_factory=list)
    aavso: AavsoStats | None = None
    simbad: SimbadStats | None = None
    ztf: ZtfStats | None = None
