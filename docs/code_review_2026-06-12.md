# Codebase review — 2026-06-12

*Five parallel review agents over the full codebase (capture/NINA chain,
VSX pipeline core, DSO family, stack/finish/photometry, CLI/webapp),
findings adversarially spot-verified before recording. Hunt scope:
correctness bugs + operational foot-guns; style excluded.*

**STATUS — same-day fix wave (2026-06-12): every item below is FIXED**
(four parallel fix agents + a main-line batch; 804 tests pass, +71 new
pins) **except** the DST-transition sampling note inside item 33, which
is accepted-as-documented (±60 min on the two transition nights/year).
Bonus shipped in the same wave: **meridian-flip awareness in `mira
capture`** — the loop polls the mount's pier side each iteration; on a
flip it emits, re-centers via plate solve (when `--platesolve-center`
is active), and counts `pier_flips` in the sidecar; guider-less/
Seestar rigs (empty pier side) are a silent no-op. The catalog/doctrine
half of item 2 means: emission targets now budget **LP 180m** for S30
sessions, and `galaxies.yaml` budgets are keyed **IR** per the filter
doctrine; off-budget filters now surface as UNBUDGETED rows in
`mira dso status`.

## Critical — fix first

1. **[FIXED 2026-06-12] TS-format sexagesimal rounds seconds to "60" with
   no carry** — `session_plan.py` `ra_to_target_scheduler_hms` /
   `dec_to_target_scheduler_dms` (and the `ra_to_hms`/`dec_to_dms` pair):
   `f"{s:02.0f}"` rounds 59.5+ to `60s`/`60"`. VERIFIED in shipped
   artifacts: `output/runs/esprit120_jc/emission/nina_targets.csv` carried
   `IC 1396A … +57° 23' 60"`. 8 catalog targets affected. NINA TS may
   reject/mis-parse rows. Fix: integer divmod with carry.

2. **Ledger can't see off-budget filters → by-the-book S30 sessions book
   ZERO progress (verified).** `target_completion_fraction` + `dso status`
   iterate only `budget_minutes` keys. But `emission_nebulae.yaml` budgets
   Ha/OIII/SII while S30 emission doctrine shoots `--filter LP`;
   `galaxies.yaml` budgets `{LP:…}` while galaxy doctrine shoots `IR`.
   Either way the session is invisible: 0% complete forever, permanent
   1.5× planner boost, no orphan-style surfacing. Fix: surface
   "unbudgeted-filter" totals in `dso status`/plan (analogous to orphans)
   AND reconcile the catalogs' budget keys with the per-rig filter
   doctrine (likely: add LP to emission budgets for the S30, change
   galaxies budgets LP→IR, or a per-rig filter-alias map).

3. **Interrupted capture sessions book 0 minutes (sidecar pre-loop writes
   `result.copied: 0`)** — `capture.py` persists a full `result` block
   *before* the loop; only a clean exit rewrites it. The ledger trusts
   `result["copied"]` whenever present, so its glob-rescue (built for
   exactly this) can never fire; a killed 3-hour session with 150 FITS on
   disk reports 0 min and gets re-scheduled. Fix: omit `copied` from the
   pre-loop persist, or persist every N frames, or ledger glob-verifies
   when copied==0 but FITS exist.

4. **`mira tonight` breaks after midnight / on UTC system clocks
   (verified)** — `tonight_pipeline.py` uses `date.today()` (system date)
   as `start_date` while the window is sampled from `start_hour_local` on
   that date: run at 00:30, every `best_local_time` lands tomorrow evening
   → post-filter empties → "Nothing observable". No `--start-date` escape
   on tonight. Fix: derive from `now_local` (site tz), minus a day when
   before `end_hour_local`.

5. **Non-preset `mira finish` silently writes the "16-bit" TIFF master as
   8-bit** — `run_finish` round-trips Siril's 48-bit TIFF through PIL
   (`Image.open(...).crop(...).save(...)`), which the agent reproduced as
   uint8 truncation under Pillow 12. The .tif is documented as the
   editable master; preset path (tifffile) is correct. Fix: crop/write via
   tifffile.

6. **AAVSO "period discovered" bonus is dead code (verified)** —
   `aavso.py:90` gates period analysis on `catalog_period is not None`,
   but the bonus requires `period_days is None` → `derived_period_days`
   is always None exactly when the bonus could apply. The documented
   anomaly signal for bright period-less targets never fires. Fix: gate
   on `count > 0` only (disagreement logic already None-safe).

## High-value medium

7. Capture copy loop marks frames `seen` BEFORE `shutil.copy2` and
   swallows OSError bare — locked/late files (OneDrive default
   `nina_root`!) are silently never copied; no final post-loop sweep
   (last sub of every run races). `capture.py:481-489`.
8. `_finish_preset` bg-extraction cache keyed by (stem, mtime≥) — two
   inputs named `result.fit` finished into one dir reuse the WRONG
   target's background; mtime-preserving copies reuse stale content.
   `cli.py:1516`. Fix: content-hash key like the StarNet cache.
9. `_verify_pointing` hardcodes the S30 FOV — on the Esprit, ASTAP gets a
   4× wrong `-fov`, solves fail, check silently degrades to fail-open.
   `capture.py:193`. Thread `capture_defaults.fov_deg` through.
10. `mira galaxies plan --relax-moon` is a silent no-op (all 51 galaxies
    are broadband → `is_narrowband` False; engine relax only applies to
    narrowband, pinned). Fix at the surface: explicit force-relax-all.
11. "tonight" output-dir suffix convention applied inconsistently —
    `--output-dir …/tonight` cleans `…/tonight/tonight` (stale packets
    survive + get archived); webapp reads `OUTPUT_DIR/` while the
    pipeline writes `OUTPUT_DIR/tonight/` unless the path ends in
    "tonight" → UI 404s. One resolver helper for both.
12. Scheduler "leapfrogs": future-opening targets beat observable-now
    targets with no idle penalty → currently-observable windows close
    unused during the gap. `scheduler.py:75-86`.
13. AAVSO cache key includes `now()`-derived JD at second resolution →
    cache NEVER hits across runs (TTL dead, dir grows ~200 files/run);
    the failure fallback substring-matches `ident=NAME` without a
    delimiter → can return the WRONG star's counts as "ok-cached".
14. Moon-separation gate unreachable when a bright moon sits below
    `max_moon_altitude_deg` (29°-high full moon at default cap 30 → no
    illumination/separation check at all). Possibly intended threshold
    semantics — but contradicts the config comment.
15. Photometry sky annulus is NOT sigma-clipped despite the documented
    contract — star-in-annulus inflates sky_std → systematically
    overestimated MERR in every AAVSO row. One-line `SigmaClip(3.0)`.
16. Tune (`run_tune`) lacks the flats-style freshness guard — the
    documented NoState stale-frame trap silently attributes the previous
    frame's stats to the new (gain, exposure) point.

## Smaller (real but low frequency/impact)

17. Flats `_setup_panel` partial failure after `close_cover` → "paper
    mode" against a CLOSED LID (all filters skipped as opaque) + EL panel
    possibly left on (teardown gated on `panel_driven`).
18. Flats `_find_capture_file` keeps a newest-mtime fallback (documented
    invariant says Filename-only) — concurrent writers (Syncthing) can
    contaminate a master.
19. `park_at_end: true` in session/config YAML silently ignored (CLI
    default False masks it; only the flag works).
20. Catalog accepts negative `ra_deg` (range −360..360) → garbage TS rows;
    `pa_deg: 360` accepted → `Rotation,360`. Normalize at parse.
21. `run_siril_stack` false "no FITS was written" for multi-dot out names
    (`M51.lrgb.tif` → looks for `M51.fit`). Path-suffix handling.
22. `--siril-calibrate` WCS gate raises raw ValueError (uncaught) when a
    frame lacks WCS; non-FITS contamination shifts frame-index pairing.
23. Space in `flat_master` path → cryptic mid-script Siril failure (only
    `work_dir` is validated). Validate early.
24. WCS flip gate compares brightest-vs-brightest star — calibration can
    legitimately reorder brightness → false "flipped" abort (conservative
    direction, misleading message). Gate on nearest-star instead.
25. StarNet subprocess failure escapes as raw CalledProcessError with
    stderr discarded; `cv2.imwrite` return unchecked.
26. Webapp: post-loop `record.result[...]=` writes bypass the documented
    `update_result` locking (torn-snapshot 500s); `/run` form floats
    unvalidated (500 on garbage, no clamp).
27. Multi-site `tonight` schedules against each candidate's best site,
    not the session site (Fairbanks rows in a JC schedule). Single-site
    configs unaffected.
28. Bare `mira` (no subcommand) crashes AttributeError instead of help.
29. `budget_minutes: {Ha: 90.5}` silently truncates to 90 (strict loader
    elsewhere). Inventory `p.stat()` unguarded in size sum (one dangling
    link kills the run). `mira galaxies` top-pick print crashes on
    `magnitude=None` via `--catalog` override.
30. VSX: early `break` on row_limit can skip whole high-RA bins with
    `--limit`; tail truncation always drops the highest-RA bin's targets
    (default configs divide evenly — smoke/limit runs biased).
31. Gaia L-family color anomaly matches LPB (blue pulsators) via
    `startswith("L")` → false bonus. Use explicit {L, LB, LC}.
32. Packet heading "(best)" tags the geometric-best site, diverging from
    the canonical score-best `primary_site` in the same run's CSV.
33. ZTF IPAC parser hardcodes `data_start = header_index + 4` (drops rows
    on 2-line sub-headers); DST transition nights distort
    minutes_above_minimum ±60min; research.md TOC anchors all dead;
    subprocess wrappers use `text=True` without `encoding=` (cp1252
    UnicodeDecodeError risk on Siril/GraXpert logs).
34. Doc drift: CLAUDE.md says photometry "picks the brightest viable comp
    star" — code is (deliberately, test-pinned) a multi-comp ensemble.

## Verified solid (the invariants held)

Auto-flats sidecar-only resolution + hard-abort chain; flat-master glob
can't cross-match filters/gains; -fitseq avoidance; WCS flip gate catches
its documented failure; snapshot-diff capture (pattern-independence
pinned); filter confirm hard-gate; dither math anchored/non-cumulative,
all reposition slews center=False; ASTAP units; saturated-sample
filtering before the flats fit; freshness + 0-stars guards;
apply_target_bonus mirroring everywhere; half-open window loop; period
tri-state gating; wildcard type matching (L≠ELL); cached_get TTL
semantics; ledger skip rules + canonical-name orphaning; FOV_FIT_TOLERANCE
incl. static-mosaic short-circuit; galaxy narrowband no-op invariant;
transients RA-hours ×15; nina_targets CSV quoting; webapp path-traversal
guards, HTML escaping, demo-mode isolation; doctor's gated hard-FAIL.
