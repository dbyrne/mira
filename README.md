# AAVSO Anomaly Scout

End-to-end variable-star observing tool: it picks targets worth a closer
look, schedules a session, runs photometry on the captured frames, and
flags whether the result deviates from expectations. Tuned for amateur
gear from urban sites (Jersey City, NJ baseline) but multi-site with a
dark-sky example (Fairbanks, AK) included.

For a clean continuation in a fresh thread or on another computer, start
with [`HANDOFF.md`](HANDOFF.md). For Claude Code instances, see
[`CLAUDE.md`](CLAUDE.md).

## What it does

1. **Pick** — Queries VSX through VizieR (`B/vsx/vsx`), enriches top
   candidates with AAVSO recent coverage, SIMBAD context, Gaia DR3
   crowding/color, and optionally ZTF light curves. Scores for amateur
   follow-up value, with a Lomb-Scargle pass that flags catalog/observed
   period disagreement.
2. **Plan** — Greedy session scheduler picks the highest-value targets
   that fit in tonight's window, biasing toward setting-soon urgency.
   Output: a chronological schedule with per-target packets.
3. **Capture** — NINA Target Scheduler ingests the exported CSV directly
   in execution order. The webapp's NINA monitor shows live status.
4. **Process** — Differential aperture photometry on each FITS frame,
   comparison stars auto-fetched from AAVSO VSP. Outputs an AAVSO
   Extended File Format submission file.
5. **Assess** — Compares your session median to the VSX catalog range
   and AAVSO recent baseline; surfaces a quantitative anomaly callout
   (consistent / watch / anomaly) so unusual results don't get lost in
   the data.

## Quick start

```powershell
python -m pip install -e .
```

### Generate a queue (research mode)

```powershell
anomaly-scout run --config config/multi_site.yaml
```

Outputs in `output/`: `candidate_queue.csv`, `best_<site>.csv`,
`shared_targets.csv`, `research_notes.md`, and per-target packets.

### Plan tonight's session

```powershell
anomaly-scout tonight --config config/s30_pro_jc.yaml --hours 4
```

Outputs in `output/s30_pro_jc/tonight/`:
- `session_schedule.html` — the primary phone-readable doc, with a
  horizontal timeline at the top, a quick-glance schedule table, and a
  detailed card per target.
- `nina_targets.csv` — NINA Target Scheduler import, in execution order.
- The standard candidate-queue artifacts (CSVs, packets) restricted to
  tonight's window.

### Webapp (recommended for live use)

```powershell
anomaly-scout webapp
```

Eight tabs, no auth (single-user, single-machine assumption):
- **Tonight** (`/first-light`) — first-light walkthrough that turns
  green as each step completes (settings → NINA → schedule → captures
  → photometry → AAVSO submission).
- **Schedule** (`/schedule`) — phone-readable session plan with a
  horizontal timeline, per-target cards, AAVSO chart links.
- **Photometry** (`/photometry`) — tonight's plan with per-target
  status, plus all dated capture sessions. Click a target to run
  photometry. Result page shows light curves (with AAVSO baseline
  + your prior nights overlaid), phase-folded plot, anomaly callout
  with the numbers, AAVSO file preview, and a per-frame deselect form.
- **NINA monitor** (`/nina`) — live status from NINA's Advanced API
  plugin (sequence progress, equipment, current target). Polls every 5s.
- **Data** (`/data/sessions`) — queryable history from the SQLite
  session store. Per-target view at `/data/target/<slug>` includes
  a multi-night light curve color-coded by session.
- **Archive** (`/archive`) — snapshots of past `tonight` runs.
- **History** (`/runs`) — every persisted run record.
- **Settings** (`/settings`) — observer code, default config, default hours.

Bind on `0.0.0.0` (default) so Tailscale peers can reach the dashboard
from your phone in the field.

## Local horizon profile

Real observing locations have trees, houses, and balcony rails that
block specific directions. The standard altitude floor (e.g. 45° from
JC) treats the sky as a clean dome, but a target that peaks behind a
tree at its best moment is wasted. To handle this, sites can carry an
optional **horizon profile** — a per-azimuth silhouette of the local
obstruction line.

`config/horizon_balcony_jc.yaml` is a real example captured from
Stellarium AR screenshots (39 points, ±5° az / ±3° alt precision).
Reference it from the site config:

```yaml
sites:
  - name: Jersey City
    horizon_profile_path: config/horizon_balcony_jc.yaml
    observer: { ... }
    observing_window: { ... }
```

`evaluate_observability` then uses `max(global_floor, horizon_at_az)`
per sample, dropping minutes where the target is technically high
enough but actually behind a tree.

## Photometry workflow

NINA captures FITS files into per-target subdirectories under
`captures/`. The webapp's `/photometry/<target>/` page asks only for an
observer code; comp stars and chart ID are pulled from AAVSO VSP at run
time. Process detail is in [`docs/photometry.md`](docs/photometry.md).

CLI equivalent:

```powershell
anomaly-scout submit --captures captures/RR_LYR/2026-05-06/ --target "RR LYR" --observer-code ABC
```

Pass `--comp-stars path/to/file.json` to override the auto-fetched
sequence with a hand-curated one. Captures should be organized as
`captures/<TARGET>/<YYYY-MM-DD>/*.fits` so multi-night data stays
separate; the legacy flat layout `captures/<TARGET>/*.fits` still works.

## What lands where

The system writes to seven storage roots (full diagram in HANDOFF.md):

- `output/<config>/tonight/` — current schedule + packets + NINA CSV
- `output/<config>/archive/<DATE>/` — snapshots of past nights
- `captures/<TARGET>/<DATE>/` — NINA frames + per-session photometry outputs
- `data/cache/` — HTTP response cache (30-day TTL, gitignored)
- `data/webapp_runs/<run_id>.json` — canonical run records
- `data/webapp_runs/sessions.db` — queryable session index (SQLite)
- `data/webapp_runs/settings.json` — observer code, defaults

`anomaly-scout cleanup --runs --cache --older-than 90d` prunes by age;
submitted sessions are protected.

## Modes

`--mode novelty` biases toward survey-prefixed (Gaia DR3 NNN…)
targets. `--mode practice` biases toward classical GCVS variables.
`--mode mixed` is half-and-half. The intended workflow is two passes:

```powershell
anomaly-scout run --config config/multi_site.yaml --output-dir output/practice
anomaly-scout run --config config/multi_site.yaml --mode novelty --ztf-top 20 --output-dir output/novelty
```

Generated packets are starting points for human review, not discovery
claims. Always inspect VSX, SIMBAD, recent literature, field crowding,
and your own calibrated photometry before submitting anything new.

## Sites

Defaults assume Jersey City, NJ (urban: 45° altitude floor, mag ≤ 14,
|b| ≥ 12°) and Fairbanks, AK (dark: 25° floor, mag ≤ 16.5, |b| ≥ 5°).
Note Fairbanks has no astronomical darkness from roughly early May
through early August — pick a `--start-date` accordingly.

## Data sources

- VSX through VizieR: `B/vsx/vsx`
- AAVSO recent coverage through the VSX object API
- AAVSO comparison-star sequences through VSP:
  `https://app.aavso.org/vsp/api/v2/chart/`
- SIMBAD context through the CDS SIMBAD TAP service
- Gaia DR3 context through VizieR `I/355/gaiadr3`
- ZTF light curves through IRSA:
  `https://irsa.ipac.caltech.edu/cgi-bin/ZTF/nph_light_curves`
- NINA Advanced API plugin (default `http://localhost:1888`)

Successful network calls are cached under `data/cache/` (gitignored).
Delete to force fresh archive queries.

## Tests

```powershell
python -m unittest discover -s tests
```
