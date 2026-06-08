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

    ``captures_root`` is where ``mira dso status`` and the ledger-aware
    ``mira dso plan`` walk for ``mira_capture.json`` sidecars. The
    homebase end of a Syncthing-mirrored rig captures dir is the
    expected setting on the Esprit. Override with ``--captures-root``.

    ``deficit_weight`` controls how strongly the ledger demotes
    already-imaged targets in ``mira dso plan``'s ranking. The score
    multiplier is ``0.5 + deficit_weight * deficit_fraction`` clamped to
    [0.5, 1.5]; with weight 1.0 (default), a never-imaged target is
    boosted 1.5× and a 100%-complete target is demoted to 0.5×. Set to
    0 to disable the ledger entirely (Phase-1 pure-observability behavior).

    ``sb_limit_mag_arcsec2`` is the ``mira galaxies`` surface-brightness
    floor: galaxies with a mean SB fainter than this are flagged
    "dark-site only". ``None`` (the narrowband default) disables the flag —
    emission targets have no integrated magnitude, so SB is undefined.
    """
    enabled: bool
    catalog_path: Path
    fov_deg: tuple[float, float]
    relax_moon: bool
    output_subdir: str
    captures_root: Path
    deficit_weight: float
    sb_limit_mag_arcsec2: float | None = None


# Sensible defaults: the shipped curated catalog, the Esprit 120 rig FOV,
# narrowband-relaxed moon, captures under the repo's `captures/`. A config
# without a `dso:` section gets these.
DSO_DEFAULTS = DsoConfig(
    enabled=True,
    catalog_path=Path("data/dso_catalog/sho_targets.yaml"),
    fov_deg=(1.6, 1.07),
    relax_moon=True,
    output_subdir="dso",
    captures_root=Path("captures"),
    deficit_weight=1.0,
)


# Defaults for the `galaxies:` section — the broadband-galaxy showpiece
# path (`mira galaxies`). Differs from the narrowband DSO defaults in three
# load-bearing ways: a galaxy catalog, moon-STRICT gating (broadband from
# the city is moon-sensitive — the opposite of narrowband), and a
# surface-brightness floor for the dark-site-only flag. FOV defaults to the
# wide S30 Pro field since that's the rig this path was built for.
GALAXY_DEFAULTS = DsoConfig(
    enabled=True,
    catalog_path=Path("data/dso_catalog/galaxies.yaml"),
    fov_deg=(4.2, 2.4),
    relax_moon=False,
    output_subdir="galaxies",
    captures_root=Path("captures"),
    deficit_weight=1.0,
    sb_limit_mag_arcsec2=22.5,
)


# Defaults for the `emission:` section — the emission-nebula planner
# (`mira emission`). Moon-RELAXED like the narrowband DSO defaults
# (Ha/OIII/SII narrowband and the S30's LP dual-band all tolerate moonlight,
# the opposite of broadband galaxies), but points at the emission-nebula
# catalog (union of the Esprit + S30 image books) and writes to its own
# `emission/` subdir. FOV defaults to the Esprit single frame; a wide-field
# rig (the S30) overrides `fov_deg` in its config so the giant complexes stop
# being mosaic-flagged. Rig-agnostic — run it with either rig's config.
EMISSION_DEFAULTS = DsoConfig(
    enabled=True,
    catalog_path=Path("data/dso_catalog/emission_nebulae.yaml"),
    fov_deg=(1.6, 1.07),
    relax_moon=True,
    output_subdir="emission",
    captures_root=Path("captures"),
    deficit_weight=1.0,
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
    galaxies: DsoConfig = GALAXY_DEFAULTS
    emission: DsoConfig = EMISSION_DEFAULTS


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
        galaxies=_parse_dso(
            raw.get("galaxies"), defaults=GALAXY_DEFAULTS, section="galaxies",
        ),
        emission=_parse_dso(
            raw.get("emission"), defaults=EMISSION_DEFAULTS, section="emission",
        ),
    )


def _parse_dso(
    raw: Any,
    *,
    defaults: DsoConfig = DSO_DEFAULTS,
    section: str = "dso",
) -> DsoConfig:
    """Parse an optional planner section (``dso:`` or ``galaxies:``).
    Missing/empty yields ``defaults`` so existing configs keep loading. A
    present section overrides field-by-field — partial sections inherit the
    rest. ``section`` only tweaks the error-message prefix."""
    if not raw:
        return defaults
    if not isinstance(raw, dict):
        raise ValueError(f"{section}: section must be a mapping")
    fov = raw.get("fov_deg", defaults.fov_deg)
    if not (
        isinstance(fov, (list, tuple))
        and len(fov) == 2
        and all(isinstance(v, (int, float)) and v > 0 for v in fov)
    ):
        raise ValueError(
            f"{section}.fov_deg must be [major, minor] positive numbers; got {fov!r}"
        )
    sb_raw = raw.get("sb_limit_mag_arcsec2", defaults.sb_limit_mag_arcsec2)
    sb_limit = float(sb_raw) if sb_raw is not None else None
    return DsoConfig(
        enabled=bool(raw.get("enabled", defaults.enabled)),
        catalog_path=Path(raw.get("catalog_path", str(defaults.catalog_path))),
        fov_deg=(float(fov[0]), float(fov[1])),
        relax_moon=bool(raw.get("relax_moon", defaults.relax_moon)),
        output_subdir=str(raw.get("output_subdir", defaults.output_subdir)),
        captures_root=Path(raw.get("captures_root", str(defaults.captures_root))),
        deficit_weight=float(raw.get("deficit_weight", defaults.deficit_weight)),
        sb_limit_mag_arcsec2=sb_limit,
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
