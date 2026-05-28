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

### `mira dso plan`

| Flag | Default | Meaning |
|---|---|---|
| `--config` | `config/esprit120_jc.yaml` | YAML config path |
| `--catalog` | from config | Override catalog YAML path |
| `--start-date` | today in first site's TZ | Local observing-start date (YYYY-MM-DD) |
| `--fov` | from config | Override rig FOV as `major,minor` degrees |
| `--strict-moon` | off | Disable narrowband moon-relax — apply VSX-style gate everywhere |
| `--output-dir` | from config | Override output directory |
| `--top` | all viable | Limit the ranked report to top N |
| `--captures-root` | from config (`captures/`) | Where to walk for the integration ledger |
| `--ignore-ledger` | off | Skip the ledger entirely — pure observability ranking (Phase-1 behavior) |

### `mira dso status`

| Flag / arg | Meaning |
|---|---|
| `--config` | YAML config (catalog + captures_root come from here) |
| `--catalog` | Override catalog YAML path |
| `--captures-root` | Override captures root |
| `target` (positional) | Canonical catalog name → per-filter detail. Omit for summary mode. |
| `--orphans` | List only orphan sessions (target_name not in catalog) |

### `mira dso research`

| Flag | Default | Meaning |
|---|---|---|
| `--config` | `config/esprit120_jc.yaml` | YAML config path |
| `--catalog` | from config | Override catalog YAML path |
| `--out` | `<catalog_dir>/research_notes.md` | Output Markdown path |

## How the ranking works

The score is intentionally simple: `minutes_above_floor + max_altitude_deg`,
with a 20% demotion for mosaic candidates (single-frame targets float
to the top). Phase 2 adds **deficit-aware scoring**: when a ledger is
available, each target's observability score is multiplied by
`0.5 + deficit_weight × deficit_fraction`, clamped to [0.5, 1.5]. So a
never-imaged target gets a 1.5× boost, a fully-imaged target gets a 0.5×
demote (but stays visible — see below), and partial completion scales
linearly in between. `deficit_weight` lives in the config's `dso:`
section and defaults to 1.0; set to 0 to disable the weighting.

The "best site" per candidate is the site with the most dark-time above
the local altitude floor; tiebreaker is peak altitude. For multi-site
configs you'll also see each site's individual observability in the
detail section.

## The integration ledger (Phase 2)

`mira dso status` walks `<captures_root>/*/mira_capture.json` and aggregates
per-(target, filter) integration time across every prior session. The
sidecar is the database — there's no separate ledger file to keep in sync.

```powershell
# Summary of every target with at least one session
mira dso status --config config/esprit120_jc.yaml

# Detail for one target — per-filter captured / budget / deficit
mira dso status --config config/esprit120_jc.yaml "NGC 6888"

# Just the orphans (captures whose target_name doesn't match the catalog)
mira dso status --config config/esprit120_jc.yaml --orphans
```

The `mira dso plan` command auto-loads the ledger by default. Pass
`--ignore-ledger` for the Phase-1 pure-observability ranking, or set
`deficit_weight: 0` in the config to keep the ledger metadata on the
output without affecting ranking order.

### Matching rule: canonical names only

Per design, the ledger matches sidecar `target_name` against the
catalog's canonical `name` field (case-insensitive but exact otherwise).
A capture session with `--target Crescent` does *not* match
`NGC 6888` — it goes into the orphan bucket. The catalog's `common_name`
field is for human display only; never use it as `--target`.

**The convention to bake in:** when you capture a DSO catalog target,
copy the canonical name from `mira dso plan`'s output into
`mira capture --target ...`. Orphans surface in `mira dso status` so
typos are immediately visible.

### Frame-count fallback

`mira capture` writes the frame count to `result.copied` at shutdown.
When a session is killed before shutdown (Ctrl-C, machine crash), the
result block is missing — the ledger falls back to globbing `*.fit*` in
the session directory and counting those, so an interrupted session
still books its actual sky time. If both the result and the FITS files
are gone, the session counts zero and is preserved in the ledger as a
zero-minute entry (so it shows up in the orphan/recent-session list).

### What the ledger doesn't measure

- **Quality.** Frames moved to `_rejected/` by `mira stack --cull-low-quality`
  still count — we're tracking *sky time*, not *frames-survived-cull*.
  A separate metric for stack-quality minutes could come later if it
  proves useful.
- **SNR.** Two 600-minute Ha stacks from different transparency or moon
  conditions give different SNRs; the ledger doesn't model this.

## What it doesn't do (yet)

This is Phase 2 of a four-phase rollout:

- ~~**Phase 2** — integration ledger~~ ✓ landed.
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

## Bright-galaxy path (`mira galaxies`)

A third target-finding concern, distinct from both the VSX variable-star
queue and the narrowband catalog above: **bright showpiece galaxies for
the S30 Pro's wide-field nights** (M51, the Leo Triplet, Markarian's
Chain, the edge-ons). It shares this planner's engine — same observability
math, same integration ledger — so it isn't a separate silo; the
distinctness is in the catalog, the ranking emphasis, and the command.

```powershell
mira galaxies plan --config config/s30_pro_jc.yaml --start-date 2026-05-28 --top 12
mira galaxies status --config config/s30_pro_jc.yaml
```

Writes `output/s30_pro_jc/galaxies/galaxy_plan.md` + `.csv`.

**Why a separate path?** For galaxies on a small OSC scope from a
light-polluted city, *integrated magnitude lies*. A mag-9 face-on spiral
(M101, M74) spreads its light thin and drowns in skyglow; a mag-10 edge-on
(NGC 891, NGC 4565) concentrates it and pops. So the catalog carries an
integrated `magnitude`, and the planner ranks on the **derived mean
surface brightness** (`SB = m + 2.5·log₁₀(ellipse area)`), not the mag:

`score = (observability + altitude) × brightness_factor(SB) × size_factor × ledger_factor`

- `brightness_factor` rewards high surface brightness.
- `size_factor` is **penalty-only** — it sinks galaxies too small to be
  more than a dot on the ~4° field, but never *bonuses* big ones (that
  would float low-SB face-on traps up the list).
- **Both are no-ops for narrowband targets** (no magnitude), so this
  cannot perturb the narrowband ranking above.

Flags in the plan:
- 🌑 **dark-site only** — mean SB fainter than `galaxies.sb_limit_mag_arcsec2`
  (default 22.5). Kept in the queue (targets shouldn't disappear), demoted.
- 🔬 **small** — major axis below FOV/40; a postage stamp on the S30,
  better shot on the longer-FL Esprit.

**Moon-strict by default** — the opposite of the narrowband `dso:`
default, because broadband galaxy imaging from the city *is* moon-sensitive.
Override with `--relax-moon` on a moonless night.

The catalog (`data/dso_catalog/galaxies.yaml`, ~50 targets) is curated by
hand like the narrowband one. Southern showpieces (M104, NGC 253) are
listed for completeness but self-filter from a JC plan — they never clear
the 45° altitude floor at +40.7° latitude.

## See also

- `docs/rig_workflow.md` — homebase↔MeLE workflow for the Esprit rig
- `config/esprit120_jc.yaml` — the example config with a `dso:` section
- `config/s30_pro_jc.yaml` — has the `galaxies:` section (S30 Pro FOV + SB floor)
- `tests/test_dso_catalog.py`, `tests/test_dso_planner.py` — what the
  schema validation guarantees + what the ranking guarantees
- `tests/test_galaxies.py` — the galaxy catalog/scoring/config guarantees
