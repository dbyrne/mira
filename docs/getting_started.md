# Getting Started

A walkthrough from "I just cloned this repo" to "I just submitted my
first observation to AAVSO." It's written for someone who has a smart
telescope but has never done variable-star photometry before.

If terms like **VSX**, **comp star**, **photometry**, or **AAVSO**
are unfamiliar, skim [Concepts](concepts.md) first.

---

## Table of contents

1. [What you'll need](#what-youll-need)
2. [Install](#install)
3. [Configure your site](#configure-your-site)
4. [Map your local horizon](#map-your-local-horizon)
5. [Generate your first schedule](#generate-your-first-schedule)
6. [Dress rehearsal (no scope required)](#dress-rehearsal-no-scope-required)
7. [Your first real observation](#your-first-real-observation)
8. [Submit to AAVSO](#submit-to-aavso)
9. [What to read next](#what-to-read-next)

---

## What you'll need

**Software** (free):
- **Python 3.11 or newer**
- **Stellarium Mobile** (to map your local horizon — free version works)
- **NINA** ([Nighttime Imaging 'N' Astronomy][nina]) — free Windows
  capture software, with the [**Advanced API plugin**][advanced-api]
  installed
- An **AAVSO observer code** — register free at
  <https://www.aavso.org/apply-observer-code>. Takes about a day.

**Hardware**:
- A smart telescope that produces FITS files with embedded WCS
  coordinates. The project is tuned for the **ZWO Seestar S30 Pro** in
  equatorial mode, but anything NINA can drive will work.
- A computer near the scope (ideally Windows for NINA), or networked to
  the scope's controller.

**Time budget**:
- ~1 hour to install, configure, and map your horizon
- ~30 minutes the first time you run a session through

[nina]: https://nighttime-imaging.eu/
[advanced-api]: https://github.com/christian-photo/ninaAPI

---

## Install

```powershell
git clone https://github.com/dbyrne/aavso-anomaly-scout.git
cd aavso-anomaly-scout
python -m pip install -e .
```

Verify the install by running the test suite:

```powershell
python -m unittest discover -s tests
```

You should see `Ran NNN tests in X.Xs ... OK`. If anything fails, see
[Troubleshooting](troubleshooting.md#tests-fail-after-install).

---

## Configure your site

The system needs to know where you're observing from. Site configs live
in YAML files under `config/`. The shipped examples are:

| Config | Where | What it's tuned for |
|---|---|---|
| `config/jersey_city.yaml` | Urban Bortle 8 sky | Bright targets (mag ≤ 14), strict altitude floor (45°), galactic-plane avoidance |
| `config/fairbanks.yaml` | Dark Bortle 2-3 sky | Fainter targets (mag ≤ 16.5), permissive altitude floor (25°) |
| `config/multi_site.yaml` | Both above | A queue scored against both sites, useful when you can choose |
| `config/s30_pro_jc.yaml` | Jersey City + Seestar S30 Pro | Tuned exposures for the gear, no fast pulsators (cadence too short for stacked OSC) |

**For your own location**, copy `config/jersey_city.yaml` to
`config/<yoursite>.yaml` and edit the four blocks at the top:

```yaml
sites:
  - name: My Backyard
    observer:
      latitude_deg: 37.7749       # your latitude (positive = N)
      longitude_deg: -122.4194    # your longitude (negative = W)
      timezone: America/Los_Angeles  # IANA tz name; use Wikipedia
    observing_window:
      start_hour_local: 20        # local time you typically start
      end_hour_local: 1           # local time you typically end (after midnight = 0–6)
      nights: 14                  # how many nights ahead to look
      sample_minutes: 30          # how often to check sky during the window
      min_altitude_deg: 30        # global altitude floor (per-direction comes later)
      max_sun_altitude_deg: -12   # nautical twilight; -18 = full astronomical dark
      max_moon_altitude_deg: 30
      max_moon_illumination: 0.7
      min_moon_separation_deg: 30
    filters:
      min_galactic_latitude_abs_deg: 12   # avoid Milky Way crowding; 0 = don't filter
      min_catalog_amplitude_mag: 0.20     # ignore quiet variables
      prefer_amplitude_mag: 0.5
      prefer_max_mag: 14                  # faintest target you want
      reject_saturated_brighter_than_mag: 4  # protect against blooming
```

Don't worry about the `vsx_query`, `scoring`, etc. sections at the
bottom — copy those from one of the existing configs as-is. They're
about *how* targets are picked, not *where* from.

> 💡 **Sanity check**: After editing, try `anomaly-scout target "RR Lyr"
> --config config/<yoursite>.yaml`. If it produces a candidate packet
> with reasonable altitudes for your location, your config is right.

---

## Map your local horizon

Real observing locations have trees, houses, and railings that block
parts of the sky. The scheduler can avoid sending you to targets behind
obstructions if you give it a horizon profile.

This is a one-time setup that takes about 20 minutes. The full procedure
is in **[Horizon profile](horizon_profile.md)** — short version:

1. Open Stellarium Mobile at your imaging spot (after dark)
2. Enable **AR mode** (camera icon at the bottom)
3. Calibrate the compass (figure-8 motion)
4. Walk around and aim at obstruction edges. For each, write down the
   azimuth and altitude shown on screen
5. Save those points to `config/horizon_<yoursite>.yaml`
6. Reference it from your site config:

   ```yaml
   sites:
     - name: My Backyard
       horizon_profile_path: config/horizon_<yoursite>.yaml
       observer:
         ...
   ```

If you don't have time tonight, **skip this step**. The default flat
altitude floor still works; you'll just occasionally schedule a target
behind a tree until you fix it. See
[Horizon profile](horizon_profile.md) when you're ready.

---

## Generate your first schedule

With your config saved, you're ready to ask the system "what should I
observe tonight?":

```powershell
anomaly-scout tonight --config config/<yoursite>.yaml --hours 4
```

You should see output like:

```
Tonight: 2026-05-07, looking ahead 4.0h (20:00 → 00:00 EDT)
Fetching up to 1500 VSX rows from VizieR...
342 targets passed site filters for tonight
22 targets observable in the next 4h
AAVSO enriched: 22
SIMBAD enriched: 22
Gaia enriched: 22
Wrote output/<yoursite>/tonight/session_schedule.html
Wrote output/<yoursite>/tonight/nina_targets.csv
Wrote 22 packets in output/<yoursite>/tonight/candidate_packets/
```

Open `output/<yoursite>/tonight/session_schedule.html` in your browser.
You'll see:

- **A horizontal timeline** at the top — colored blocks for each
  scheduled target, hour ticks below
- **A quick-glance schedule table** — start/end time, target name,
  expected magnitude, type, exposure plan
- **Per-target cards** with everything you need at the scope: AAVSO
  finder chart link, expected brightness with comparison-star
  brackets, recent AAVSO observations, SIMBAD object type, Gaia
  context

This is the primary phone-readable doc for the night.

> 💡 **Tip**: If you have a Tailscale or local network, run
> `anomaly-scout webapp` and view the same schedule on your phone at
> `http://<your-host>:8000/schedule`. The webapp also drives photometry
> and AAVSO submission in the same UI.

---

## Dress rehearsal (no scope required)

Before your first real session, exercise the photometry pipeline with
synthetic data. This catches integration issues — a broken VSP endpoint,
a corrupted FITS header parser, a misconfigured AAVSO writer — when
they're easy to fix.

```powershell
anomaly-scout rehearse --target "RR Lyr" --frames 10
```

The system will:

1. Look up RR Lyrae in VSX (real network)
2. Fetch comparison stars from AAVSO VSP (real network)
3. Generate 10 synthetic FITS frames with the target and comps planted
   at correct sky positions, with a small magnitude jitter per frame
4. Run the full photometry pipeline on those frames
5. Write a real AAVSO Extended File (with `OBSCODE=TEST` so you don't
   accidentally submit it)
6. Print a recovered-vs-planted residual report

A healthy report looks like:

```
=== Rehearsal report ===
Target:           RR Lyr
  RA / Dec:       291.36630 / +42.78436
  Planted mag:    7.17
  Chart:          X42293DG (4 comps in V)
Frames:           10
Recovered mag:    median 7.12 (range 7.06–7.24, residual -0.05 mag)
AAVSO file:       captures/_rehearsal/aavso_RR_Lyr.txt
No issues. Pipeline looks healthy.
```

If the residual is greater than ±0.4 mag, the rehearsal will flag it.
See [Troubleshooting](troubleshooting.md#rehearsal-residual-too-large)
for what to investigate.

---

## Your first real observation

When the gear is ready and the sky is clear, the workflow is:

### Before dark

1. **Open the webapp**: `anomaly-scout webapp`. Visit `/first-light` —
   this page walks you through each step and turns green as you complete it.
2. **Save your AAVSO observer code** at `/settings`. The system will
   remember it for every photometry run going forward.
3. **Generate tonight's schedule** from the dashboard. Click *Generate
   plan*; in ~2 minutes you'll have an updated schedule.
4. **Verify NINA is reachable** at `/nina`. The page polls the Advanced
   API plugin every 5 seconds. If it shows "unreachable," see
   [NINA setup](nina_setup.md).

### As night falls

5. **Polar-align** your scope (the Seestar app handles this on the EQ
   wedge).
6. **Import** `output/<yoursite>/tonight/nina_targets.csv` into NINA's
   Target Scheduler. The rows are in execution order.
7. **Start the sequence** in NINA. NINA will:
   - Slew to each target
   - Plate-solve to confirm pointing
   - Capture the planned frames
   - Save FITS into `captures/<TARGET>/<YYYY-MM-DD>/`

### Capture is running

You don't have to do anything. The webapp's `/photometry` page shows
each scheduled target's status:

- **Awaiting capture** — NINA hasn't started this target yet
- **Ready for photometry** — frames are in, ready to process
- **Processing** — pipeline is running
- **Processed** — light curve generated, awaiting your review
- **Submitted** — you've uploaded to AAVSO

### As targets finish

8. **Tap a target** with frames available. Type any chart-ID override
   (or leave blank to auto-fetch from VSP), and click *Run photometry*.
9. **Review the result**: light curve, AAVSO recent overlay, anomaly
   callout, per-frame table. Untick any frames that look wrong (clouds,
   bad guiding).
10. **Download AAVSO file**, inspect the plain-text rows, then upload
    at <https://www.aavso.org/webobs/file>.
11. **Click "Mark as submitted"** so the run history reflects state.

---

## Submit to AAVSO

The AAVSO Extended File the system produces is plain text in a
well-defined format. Lines starting with `#` are headers; the rest are
observation rows.

A typical row looks like:

```
RR LYR,2461168.50000,7.123,0.045,TG,NO,STD,ENSEMBLE,9.700,na,0.000,na,na,X42293DG,na
```

Columns: `NAME,DATE,MAG,MERR,FILT,TRANS,MTYPE,CNAME,CMAG,KNAME,KMAG,AMASS,GROUP,CHART,NOTES`.

**Before you upload**, sanity-check:

- Magnitudes are within the catalog range for the target (RR Lyr is
  ~7.0–8.1 mag)
- Errors are reasonable for your gear (~0.05 mag for OSC at urban skies
  is typical)
- The chart ID matches what the comp stars came from

Upload at <https://www.aavso.org/webobs/file>. AAVSO usually accepts
within a minute and you'll see your data in WebObs immediately.

> ⚠️ **Don't submit the rehearsal file.** Its observer code is `TEST`
> by design, but better not to push test data to production AAVSO.

---

## What to read next

- **[Concepts](concepts.md)** — if any term in this guide was unclear
- **[Horizon profile](horizon_profile.md)** — when you're ready to map
  your local obstructions
- **[Photometry pipeline](photometry.md)** — what the system does after
  you press *Run photometry*
- **[Troubleshooting](troubleshooting.md)** — when something doesn't work
