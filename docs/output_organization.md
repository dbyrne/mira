# output/ organization convention

Status: **proposed** (2026-06-05). Migration not yet executed — see "Migration"
below. This doc is the standing target structure for `output/`.

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
```

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

- `m51_work` → `processed/m51/` (keepers to root, rest to `work/`)
- `m57_work` + `m57_20260530` → `processed/m57/`
- `m97` + `M97_curveshootout` → `processed/m97/` (`_curveshootout` → `work/`)
- `ngc6888` + `ngc6888_work` + `NGC6888_curveshootout` → `processed/ngc6888/`
- `m13` + `m13_work` → `processed/m13/`
- `ngc4631` → `processed/ngc4631/`
- `m27` → `processed/m27/`
- `cygnus_mosaic` → `processed/cygnus/`
- `s30_pro_jc/`, `esprit120_jc/` → `runs/s30_pro_jc/`, `runs/esprit120_jc/`

Note: update path references in skills, memories, and per-target
`PROCESSING_LOG.md` files as part of the move.
```
