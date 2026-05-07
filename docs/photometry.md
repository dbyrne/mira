# Photometry pipeline

After NINA finishes a session, captured FITS files need to be turned
into AAVSO observation rows. The webapp's `/photometry` view (or the
`anomaly-scout submit` CLI) does this end-to-end: it pulls a comparison-
star sequence from AAVSO VSP, runs aperture photometry on each frame,
flags outliers, generates a light curve plus phase-folded plot, runs an
anomaly assessment, and writes an AAVSO Extended File Format file ready
for upload.

## Prerequisites

- **WCS in FITS headers.** NINA must plate-solve before saving (Center
  on Target / Solve & Sync, or per-frame Plate Solve). The pipeline
  pre-flights the first frame and bails fast if the WCS is missing.
- **Dated capture directories.** Organize as
  `captures/<TARGET>/<YYYY-MM-DD>/*.fits` so each night is its own
  session. The flat layout `captures/<TARGET>/*.fits` still works for
  legacy data and is treated as a single undated session.
- **AAVSO observer code** — free, register at
  https://www.aavso.org/. Required by AAVSO Extended File format.
- **(Optional) local horizon profile** — see HANDOFF.md "Storage
  layout"; YAML at `config/horizon_balcony_jc.yaml` is a real example.
  When set on a site config, the scheduler drops directions where
  trees/houses block the view, even when the target's altitude alone
  would qualify.

## Running it

### Webapp (recommended)

1. `anomaly-scout webapp` and open the dashboard on phone or laptop.
2. Navigate to `/photometry`. If a schedule is loaded, the page shows
   each scheduled target's status (awaiting capture / captured /
   processing / processed / submitted).
3. Tap a target with captures. Type your observer code; comp stars and
   chart ID are auto-fetched from VSP. Optional: paste a comp-stars
   JSON path under "override" if you want a hand-curated sequence.
4. Hit "Run photometry." The page polls every 2s and streams per-frame
   results, log lines, an anomaly callout, and the light-curve plot
   (plus a phase-folded plot when the catalog period is known).
5. When done, "Download AAVSO file" sends you the Extended Format file.
   Inspect it (it's plain text), then upload at
   https://www.aavso.org/webobs/file. Hit "Mark as submitted" to track
   completion in the run history.

### CLI

```powershell
anomaly-scout submit --captures captures/RR_LYR/ --target "RR LYR" --observer-code ABC
```

Auto-fetches comps from VSP. Override with:

```powershell
anomaly-scout submit `
  --captures captures/RR_LYR/ `
  --target "RR LYR" `
  --observer-code ABC `
  --comp-stars docs/comp_stars/rr_lyr.json `
  --chart-id X12345AAB
```

## Anomaly assessment

After photometry, the app compares your session median against:

1. **VSX catalog range.** If outside `max_mag − 0.3` (brighter) or
   `min_mag + 0.3` (fainter), it's flagged as anomaly.
2. **AAVSO recent baseline.** If 10+ AAVSO observations exist in the
   last 90 days, the app computes a robust median + MAD-based sigma
   and flags >3σ deviations as anomaly, 2–3σ as watch.

The result rolls up to one of:
- **Consistent** (info) — observation matches expectations.
- **Watch** — slightly off baseline, worth a closer look.
- **Anomaly** — clearly out of expected range; flag for AAVSO follow-up.

The light-curve plot overlays your night's points (with error bars) on
recent AAVSO observations so you can verify the call visually.

## Comp stars

By default, comps come from the AAVSO VSP API
(`app.aavso.org/vsp/api/v2/chart/?star=<name>&fov=60&maglimit=14.5`).
The pipeline picks comps within ±2 mag of the target's expected
brightness, capped at 6.

To override with a hand-curated sequence, prepare a JSON file:

```json
[
  {"label": "095", "ra_deg": 282.453, "dec_deg": 33.357, "catalog_mag": 9.512, "catalog_band": "V"},
  {"label": "102", "ra_deg": 282.612, "dec_deg": 33.401, "catalog_mag": 10.234, "catalog_band": "V"},
  {"label": "115", "ra_deg": 282.387, "dec_deg": 33.298, "catalog_mag": 11.512, "catalog_band": "V"}
]
```

- `label` — AAVSO sequence label (the variable's mag × 10 typically).
- `ra_deg`, `dec_deg` — ICRS coordinates from the AAVSO photometry table.
- `catalog_mag` — V-band magnitude.
- `catalog_band` — usually `V`. The pipeline submits as `TG` for OSC
  sensors (per AAVSO convention) and logs a one-line note when this
  band swap happens.

## Verifying before upload

- Read the `aavso_<TARGET>.txt` plain-text file. Each row should look
  reasonable (magnitudes within the catalog range, MERR small, JD
  matching the session date).
- The pipeline flags MAD-based outliers in the per-frame results table
  but **does not** remove them from the AAVSO file. If a frame's
  magnitude is wildly off (cloud, target out of field, bad solve), edit
  the file to remove that row before uploading.
- The pipeline never auto-submits to AAVSO. Always inspect, then upload
  manually.

## First-light checklist

Before you observe, walk through this once:

1. ☐ NINA Advanced API plugin installed, port 1888 open. Verify by
   loading `/nina` in the webapp.
2. ☐ Polar alignment routine done (Seestar app handles this on the EQ
   wedge).
3. ☐ Test schedule generated: `anomaly-scout tonight --hours 4`.
   Confirm `output/.../session_schedule.html` shows scheduled targets.
4. ☐ NINA Target Scheduler imports `nina_targets.csv` cleanly.
5. ☐ AAVSO observer code memorized or saved somewhere quick to copy.
6. ☐ Webapp reachable from phone via Tailscale (test with
   `gaming-rig-windows.tail4ab263.ts.net:8000` or your magic DNS name).

After capture:

1. ☐ Captures land in `captures/<TARGET>/`.
2. ☐ `/photometry` shows the target with "ready for photometry" status.
3. ☐ Run, inspect light curve, check anomaly callout.
4. ☐ Download AAVSO file, inspect rows, edit if needed.
5. ☐ Upload at https://www.aavso.org/webobs/file.
6. ☐ Click "Mark as submitted" so the run history reflects state.

## Tuning notes

- `--aperture-arcsec` default is 6". For a 30mm scope at urban sky that
  matches typical seeing (4–5"). Bump to 8–10" if seeing is poor or
  FWHM in the FITS is large; drop to 4" if seeing is excellent.
- The pipeline assumes ADU ≈ counts for noise propagation. For more
  accurate errors, set the camera GAIN parameter from the FITS header
  in a future enhancement.
- For OSC sensors the band code defaults to `TG` (transformed green
  from the green Bayer channel). AAVSO accepts this. Don't submit as
  `V` unless you're using a Johnson-Cousins V filter.
- The pipeline picks the *brightest* comp star per frame. A multi-comp
  weighted ensemble is the AAVSO gold standard but is left for a
  future pass — it'd improve precision marginally on dim targets.
