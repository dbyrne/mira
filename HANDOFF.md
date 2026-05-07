# AAVSO Anomaly Scout — Handoff

Clean context for continuing the project on a new machine or in a fresh
thread. README.md covers user-facing intent; this document covers
*current state of the system* and *what to read first*.

## Project goal

End-to-end variable-star observing pipeline:

1. **Pick** — find VSX targets worth amateur follow-up (urban-friendly,
   under-observed, possibly off-baseline) and score them.
2. **Plan** — schedule a session for tonight's window with greedy +
   urgency selection; export a Target Scheduler CSV for NINA.
3. **Capture** — NINA Target Scheduler imports the CSV and images each
   target. The webapp's NINA monitor shows live status.
4. **Process** — aperture photometry on each FITS, comp stars
   auto-fetched from AAVSO VSP, multi-comp ensemble.
5. **Assess** — quantitative anomaly check against catalog range and
   AAVSO recent baseline. AAVSO Extended File ready for upload.

## Repository

- GitHub: `https://github.com/dbyrne/aavso-anomaly-scout` (private)
- Default branch: `master`
- Python package entry point: `anomaly-scout`

## Setup on a new computer

```powershell
git clone https://github.com/dbyrne/aavso-anomaly-scout.git
cd aavso-anomaly-scout
python -m pip install -e .
python -m unittest discover -s tests
```

Python 3.11+ is required.

## Two ways to drive it

### Webapp (recommended for live observing)

```powershell
anomaly-scout webapp
```

Then open `http://localhost:8000` (or via Tailscale on phone). Five
tabs:

- **Tonight** (`/first-light`) — walkthrough page that turns each step
  green as it completes (settings → NINA → schedule → captures →
  photometry → submission).
- **Schedule** (`/schedule`) — phone-readable session schedule with a
  CSS timeline, per-target cards, AAVSO chart links.
- **Photometry** (`/photometry`) — each scheduled target with status,
  click to run photometry. Result page shows light curve, phase-folded
  plot, anomaly callout, AAVSO file preview, frame-deselect form.
- **NINA** (`/nina`) — live status from the Advanced API plugin, plus
  experimental "push schedule to NINA" button.
- **History** (`/runs`) — all past runs with outcomes.
- **Settings** (`/settings`) — observer code, default config, default
  hours.

### CLI (scriptable)

```powershell
anomaly-scout run --config config/multi_site.yaml
anomaly-scout tonight --config config/s30_pro_jc.yaml --hours 4
anomaly-scout submit --captures captures/RR_LYR/ --target "RR LYR" --observer-code ABC
anomaly-scout target "RR Lyr" --config config/multi_site.yaml --start-date 2026-09-15 --ztf
```

## Outputs to read first

- `output/<config>/tonight/session_schedule.html` — primary phone-
  readable plan (also served at `/schedule`).
- `output/<config>/tonight/research_notes.md` — top-line summary.
- `output/<config>/tonight/candidate_queue.csv` — ranked queue.
- `output/<config>/tonight/candidate_packets/*.md` — per-target review.

## Current architecture

```
cli.py / __main__.py    Command-line orchestration
config.py               YAML → frozen dataclasses
vsx.py                  VSX/VizieR fetch (RA-bin sampling, retry)
observability.py        Site-specific altitude/window calculations
scoring.py              Filtering + score reasons
aavso.py                Recent AAVSO coverage + Lomb-Scargle period
simbad.py               SIMBAD TAP cross-IDs
gaia.py                 Gaia DR3 color/parallax/RUWE
ztf.py                  Optional ZTF light curves + period analysis
period_analysis.py      Lomb-Scargle shared between AAVSO + ZTF
scheduler.py            Greedy session schedule with urgency bonus
session_plan.py         Menu (all viable targets) writer
session_schedule.py     Schedule (picked subset) writer + NINA CSV
nightly_html.py         session_schedule.html (timeline + cards)
report.py               Research notes, candidate packets, queue CSVs

photometry.py           FITS aperture photometry, multi-comp ensemble,
                        AAVSO Extended File writer
vsp.py                  AAVSO VSP comp-star auto-fetch
lightcurve.py           matplotlib plots (JD-vs-mag, phase-folded)
                        with AAVSO + prior-session overlays
anomaly.py              Catalog + baseline anomaly assessment

webapp/__init__.py      Flask factory
webapp/routes.py        All routes (dashboard, photometry, NINA, runs, settings)
webapp/runs.py          RunRegistry (ThreadPoolExecutor + JSON persistence)
webapp/settings.py      Persistent app-level settings
webapp/nina_client.py   NINA Advanced API client (status + push)
webapp/static/          style.css, htmx.min.js, favicon.svg
webapp/templates/       Jinja2 templates (base.html + page templates)

cache.py                File-based HTTP cache under data/cache/
tonight_pipeline.py     Shared tonight orchestration (CLI + webapp)
models.py               Shared dataclasses (VsxTarget, Observability,
                        AavsoStats, SimbadStats, GaiaStats, ZtfStats)
tests/                  unittest suite (322+ tests)
```

## Storage layout

The system writes to seven distinct roots, each with its own lifecycle.
Knowing what lives where matters for backups, debugging, and cleanup.

```
output/
└── <config>/
    ├── tonight/                      # current generated session
    │   ├── session_schedule.{html,md,csv}
    │   ├── session_overflow.csv
    │   ├── nina_targets.csv          # → import into NINA Target Scheduler
    │   ├── candidate_queue.csv
    │   ├── candidate_packets/        # one .md per top candidate
    │   └── research_notes.md
    └── archive/                      # snapshots of past tonight runs
        └── 2026-05-06/               # date-stamped copy of tonight/
            └── …

captures/                             # NINA writes here; we read here
└── <TARGET>/                         # e.g., RR_LYR/
    └── 2026-05-06/                   # one dated subdir per session
        ├── frame001.fits
        ├── frame002.fits
        ├── aavso_<TARGET>.txt        # photometry output
        ├── lightcurve.png            # photometry output
        └── lightcurve_folded.png     # photometry output

data/                                 # gitignored (regenerable)
├── cache/                            # HTTP response cache, 30-day TTL
│   ├── vsx/<digest>.json
│   ├── aavso/<digest>.json
│   ├── simbad/<digest>.json
│   ├── gaia/<digest>.json
│   ├── vsp/<digest>.json
│   └── ztf/<digest>.json
└── webapp_runs/                      # webapp state, configurable via --state-dir
    ├── <run_id>.json                 # one per pipeline/photometry run; canonical source of truth
    ├── sessions.db                   # SQLite index of finished photometry sessions
    ├── settings.json                 # observer code, default config, default hours
    └── history-charts/<slug>.png     # cached multi-night trend plots
```

**Lifecycles:**
- `output/<config>/tonight/` is overwritten every time `anomaly-scout tonight` runs.
- `output/<config>/archive/<DATE>/` is written once per night and never edited.
- `captures/<TARGET>/<DATE>/` is appended to during a NINA session; photometry
  re-writes the AAVSO file + plots in place when the user re-runs.
- `data/cache/` is purged by `anomaly-scout cleanup --cache --older-than Nd`.
- `data/webapp_runs/<run_id>.json` is the canonical run record. Submitted
  sessions are protected from `cleanup --runs`; everything else ages out.
- `data/webapp_runs/sessions.db` is a queryable index that can be rebuilt
  any time from the JSON files via `anomaly-scout migrate-runs`.

**Gitignore:** `data/cache/` and `data/webapp_runs/` are gitignored.
`output/` is *committed* as handoff artifacts so a fresh clone has
example outputs to inspect.

## Hardware setup (single observer)

- Seestar S30 Pro (30 mm OSC, IMX585) on equatorial wedge
- Polar-aligned via Seestar app
- NINA controlling capture via ASCOM Alpaca, Advanced API on :1888
- Tailscale magic DNS for phone access:
  `gaming-rig-windows.tail4ab263.ts.net:8000`

## Important implementation notes

- VSX RA-bin sampling matters — do not switch to a single bulk query
  without preserving both bin sampling and per-bin oversample.
- `_get_with_retries` in vsx.py does 3 attempts with backoff; transient
  network failures look identical to "not found" without it.
- Period analysis (`period_analysis.py`) is shared between AAVSO and
  ZTF; period disagreement is gated by min/max search range and a
  configurable peak-power threshold.
- Score-affecting bonuses applied AFTER `build_candidates` must use
  `apply_target_bonus` / `apply_target_reason` so per-site scores stay
  in sync with the global score.
- Photometry uses a multi-comp weighted ensemble (`ensemble_magnitude`
  in photometry.py): per-comp mag estimates, MAD-based >2σ outlier
  drop, weighted mean by 1/σ². CNAME=ENSEMBLE in the AAVSO file when
  2+ comps survive.
- VSP auto-fetch (`vsp.py`) is the default; manual JSON path is
  optional override.
- Anomaly thresholds (`anomaly.py`): catalog-range tolerance ±0.3 mag;
  baseline σ-cutoffs 2σ (watch) / 3σ (anomaly); minimum 10 AAVSO
  samples to trust the baseline.
- Local horizon profile (`horizon.py`): per-azimuth silhouette of
  trees/buildings, captured from Stellarium AR screenshots. Sites
  reference one via `horizon_profile_path` in the YAML, and
  observability uses `max(global_floor, horizon_at_az)` per sample
  instead of just the flat altitude floor.
- Moon proximity (`observability.moon_separation_deg`): when the moon
  is up, samples within `min_moon_separation_deg` of the moon are
  rejected. Default 30°.
- VsxTarget field naming: `bright_mag` is the brighter end of the
  catalog range (numerically smaller). `faint_mag` is either the
  dimmer end OR the amplitude in mag — `faint_is_amplitude` says which.
- RunRegistry persists to `state_dir/<run_id>.json`; in-flight runs at
  startup are marked failed.
- `_human_time` Jinja filter accepts both float (Unix epoch) and
  datetime.

## Known caveats

- Scheduler doesn't optimize slew time between targets (constant 3-min
  buffer).
- NINA push is experimental — Advanced API doesn't standardize a
  Target Scheduler import endpoint. Manual CSV import is the reliable
  path.
- Anomaly check requires AAVSO baseline of 10+ recent obs; deep-sky
  targets with sparse coverage skip the baseline check entirely.
- Photometry assumes ADU ≈ counts for noise propagation. For accurate
  errors, plumb GAIN from the FITS header.
- VSX lookup returns None on both "not found" and "transient network
  error after 3 retries" — error message acknowledges both.

## Verification

```powershell
python -m unittest discover -s tests
```

322+ tests as of this writing. Cover observability geometry, parsing
(VSX/AAVSO/SIMBAD/Gaia/ZTF/VSP), scheduler, scoring, photometry math,
ensemble photometry, webapp routes, anomaly thresholds, settings
persistence.

## Git notes

Before switching machines, ensure the working tree is clean:

```powershell
git status --short --branch
git push
```

On the new machine, clone the private repo and run the setup commands
above. Generated outputs in `output/` are committed as handoff
artifacts; `data/cache/` is gitignored.
