from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .horizon import HorizonProfile, load_horizon_profile


@dataclass(frozen=True)
class ObserverConfig:
    latitude_deg: float
    longitude_deg: float
    timezone: str


@dataclass(frozen=True)
class WindowConfig:
    start_hour_local: int
    end_hour_local: int
    nights: int
    sample_minutes: int
    min_altitude_deg: float
    max_sun_altitude_deg: float
    max_moon_altitude_deg: float
    max_moon_illumination: float
    # When the moon is up and bright, targets within this angular distance
    # of it have ruined backgrounds — drop those samples even if everything
    # else (altitude, sun, horizon) passes. Set to 0 to disable.
    min_moon_separation_deg: float = 30.0


@dataclass(frozen=True)
class VsxQueryConfig:
    row_limit: int
    ra_bin_degrees: float
    oversample_factor: int
    min_declination_deg: float
    max_bright_mag: float
    require_period: bool
    include_types: tuple[str, ...]


@dataclass(frozen=True)
class FilterConfig:
    min_galactic_latitude_abs_deg: float
    min_catalog_amplitude_mag: float
    prefer_amplitude_mag: float
    prefer_max_mag: float
    reject_saturated_brighter_than_mag: float


@dataclass(frozen=True)
class SiteConfig:
    name: str
    observer: ObserverConfig
    observing_window: WindowConfig
    filters: FilterConfig
    # Optional local horizon mask (trees, buildings, terrain). When set,
    # evaluate_observability uses max(window.min_altitude_deg, profile_at_az)
    # per sample instead of just the global floor. None = clear sky to the
    # global floor everywhere (the original behavior).
    horizon_profile: "HorizonProfile | None" = None


@dataclass(frozen=True)
class ScoringConfig:
    uncertain_type_bonus: int
    survey_name_bonus: int
    classical_name_bonus: int
    sparse_aavso_bonus: int
    well_observed_aavso_penalty: int
    high_amplitude_bonus: int
    moderate_amplitude_bonus: int
    bright_target_bonus: int
    long_period_bonus: int
    time_series_bonus: int
    clean_field_bonus: int
    period_disagreement_bonus: int
    period_discovered_bonus: int
    gaia_color_anomaly_bonus: int
    gaia_crowding_penalty: int


@dataclass(frozen=True)
class AavsoConfig:
    enabled: bool
    enrich_top: int
    recent_days: int
    sparse_recent_threshold: int
    timeout_seconds: int
    bands: tuple[str, ...]
    period_min_peak_power: float


@dataclass(frozen=True)
class SimbadConfig:
    enabled: bool
    enrich_top: int
    search_radius_arcsec: float
    timeout_seconds: int


@dataclass(frozen=True)
class GaiaConfig:
    enabled: bool
    enrich_top: int
    search_radius_arcsec: float
    timeout_seconds: int


@dataclass(frozen=True)
class ZtfConfig:
    enabled: bool
    search_radius_arcsec: float
    timeout_seconds: int
    bad_catflags_mask: int
    bands: tuple[str, ...]
    period_min_peak_power: float


@dataclass(frozen=True)
class OutputConfig:
    directory: Path
    top_packets: int


@dataclass(frozen=True)
class DsoConfig:
    """Optional DSO/narrowband planner settings. Absent in VSX-only configs.

    ``fov_deg`` is (major, minor) of the rig's FOV in degrees — used to
    flag mosaic candidates. ``relax_moon=True`` is the narrowband default
    (Ha/SII/OIII tolerate moonlight); set False for strict broadband-style
    moon gating. ``output_subdir`` is the dir-name appended to
    ``output.directory`` for plan files; full path becomes
    ``output.directory / output_subdir``.
    """
    enabled: bool
    catalog_path: Path
    fov_deg: tuple[float, float]
    relax_moon: bool
    output_subdir: str


# Sensible defaults: the shipped curated catalog, the Esprit 120 rig FOV,
# narrowband-relaxed moon. A config without a `dso:` section gets these.
DSO_DEFAULTS = DsoConfig(
    enabled=True,
    catalog_path=Path("data/dso_catalog/sho_targets.yaml"),
    fov_deg=(1.6, 1.07),
    relax_moon=True,
    output_subdir="dso",
)


@dataclass(frozen=True)
class ScoutConfig:
    sites: tuple[SiteConfig, ...]
    vsx_query: VsxQueryConfig
    scoring: ScoringConfig
    aavso: AavsoConfig
    simbad: SimbadConfig
    gaia: GaiaConfig
    ztf: ZtfConfig
    output: OutputConfig
    dso: DsoConfig = DSO_DEFAULTS


def load_config(path: str | Path) -> ScoutConfig:
    with Path(path).open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)

    sites = tuple(_parse_site(item) for item in raw["sites"])
    if not sites:
        raise ValueError("config must list at least one site under 'sites'")

    return ScoutConfig(
        sites=sites,
        vsx_query=VsxQueryConfig(
            row_limit=int(raw["vsx_query"]["row_limit"]),
            ra_bin_degrees=float(raw["vsx_query"].get("ra_bin_degrees", 15)),
            oversample_factor=int(raw["vsx_query"].get("oversample_factor", 3)),
            min_declination_deg=float(raw["vsx_query"]["min_declination_deg"]),
            max_bright_mag=float(raw["vsx_query"]["max_bright_mag"]),
            require_period=bool(raw["vsx_query"].get("require_period", False)),
            include_types=tuple(str(item) for item in raw["vsx_query"]["include_types"]),
        ),
        scoring=ScoringConfig(**_coerce_numbers(raw["scoring"])),
        aavso=AavsoConfig(
            enabled=bool(raw.get("aavso", {}).get("enabled", True)),
            enrich_top=int(raw.get("aavso", {}).get("enrich_top", 0)),
            recent_days=int(raw.get("aavso", {}).get("recent_days", 730)),
            sparse_recent_threshold=int(raw.get("aavso", {}).get("sparse_recent_threshold", 5)),
            timeout_seconds=int(raw.get("aavso", {}).get("timeout_seconds", 20)),
            bands=tuple(str(item) for item in raw.get("aavso", {}).get("bands", ["V", "Vis."])),
            period_min_peak_power=float(raw.get("aavso", {}).get("period_min_peak_power", 0.3)),
        ),
        simbad=SimbadConfig(
            enabled=bool(raw.get("simbad", {}).get("enabled", True)),
            enrich_top=int(raw.get("simbad", {}).get("enrich_top", 0)),
            search_radius_arcsec=float(raw.get("simbad", {}).get("search_radius_arcsec", 5)),
            timeout_seconds=int(raw.get("simbad", {}).get("timeout_seconds", 20)),
        ),
        gaia=GaiaConfig(
            enabled=bool(raw.get("gaia", {}).get("enabled", True)),
            enrich_top=int(raw.get("gaia", {}).get("enrich_top", 0)),
            search_radius_arcsec=float(raw.get("gaia", {}).get("search_radius_arcsec", 3)),
            timeout_seconds=int(raw.get("gaia", {}).get("timeout_seconds", 30)),
        ),
        ztf=ZtfConfig(
            enabled=bool(raw["ztf"].get("enabled", True)),
            search_radius_arcsec=float(raw["ztf"]["search_radius_arcsec"]),
            timeout_seconds=int(raw["ztf"]["timeout_seconds"]),
            bad_catflags_mask=int(raw["ztf"]["bad_catflags_mask"]),
            bands=tuple(str(item) for item in raw["ztf"]["bands"]),
            period_min_peak_power=float(raw["ztf"].get("period_min_peak_power", 0.3)),
        ),
        output=OutputConfig(
            directory=Path(raw["output"]["directory"]),
            top_packets=int(raw["output"]["top_packets"]),
        ),
        dso=_parse_dso(raw.get("dso")),
    )


def _parse_dso(raw: Any) -> DsoConfig:
    """Parse the optional `dso:` config section. Missing/empty yields the
    DSO_DEFAULTS so existing VSX-only configs continue to load. A present
    section overrides field-by-field — partial sections inherit the rest."""
    if not raw:
        return DSO_DEFAULTS
    if not isinstance(raw, dict):
        raise ValueError("dso: section must be a mapping")
    fov = raw.get("fov_deg", DSO_DEFAULTS.fov_deg)
    if not (
        isinstance(fov, (list, tuple))
        and len(fov) == 2
        and all(isinstance(v, (int, float)) and v > 0 for v in fov)
    ):
        raise ValueError(
            f"dso.fov_deg must be [major, minor] positive numbers; got {fov!r}"
        )
    return DsoConfig(
        enabled=bool(raw.get("enabled", DSO_DEFAULTS.enabled)),
        catalog_path=Path(raw.get("catalog_path", str(DSO_DEFAULTS.catalog_path))),
        fov_deg=(float(fov[0]), float(fov[1])),
        relax_moon=bool(raw.get("relax_moon", DSO_DEFAULTS.relax_moon)),
        output_subdir=str(raw.get("output_subdir", DSO_DEFAULTS.output_subdir)),
    )


def _parse_site(raw: dict[str, Any]) -> SiteConfig:
    window_raw = dict(_coerce_numbers(raw["observing_window"]))
    window_raw.setdefault("max_sun_altitude_deg", -12.0)
    window_raw.setdefault("max_moon_altitude_deg", 30.0)
    window_raw.setdefault("max_moon_illumination", 0.7)
    window_raw.setdefault("min_moon_separation_deg", 30.0)
    horizon_path = raw.get("horizon_profile_path")
    horizon_profile: HorizonProfile | None = None
    if horizon_path:
        horizon_profile = load_horizon_profile(Path(str(horizon_path)))
    return SiteConfig(
        name=str(raw["name"]),
        observer=ObserverConfig(
            latitude_deg=float(raw["observer"]["latitude_deg"]),
            longitude_deg=float(raw["observer"]["longitude_deg"]),
            timezone=str(raw["observer"]["timezone"]),
        ),
        observing_window=WindowConfig(**window_raw),
        filters=FilterConfig(**_coerce_numbers(raw["filters"])),
        horizon_profile=horizon_profile,
    )


def _coerce_numbers(values: dict[str, Any]) -> dict[str, Any]:
    coerced: dict[str, Any] = {}
    for key, value in values.items():
        if isinstance(value, bool):
            coerced[key] = value
        elif isinstance(value, int):
            coerced[key] = value
        elif isinstance(value, float):
            coerced[key] = value
        else:
            try:
                coerced[key] = int(value)
            except (TypeError, ValueError):
                try:
                    coerced[key] = float(value)
                except (TypeError, ValueError):
                    coerced[key] = value
    return coerced
