# NINA Setup for the Mira Workflow

This walks through configuring NINA to drive a Seestar S30 Pro using the
nightly target list this pipeline produces. The end state: you run
`mira tonight ...`, NINA imports the target list, and clicks
through slew → plate-solve → focus → capture → dither → next target without
further human input. Then a separate post-processing step (described in
`docs/photometry.md`) turns the captured FITS into AAVSO submissions.

## Prerequisites

- **NINA 3.x** (Windows). The "Advanced Sequencer" and Target Scheduler
  plugin both require 3.x. https://nighttime-imaging.eu/
- **ASCOM Platform 7+** — required for the Alpaca bridge.
- **Seestar S30 Pro** with firmware that supports ASCOM Alpaca and station
  mode (October 2025 firmware or newer). Updates happen via the Seestar
  app under Settings → Firmware.
- **Equatorial wedge** (e.g., the ZWO TH10) and a tripod tall enough for
  your observing site. NINA's sequencing assumes EQ tracking.

## One-time NINA configuration

### 1. Connect the S30 Pro to NINA

1. Power on the S30 Pro and let it connect to your home WiFi (station mode,
   not its own AP). The Seestar app shows the station-mode IP under
   Settings → WiFi.
2. In NINA, open Equipment → Telescope. Click "Add" → choose
   **ASCOM Alpaca** as the protocol. NINA's discovery should find the
   Seestar on the network.
3. Repeat for Equipment → Camera (also ASCOM Alpaca, same Seestar).
4. Equipment → Focuser, Filter Wheel: leave disconnected. The Seestar S30
   Pro has fixed focus and a single OSC sensor.
5. Equipment → Plate Solver: pick **ASTAP** (free, fast, recommended) or
   **astrometry.net** (slower but no install). Configure with default star
   catalog.

### 2. Install Target Scheduler plugin

In NINA: Plugins → Available → search "Target Scheduler" by Tom Palmer.
Install, restart NINA. Documentation:
https://tcpalmer.github.io/nina-scheduler/

### 3. Create an exposure-plan template

This is the per-target capture recipe. Once created, every imported
target reuses it.

In Target Scheduler: Profiles → your profile → Exposure Templates → Add.

Suggested S30 Pro / OSC values for variable-star photometry:

| Field | Value | Why |
|---|---|---|
| Filter | None (OSC) | S30 Pro is single-shot color |
| Exposure | 30 s (or per-target from `nina_targets.csv` if customised later) | Conservative for 30mm aperture |
| Gain | as configured by the S30 Pro driver | Usually fixed |
| Offset | as configured | Usually fixed |
| Binning | 1×1 | Don't bin; you want full pixel scale for photometry |
| Frame count | 60 | 30 min total integration is plenty for mag 9–12 |
| Dither every | 10 frames | Reduces fixed-pattern noise |

Save the template as **`S30 Pro OSC 30s`** (or similar).

### 4. Create a project for the pipeline targets

Target Scheduler organises targets into Projects. Create one:

- Name: **Mira**
- Description: "Targets imported from `mira tonight`"
- State: Active
- Mosaic: Off
- Exposure Order: as the template defines

You'll re-import targets into this project each session.

## Each-night workflow

### 1. Generate tonight's targets

```powershell
mira tonight --config config/s30_pro_jc.yaml --hours 4
```

This writes `output/s30_pro_jc/tonight/nina_targets.csv` plus the
session plan markdown for your phone.

### 2. Import into Target Scheduler

In NINA: Target Scheduler → Targets → Import CSV.

- File: `output/s30_pro_jc/tonight/nina_targets.csv`
- Project: `Mira` (the one you created above)
- Template: `S30 Pro OSC 30s` (so each target gets the same exposure plan)

The plugin parses the documented six-column format
(Type, Name, Ra, Dec, Rotation, ROI) and creates a target row per
candidate. Targets that were already in the project carry over their
prior state (last imaged, etc).

### 3. Run the sequence

In NINA: Sequencer → Advanced Sequencer → Load Sequence → load the
**Target Scheduler-driven sequence template** that ships with the
plugin (Patriot Astrophotography has a good one referenced from the
plugin docs). Press **Run**.

The sequence will: pick the next observable target from the project's
priority order → slew → plate-solve → autofocus (skipped on S30 Pro) →
run the exposure plan → repeat.

### 4. After the session

FITS files land in NINA's configured image directory, organized by
target name. The next batch (Phase 3) covers automated photometry +
AAVSO submission against those FITS files.

## Dry-running with NINA simulators

Before the S30 Pro arrives you can verify the whole stack against
NINA's built-in simulators:

1. Equipment → Telescope: choose **Telescope Simulator**.
2. Equipment → Camera: choose **Camera Simulator** (set to OSC, image
   size matching S30 Pro: 3008×3008).
3. Equipment → Plate Solver: leave as ASTAP/astrometry — they work
   against simulator-generated star fields.

Run a `tonight` pipeline, import the CSV, run the sequence. NINA will
report simulated slews/captures and write fake FITS files. Confirms the
target list parses, the sequence template executes, and your project
configuration is sound.

## Troubleshooting

- **Target Scheduler import errors** usually mean the CSV header isn't
  exact. The plugin is strict about column names: `Type, Name, Ra, Dec,
  Rotation, ROI`. Mira writes these exactly; if you've edited
  the CSV, verify column names case-sensitive.
- **Ra/Dec format mismatch**: Target Scheduler accepts `HHh MMm SSs` and
  `±DD° MM' SS"`. Mira writes that format. If you've imported
  Telescopius CSVs in the past and tweaked the parser, restore defaults.
- **NINA can't see the S30 Pro**: check the Seestar is in station mode
  (not AP mode) and on the same WiFi as your NINA computer. Some
  routers isolate clients — toggle "Client Isolation" off if you find
  Alpaca discovery failing.
- **Plate solve fails**: the S30 Pro's 4.6° FOV is generous; ASTAP
  should solve in under 5 seconds on first attempt. Failures usually
  indicate the rough pointing was off (poor polar alignment) or the
  filename pattern includes characters NINA's solver can't handle. Use
  default filename pattern.
