# output/ organization convention

Status: **proposed** (2026-06-05; extended 2026-06-09 with the post-06-05
additions, a `captures/` convention, and a migration tool). Migration not yet
executed — run `python scripts/organize_output.py` to see the live move plan
(dry-run by default; `--apply` executes `git mv` / `mv`, never deletes).

## Why

`output/` had grown two tangled concerns and ~5 naming conventions for the same
thing:

- The same target sprawled across dirs — e.g. `ngc6888` + `ngc6888_work` +
  `NGC6888_curveshootout`; `m97` + `M97_curveshootout`; `m57_work` +
  `m57_20260530`.
- Inconsistent case (`m97` vs `M97_…`) and keepers / iterations / scratch all
  flat in the same directory.
- Pipeline auto-output (`mira run/tonight/galaxies/transients/dso`) lived
  alongside hand-finished image processing with no separation.

## Target structure

```
output/
  runs/<config>/…            # pipeline auto-output (mira run/tonight/galaxies/…)
                             #   e.g. runs/s30_pro_jc/tonight/, runs/esprit120_jc/dso/
  processed/<target>/        # one dir per target; canonical lowercase name
      <TARGET>_<descriptor>_<date>.png    # keeper finals      (committed; TIFF via LFS)
      <TARGET>_<descriptor>_<date>.tiff
      <TARGET>_widefield_<date>.fit       # sky-viewer gallery asset (LFS)
      PROCESSING_LOG.md                   # the processing record (committed)
      *.ssf, stretch_*.py                 # scripts used        (committed)
      work/                               # ALL scratch         (gitignored)
  books/                     # curated reference artifacts (emission image books)
  trips/<trip>/              # dark-site trip plans + their reduction scripts
                             #   e.g. trips/catskills_jun18/
  site/                      # site/hardware studies (rooftop eval, horizon
                             #   compares, mounting-bracket photo annotations)
  scratch/                   # root-level one-offs pending manual triage
```

### captures/ convention (companion)

```
captures/
  <target>/<YYYY-MM-DD>/       # one night, one dir (FITS + mira_capture.json)
  <target>/combined_<desc>/    # cross-night hardlink sets fed to `mira stack`
```

This matches what `docs/photometry.md` already documents; today's reality is
flat `captures/<target>_<date>/`. **Code dependency:** the integration ledger
walks `<captures_root>/*/mira_capture.json` exactly one level deep — adopting
the nested layout requires switching `dso/ledger.py` to a recursive walk
(small change, do it in the same commit as the captures migration). Hardlink
sets stay intact under same-volume `git mv`/`mv`. Mosaic panels keep the panel
in the NIGHT dir name, not the target name (`veil/2026-06-18_p1_west/`), so
the ledger's parent-target grouping (planned) can aggregate them.

Rules:

- **One target → one `processed/<target>/` dir.** Canonical lowercase dir name
  (`m51`, `m57`, `m97`, `m13`, `m27`, `ngc4631`, `ngc6888`, …). Keeper files use
  the Title-cased catalog prefix (`M51_…`, `NGC6888_…`).
- **Keepers + log + scripts at the dir root** (committed). A "keeper" is a
  finished, chosen image: `<TARGET>_<descriptor>_<date>.{png,tiff}` plus the
  `_widefield_<date>.fit` gallery asset.
- **Everything regenerable goes in `work/`** — intermediates, curve_lab
  `variants/`, `_*`-prefixed scratch, `<curve>__<params>` dumps, `*_stack_preview`,
  `*_compare`, `.npy`, and superseded stretch iterations. All of it reproduces
  from the linear `*_cc` FITS.
- **`runs/` is volatile** (rewritten every pipeline run) and kept separate from
  the curated `processed/` tree.

## Gitignore (post-migration)

The dozen transitional scratch patterns currently in `.gitignore` collapse to
**one rule** once everything scratch lives under `work/`:

```
output/processed/**/work/
output/**/*.npy            # belt-and-suspenders
```

(Plus the existing `output/**/*.fit[s]` for linear stacks/masters, and — if
adopted — an LFS `.gitattributes` for `*.tiff` and `*_widefield_*.fit`.)

## Open decisions

1. **TIFF / `.fit` finals → git-LFS.** Keeper TIFFs (483 MB as of 2026-06-05)
   are in plain git history; the `_widefield_*.fit` gallery assets are gitignored
   entirely. git-LFS keeps clones light while still versioning the finals.
   Pulling the *already-committed* TIFFs into LFS requires a history rewrite +
   force-push — do this deliberately, not mid-session. New finals can adopt LFS
   without a rewrite.
2. **`runs/` churn.** `tonight/` outputs rewrite on every run (large diffs each
   session). Option: gitignore the volatile run files and snapshot only on
   demand, rather than committing every regeneration.

## Migration

All `git mv` (no deletions), reversible, one reorg commit per target group:

- `m51_work` + `m51_bakeoff` → `processed/m51/` (keepers to root, rest to `work/`)
- `m57_work` + `m57_20260530` → `processed/m57/`
- `m97` + `M97_curveshootout` → `processed/m97/` (`_curveshootout` → `work/`)
- `ngc6888` + `ngc6888_work` + `NGC6888_curveshootout` → `processed/ngc6888/`
- `m81` + `M81_curveshootout` → `processed/m81/` (added 06-09)
- `m13` + `m13_work` → `processed/m13/`
- `ngc4631` → `processed/ngc4631/`
- `m27` → `processed/m27/`
- `cygnus_mosaic` → `processed/cygnus/`
- `s30_pro_jc/`, `esprit120_jc/`, `practice/`, `novelty/`, `sanity/` → `runs/…`
- root-level legacy pipeline files (`candidate_queue.csv`, `best_*.csv`,
  `shared_targets.csv`, `research_notes.md`, `candidate_packets/`) → `runs/_legacy_root/`
- `esprit_emission_book`, `s30_emission_book` → `books/`
- `catskills_jun18` → `trips/catskills_jun18/`
- `rooftop_eval` + the mounting/bracket study images (`buckeye_*.png`,
  `_mele_base.png`, `_plate_end.png`, `_b*_*.png`) → `site/`
- Sh2-119 framing studies (`clamshell_*.png`, `clam_wide.jpg`) →
  `processed/sh2-119/work/` (planning artifacts for a future target)
- remaining root one-offs (`_annotate*.py`, `_webapp.log`,
  `venus_jupiter_framing.png`, `ngc7000_capture_log.txt`,
  `schedule_tonight.sh`) → `scratch/` for manual triage
- ALSO at repo root (not output/): a stray file literally named
  `C:miraoutput_annotate.py` (private-use colon glyph, path-quoting accident)
  — flagged for manual deletion (deletions are always manual).

Run `python scripts/organize_output.py` for the live plan computed from disk;
`--apply` executes it as moves (git mv for tracked, mv for untracked). Update
path references in skills, memories, and per-target `PROCESSING_LOG.md` files
as part of the move; `mira finish --preset` provenance docstrings reference
`output/{m81,m51_bakeoff,ngc6888}` paths that become `processed/…`.
```
