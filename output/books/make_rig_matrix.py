#!/usr/bin/env python
"""Cross-rig fit matrix: one row per emission target, one column per rig.

Reads the three image-book CSVs (Esprit 120 / Esprit 80 / S30 Pro) and emits
rig_fit_matrix.md — the "which rig owns this target" one-pager. Verdict =
the longest-focal-length rig that frames the target (fits/tight, smalls and
overflows excluded), i.e. the most resolution that still fits; the per-rig
cells carry the full story when you want to trade context for sampling.

Run:  python output/books/make_rig_matrix.py   (after rebuilding any book)
"""
import csv
from pathlib import Path

BOOKS = Path("output/books")
SRC = [
    ("Esprit 120", "1.60°×1.07°, rotates", BOOKS / "esprit_emission_book/emission_book.csv"),
    ("Esprit 80",  "3.37°×2.25°, rotates", BOOKS / "esprit80_emission_book/emission_book.csv"),
    ("S30 Pro",    "3.91°×2.20°, FIXED N–S", BOOKS / "s30_emission_book/emission_book.csv"),
]
OUT = BOOKS / "rig_fit_matrix.md"

CAN_FRAME = {"fits", "tight"}
SEASON = {m: i for i, m in enumerate(
    ["Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May"])}


def load(p):
    return {r["qid"]: r for r in csv.DictReader(open(p, encoding="utf-8"))}


books = [(name, fovnote, load(path)) for name, fovnote, path in SRC]
names = []
for _, _, b in books:
    names += [n for n in b if n not in names]

rows = []
for n in names:
    cells = [b.get(n) for _, _, b in books]
    base = next(c for c in cells if c)
    fits = [c["fit"] if c else "—" for c in cells]
    # verdict: most resolution that still frames it (120 -> 80 -> S30)
    verdict = "—"
    for (rig, _, _), f in zip(SRC, fits):
        if f in CAN_FRAME:
            verdict = rig + (" (tight)" if f == "tight" else "")
            break
    if verdict == "—":
        verdict = "2-panel / crop (overflows all)"
    rows.append(dict(
        qid=n, common=base["common"], size=f"{base['maj']}'×{base['min']}'",
        peak=base["peak"], maxalt=base["maxalt"], fits=fits, verdict=verdict,
    ))

rows.sort(key=lambda r: (SEASON.get(r["peak"], 99), -int(r["maxalt"])))

md = ["# Emission targets — rig fit matrix",
 "",
 "One row per image-book target, one column per rig; cell = that book's fit class "
 "(`fits` / `tight` / `small` / `EW-overflow` / `overflow`, `—` = not in that book). "
 "**Verdict = the most resolution that still frames it** (Esprit 120 → Esprit 80 → S30); "
 "read the cells when you'd rather trade sampling for context. `small` means the rig "
 "can shoot it but it's a feature for a longer FL; `EW-overflow` is the S30's fixed-frame "
 "casualty class (no rotator — E–W extent vs the 2.20° axis). Books: "
 "`esprit_emission_book/`, `esprit80_emission_book/`, `s30_emission_book/`. "
 "Shared exclusions (too low from JC): M8, M20, M16, M17.",
 "",
 "| Target | Common | Size | Peak | maxAlt | " + " | ".join(f"{n} ({f})" for n, f, _ in SRC) + " | Verdict |",
 "|---|---|---|---|---|---|---|---|---|"]
for r in rows:
    md.append(f"| {r['qid']} | {r['common']} | {r['size']} | {r['peak']} | {r['maxalt']}° | "
              + " | ".join(r["fits"]) + f" | **{r['verdict']}** |")
md.append("")
OUT.write_text("\n".join(md), encoding="utf-8")
print(f"wrote {OUT} — {len(rows)} targets")
