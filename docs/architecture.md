# Architecture

A developer-oriented reference. If you're a *user* trying to install and
run Mira, read **[Getting Started](getting_started.md)** instead.

This document covers:

- [Module map](#module-map) — what each Python module is responsible for
- [Storage layout](#storage-layout) — where things get written and how
  long they stick around
- [Implementation invariants](#implementation-invariants) — non-obvious
  contracts you'd violate by accident
- [Known caveats](#known-caveats) — things the project doesn't do, on
  purpose
- [Reference setup](#reference-setup) — the hardware/software stack the
  project is developed against

For the user-facing project goal and workflow, see [README](../README.md)
and [Concepts](concepts.md).

---

## Module map

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
flats.py                Per-filter flat calibration: drive wheel,
                        auto-bracket exposure, validated series,
                        Siril master (data/flats/, gitignored);
                        resolve_master_for_lights() for stack --auto-flats
vsp.py                  AAVSO VSP comp-star auto-fetch
lightcurve.py           matplotlib plots (JD-vs-mag, phase-folded)
                        with AAVSO + prior-session overlays
anomaly.py              Catalog + baseline anomaly assessment
horizon.py              Per-azimuth horizon profile (loader + interpolator)
rehearsal.py            Synthetic-FITS dress rehearsal
submit_pipeline.py      Shared photometry orchestration (CLI + webapp)
tonight_pipeline.py     Shared tonight orchestration (CLI + webapp)

webapp/__init__.py      Flask factory
webapp/routes.py        All routes (dashboard, photometry, NINA, runs, settings)
webapp/runs.py          RunRegistry (ThreadPoolExecutor + JSON persistence)
webapp/settings.py      Persistent app-level settings
webapp/nina_client.py   NINA Advanced API client (status + push)
webapp/db.py            SQLite session-store (thread-safe wrapper)
webapp/static/          style.css, htmx.min.js, favicon.svg
webapp/templates/       Jinja2 templates (base.html + page templates)

cache.py                File-based HTTP cache under data/cache/
models.py               Shared dataclasses (VsxTarget, Observability,
                        AavsoStats, SimbadStats, GaiaStats, ZtfStats)
tests/                  unittest suite (325+ tests)
```

---

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
├── flats/                            # `mira flats` per-filter calibration
│   └── <filter>_g<gain>_<date>/
│       ├── raw/<frame>.fits          # validated raw flats
│       ├── master_flat.fit           # CANONICAL master (Siril calibrate -flat=)
│       ├── master_flat.tif/_preview.png  # human previews only
│       └── metadata.json             # filter, gain, exposure, ADU, n_frames
│   # lights from `mira capture --filter` carry a mira_capture.json
│   # sidecar; `mira stack --auto-flats` matches it to the master above
│   # (NINA's FITS carry GAIN but no FILTER keyword — verified)
└── webapp_runs/                      # webapp state, configurable via --state-dir
    ├── <run_id>.json                 # one per pipeline/photometry run; canonical source of truth
    ├── sessions.db                   # SQLite index of finished photometry sessions
    ├── settings.json                 # observer code, default config, default hours
    └── history-charts/<slug>.png     # cached multi-night trend plots
```

**Lifecycles:**
- `output/<config>/tonight/` is overwritten every time `mira tonight` runs.
- `output/<config>/archive/<DATE>/` is written once per night and never edited.
- `captures/<TARGET>/<DATE>/` is appended to during a NINA session; photometry
  re-writes the AAVSO file + plots in place when the user re-runs.
- `data/cache/` is purged by `mira cleanup --cache --older-than Nd`.
- `data/flats/<filter>_g<gain>_<date>/` is written once per `mira flats`
  run; masters are reusable session-to-session (sealed S30 Pro) until
  focus/optics change.
- `data/webapp_runs/<run_id>.json` is the canonical run record. Submitted
  sessions are protected from `cleanup --runs`; everything else ages out.
- `data/webapp_runs/sessions.db` is a queryable index that can be rebuilt
  any time from the JSON files via `mira migrate-runs`.

**Gitignore:** `data/cache/`, `data/flats/`, and `data/webapp_runs/` are gitignored.
`output/` is *committed* as handoff artifacts so a fresh clone has
example outputs to inspect.

---

## Implementation invariants

Things that are non-obvious and that you'd break by accident if you
didn't know about them. Most of these came from real bugs or design
discussions.

- **VSX RA-bin sampling.** Don't switch to a single bulk query without
  preserving both the bin sampling and the per-bin oversample with two
  OID sort directions (`+OID` and `-OID`). The dual-sort balances
  GCVS-era classical entries against newer survey discoveries; without
  it the catalog skews toward whichever epoch was indexed first.
- **`_get_with_retries` in vsx.py** does 3 attempts with backoff;
  transient network failures otherwise look identical to "not found."
- **Period analysis (`period_analysis.py`)** is shared between AAVSO and
  ZTF. Period disagreement is gated by min/max search range and a
  configurable peak-power threshold. Returns None (not False) when a
  gate fails so callers can distinguish "no signal" from "signal
  disagrees."
- **Score-affecting bonuses** applied AFTER `build_candidates` (AAVSO
  sparse, AAVSO/ZTF period disagreement, AAVSO/ZTF period discovered,
  Gaia color anomaly, Gaia crowding penalty) must use
  `apply_target_bonus` / `apply_target_reason` from `scoring.py`. These
  mirror the change to *every* per-site score+reasons so the per-site
  CSVs stay honest. Naively writing `candidate.score += X` would only
  update the global score and silently desync the per-site views.
- **`Candidate.best_site_name`** (set in `build_candidates`) is the site
  whose score is the global max. `best_observability` resolves through
  it, so unified-CSV rows are internally consistent: `primary_site`,
  observability columns, score, and reasons all reflect the same site.
- **Photometry uses a multi-comp weighted ensemble** (`ensemble_magnitude`
  in photometry.py): per-comp mag estimates, MAD-based >2σ outlier
  drop, weighted mean by 1/σ². CNAME=ENSEMBLE in the AAVSO file when
  2+ comps survive.
- **VSP auto-fetch (`vsp.py`)** is the default; manual JSON path is an
  optional override.
- **Anomaly thresholds (`anomaly.py`):** catalog-range tolerance
  ±0.3 mag; baseline σ-cutoffs 2σ (watch) / 3σ (anomaly); minimum 10
  AAVSO samples to trust the baseline.
- **Local horizon profile (`horizon.py`):** per-azimuth silhouette of
  trees/buildings, captured from Stellarium AR screenshots. Sites
  reference one via `horizon_profile_path` in the YAML, and
  observability uses `max(global_floor, horizon_at_az)` per sample
  instead of just the flat altitude floor. Wraparound through 0°/360°
  is handled by linear interpolation.
- **Moon proximity (`observability.moon_separation_deg`):** when the
  moon is up, samples within `min_moon_separation_deg` of the moon are
  rejected. Default 30°.
- **VsxTarget field naming:** `bright_mag` is the brighter end of the
  catalog range (numerically smaller). `faint_mag` is either the dimmer
  end OR the amplitude in mag — `faint_is_amplitude` says which.
- **RunRegistry** persists to `state_dir/<run_id>.json`. In-flight runs
  at startup are detected and marked failed.
- **The window-sample loop** iterates `[start, end)` (half-open). N
  intervals produce N samples; multiplying samples × `sample_minutes`
  gives the actual minutes spanned. Off-by-one here is what
  `test_window_sample_count_matches_interval_count` guards against.
- **`_human_time` Jinja filter** accepts both float (Unix epoch) and
  datetime — code at the boundary mixes both.

---

## Known caveats

- **Scheduler doesn't optimize slew time** between targets (constant
  3-min buffer). For a small home setup the slew penalty is negligible;
  if TSP-style routing is ever wanted, it goes in `scheduler.py`.
- **NINA push is experimental.** The Advanced API doesn't standardize a
  Target Scheduler import endpoint. Manual CSV import is the reliable
  path.
- **Anomaly check requires AAVSO baseline of 10+ recent obs.** Deep-sky
  targets with sparse coverage skip the baseline check entirely, so
  the only anomaly signal is catalog-range tolerance.
- **Photometry assumes ADU ≈ counts** for noise propagation. For
  accurate errors, plumb GAIN from the FITS header.
- **VSX lookup returns None** on both "not found" and "transient
  network error after 3 retries." Error message acknowledges both.

---

## Reference setup

The project is developed against this hardware/software stack. Other
combinations work; this is what's been most thoroughly exercised:

- **Telescope:** ZWO Seestar S30 Pro (30 mm OSC, IMX585) on equatorial
  wedge
- **Polar alignment:** via Seestar app
- **Capture software:** NINA controlling the scope via ASCOM Alpaca,
  with the [Advanced API plugin][advanced-api] on port 1888
- **Phone access:** Tailscale magic DNS pointing at the imaging host
  (`<your-host>.<your-tailnet>.ts.net:8000`)

Other smart telescopes (Vespera, Stellina, etc.) work as long as they
produce plate-solved FITS files.

[advanced-api]: https://github.com/christian-photo/ninaAPI

---

## Verification

```powershell
python -m unittest discover -s tests
python -m ruff check src/
python -m mypy src/mira/ --ignore-missing-imports
```

All three should be clean before merging. See
[CONTRIBUTING.md](../CONTRIBUTING.md) for the dev workflow in full.
