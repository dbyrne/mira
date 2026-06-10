#!/usr/bin/env python
"""Plan (and optionally apply) the output/ reorganization.

Implements docs/output_organization.md: runs/ + processed/<target>/ (+work/)
+ books/ + trips/ + site/ + scratch/. DRY-RUN BY DEFAULT — prints the move
plan computed from the current disk state. `--apply` executes it: `git mv`
for tracked paths, plain move for untracked. NOTHING is ever deleted, and an
existing destination is never overwritten (the move is skipped and reported).

Keeper classification inside a target group (immediate children of each
source dir):
  stay at processed/<target>/ root:  PROCESSING_LOG*.md / PROCESSING_NOTES*.md,
      *.py, *.ssf, <NAME>_*_20??????.{png,tiff} keeper finals,
      *_widefield_*.fit gallery assets
  everything else (including whole subdirectories) -> processed/<target>/work/

Name collisions across merged sources get a `__<source>` suffix instead of
being skipped silently.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "output"

# processed/<target>  <-  source dirs merged into it
GROUPS: dict[str, list[str]] = {
    "m51": ["m51_work", "m51_bakeoff"],
    "m57": ["m57_work", "m57_20260530"],
    "m97": ["m97", "M97_curveshootout"],
    "ngc6888": ["ngc6888", "ngc6888_work", "NGC6888_curveshootout"],
    "m81": ["m81", "M81_curveshootout"],
    "m13": ["m13", "m13_work"],
    "ngc4631": ["ngc4631"],
    "m27": ["m27"],
    "cygnus": ["cygnus_mosaic"],
}

RUNS = ["s30_pro_jc", "esprit120_jc", "practice", "novelty", "sanity"]
BOOKS = ["esprit_emission_book", "s30_emission_book"]
TRIPS = ["catskills_jun18"]
SITE_DIRS = ["rooftop_eval"]
SITE_FILES = ["buckeye_mounting_annotated.png", "buckeye_mounting_v2.png",
              "_mele_base.png", "_plate_end.png", "_b_side.png", "_b1_center.png",
              "_anno_bracket_crop.png"]
SH2119_FILES = ["clamshell_esprit_framing.png", "clamshell_mosaic_2panel.png",
                "clamshell_mosaic_EW.png", "clam_wide.jpg"]
LEGACY_ROOT = ["candidate_queue.csv", "best_jersey_city.csv", "best_fairbanks.csv",
               "shared_targets.csv", "research_notes.md", "candidate_packets"]

# Active work pinned in place — the catch-all must NOT sweep these to scratch/.
EXCLUDE_RE = re.compile(r"(?i)venus|jupiter")

KEEPER_RE = re.compile(r"^[A-Za-z0-9+\-]+_.+_20\d{6}.*\.(png|tiff|tif)$")
ROOT_KEEP_RE = re.compile(r"(^(PROCESSING_(LOG|NOTES)|MOSAIC_PLAN).*\.md$)|(\.py$)|(\.ssf$)|(_widefield_.*\.fits?$)")


def is_root_keeper(name: str) -> bool:
    return bool(KEEPER_RE.match(name) or ROOT_KEEP_RE.search(name))


def git_tracked(path: Path) -> bool:
    """True if path (file or directory) has tracked content. Directories use
    a plain ls-files listing — a false negative here would degrade git mv to
    shutil.move and lose rename tracking for tracked files."""
    r = subprocess.run(["git", "ls-files", "--", str(path.relative_to(REPO))],
                       cwd=str(REPO), capture_output=True, text=True)
    return r.returncode == 0 and bool(r.stdout.strip())


class Plan:
    def __init__(self) -> None:
        self.moves: list[tuple[Path, Path]] = []
        self._claimed_dst: set[Path] = set()
        self.claimed_src: set[Path] = set()

    def add(self, src: Path, dst: Path, source_tag: str = "") -> None:
        if dst in self._claimed_dst or dst.exists():
            if source_tag:
                dst = dst.with_name(f"{dst.stem}__{source_tag}{dst.suffix}")
            if dst in self._claimed_dst or dst.exists():
                print(f"  SKIP (destination exists): {src} -> {dst}")
                return
        self.moves.append((src, dst))
        self._claimed_dst.add(dst)
        self.claimed_src.add(src)


def plan_target_group(plan: Plan, target: str, sources: list[str]) -> None:
    dst_root = OUT / "processed" / target
    for src_name in sources:
        src = OUT / src_name
        if not src.is_dir():
            continue
        for child in sorted(src.iterdir()):
            if child.is_file() and is_root_keeper(child.name):
                plan.add(child, dst_root / child.name, source_tag=src_name)
            else:
                plan.add(child, dst_root / "work" / child.name, source_tag=src_name)
        plan.claimed_src.add(src)  # source dir itself empties out


def build_plan() -> Plan:
    plan = Plan()
    for target, sources in GROUPS.items():
        plan_target_group(plan, target, sources)
    for name, bucket in ([(n, "runs") for n in RUNS] + [(n, "books") for n in BOOKS]
                         + [(n, "trips") for n in TRIPS] + [(n, "site") for n in SITE_DIRS]):
        src = OUT / name
        if src.exists():
            plan.add(src, OUT / bucket / name)
    for name in SITE_FILES:
        src = OUT / name
        if src.exists():
            plan.add(src, OUT / "site" / name)
    for name in SH2119_FILES:
        src = OUT / name
        if src.exists():
            plan.add(src, OUT / "processed" / "sh2-119" / "work" / name)
    for name in LEGACY_ROOT:
        src = OUT / name
        if src.exists():
            plan.add(src, OUT / "runs" / "_legacy_root" / name)
    # catch-all: whatever is still loose at output/ root -> scratch/
    categories = {"runs", "processed", "books", "trips", "site", "scratch"}
    for child in sorted(OUT.iterdir()):
        if child.name in categories or child in plan.claimed_src:
            continue
        if EXCLUDE_RE.search(child.name):
            print(f"  PINNED (active work, not moved): {child.name}")
            continue
        if any(child == s or child in (s.parents if False else []) for s, _ in plan.moves):
            continue
        if child not in {s for s, _ in plan.moves}:
            plan.add(child, OUT / "scratch" / child.name)
    return plan


def apply_moves(plan: Plan) -> None:
    for src, dst in plan.moves:
        dst.parent.mkdir(parents=True, exist_ok=True)
        if git_tracked(src):
            r = subprocess.run(["git", "mv", str(src.relative_to(REPO)), str(dst.relative_to(REPO))],
                               cwd=str(REPO), capture_output=True, text=True)
            if r.returncode != 0:
                print(f"  git mv failed ({r.stderr.strip()}); falling back to plain move")
                shutil.move(str(src), str(dst))
        else:
            shutil.move(str(src), str(dst))
    # tidy: remove now-empty source dirs (rmdir only succeeds when empty — not a delete)
    for d in sorted({s.parent for s, _ in plan.moves} | plan.claimed_src, reverse=True):
        try:
            if d.is_dir() and d != OUT:
                d.rmdir()
        except OSError:
            pass


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true", help="execute the plan (default: dry-run print)")
    args = ap.parse_args()

    plan = build_plan()
    by_bucket: dict[str, int] = {}
    print(f"output/ reorganization plan — {len(plan.moves)} moves\n")
    for src, dst in plan.moves:
        rel_s, rel_d = src.relative_to(OUT), dst.relative_to(OUT)
        bucket = rel_d.parts[0]
        by_bucket[bucket] = by_bucket.get(bucket, 0) + 1
        print(f"  {rel_s}  ->  {rel_d}")
    print("\nsummary: " + ", ".join(f"{k}: {v}" for k, v in sorted(by_bucket.items())))
    if not args.apply:
        print("\nDRY RUN — nothing moved. Re-run with --apply to execute "
              "(git mv for tracked, mv for untracked; nothing is deleted).")
        return
    apply_moves(plan)
    print("\nApplied. Review with `git status`; commit the reorg as its own commit.")


if __name__ == "__main__":
    main()
