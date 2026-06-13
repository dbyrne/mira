"""Curated DSO catalog loader.

The catalog is a YAML file the user maintains (the shipped one lives at
``data/dso_catalog/sho_targets.yaml``). No remote queries — narrowband
targets are a known finite set and the user's taste matters more than
algorithmic ranking. New targets get appended by hand; SIMBAD enrichment
is intentionally out of scope for now.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


# Object-type codes used in the catalog. Kept loose (a string) rather than
# an enum so adding new categories (e.g. GALACTIC_CIRRUS) is a YAML edit.
KNOWN_OBJECT_TYPES = frozenset({
    "HII",      # HII region / emission nebula
    "PN",       # Planetary nebula
    "SNR",      # Supernova remnant
    "WR",       # Wolf-Rayet bubble
    "DARK",     # Dark nebula
    "REF",      # Reflection nebula
    "OPEN",     # Open cluster (rarely a narrowband target)
    "GLOB",     # Globular cluster (rarely a narrowband target)
    "GALAXY",   # Galaxy — the `mira galaxies` broadband-showpiece path
})


@dataclass(frozen=True)
class DsoTarget:
    """One row from the DSO catalog.

    ``budget_minutes`` is a dict mapping NINA wheel labels (Ha, OIII, SII,
    L, R, G, B, V, …) to integration-minutes targets. Keys not present in
    the wheel are ignored at capture time; the planner only knows about
    the keys listed here.

    ``size_arcmin`` is (major, minor). Used to flag mosaic candidates
    against the rig's FOV (configured separately, since FOV depends on
    OTA + sensor — not on the target catalog).

    ``magnitude`` is the target's *integrated* visual magnitude. Optional —
    narrowband emission targets don't carry one (it's meaningless for an
    HII region whose brightness is line-flux, not a point-source mag), so
    it stays ``None`` for them. Galaxies (the ``mira galaxies`` path) set
    it: combined with ``size_arcmin`` it yields the mean surface brightness,
    which — not integrated mag — is what decides whether a galaxy is
    recoverable from a light-polluted urban sky on a small OSC scope."""
    name: str
    common_name: str
    object_type: str
    ra_deg: float
    dec_deg: float
    size_arcmin: tuple[float, float]
    constellation: str
    budget_minutes: dict[str, int]
    mosaic: bool = False
    notes: str = ""
    magnitude: float | None = None
    # Suggested camera position angle (deg, N->E) from the image books —
    # feeds the NINA Target Scheduler import's Rotation column (CAA rigs).
    # Optional: None means "no preference" and exports as Rotation 0.
    pa_deg: float | None = None

    @property
    def total_budget_minutes(self) -> int:
        return sum(self.budget_minutes.values())

    @property
    def is_narrowband(self) -> bool:
        """True if any narrowband filter has a positive budget. Used to
        decide whether the moon-relax behavior applies to this target."""
        return any(
            f in self.budget_minutes and self.budget_minutes[f] > 0
            for f in ("Ha", "OIII", "SII")
        )

    @property
    def is_galaxy(self) -> bool:
        return self.object_type == "GALAXY"

    @property
    def surface_brightness(self) -> float | None:
        """Mean surface brightness over the D25 ellipse, in mag/arcsec².
        ``None`` when no integrated magnitude is set.

        SB = m + 2.5·log₁₀(area), area = π·(a/2)·(b/2) in arcsec². This is
        the *average* across the whole isophotal ellipse — a galaxy's core
        is brighter and its outskirts fainter, so treat it as a
        conservative "will the whole thing show" figure, not a peak."""
        if self.magnitude is None:
            return None
        major_arcsec = self.size_arcmin[0] * 60.0
        minor_arcsec = self.size_arcmin[1] * 60.0
        area = math.pi * (major_arcsec / 2.0) * (minor_arcsec / 2.0)
        if area <= 0:
            return None
        return self.magnitude + 2.5 * math.log10(area)


@dataclass(frozen=True)
class DsoCatalog:
    """The catalog as loaded — version + defaults block + targets tuple."""
    version: str
    defaults: dict[str, Any]
    targets: tuple[DsoTarget, ...]

    def by_name(self, name: str) -> DsoTarget | None:
        """Case-insensitive lookup by canonical name. Returns None if absent."""
        needle = name.strip().casefold()
        for target in self.targets:
            if target.name.casefold() == needle:
                return target
        return None


def load_dso_catalog(path: str | Path) -> DsoCatalog:
    """Read and validate the DSO YAML catalog. Raises ValueError on schema
    violations with a message pointing at the offending entry — catalogs
    are hand-edited, so the error needs to be readable."""
    raw_path = Path(path)
    if not raw_path.exists():
        raise FileNotFoundError(f"DSO catalog not found: {raw_path}")
    with raw_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)

    if not isinstance(raw, dict):
        raise ValueError(f"{raw_path}: top-level YAML must be a mapping")

    targets_raw = raw.get("targets")
    if not isinstance(targets_raw, list) or not targets_raw:
        raise ValueError(f"{raw_path}: 'targets' must be a non-empty list")

    seen_names: set[str] = set()
    targets: list[DsoTarget] = []
    for index, item in enumerate(targets_raw):
        if not isinstance(item, dict):
            raise ValueError(f"{raw_path} targets[{index}]: must be a mapping")
        try:
            target = _parse_target(item)
        except (KeyError, TypeError, ValueError) as exc:
            name_hint = item.get("name", f"index {index}")
            raise ValueError(f"{raw_path} target '{name_hint}': {exc}") from exc
        if target.name.casefold() in seen_names:
            raise ValueError(
                f"{raw_path}: duplicate target name '{target.name}' "
                "(case-insensitive). Each catalog entry must have a unique name."
            )
        seen_names.add(target.name.casefold())
        targets.append(target)

    return DsoCatalog(
        version=str(raw.get("catalog_version", "unknown")),
        defaults=dict(raw.get("defaults", {})),
        targets=tuple(targets),
    )


def _parse_target(item: dict[str, Any]) -> DsoTarget:
    name = str(item["name"]).strip()
    if not name:
        raise ValueError("name is empty")
    ra_deg = float(item["ra_deg"])
    dec_deg = float(item["dec_deg"])
    # Strict [0, 360): a pasted negative RA (or a 360.0) would survive into
    # the TS export as a garbage sexagesimal row. Catalogs are J2000 decimal
    # degrees — normalizing here would hide the paste error, so reject.
    if not 0.0 <= ra_deg < 360.0:
        raise ValueError(f"ra_deg out of range [0, 360): {ra_deg}")
    if not -90.0 <= dec_deg <= 90.0:
        raise ValueError(f"dec_deg out of range: {dec_deg}")
    obj_type = str(item["object_type"]).strip().upper()
    if obj_type not in KNOWN_OBJECT_TYPES:
        # Warn-only would silently hide typos — be strict instead.
        raise ValueError(
            f"object_type '{obj_type}' not in {sorted(KNOWN_OBJECT_TYPES)}"
        )
    size_raw = item.get("size_arcmin")
    if (
        not isinstance(size_raw, (list, tuple))
        or len(size_raw) != 2
        or not all(isinstance(v, (int, float)) and v > 0 for v in size_raw)
    ):
        raise ValueError(f"size_arcmin must be [major, minor] positive numbers; got {size_raw!r}")
    budget_raw = item.get("budget_minutes")
    if not isinstance(budget_raw, dict) or not budget_raw:
        raise ValueError("budget_minutes must be a non-empty filter→minutes mapping")
    budget: dict[str, int] = {}
    for filter_name, minutes_raw in budget_raw.items():
        # int(90.5) would silently truncate a hand-edited fractional budget;
        # whole ints and integral floats (90, 90.0) are the only valid spellings.
        if isinstance(minutes_raw, float) and not minutes_raw.is_integer():
            raise ValueError(
                f"budget_minutes['{filter_name}'] must be whole minutes; "
                f"got {minutes_raw!r}"
            )
        budget[str(filter_name)] = int(minutes_raw)
    if any(v < 0 for v in budget.values()):
        raise ValueError("budget_minutes values must be non-negative")
    magnitude = _parse_magnitude(item.get("magnitude"))
    pa_deg = _parse_pa_deg(item.get("pa_deg"))
    return DsoTarget(
        name=name,
        common_name=str(item.get("common_name", name)),
        object_type=obj_type,
        ra_deg=ra_deg,
        dec_deg=dec_deg,
        size_arcmin=(float(size_raw[0]), float(size_raw[1])),
        constellation=str(item.get("constellation", "")).strip(),
        budget_minutes=budget,
        mosaic=bool(item.get("mosaic", False)),
        notes=str(item.get("notes", "")).strip(),
        magnitude=magnitude,
        pa_deg=pa_deg,
    )


def _parse_pa_deg(raw: Any) -> float | None:
    """Optional suggested camera PA. Absent → None. Accepts 0–360 inclusive
    (the books record 0-360 conventions) but stores it mod 360 — an author's
    ``pa_deg: 360`` parses as 0.0, so the TS export's Rotation column stays
    in [0, 360) instead of emitting ``Rotation,360``."""
    if raw is None:
        return None
    try:
        pa = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"pa_deg must be a number; got {raw!r}") from exc
    if not 0.0 <= pa <= 360.0:
        raise ValueError(f"pa_deg out of range [0, 360]: {pa}")
    return pa % 360.0


def _parse_magnitude(raw: Any) -> float | None:
    """Optional integrated magnitude. Absent → None (narrowband targets).
    Range-checked loosely: brighter than M31 (mag 3.4) or fainter than ~16
    is almost certainly a typo for a curated showpiece catalog."""
    if raw is None:
        return None
    try:
        mag = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"magnitude must be a number; got {raw!r}") from exc
    if not -5.0 <= mag <= 20.0:
        raise ValueError(f"magnitude out of plausible range: {mag}")
    return mag
