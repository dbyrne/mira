# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Project Purpose

Mira produces a short observing queue of known VSX variable stars worth amateur follow-up from Jersey City, NJ. The intentional output is a candidate packet for human triage, not a discovery catalog. Scope is deliberately narrow: known VSX objects, public archive metadata, practical urban-photometry triage. See `HANDOFF.md` for project state and recommended next work.

## Commands

Editable install (Python 3.11+ required):

```powershell
python -m pip install -e .
```

Run the full pipeline:

```powershell
mira run --config config/jersey_city.yaml
```

Fast smoke test:

```powershell
mira run --config config/jersey_city.yaml --limit 50 --top 10 --aavso-top 5 --simbad-top 5 --ztf-top 0
```

Run all tests:

```powershell
python -m unittest discover -s tests
```

Run a single test file or test:

```powershell
python -m unittest tests.test_observability
python -m unittest tests.test_observability.TestObservability.test_method_name
```

CLI flags `--limit`, `--top`, `--aavso-top`, `--simbad-top`, `--ztf-top`, and `--start-date` override values from the YAML config. `--start-date` is local observing start (YYYY-MM-DD).

## Architecture

The pipeline runs as a linear orchestration in `cli.py:run`:

1. `vsx.fetch_vsx_targets` — query VSX through VizieR (`B/vsx/vsx`), sampled in RA bins to avoid RA=0 bias.
2. `scoring.build_candidates` — apply Jersey City observability + filter rules and assign initial scores. Uses `observability` for altitude/window calculations against the configured nightly window (default 20:00–01:00 local, altitude floor 45°). `minutes_above_minimum` is the best single-night time above floor, not a sum.
3. `aavso.enrich_candidates_with_aavso` — fetch recent AAVSO coverage (top N). Sparse coverage yields a scoring bonus; well-observed targets get a penalty.
4. `simbad.enrich_candidates_with_simbad` — SIMBAD TAP context and cross-identifiers (top N).
5. `ztf.enrich_with_ztf` — optional ZTF light curves through IRSA (top N). Often slow or times out; the run continues and the packet records an unavailable status. Never make ZTF mandatory for the main queue.
6. `report.write_outputs` — emit `candidate_queue.csv`, `research_notes.md`, and per-target packets in `output/candidate_packets/`.

Cross-cutting modules:

- `config.py` — YAML loaded into dataclasses; CLI overrides applied via `dataclasses.replace`.
- `models.py` — shared data structures passed between stages.
- `cache.py` — simple HTTP response cache under `data/cache/`. Delete that directory to force fresh archive queries; `data/cache/` is gitignored, but `output/` is committed as handoff artifacts.

## Implementation Notes

- VSX RA-bin sampling matters — do not switch to a single bulk query without preserving the bin sampling.
- Scoring is heuristic, not a statistical novelty model. Broaden tests in `tests/` before changing scoring or parser behavior substantially.
- AAVSO finder-chart (VSP) links are generated into packets and research notes.
- The default Jersey City config assumes: lat 40.7178, lon −74.0431, altitude floor 45°, mag floor 15, declination ≥ −10°, |galactic latitude| ≥ 12°.
