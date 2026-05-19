# Changelog

All notable changes to Mira. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/). Versions are git tags.

## [1.0.0] — 2026-05-19

First versioned release: the field-deployable, "take it on a trip"
milestone. Everything below is on `master` and test-covered (full suite
green).

### Added
- **`mira doctor`** — one preflight that verifies the whole rig
  (Python/deps, numpy<2.3 for GraXpert, Siril + version, ASTAP + star
  DB, GraXpert, NINA API on 1888/1889 incl. the `NoState` degraded-
  connection tell, filter wheel, darkness-tonight, capture-disk space,
  config). Never raises; ASCII-only; non-zero exit on hard failure.
- **`scripts/bootstrap.ps1`** — idempotent native installer (Python
  venv + pinned deps, Siril, ASTAP, optional GraXpert) ending in
  `mira doctor`. Does not (cannot) install NINA/ASCOM — prints the
  manual checklist.
- **`requirements-lock.txt`** — pinned known-good dependency set
  (numpy==2.2.6 is load-bearing for GraXpert).
- **Per-filter flat calibration (`mira flats`)** + filter-aware
  `mira capture --filter` / `mira tune --filter` (select + confirm the
  wheel, hard-abort if unconfirmed) + `mira stack --auto-flats` (resolve
  the matching prebuilt master from the capture sidecar, since NINA
  FITS carry no FILTER keyword).
- **Claude Code skills** under `.claude/skills/` (field-setup,
  preflight, nightly-run, take-flats, deep-capture, photometry-submit,
  nina-troubleshoot). The two hardware skills are user-invoked only.
- **`docs/FIELD_GUIDE.md`** — bare-laptop-to-capturing runbook.
- **`mira --version`**; rotating field log at `logs/mira.log` (WARN+,
  for offline post-mortems).

### Changed / hardened
- `cached_get` coerces a missing/zero timeout to a finite default —
  no external call can hang forever on flaky field internet.
- `fetch_vsx_targets` raises `VsxUnavailableError` on a total VSX
  outage instead of silently returning an empty queue; `mira run` /
  `mira tonight` fail loudly with an actionable message.
- Version bumped 0.1.0 → 1.0.0.

### Known limitations (honest)
- **AAVSO output is not submission-grade** — no color-term /
  transformation correction. Light curves are for your own analysis.
- **No offline mode** — `mira tonight` needs VSX; a no-signal site
  fails loudly but still fails. Tether/Starlink is a hard dependency.
- **Flats fix vignette/dust, not light-pollution gradient.**
- **Siril pinned to 1.4.3** for script-generation compatibility;
  `mira doctor` warns on mismatch.
- NINA/ASCOM/Seestar have no headless or Docker path — native Windows
  GUI install only.
