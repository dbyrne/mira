# AAVSO Anomaly Scout Handoff

This document is the clean context handoff for continuing the project on a new
computer or in a fresh Codex thread.

## Project Goal

Build a practical amateur astronomy workflow for Jersey City, NJ:

- find known VSX variable stars that are under-observed or under-characterized
- keep only targets that are plausible from an urban site
- produce candidate packets that are easy to vet before observing
- bias toward useful AAVSO follow-up, not one-off novelty theater

The current project scope is deliberately narrow: known VSX objects, public
archive metadata, and practical follow-up triage.

## Repository

- GitHub: `https://github.com/dbyrne/aavso-anomaly-scout`
- Visibility: private
- Default branch: `master`
- Python package entry point: `anomaly-scout`

## Setup On A New Computer

```powershell
git clone https://github.com/dbyrne/aavso-anomaly-scout.git
cd aavso-anomaly-scout
python -m pip install -e .
python -m unittest discover -s tests
```

If the editable install fails, check that Python 3.11+ is active.

## Main Run Commands

Fast smoke test:

```powershell
anomaly-scout run --config config/jersey_city.yaml --limit 50 --top 10 --aavso-top 5 --simbad-top 5 --ztf-top 0 --start-date 2026-05-04
```

Current useful run:

```powershell
anomaly-scout run --config config/jersey_city.yaml --limit 300 --top 20 --aavso-top 20 --simbad-top 20 --ztf-top 0 --start-date 2026-05-04
```

Selective ZTF enrichment:

```powershell
anomaly-scout run --config config/jersey_city.yaml --limit 300 --top 20 --aavso-top 20 --simbad-top 20 --ztf-top 3 --start-date 2026-05-04
```

ZTF/IRSA calls are often slow or unavailable. The tool should keep running and
mark the packet with an unavailable status when ZTF does not cooperate.

## Outputs To Read First

- `output/research_notes.md`: highest-signal human summary
- `output/candidate_queue.csv`: ranked machine-readable queue
- `output/candidate_packets/*.md`: per-target review packets

Generated outputs are committed because they are useful handoff artifacts.
`data/cache/` is ignored because it only stores repeatable archive/API responses.

## Current Top Candidates

As of the current generated output:

1. `ASASSN-V J160002.35+453848.8`
   - VSX: `SR`
   - SIMBAD: `2MASS J16000234+4538488`, type `S*?`
   - Recent AAVSO observations: `0`
   - Best as long-cadence monitoring.

2. `WISE J120003.9+632552`
   - VSX: `EW|EA`
   - SIMBAD: `TYC 4157-625-1`, type `EB*`
   - Recent AAVSO observations: `0`
   - Best as a time-series target.

3. `ASASSN-V J180001.26+355054.1`
   - VSX: `SR`
   - SIMBAD: `TYC 2633-490-1`, type `*`
   - Recent AAVSO observations: `0`
   - Best as long-cadence monitoring.

4. `IRAS 07557+6048`
   - VSX: `SRS`
   - SIMBAD: `IRAS 07557+6048`, type `*`
   - Recent AAVSO observations: `0`
   - Best as long-cadence monitoring.

Treat these as candidates, not claims. The next human step is to check finder
charts, comparison stars, field crowding, and recent literature before observing.

## Architecture Map

- `src/anomaly_scout/cli.py`: command-line orchestration
- `src/anomaly_scout/config.py`: YAML config dataclasses
- `src/anomaly_scout/vsx.py`: VSX/VizieR fetch and parse
- `src/anomaly_scout/observability.py`: Jersey City altitude/window calculations
- `src/anomaly_scout/scoring.py`: candidate filtering and score reasons
- `src/anomaly_scout/aavso.py`: recent AAVSO observation count
- `src/anomaly_scout/simbad.py`: SIMBAD TAP context and cross-identifiers
- `src/anomaly_scout/ztf.py`: optional ZTF light-curve enrichment
- `src/anomaly_scout/report.py`: CSV, research notes, and packets
- `src/anomaly_scout/cache.py`: simple HTTP response cache
- `tests/`: unit tests for core parsing/geometry helpers

## Important Implementation Notes

- Observability uses a practical local window from `20:00` to `01:00`.
- `minutes_above_minimum` is now the best single-night time above the altitude
  floor, not a sum across all configured nights.
- VSX rows are sampled in RA bins so the query is not biased toward RA 0.
- SIMBAD and AAVSO enrichment are intentionally shallow but useful for triage.
- AAVSO coverage affects ranking: sparse targets get a bonus; heavily covered
  targets receive a penalty.
- AAVSO finder-chart links are generated in packets and research notes.
- ZTF is optional because IRSA calls can time out; do not make it mandatory for
  the main queue.

## Known Caveats

- The current scoring is heuristic, not a statistical novelty model.
- It does not yet check field crowding from images.
- It does not yet verify AAVSO comparison-star availability beyond linking VSP.
- It does not perform period analysis or folded light-curve fitting yet.
- It does not query Gaia DR3 directly yet; SIMBAD often exposes Gaia IDs.
- It does not yet create observing-night schedules by weather or moon phase.

## Recommended Next Work

1. Add a `--target` command to enrich and regenerate one candidate packet.
2. Add Gaia DR3 context: color, parallax, absolute magnitude, RUWE if available.
3. Add a real period-check module for ZTF/TESS light curves.
4. Add VSP/finder-chart validation or at least chart ID extraction.
5. Add a field-crowding check from Pan-STARRS/DSS cutouts.
6. Split practice targets from novelty targets in the report.
7. Add weather/moon-aware nightly observing queues for Jersey City.

## Verification

Current test command:

```powershell
python -m unittest discover -s tests
```

This currently covers observability sanity checks plus AAVSO and SIMBAD parsing.
Broaden tests before changing scoring or parser behavior substantially.

## Git Notes

Before switching machines, make sure the working tree is clean:

```powershell
git status --short --branch
git push
```

On the new machine, clone the private repo and run the setup commands above.

