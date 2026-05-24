"""Curated DSO catalog loader.

The catalog is a YAML file the user maintains (the shipped one lives at
``data/dso_catalog/sho_targets.yaml``). No remote queries — narrowband
targets are a known finite set and the user's taste matters more than
algorithmic ranking. New targets get appended by hand; SIMBAD enrichment
is intentionally out of scope for now.
"""
from __future__ import annotations

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
    OTA + sensor — not on the target catalog)."""
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
    if not -360.0 <= ra_deg <= 360.0:
        raise ValueError(f"ra_deg out of range: {ra_deg}")
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
    budget = {str(k): int(v) for k, v in budget_raw.items()}
    if any(v < 0 for v in budget.values()):
        raise ValueError("budget_minutes values must be non-negative")
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
    )
