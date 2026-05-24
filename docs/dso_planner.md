# DSO / narrowband planner

A curated-catalog planner for deep-sky imaging targets — separate from
Mira's variable-star queue. Use this on Esprit-rig nights when the goal
is narrowband nebula imaging (Ha/OIII/SII), broadband DSO imaging
(L+RGB), or any mix.

## What it does

- Loads a hand-curated YAML catalog of DSO targets (the shipped one is
  `data/dso_catalog/sho_targets.yaml` — ~45 narrowband-friendly targets
  from Jersey City's latitude).
- Evaluates each target against the configured site(s) using the same
  observability math as the VSX side — altitude floor, sun gate, horizon
  mask. For narrowband targets the moon gate is relaxed (Ha/SII punch
  through bright moons cleanly; OIII less so but still acceptable).
- Flags mosaic candidates by comparing each target's size against the
  rig's FOV.
- Writes a Markdown plan (`dso_plan.md`) for phone reading + a CSV
  (`dso_plan.csv`) for spreadsheet triage or NINA Target Scheduler
  import (Phase 3 will polish the NINA format).

## Quick start

```powershell
mira dso plan --config config/esprit120_jc.yaml
```

For tonight specifically:

```powershell
mira dso plan --config config/esprit120_jc.yaml --start-date 2026-08-15 --top 10
```

Output lands in `output/esprit120_jc/dso/dso_plan.md` and `dso_plan.csv`.
The top of the Markdown is a ranked table; below it, every viable
candidate gets a detail block with coords, size, FOV-fit verdict,
per-filter budget, and per-site observability.

## Catalog schema

The catalog is YAML at `data/dso_catalog/sho_targets.yaml` (override with
`--catalog` or in the config's `dso.catalog_path`). One entry:

```yaml
- name: "NGC 6888"            # canonical catalog identifier
  common_name: "Crescent Nebula"
  object_type: WR             # HII | PN | SNR | WR | DARK | REF | OPEN | GLOB
  ra_deg: 303.025             # J2000
  dec_deg: 38.350
  size_arcmin: [18, 13]       # [major, minor]
  constellation: Cyg
  budget_minutes:             # NINA wheel-label → integration minutes target
    Ha: 600
    OIII: 900
    SII: 540
  mosaic: false               # true if size exceeds single-frame FOV
  notes: "Wolf-Rayet bubble — OIII shell is the headline"
```

Adding a target is a YAML edit. The loader rejects:

- Unknown `object_type` codes (typos don't silently lose targets).
- Out-of-range RA/Dec.
- Duplicate names (case-insensitive).
- Negative budget minutes.
- Missing required fields.

Run `python -m unittest tests.test_dso_catalog` after editing the
catalog to validate.

## Config options

Optional `dso:` section in the config YAML. All fields have defaults
(see `DSO_DEFAULTS` in `src/mira/config.py`):

```yaml
dso:
  enabled: true
  catalog_path: data/dso_catalog/sho_targets.yaml
  # Rig FOV in degrees (major, minor). Esprit 120 + ASI2600MM Pro = 1.6 × 1.07.
  fov_deg: [1.6, 1.07]
  # Narrowband-aware moon gate: any target with Ha/OIII/SII budget skips
  # the VSX moon-altitude/illumination/separation filter. Broadband-only
  # targets still apply the moon gate.
  relax_moon: true
  output_subdir: dso
```

A config without a `dso:` section gets these defaults — `mira dso plan`
works on `config/s30_pro_jc.yaml` too, though the S30 Pro's FOV is
different and you'd want to override `--fov` or add a `dso:` section.

## Command flags

| Flag | Default | Meaning |
|---|---|---|
| `--config` | `config/esprit120_jc.yaml` | YAML config path |
| `--catalog` | from config | Override catalog YAML path |
| `--start-date` | today in first site's TZ | Local observing-start date (YYYY-MM-DD) |
| `--fov` | from config | Override rig FOV as `major,minor` degrees |
| `--strict-moon` | off | Disable narrowband moon-relax — apply VSX-style gate everywhere |
| `--output-dir` | from config | Override output directory |
| `--top` | all viable | Limit the ranked report to top N |

## How the ranking works

The score is intentionally simple: `minutes_above_floor + max_altitude_deg`,
with a 20% demotion for mosaic candidates (single-frame targets float
to the top). Phase 2 will fold in the integration ledger so targets with
the biggest budget deficit rank higher; for now, ranking is observability-
only.

The "best site" per candidate is the site with the most dark-time above
the local altitude floor; tiebreaker is peak altitude. For multi-site
configs you'll also see each site's individual observability in the
detail section.

## What it doesn't do (yet)

This is Phase 1 of a four-phase rollout:

- **Phase 2** — integration ledger. Walk every `mira_capture.json`
  sidecar under `captures/`, aggregate `(target, filter) → total minutes`,
  expose `mira dso status <target>` for current deficits.
- **Phase 3** — per-night scheduler with filter rotation. Pick tonight's
  target + an Ha/OIII/SII sequence weighted by both deficit and current
  moon phase (Ha when moon is bright, OIII when dark).
- **Phase 4** — Aladin Lite viewer in the webapp. Interactive sky map
  with FOV boxes and thumbnails for completed targets.

## Tips

- **Mosaic targets stay in the ranking.** They're flagged but not hidden
  so you can still plan around them (NGC 7000 / IC 1396 / Heart-Soul
  are too big for a single 1.6° frame on the Esprit).
- **Reflection nebulae and galaxies use broadband budgets** (L/R/G/B).
  The catalog includes a handful — M31, M33, NGC 7023, NGC 1977 — for
  L+RGB nights.
- **Re-running is cheap.** No remote queries; the planner is pure-Python
  over a small YAML file. Re-run as you tweak the catalog.

## See also

- `docs/rig_workflow.md` — homebase↔MeLE workflow for the Esprit rig
- `config/esprit120_jc.yaml` — the example config with a `dso:` section
- `tests/test_dso_catalog.py`, `tests/test_dso_planner.py` — what the
  schema validation guarantees + what the ranking guarantees
