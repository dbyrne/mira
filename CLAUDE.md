# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Purpose

AAVSO Anomaly Scout produces a short observing queue of known VSX variable stars worth amateur follow-up. Two sites are supported out of the box (Jersey City, NJ urban site; Fairbanks, AK dark site) and a config can list any number. The intentional output is a candidate packet for human triage, not a discovery catalog. See `HANDOFF.md` for the original project state.

## Commands

Editable install (Python 3.11+ required):

```powershell
python -m pip install -e .
```

Run the full pipeline (multi-site is the typical run):

```powershell
anomaly-scout run --config config/multi_site.yaml
anomaly-scout run --config config/jersey_city.yaml
anomaly-scout run --config config/fairbanks.yaml
```

Generate a packet for a single named target without running the queue:

```powershell
anomaly-scout target "RR Lyr" --config config/multi_site.yaml --start-date 2026-09-15 --ztf
```

Plan a single observing session for tonight (uses today's date, restricts to next N hours, tuned-for-S30-Pro config):

```powershell
anomaly-scout tonight --config config/s30_pro_jc.yaml --hours 4
```

That writes `output/s30_pro_jc/tonight/`:
- `candidate_queue.csv`, `best_<site>.csv`, `shared_targets.csv`, `research_notes.md`, packet markdown — same as `run`, but filtered to tonight's window.
- `session_plan.md` — phone-readable, chronological, with per-target RA/Dec in HH:MM:SS / DMS, recommended exposure plan, AAVSO/SIMBAD chart links.
- `session_plan.csv` — same data as a CSV that can be imported into NINA's Target Scheduler or pasted into a session log.

Fast smoke test:

```powershell
anomaly-scout run --config config/multi_site.yaml --limit 50 --top 10 --aavso-top 5 --simbad-top 5 --ztf-top 0
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

CLI flags `--limit`, `--top`, `--aavso-top`, `--simbad-top`, `--gaia-top`, `--ztf-top`, `--start-date`, `--mode`, and `--output-dir` override YAML values. `--start-date` is local observing start (YYYY-MM-DD). `--mode novelty` (survey=12, classical=0), `--mode practice` (survey=0, classical=12), or `--mode mixed` (6/6) overrides the per-name bonuses; without it, the YAML's `scoring.survey_name_bonus` / `classical_name_bonus` are used. `--output-dir` overrides `output.directory` so the practice and novelty passes can write to separate trees.

The intended workflow is two passes per session:

```powershell
anomaly-scout run --config config/multi_site.yaml --start-date 2026-09-15 --output-dir output/practice
anomaly-scout run --config config/multi_site.yaml --start-date 2026-09-15 --mode novelty --ztf-top 20 --output-dir output/novelty
```

## Architecture

The pipeline runs as a linear orchestration in `cli.py:run`:

1. `vsx.fetch_vsx_targets` — query VSX through VizieR (`B/vsx/vsx`), sampled in RA bins. Each bin issues *two* queries (sort `OID` ascending and `-OID` descending) to balance GCVS-era classical entries against newer survey discoveries; results are merged, deduped by OID, and random-sampled to `per_bin_target` with a deterministic per-bin seed. The OID sorts also fix the bin-edge bias where the default sort returned rows clustered at each bin's lower RA boundary.
2. `scoring.build_candidates` — for each target, evaluates observability against every configured site; keeps the candidate if any site passes its filters + altitude floor + galactic-latitude floor. The score uses the *best* site (most minutes above floor, then highest max altitude). All viable sites are stored on the Candidate.
3. `aavso.enrich_candidates_with_aavso` — fetch recent AAVSO coverage (top N). Sparse coverage yields a scoring bonus; well-observed targets get a penalty. The same observations are run through Lomb-Scargle (via `period_analysis`) so an AAVSO period that disagrees with the VSX catalog also fires `period_disagreement_bonus` — this is how the pipeline gets period-anomaly signal for bright targets that ZTF can't see.
4. `simbad.enrich_candidates_with_simbad` — SIMBAD TAP context and cross-identifiers (top N).
5. `gaia.enrich_candidates_with_gaia` — Gaia DR3 source ID, G mag, BP-RP color, parallax, RUWE, and the `phot_variable_flag` via the ESA TAP service. A `gaia_color_anomaly_bonus` is applied when the BP-RP color is inconsistent with the VSX type family (e.g., M-Mira but BP-RP < 1.5).
6. `ztf.enrich_with_ztf` — optional ZTF light curves through IRSA (top N). Often slow or times out; the run continues and the packet records an unavailable status. Never make ZTF mandatory for the main queue. After fetching, `estimate_period_from_rows` runs Lomb-Scargle (scipy) over the (mjd, mag) data; if the peak period disagrees with the VSX catalog period (after half/double-period alias check), `period_disagreement_bonus` is applied — this is the strongest single-target anomaly signal the pipeline produces.
7. `report.write_outputs` — emit `candidate_queue.csv` (unified, ranked by global score+tiebreakers), one `best_<site>.csv` per site (filtered to candidates observable from that site, ranked score-first with per-site observability as tiebreaker), `shared_targets.csv` (multi-site only, candidates observable from 2+ sites), plus `research_notes.md` with sections for each view, and per-target packets with one Observability section per site plus Gaia and ZTF enrichment sections.

Cross-cutting modules:

- `config.py` — YAML loaded into dataclasses. `ScoutConfig.sites` is a tuple of `SiteConfig`, each with its own observer/window/filters. The shared (target-level) config sections are `vsx_query`, `scoring`, `aavso`, `simbad`, `ztf`, `output`.
- `models.py` — shared data structures. `Observability` carries `site_name`; `Candidate.observabilities` is a list ordered best-first; `Candidate.best_observability` is the shortcut.
- `cache.py` — simple HTTP response cache under `data/cache/`. Delete that directory to force fresh archive queries; `data/cache/` is gitignored, but `output/` is committed as handoff artifacts.

## Implementation Notes

- The `vsx_query.max_bright_mag` must accommodate the *deepest* site's `prefer_max_mag`. A target is hard-rejected at a site when `bright_mag > prefer_max_mag + FAINT_TOLERANCE_MAG` (1.0 mag, in `scoring.py`).
- VSX RA-bin sampling matters — do not switch to a single bulk query without preserving both the bin sampling and the per-bin oversample+random-sample. Server-side `-sort=OID` is part of that contract.
- `minutes_above_minimum` on `Observability` is the *best single-night* time above the altitude floor *during darkness* — samples where the sun is above `window.max_sun_altitude_deg` (default −12, nautical) are excluded before counting. Multiple sites compute this independently.
- The window-sample loop iterates `[start, end)` (half-open). N intervals produce N samples; multiplying samples × `sample_minutes` gives the actual minutes spanned. An off-by-one here is what the test `test_window_sample_count_matches_interval_count` guards against.
- Period analysis (`period_analysis.py`) is shared by ZTF and AAVSO. `assess_period_disagreement` returns `None` (not False) and a gating note in three cases: catalog period below the searched minimum, catalog period above `time_span / 2`, or peak power below the configurable confidence threshold. Only when all gates pass does it return True/False.
- Score-affecting bonuses applied AFTER `build_candidates` (AAVSO sparse, AAVSO/ZTF period disagreement, AAVSO/ZTF period discovered, Gaia color anomaly, Gaia crowding penalty) must use `apply_target_bonus` / `apply_target_reason` from `scoring.py`. These mirror the change to *every* per-site score+reasons so the per-site CSVs stay honest. Naively writing `candidate.score += X` would only update the global score and silently desync the per-site views.
- `Candidate.best_site_name` (set in `build_candidates`) is the site whose score is the global max. `best_observability` resolves through it, so unified-CSV rows are internally consistent: `primary_site`, observability columns, score, and reasons all reflect the same site. Don't introduce divergent "best by minutes" semantics anywhere — sort the per-site list of `(site, observability)` for display, but the canonical "best site" is by score.
- `compute_packet_union_oids` returns the OIDs that appear in any top-N view (global + per-site + shared). The CLI passes this set to AAVSO/SIMBAD/Gaia enrichers as `extra_oids` so a target that's #1 in JC's queue but #300 globally still gets enriched. ZTF stays strictly top-N because IRSA is slow and rate-limited.
- `cached_get` enforces a 30-day TTL by default. Pass `max_age_days=0` (or negative) to keep entries forever for queries known not to drift.
- The `tonight` subcommand overrides each site's `observing_window.nights` to 1 via `dataclasses.replace`, runs the standard pipeline against today's date, then post-filters candidates whose `best_local_time` falls in `[now − 1h, now + N hours]`. Output goes to `output_dir / tonight/` so it's separate from the multi-night queue.
- `session_plan.py` produces a phone-readable Markdown plan plus a NINA-importable CSV. Per-target exposure recommendations (`recommended_exposure_plan`) are tuned for the S30 Pro in EQ mode: 5s/15s/30s/60s for bright/mid/faint/very-faint targets. Adjust per actual sky conditions.
- `config/s30_pro_jc.yaml` is the gear-tuned profile: 30mm OSC sensor reach (`prefer_max_mag: 12`), urban-amplitude floor (`min_catalog_amplitude_mag: 0.20`), no fast eclipsing/short-period types in `include_types`, ZTF disabled.
- Solar position is computed by `sun_position` in `observability.py` (low-precision, ~1° accuracy — fine for "is it dark"). To disable the darkness filter for a site, set `max_sun_altitude_deg: 0` (sun-on-horizon).
- VSX type matching is token-aware. `tokenize_var_type` splits on `/` and `|`, strips trailing `?` and `:`. Include patterns can be exact (e.g., `EW`) or family wildcards with a trailing `*` (e.g., `SR*` matches SR/SRA/SRB/SRC/SRD/SRS but not the unrelated string `MSR`). The chief regression we guard against in `test_prefix_wildcard_does_not_match_via_substring` is `L` matching `ELL`.
- `is_uncertain_type` flags only real uncertainty markers — `?`, `:`, `|` modifiers in the type string, blank type, or the broad categories `VAR`/`MISC`. Well-defined classes like `SR`, `SRA`, `LB`, `RRAB` are *not* uncertain.
- Sorting uses `candidate_sort_key` (in `scoring.py`) — score desc, then AAVSO recent_obs asc (None last), then minutes-above-floor desc, max-altitude desc, amplitude desc. The aavso re-sort after enrichment uses the same key.
- `survey_name_bonus` and `classical_name_bonus` are mutually exclusive per target (a name is either survey-prefixed via `is_survey_name` or matches `GCVS_NAME_RE`, not both). Tune the two values to bias the queue toward novelty (12/0), classical practice (0/12), or mixed (6/6, default).
- Scoring is heuristic, not a statistical novelty model. Site-dependent bonuses (`bright_target_bonus`, `clean_field_bonus`, altitude/window bonuses) use the best site's filters and window.
- AAVSO finder-chart (VSP) links are generated into packets and research notes.
- Default site assumptions:
  - Jersey City: lat 40.7178, lon −74.0431, altitude floor 45°, prefer mag ≤ 14, |b| ≥ 12°.
  - Fairbanks: lat 64.8378, lon −147.7164, altitude floor 25°, prefer mag ≤ 16.5, |b| ≥ 5°. Note that Fairbanks has no astronomical darkness from roughly early May through early August — pick a `--start-date` accordingly.
