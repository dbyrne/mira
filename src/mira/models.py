from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass
class VsxTarget:
    """A VSX catalog row, with field names that say what they mean.

    `bright_mag` is the *brighter* end of the photometric range — the
    numerically smaller magnitude. (VSX stores it as 'max', but that's
    confusing since brighter = smaller mag.)

    `faint_mag` is the dimmer end OR the amplitude in mag, depending on
    `faint_is_amplitude`. Both VSX conventions exist in the catalog;
    the source's `min_band` tells us which.
    """
    oid: int
    name: str
    var_type: str
    bright_mag: float | None
    faint_mag: float | None
    bright_band: str
    faint_band: str
    faint_is_amplitude: bool
    period_days: float | None
    spectral_type: str
    ra_deg: float
    dec_deg: float

    @property
    def catalog_amplitude(self) -> float | None:
        if self.faint_mag is None or self.bright_mag is None:
            return None
        if self.faint_is_amplitude:
            return self.faint_mag
        if self.faint_mag >= self.bright_mag:
            return self.faint_mag - self.bright_mag
        return None

    @property
    def vsx_url(self) -> str:
        return f"https://www.aavso.org/vsx/index.php?view=detail.top&oid={self.oid}"


@dataclass
class Observability:
    site_name: str
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
    derived_period_days: float | None = None
    period_power: float | None = None
    period_disagrees: bool | None = None
    plot_path: str | None = None
    folded_plot_path: str | None = None
    note: str = ""


@dataclass
class AavsoStats:
    status: str
    recent_observations: int = 0
    from_jd: float | None = None
    to_jd: float | None = None
    last_observation_jd: float | None = None
    note: str = ""
    derived_period_days: float | None = None
    period_power: float | None = None
    period_disagrees: bool | None = None
    period_note: str = ""
    recent_median_mag: float | None = None
    recent_min_mag: float | None = None
    recent_max_mag: float | None = None
    recent_samples: list[tuple[float, float, str]] = field(default_factory=list)


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
class GaiaStats:
    status: str
    source_id: str = ""
    g_mag: float | None = None
    bp_rp: float | None = None
    parallax_mas: float | None = None
    parallax_error_mas: float | None = None
    ruwe: float | None = None
    photometric_variable: bool = False
    separation_arcsec: float | None = None
    ipd_frac_multi_peak: float | None = None
    color_anomaly: str = ""
    note: str = ""


@dataclass
class Candidate:
    target: VsxTarget
    observabilities: list[Observability]
    score: float
    reasons: list[str] = field(default_factory=list)
    best_site_name: str = ""
    site_scores: dict[str, float] = field(default_factory=dict)
    site_reasons: dict[str, list[str]] = field(default_factory=dict)
    aavso: AavsoStats | None = None
    simbad: SimbadStats | None = None
    gaia: GaiaStats | None = None
    ztf: ZtfStats | None = None

    @property
    def best_observability(self) -> Observability:
        if self.best_site_name:
            for obs in self.observabilities:
                if obs.site_name == self.best_site_name:
                    return obs
        return self.observabilities[0]

    @property
    def observable_site_names(self) -> tuple[str, ...]:
        return tuple(observation.site_name for observation in self.observabilities)
