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

Three layers, no auth (single-user, single-machine assumption):
- **Dashboard** (`/`) — kick off `tonight`, view the schedule.
- **Photometry** (`/photometry`) — see tonight's plan with per-target
  status (awaiting / captured / processing / processed / submitted),
  click a target to run photometry. Light curves plus phase-folded
  versions render in the result, anomaly callout shows whether the
  observation is consistent with catalog + AAVSO baseline.
- **NINA monitor** (`/nina`) — live status from NINA's Advanced API
  plugin (sequence progress, equipment, current target). Polls every 5s.

Bind on `0.0.0.0` (default) so Tailscale peers can reach the dashboard
from your phone in the field.

## Photometry workflow

NINA captures FITS files into per-target subdirectories under
`captures/`. The webapp's `/photometry/<target>/` page asks only for an
observer code; comp stars and chart ID are pulled from AAVSO VSP at run
time. Process detail is in [`docs/photometry.md`](docs/photometry.md).

CLI equivalent:

```powershell
anomaly-scout submit --captures captures/RR_LYR/ --target "RR LYR" --observer-code ABC
```

Pass `--comp-stars path/to/file.json` to override the auto-fetched
sequence with a hand-curated one.

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
