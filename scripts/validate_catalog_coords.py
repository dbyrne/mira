"""Audit hand-edited catalog coordinates against SIMBAD.

The Medusa bug (Abell 21 shipped at the galaxy CLUSTER's position, 100 deg
from the nebula) came from an unverified name->coordinate step. Run this
after editing any data/dso_catalog/*.yaml by hand:

    python scripts/validate_catalog_coords.py

Thresholds: >30' = almost certainly wrong (FIX); 10-30' = check by hand.
Rows whose centers are DELIBERATELY offset from the SIMBAD object (framing
anchors for sprawling complexes) are listed in INTENTIONAL and skipped.
"Abell N" PNe must resolve via "PN A66 N" — plain Abell names hit clusters.

First full audit 2026-06-11: 11 rows in sho_targets.yaml were >30' off
(both Veil halves ~1 deg off; Abell 31/78 resolved to galaxy clusters);
galaxies.yaml was clean 51/51.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from mira.dso.catalog import load_dso_catalog  # noqa: E402

from astroquery.simbad import Simbad  # noqa: E402
from astropy.coordinates import SkyCoord  # noqa: E402
import astropy.units as u  # noqa: E402

QUERY_FIX = {
    "Abell 21": "PN A66 21",
    "Abell 31": "PN A66 31",
    "Abell 78": "PN A66 78",
}

# (catalog, name) pairs whose centers are deliberate framing anchors, with
# the reason — these are NOT errors.
INTENTIONAL = {
    ("sho_targets.yaml", "IC 1318"): "centered on Sadr, the frame anchor for the 4x3 deg complex",
    ("sho_targets.yaml", "NGC 2237"): "centered on the NGC 2244 cluster = Rosette center (SIMBAD's 2237 is a rim segment)",
    ("sho_targets.yaml", "NGC 7822"): "centered on Ced 214/Berkeley 59 core per the row's common_name",
}


def resolve(name: str):
    try:
        r = Simbad.query_object(QUERY_FIX.get(name, name))
        if r is None:
            return None
        row = r[0]
        rc = "ra" if "ra" in r.colnames else "RA"
        dc = "dec" if "dec" in r.colnames else "DEC"
        try:
            return SkyCoord(float(row[rc]) * u.deg, float(row[dc]) * u.deg)
        except Exception:
            return SkyCoord(str(row[rc]), str(row[dc]), unit=(u.hourangle, u.deg))
    except Exception:
        return None


def audit(path: str) -> int:
    cat = load_dso_catalog(Path(path))
    fname = Path(path).name
    print(f"\n=== {path} ({len(cat.targets)} targets) ===")
    bad = check = unresolved = skipped = 0
    for t in cat.targets:
        if (fname, t.name) in INTENTIONAL:
            skipped += 1
            continue
        sc = resolve(t.name)
        if sc is None:
            unresolved += 1
            print(f"  UNRESOLVED  {t.name:<22} ({t.common_name})")
            continue
        cat_c = SkyCoord(t.ra_deg * u.deg, t.dec_deg * u.deg)
        sep = cat_c.separation(sc).arcminute
        if sep > 30:
            bad += 1
            print(f"  FIX  {t.name:<22} cat=({t.ra_deg:.3f},{t.dec_deg:+.3f}) "
                  f"simbad=({sc.ra.deg:.3f},{sc.dec.deg:+.3f}) sep={sep:.0f}'")
        elif sep > 10:
            check += 1
            print(f"  check {t.name:<21} sep={sep:.0f}'  ({t.common_name})")
    print(f"  -> {bad} FIX, {check} check, {unresolved} unresolved, "
          f"{skipped} intentional-skipped")
    return bad


if __name__ == "__main__":
    total_bad = 0
    total_bad += audit("data/dso_catalog/sho_targets.yaml")
    total_bad += audit("data/dso_catalog/galaxies.yaml")
    sys.exit(1 if total_bad else 0)
