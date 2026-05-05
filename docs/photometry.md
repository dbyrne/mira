# Photometry Pipeline

After NINA finishes a session, the captured FITS files need to be turned into
AAVSO observation rows. The `anomaly-scout submit` subcommand does this.

## Prerequisites

- FITS files must have a celestial WCS in their headers. NINA does this
  automatically when its plate-solve step runs (Center on Target / Solve
  & Sync). Verify in NINA's log that the solve succeeded for each frame.
- One target per directory (e.g. NINA's "Target name" subfolder).
- An AAVSO **observer code** (free, register at https://www.aavso.org/).
- An AAVSO **chart** for the target with comparison-star photometry: open
  https://apps.aavso.org/vsp/, enter the target name, click "Plot," then
  use the "Standard Field Photometry Table" link to get exact RA/Dec/V
  for each comparison star.

## Per-target setup: comp_stars.json

For each target you'll observe regularly, prepare a JSON file like
`docs/comp_stars_example.json`:

```json
[
  {"label": "095", "ra_deg": 282.453, "dec_deg": 33.357, "catalog_mag": 9.512, "catalog_band": "V"},
  {"label": "102", "ra_deg": 282.612, "dec_deg": 33.401, "catalog_mag": 10.234, "catalog_band": "V"},
  {"label": "115", "ra_deg": 282.387, "dec_deg": 33.298, "catalog_mag": 11.512, "catalog_band": "V"}
]
```

- `label` — the comp star's AAVSO sequence label (the number printed by the
  variable on the chart, omitting decimals). For the upload file's CNAME field.
- `ra_deg`, `dec_deg` — ICRS coordinates from the AAVSO photometry table.
- `catalog_mag` — V (or other band) magnitude from the same table.
- `catalog_band` — the AAVSO band code; usually `V`. Influences the band code
  in the upload file. The pipeline submits as `TG` for OSC sensors regardless,
  but it uses `catalog_band` to scale magnitudes.

Pick **2–4 stars** that bracket the variable's expected brightness range.
The pipeline picks the brightest comp with positive flux per frame, so a
range gives the photometry a chance even when a target dims.

## Running the pipeline

```powershell
anomaly-scout submit `
  --captures "C:/path/to/NINA/captures/RR_LYR/" `
  --target "RR LYR" `
  --comp-stars docs/comp_stars/rr_lyr.json `
  --observer-code ABC `
  --chart-id X12345AAB
```

What it does:
1. Looks up the target's RA/Dec via VSX (so coordinates always match the
   catalog).
2. Reads each FITS file in the captures directory, extracts the WCS, and
   converts target + comp-star RA/Dec to pixel coordinates.
3. Runs circular-aperture photometry (6" radius default) with sigma-
   clipped annular sky subtraction.
4. Picks the brightest comp star with positive flux, computes a
   differential magnitude, propagates flux errors.
5. Writes an AAVSO Extended File Format file:
   `aavso_<TARGET>.txt` in the captures directory.
6. Prints a per-frame magnitude line plus a session summary.

## Verifying before upload

- Open the generated `aavso_<TARGET>.txt` file and read it. It's plain text.
  Each row should look reasonable (magnitudes within the catalog range, MERR
  small, JD matching the session date).
- If a frame's magnitude is wildly different from the others, that frame
  may have been clouded out or the target out of the field. Edit the file
  to remove that row before uploading.
- Don't auto-submit. The pipeline deliberately does not POST to AAVSO —
  always inspect, then upload manually at
  https://www.aavso.org/webobs/file with the file as the input.

## Tuning notes

- `--aperture-arcsec` default is 6". For a 30mm scope at urban sky that
  matches typical seeing (4–5"). Bump to 8–10" if your seeing is poor or
  the FWHM in the FITS is large; drop to 4" if seeing is excellent.
- The pipeline assumes ADU ≈ counts for noise propagation. For more
  accurate errors, set the camera GAIN parameter from the FITS header in
  a future enhancement.
- For OSC sensors the band code defaults to `TG` (transformed green from
  the green Bayer channel). AAVSO accepts this; do not submit as `V`
  unless you're using a Johnson-Cousins V filter.
