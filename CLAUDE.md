# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Purpose

Mira is the software side of a **two-mission home observatory**:

1. **Variable-star photometry (the original mission):** produce a short observing queue of known VSX variable stars worth amateur follow-up, then reduce captures into AAVSO submissions (`mira run/tonight` → capture → `mira submit`). Two sites are supported out of the box (Jersey City, NJ urban site; Fairbanks, AK dark site) and a config can list any number. The intentional output is a candidate packet for human triage, not a discovery catalog.
2. **Deep-sky astrophotography (currently the dominant mode):** plan, capture, and finish pretty-picture targets across five target-finding paths (VSX variables, narrowband DSO, bright galaxies, transients, emission nebulae), with per-rig image books, dark-site trip kits, and a verified finishing pipeline (`mira solve/cull/stack/finish`).

The two missions deliberately share one engine (sites, observability, scoring, ledger, capture/stack tooling) and diverge only at catalogs, scoring surfaces, and output reports — that duality is a feature, not an inconsistency to resolve. See `docs/architecture.md` for the module map, storage layout, and implementation invariants; `docs/rigs.md` for the hardware truth.

## Rigs

Three rigs share the codebase (full hardware truth: **`docs/rigs.md`** — when an older plan doc disagrees with it, `rigs.md` wins). Pick the profile that matches what's on the pier tonight.

- **ZWO Seestar S30 Pro (Jersey City)** — wide-field OSC scout. Config: `config/s30_pro_jc.yaml`. **Measured field 3.9°×2.2° @ 3.66″/px (eff. fl ≈ 163mm — use `-focal=163`, not nominal 150)**, fixed frame (long axis ≈ N–S). Reaches mag ~12, operated on an equatorial wedge (**EQ mode, not alt-az** — so no field rotation; long subs are fine), single-machine workflow (NINA + Mira on the same laptop). LP dual-band / IR-cut filters only — AAVSO submissions emit TG (tri-color green) per the OSC convention, not Johnson V.
- **Sky-Watcher Esprit 80 ED + shared ASI2600MM train + AM7 (Jersey City / trips)** — the in-between field. Config: `config/esprit80_jc.yaml`. 400mm f/5 → 3.37°×2.25° @ 1.94″/px, manual camera rotation (per-target PA in its image book). Shares the 120's *entire* camera train, mount, MeLE, and finder-shoe guide module — only the tube swaps (~10 min). Role: dark-site trips, broadband LRGB dust/reflection, and the medium-large emission complexes the 120 must mosaic. Reaches mag ~15 for photometry (true Johnson V). Flats are paper-mode only (the Wanderer panel doesn't fit the 80).
- **Sky-Watcher Esprit 120 EDX + ASI2600MM Pro + AM7 (Jersey City)** — science rig. Config: `config/esprit120_jc.yaml`. 840mm f/7 → 1.6°×1.07° @ 0.92″/px. Reaches mag ~16 from urban skies, guided EQ with autofocus, Antlia LRGB-V (V is Johnson-V photometric) + SHO 3nm narrowband, motorized Wanderer Cover V4-EC 190mm for unattended flats. Two-machine workflow: MeLE Quieter 4C on the rig drives NINA, homebase plans + processes + submits. See `docs/rig_workflow.md` for the Syncthing-based split and Siril Live Stack integration.

The Esprit 120 is *primarily a narrowband astrophotography rig* in the medium term. Mira plans only its variable-star photometry nights; narrowband nights run directly through NINA Target Scheduler without going through `mira tonight`. The `esprit120_jc.yaml` profile is for photometry use only. Cross-rig target arbitration ("which rig owns this object") lives in `output/books/rig_fit_matrix.md`.

## Docs map

By mission — hardware/current-state first, then per-mission workflow docs:

- **Hardware truth:** `docs/rigs.md` (all three rigs, shared-train model, gotchas). `astrophotography_rig_plan_v7/v8.md` are planning **history** only.
- **Architecture/invariants:** `docs/architecture.md` (module map), `docs/output_organization.md` (output/ layout convention), `docs/concepts.md`, `docs/getting_started.md`, `docs/FIELD_GUIDE.md`.
- **Photometry mission:** `docs/photometry.md` (reduce + AAVSO submit), `docs/comp_stars_example.json`, `docs/nina_setup.md` (S30), `docs/nina_setup_esprit.md` (Esprit), `docs/esprit_preflight_30d.md`.
- **Astrophotography mission:** `docs/dso_planner.md` (planner phases), `docs/rig_workflow.md` (MeLE ↔ homebase split, Siril Live Stack), image books under `output/books/`, trip kits under `output/trips/<trip>/`, finishing recipes baked in `src/mira/finish_presets.py`.
- **Shared ops:** `docs/troubleshooting.md`, `docs/horizon_profile.md`, `plans/` for open design docs (incl. `plans/pixinsight_evaluation.md`).

## Commands

Editable install (Python 3.11+ required):

```powershell
python -m pip install -e .
```

Run the full pipeline (multi-site is the typical run):

```powershell
mira run --config config/multi_site.yaml
mira run --config config/jersey_city.yaml
mira run --config config/fairbanks.yaml
```

Generate a packet for a single named target without running the queue:

```powershell
mira target "RR Lyr" --config config/multi_site.yaml --start-date 2026-09-15 --ztf
```

Plan a DSO / narrowband imaging session from a curated catalog (separate path from the VSX variable-star queue; for the Esprit rig's nebula nights):

```powershell
mira dso plan --config config/esprit120_jc.yaml
mira dso plan --config config/esprit120_jc.yaml --start-date 2026-08-15 --top 10
```

That writes `output/runs/esprit120_jc/dso/`:
- `dso_plan.md` — ranked queue + per-target detail. Phone-readable.
- `dso_plan.csv` — flat rows for spreadsheet triage / NINA Target Scheduler import.

Inspect what's been imaged so far via the integration ledger (walks `mira_capture.json` sidecars under `captures/`):

```powershell
mira dso status --config config/esprit120_jc.yaml             # summary across all imaged targets
mira dso status --config config/esprit120_jc.yaml "NGC 6888"  # per-filter detail + deficit
mira dso status --config config/esprit120_jc.yaml --orphans   # sessions with target_name not in catalog
```

Plan a bright-galaxy imaging session (a *third* target-finding path, distinct from the VSX variable-star queue and the narrowband `dso` catalog; built for the S30 Pro's wide-field galaxy nights — M51, Leo Triplet, Markarian's Chain, edge-ons):

```powershell
mira galaxies plan --config config/s30_pro_jc.yaml
mira galaxies plan --config config/s30_pro_jc.yaml --start-date 2026-05-28 --top 12
mira galaxies status --config config/s30_pro_jc.yaml          # integration ledger (shared with dso)
```

That writes `output/runs/s30_pro_jc/galaxies/` (`galaxy_plan.md` + `.csv`). Ranking is by observability **× surface brightness** (not integrated magnitude — SB is what survives urban light pollution on a 30mm OSC scope) **× a size penalty** for galaxies too small to be more than a dot on the wide field. Low-SB face-ons (M101, M33, M74) stay in the queue but are flagged "dark-site only"; sub-FOV/40 galaxies are flagged "better on the Esprit". Moon-strict by default (broadband, unlike narrowband `dso`).

Check for bright transients (supernovae/novae) worth follow-up tonight — a *fourth* target-finding path, and the most moon-tolerant one (transients are point sources, so moonlight barely touches them, and they're AAVSO-submittable):

```powershell
mira transients --config config/s30_pro_jc.yaml                 # S30 reach (mag ~12)
mira transients --config config/esprit120_jc.yaml               # deeper reach (mag ~16)
mira transients --config config/s30_pro_jc.yaml --max-mag 14    # override the reach limit
```

That writes `output/<config>/transients/` (`transients.md` + `.csv`). Scrapes Rochester Astronomy's curated "active supernovae over mag 17" table, filters by observability from the site(s) and the rig's magnitude reach, and ranks reachable-first then brightest. Targets fainter than the reach are still listed under "beyond this rig's reach" (so you see what a deeper rig could grab); stale entries (last obs > 1 month) are flagged. Note the S30's ~mag-12 reach means it usually finds **0 within reach** — most amateur-bright SNe are mag 14–16, Esprit territory.

Plan an emission-nebula session (a *fifth* target-finding path — HII regions, planetary nebulae, supernova remnants, WR bubbles — moon-relaxed, and the **rig-agnostic** one: the same catalog frames the giants as mosaics on the Esprit and single-shot on the S30):

```powershell
mira emission plan --config config/esprit120_jc.yaml     # single-frame 1.6°×1.07°
mira emission plan --config config/esprit80_jc.yaml      # mid-field 3.37°×2.25°
mira emission plan --config config/s30_pro_jc.yaml       # wide-field 3.9°×2.2° (measured)
mira emission plan --config config/s30_pro_jc.yaml --start-date 2026-08-15 --top 12
mira emission status --config config/esprit120_jc.yaml   # integration ledger
mira emission research --config config/esprit120_jc.yaml # offline catalog notes
```

That writes `output/<config>/emission/` (`dso_plan.md` + `.csv`, same DSO report). The curated catalog (`data/dso_catalog/emission_nebulae.yaml`, ~40 emission targets, union of the Esprit 120 + Esprit 80 + S30 image books under `output/books/{esprit,esprit80,s30}_emission_book/`) is rig-agnostic — the per-rig `emission:` config section sets `fov_deg`, so the giant complexes (North America, Heart) are mosaic-flagged on the Esprit 120 single frame but fit one Esprit 80 / S30 frame. `output/books/rig_fit_matrix.md` (regen: `python output/books/make_rig_matrix.py`) is the cross-rig one-pager: per-target fit class on all three rigs + a most-resolution-that-frames-it verdict.

Inventory the raw capture data (walks every `captures/` session dir — sidecars + FITS headers — and writes the committed what-do-we-have report linking sessions to `output/processed/` results):

```powershell
mira inventory                                   # -> output/inventory/captures_inventory.{md,csv}
mira inventory --captures-root captures --out output/inventory
```

Read-only by design: legacy dirs without a `mira_capture.json` are reported from FITS headers/dirnames (filter honestly "?" — FITS carry no FILTER keyword), never backfilled, so `--auto-flats` can never be fed a guessed filter. Regenerate + commit after capture sessions.

Plan a single observing session for tonight (uses today's date, restricts to next N hours, tuned-for-S30-Pro config):

```powershell
mira tonight --config config/s30_pro_jc.yaml --hours 4
```

That writes `output/runs/s30_pro_jc/tonight/`:
- `candidate_queue.csv`, `best_<site>.csv`, `shared_targets.csv`, `research_notes.md`, packet markdown — same as `run`, but filtered to tonight's window.
- `session_schedule.md` — **the primary phone-reading doc.** A prescriptive, chronological plan: a quick-glance time-slot table, then a detailed section per scheduled target embedded inline (catalog, observability, why bullets, AAVSO recent observations, SIMBAD/Gaia/ZTF context). Footer lists overflow candidates that didn't fit the window.
- `session_schedule.csv` — tabular schedule (order, start/end timestamps, target, exposure plan).
- `session_plan.md` / `session_plan.csv` — the *menu* view: all viable candidates chronologically. Useful when you want to override the auto-pick.
- `nina_targets.csv` — NINA Target Scheduler import format. Contains **only the scheduled subset, in execution order**, so the imported rows match the schedule.

After NINA captures FITS files, run photometry and produce an AAVSO upload:

```powershell
mira submit `
  --captures "C:/NINA/captures/RR_LYR/" `
  --target "RR LYR" `
  --comp-stars docs/comp_stars/rr_lyr.json `
  --observer-code ABC `
  --chart-id X12345AAB
```

This reads each FITS, runs circular-aperture differential photometry against
the comp stars listed in the JSON file, and writes
`aavso_<TARGET>.txt` (AAVSO Extended File Format) for manual upload at
https://www.aavso.org/webobs/file.

Per-filter flat calibration (motorized Wanderer panel on the Esprit closes the cover + lights up automatically; on the S30 tape paper over the aperture once, then walk away):

```powershell
mira flats --gain 120 --target-adu 30000 --frames 25
mira flats --filters LP,IR --gain 120          # explicit subset
```

The loop closes via the capture sidecar (NINA FITS have no FILTER keyword):

```powershell
mira capture --ra .. --dec .. --exposure 45 --gain 120 --filter LP --dest captures/x
mira stack --lights captures/x --out output/x.tif --auto-flats   # resolves LP_g120 master
```

Drives the NINA filter wheel, auto-brackets exposure (wide geometric scan
then a linear-model fine refine to ~target ADU), captures a validated
series per filter, and builds a Siril master flat each into
`data/flats/<filter>_g<gain>_<date>/` (+ `metadata.json`, gitignored).
Opaque positions (e.g. a `Dark` blocking filter) are auto-detected and
skipped. The S30 Pro is a sealed system, so a master flat is reusable
session-to-session for that filter/gain until focus or optics change.

Fast smoke test:

```powershell
mira run --config config/multi_site.yaml --limit 50 --top 10 --aavso-top 5 --simbad-top 5 --ztf-top 0
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
mira run --config config/multi_site.yaml --start-date 2026-09-15 --output-dir output/runs/practice
mira run --config config/multi_site.yaml --start-date 2026-09-15 --mode novelty --ztf-top 20 --output-dir output/runs/novelty
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
- `config/s30_pro_jc.yaml` is the gear-tuned profile for the Seestar S30 Pro: 30mm OSC sensor reach (`prefer_max_mag: 12`), urban-amplitude floor (`min_catalog_amplitude_mag: 0.20`), no fast eclipsing/short-period types in `include_types`, ZTF disabled.
- `config/esprit120_jc.yaml` is the gear-tuned profile for the Esprit 120 EDX + ASI2600MM Pro + AM7: deeper aperture (`prefer_max_mag: 16`), real-photometry amplitude floor (`min_catalog_amplitude_mag: 0.10`), eclipsing/short-period types re-enabled in `include_types` (EA/EB/EW/RR*/DSCT — guided EQ + dither handles sub-30s cadence cleanly), ZTF re-enabled (target range overlaps ZTF coverage). The config also declares a `dso:` section (FOV 1.6°×1.07°, narrowband moon-relax on) consumed by `mira dso plan`. The variable-star and DSO sides share the same site/observer/window definition; they diverge only at scoring + catalog. See `docs/rig_workflow.md` for the MeLE-rig ↔ homebase split.
- `src/mira/dso/` is the narrowband/DSO planner package: `catalog.py` (curated YAML loader, `DsoTarget` + `DsoCatalog` dataclasses, strict schema validation), `planner.py` (`build_dso_candidates` reuses `evaluate_observability_at_coords` and applies a narrowband-aware moon-relax via `dataclasses.replace` on the site's `WindowConfig`; takes an optional `ledger` for deficit-aware scoring), `report.py` (Markdown + CSV writers; ledger-aware columns when a ledger is provided), `research.py` (offline-research Markdown rendering), `ledger.py` (Phase 2 integration ledger — walks `mira_capture.json` sidecars under `captures_root`, aggregates per `(target, filter)`, with a frame-count fallback that globs `*.fit*` when the sidecar's `result.copied` is missing). Catalog is hand-edited (`data/dso_catalog/sho_targets.yaml`, ~45 targets across all seasons). The ledger matches sidecar `target_name` against catalog `name` only — **canonical-name-only** is the rule (no common-name aliasing); sessions with a non-matching `target_name` go into `Ledger.orphan_target_names` so typos surface in `mira dso status`.
- DSO scoring: `score = (observability + altitude) × mosaic_factor × ledger_factor`. The ledger factor is `0.5 + deficit_weight × deficit_fraction` clamped to [0.5, 1.5]; never-imaged target → 1.5×, fully imaged → 0.5×. `deficit_weight` (default 1.0, configurable) controls strength; 0 disables. `ledger=None` *also* disables (Phase-1 pure-observability behavior). Completed targets stay visible in the queue by design (per user — "targets shouldn't disappear"), they're just deprioritized.
- `mira dso plan` / `mira dso status` / `mira dso research` are the Phase 1–2 entry points; Phase 3 (per-night filter-rotation scheduler) and Phase 4 (Aladin Lite viewer) are not yet built. See `docs/dso_planner.md`.
- **Bright-galaxy path** (`mira galaxies plan` / `status`): a third target-finding concern distinct from VSX variable stars and narrowband DSO, built for the S30 Pro's wide-field galaxy nights. It *reuses the DSO engine* (`build_dso_candidates`, ledger, `evaluate_observability_at_coords`) rather than forking a third silo — the distinctness lives at the surfaces: a separate command, a separate config section (`galaxies:`, with `cfg.galaxies` a `DsoConfig` defaulting to `GALAXY_DEFAULTS` — **moon-strict**, `output_subdir: galaxies`, `sb_limit_mag_arcsec2: 22.5`), a separate curated catalog (`data/dso_catalog/galaxies.yaml`, ~50 showpieces with a `magnitude` field + `object_type: GALAXY`), and a dedicated report (`dso/galaxy_report.py`, `galaxy_plan.md`/`.csv`).
- Galaxy scoring extends DSO scoring with two **magnitude-gated** factors: `score = (observability + altitude) × brightness_factor(SB) × size_factor × ledger_factor`. `surface_brightness` is a derived `DsoTarget` property (`m + 2.5·log₁₀(ellipse area in arcsec²)`, mean over the D25 isophote). `brightness_factor` rewards high SB (the honest urban-OSC predictor — integrated mag misleads: a mag-9 face-on can be invisible while a mag-10 edge-on pops). `size_factor` is **penalty-only** (clamped to ≤ 1.0) so a large low-SB face-on can't ride its size past a compact high-SB target — it only sinks the too-small. **Both factors are strict no-ops when `magnitude is None`** (every narrowband target), so DSO ranking is preserved bit-for-bit — pinned by `test_galaxies.NarrowbandNoOpInvariantTests`. Flags: `dark_site_only` (mean SB > `sb_limit_mag_arcsec2`; kept in queue but demoted) and `under_sampled` (major axis < FOV/40 → "better on the Esprit"). Low-SB traps (M101/M33/M74) self-flag; southern showpieces (M104/NGC 253) self-filter from a JC plan (never clear the 45° floor).
- **Emission-nebula path** (`mira emission plan` / `status` / `research`): a fifth target-finding concern, and the cleanest example of the engine-reuse pattern — it adds **zero new engine/report code**, just a config section + catalog + CLI handler that reuse `build_dso_candidates` and `write_dso_plan` (the narrowband DSO report) verbatim. The distinctness is purely at the surfaces: a separate command, `cfg.emission` (a `DsoConfig` defaulting to `EMISSION_DEFAULTS` — **moon-relaxed** like `dso`, `output_subdir: emission`, no SB floor), and a separate catalog (`data/dso_catalog/emission_nebulae.yaml`, generated from the three image books — Esprit 120 / Esprit 80 / S30 — by `output/books/esprit_emission_book/make_mira_catalog.py`; book SIMBAD lookups override ambiguous ids, e.g. "Abell 21" must query `PN A66 21` or it resolves to the galaxy cluster). The point of the path is **rig-agnosticism**: one emission catalog serves both rigs, and per-rig single-frame fit is computed at plan time from the `emission:` section's `fov_deg` (Esprit 1.6°×1.07°, S30 **measured** 3.9°×2.2° — 3.66″/px plate scale / eff. 163mm fl, not the nominal-150mm 4.25°×2.39°) — NOT from the catalog's static `mosaic` flag, which is reserved for objects that overflow *even the S30's* wide field (only Cygnus Loop, IC 1318, Simeis 147). The fit check applies `FOV_FIT_TOLERANCE` (10% per axis, `planner.py`): a diffuse rim that overflows by <10% is still a single-frame shot (full IC 1396 at 140′ in the S30's 132′ short axis — the Catskills case), while real giants stay mosaics. So the medium giants (NGC 7000, Heart) correctly read as mosaics on the Esprit and single-frame on the S30 from the same catalog row. Pinned by `test_emission.EmissionFovBehaviorTests` (incl. the rim-tolerance cases). Caveat the planner does NOT model: the S30's frame is fixed (no rotator, long axis ≈N–S), so an E–W-elongated 145′ target (California) passes the orientation-blind size check but clips in practice — the *books* carry that honesty (`EW-overflow` flag), not the planner.
- **Bright-transient path** (`mira transients`): a fourth target source — recent bright supernovae/novae worth follow-up — in `src/mira/transients/` (`catalog.py` scrape+parse, `planner.py` observability+reach filter, `report.py`). `catalog.py` scrapes Rochester Astronomy's "active supernovae over mag 17" HTML table (no API key); the parser is defensive (a bad row is skipped, a missing table → `[]`, never fatal). **Coordinate-units gotcha (pinned by test):** the wikisky link's `?ra=` is in decimal HOURS, `de=` in degrees — `_parse_row` multiplies ra by 15. `planner.build_transient_candidates` reuses `evaluate_observability_at_coords` but **relaxes the moon gate** (point sources tolerate moonlight — the whole reason transients are the bright-moon fallback), drops the unobservable, and flags `within_reach` against the deepest site's `prefer_max_mag` (or `--max-mag`). Sort: reachable-first, then brightest. Out-of-reach observable targets are listed (not hidden) so you see what a deeper rig could grab; stale entries (Rochester's `*` = last obs > 1 month) are flagged. The S30's ~mag-12 reach usually yields 0 reachable (amateur-bright SNe are mag 14–16 → Esprit). Transients are AAVSO-submittable via `mira submit` (OSC → TG band). On-demand only; no scheduled automation (per user, for now).
- `photometry.py` performs circular-aperture differential photometry on NINA-captured FITS. Requires NINA to have plate-solved (a celestial WCS in headers). Picks the brightest viable comp star per frame, propagates flux errors, writes the AAVSO Extended File Format. Uses `astropy.io.fits` + `astropy.wcs` + `photutils.aperture`. Tested with synthetic FITS that pin the magnitude recovery to within 0.4 mag of planted values. The AAVSO band is derived from the capture sidecar via `filter_to_aavso_band(read_capture_filter(captures_dir))` — a real V filter (Antlia LRGB-V) emits Johnson `V`; imaging-grade RGB emits tri-color `TR`/`TG`/`TB`; OSC/Seestar `LP`/`IR` emit `TG`/`Bn`; unknown or narrowband labels fall back to `TG` (conservative — never over-claims a photometric standard). When no sidecar exists, the historical V→TG OSC convention applies.
- `flats.py` is per-filter flat calibration (`mira flats`). `solve_exposure` is pure (least-squares invert of `median ≈ bias + k·exposure`); saturated samples are filtered out before the fit (the clipped plateau carries no slope and flattens it — a real bug caught in test). `bracket_filter` does a wide geometric scan then a fine refine + a two-shot repeatability gate (the 2026-05-19 session proved a hand-placed diffuse source can be non-repeatable). Two guards are core, not options: **freshness** (image-history `Filename` must change — the `NoState` stale-frame trap returned byte-identical stats twice that night) and **0-stars** (a frame with stars is sky, not a flat). Opaque positions (`Dark`) are auto-detected (near-bias median at the longest exposure) and skipped. Captured frame→file mapping is by image-history `Filename` basename, not newest-mtime (mtime collides when frames are written within one filesystem tick). Pure math + injected client → unit-tested without NINA, mirroring `capture.py`. Masters go to `data/flats/<filter>_g<gain>_<date>/` as `master_flat.fit` (the canonical Siril master; `.tif`/`.png` are previews), gitignored. Flat source is automatic: `_setup_panel` probes `flat_device_info` at run start — when a Cover Calibrator is connected (Wanderer Cover V4-EC on the Esprit), it closes the lid, sets brightness, turns the EL panel on; on teardown the light goes off (cover stays closed as a dust cap). Otherwise paper-over-aperture is assumed (the S30 Pro path). `--no-panel` forces paper mode even when a device is present. The bracket loop is identical for both — `target_adu` is reached by tuning *exposure*, not brightness, so any diffuse source works. Panel teardown lives in a `try/finally` so a crash mid-run still kills the light. The S30 Pro is a sealed system (focus + optics don't move), so its masters are reusable session-to-session; the Esprit's are reusable only as long as focus, rotation, and dust pattern haven't changed (refocus → re-shoot flats). `mira capture --filter` and `mira tune --filter` select + **confirm** the wheel before shooting and hard-abort if it can't confirm (a multi-hour stack must never silently run through the wrong/no filter — that invalidates flat calibration); the wheel is driven via `nina_client.set_filter`, which never raises.
- Auto-resolve: NINA's API-capture FITS carry `GAIN` but **no `FILTER`** keyword (verified 2026-05-19 — the same lossy-metadata path as the missing-WCS bug; do not try to read the filter from light FITS). So `mira capture` writes a `mira_capture.json` sidecar (filter/gain/exposure) into the dest dir, and `mira stack --auto-flats` keys off *that* (not the FITS) to resolve the newest matching `data/flats/<filter>_g<gain>_*/master_flat.fit`, feeding Siril the prebuilt master via `calibrate -flat=` (no re-stack). `resolve_master_for_lights` (sidecar-keyed) and `find_master_for_filter_gain(filter, gain, flats_root)` (direct, used by the capture-time live-stack hint) share the same matcher. Both return `(None, reason)` on any miss and the CLI **hard-aborts** rather than silently stacking without the matched flat; `--flats` (raw dir, Siril rebuilds) still works and overrides. `flat_master` in `build_stack_script` takes precedence over `flats_dir`. The capture sidecar is *also* the source of truth for AAVSO band in `mira submit`, not just flat matching.
- `mira capture` prints a Siril Live Stacking hint at session start: the resolved watch folder (absolute capture dest) and the resolved master flat. Paste both into Siril's Live Stacking panel on homebase for a real-time SNR-building preview as Syncthing mirrors frames in from the MeLE. Lag is honest (~5–10s per FITS over LAN); not a replacement for the end-of-session `mira stack`.
- `docs/nina_setup.md` and `docs/photometry.md` walk through the per-night workflow end-to-end for the S30 Pro (NINA configuration, Target Scheduler plugin, comp-star JSON, submit command, per-filter `mira flats`). `docs/nina_setup_esprit.md` is the Esprit-rig equivalent (mount + cam + wheel + focuser + guider; canonical filter labels are a hard requirement). Keep these docs aligned with code changes that affect the workflow.
- `scripts/bootstrap.ps1` takes `-Rig esprit` to additionally install Syncthing + PHD2 (silent winget) and run `mira doctor` against `config/esprit120_jc.yaml`. The s30 default path is unchanged.
- `mira doctor`'s filter-wheel check enforces canonical names (`Ha`/`OIII`/`SII`/`L`/`R`/`G`/`B`/`V`) as a hard FAIL when the loaded config has DSO enabled. Auxiliary opaque positions (`Dark`/`Block`) are tolerated. This is the foot-gun guard so an "H-alpha" wheel label can never silently dump captures into orphan ledger entries for hours.
- `webapp/` is a Flask app that wraps the CLI commands as a web UI. Three layers: (1) kick off `tonight` and view the schedule, (2) run photometry on capture directories with live results, (3) live NINA monitoring via the Advanced API plugin. Single user, single machine, no auth. Background tasks via `ThreadPoolExecutor`; in-memory state. HTMX for partial updates so there's no JS framework to maintain. Templates use the same red-light dark-mode CSS as the static `nightly_html.py`.
- Start it with `mira webapp --output-dir ... --captures-root ... --nina-url http://localhost:1888`. The `serve` subcommand is now a deprecated alias that forwards to `webapp` with default settings.
- `scheduler.py` builds the prescriptive session schedule via greedy selection: at each step pick the candidate with the highest `score + setting-soon urgency bonus` whose recommended integration fits before its observable window closes. Setting-soon urgency = `max(0, URGENCY_HORIZON_MINUTES - time_until_set)`, which biases toward grabbing targets before they drop. Observable window per candidate is approximated as `best_local_time ± minutes_above_minimum/2`; if a tighter approximation matters later, walk the per-sample altitude data in `observability.py` and store start/end on `Observability`.
- The scheduler does NOT optimize slew time between targets (constant `SLEW_BUFFER_MINUTES_DEFAULT = 3.0`). For a small home setup this is fine; if you ever want TSP-style routing it'd go here.
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
