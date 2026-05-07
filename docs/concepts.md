# Concepts

A glossary and a few mental models. Read this if any term in
[Getting Started](getting_started.md) felt unfamiliar, or if you want
to know *why* the system does what it does, not just *how*.

---

## The big picture

Variable stars change brightness over time. Some pulse on a regular
schedule (Cepheids, RR Lyrae); some explode unpredictably (cataclysmic
variables, supernovae); some have eclipsing companions (Algol-type
binaries). Watching them — even with modest backyard gear — produces
genuinely useful data, because the universe of stars to monitor is
much larger than the population of professional telescope time.

The **AAVSO** (American Association of Variable Star Observers) has
coordinated this kind of work for over a century. Amateurs submit
observations; professional astronomers use the resulting decades-long
light curves to study stellar physics, calibrate distance scales, and
catch outbursts.

This project automates the parts that are tedious enough to discourage
beginners: picking which targets are worth observing, scheduling the
night, running differential photometry on captured frames, and
formatting submissions.

---

## Glossary

### Catalogs

**VSX** — *Variable Star Index*. AAVSO's master catalog of known and
suspected variable stars. ~2 million entries with positions, types,
periods, magnitude ranges. Queryable at
[`vsx.aavso.org`](https://vsx.aavso.org/) or programmatically through
VizieR. The system uses VSX as the source of all candidate targets.

**VSP** — *Variable Star Plotter*. AAVSO's tool for generating
photometry charts (finder charts with comparison stars marked). Each
chart has a unique ID like `X42293DG`. The system auto-fetches comp
stars from VSP for any target.

**SIMBAD** — A general astronomical database from CDS Strasbourg, with
cross-identifications for nearly every catalogued object. Used for
context: "the VSX entry's actual SIMBAD object type is `LP*`
(long-period variable)."

**Gaia DR3** — ESA's all-sky photometric/astrometric survey, third data
release. Used for sanity checks: parallax (distance), color (BP–RP),
RUWE (whether the source is a clean point or a blend).

**ZTF** — *Zwicky Transient Facility* light curves through IRSA. Optional
enrichment for top-ranked targets. Slow and rate-limited, so it's
strictly opt-in.

### Observing

**FITS** — *Flexible Image Transport System*. The standard astronomical
image file format. The system reads FITS files saved by NINA after the
scope captures and plate-solves each frame.

**WCS** — *World Coordinate System*. The transformation that maps pixel
positions in a FITS image to celestial coordinates (RA/Dec). NINA
performs **plate-solving** to determine the WCS, which lets the
photometry code locate target + comparison stars by sky position
rather than by where they happen to land in the frame.

**Plate-solving** — Comparing the stars in your captured image against
a star catalog to determine exactly where the telescope is pointing.
NINA does this automatically before each capture; the system trusts
the resulting WCS in the FITS header.

**Altitude** — How high a target is in the sky, in degrees from the
horizon (0° = horizon, 90° = directly overhead). Most observable
targets are above 25–45°, depending on light pollution.

**Azimuth** — Compass direction of a target, in degrees from North,
increasing clockwise. North = 0°, East = 90°, South = 180°, West = 270°.

**Galactic latitude** (`b`) — Angular distance from the Milky Way's
plane. Targets near the plane (`|b| < 12°`) sit in dense star fields
where photometry is harder; the system filters them out by default.

### Photometry

**Differential photometry** — Measuring a target's brightness *relative
to* nearby stars of known brightness, rather than measuring an
absolute flux. Cancels out atmospheric extinction and most calibration
errors. The system always does differential photometry.

**Comp star** (comparison star) — A nearby star of known, stable
brightness. Used as the reference in differential photometry. AAVSO
publishes vetted comp-star sequences for thousands of targets through
VSP.

**Ensemble photometry** — Using multiple comp stars at once and taking
a weighted average, instead of just one. More robust to a single bad
comp (cloud, contamination, blend). The system does this automatically
when 2+ comps are usable.

**Aperture photometry** — Summing pixel values in a circle around the
target, subtracting the average sky background measured in an annulus
around the source. Simple and well-understood. The system uses a 6"
radius aperture by default.

**Magnitude** — A logarithmic brightness scale where smaller numbers
mean brighter objects. The Sun is mag −27, Sirius is mag −1.5, the
faintest stars visible to the naked eye are about mag 6, the Seestar
S30 Pro reaches mag ~12 from urban skies.

**MAD** (median absolute deviation) — A robust spread estimator. Used
to flag outlier frames: any frame whose magnitude is more than 3·MAD
from the session median is marked as a likely bad measurement.

### Submission

**AAVSO Extended File Format** — The plain-text format AAVSO accepts
for upload. One header block followed by one row per observation. The
system writes this automatically.

**Observer code** — A 3–5 character identifier AAVSO assigns to you
when you register. Required on every submission so AAVSO can credit you.

**TG band** — Tri-color Green. The conventional band code for
observations made with the green channel of an OSC (one-shot color)
sensor. Close to V band but not identical; AAVSO accepts TG as a
distinct band.

### Anomaly

In this project, an **anomaly** is a session where your measured
median magnitude meaningfully differs from expectations. Two
expectations are checked:

1. **Catalog range**: VSX gives a brightness range for each target
   (e.g., RR Lyr varies between 7.06 and 8.12 mag). If your median is
   more than 0.3 mag outside this range, that's flagged.
2. **AAVSO recent baseline**: if the AAVSO archive has 10+ recent
   observations of this target, the system computes a robust median
   and MAD-based sigma. If your median is >3σ off the recent baseline,
   that's flagged as an anomaly. 2–3σ is flagged as "watch."

A flagged anomaly doesn't mean you've discovered something — it usually
means your photometry has a systematic error. But occasionally it
means the star is actually doing something interesting, and that's
worth following up.

---

## Mental models

### How the scheduler thinks

Given tonight's observing window (e.g., 20:00–00:00), the scheduler
greedy-picks targets one at a time. At each step:

1. From the candidate queue, find every target whose **observable
   window** intersects the current cursor time.
2. Among those, pick the one with the highest **score + urgency
   bonus**. Urgency is `max(0, 30 minutes - time_until_set)` — targets
   about to drop below the horizon get prioritized.
3. Allocate slew + integration time, advance the cursor.
4. Repeat until the night ends or no candidates remain.

**Observable window** is approximated as `best_local_time ±
(minutes_above_horizon / 2)`. It's not a true rise/set window; it's a
"target is high enough during this stretch" window. Good enough for a
scheduling decision; not for arc-second pointing.

**Horizon profile** (when configured) tightens the floor per direction.
A target whose peak altitude over the night is high enough to clear the
global floor but whose *peak moment* puts it behind your tree gets
correctly rejected.

The scheduler does *not* optimize slew distance between consecutive
targets. For a small home setup, the slew penalty is negligible.

### How photometry works

When you press *Run photometry* on a captures directory:

1. **Look up the target in VSX** to get its catalog RA/Dec.
2. **Fetch comp stars from VSP** (or use a hand-curated JSON file).
3. **Pre-flight**: read the first FITS frame, verify it has a celestial
   WCS. Bail fast if it doesn't (saves time vs. churning through 30
   frames before failing).
4. For each FITS frame:
   - Find the target's pixel position via the WCS
   - Sum aperture flux around it, subtract sigma-clipped sky background
   - Do the same for each comp star
   - Compute differential magnitude: `target_mag = comp_mag - 2.5·log10(target_flux / comp_flux)`
   - When 2+ comps survive, compute a weighted ensemble average and
     drop any individual estimate >2σ from the median
5. **Flag outliers** across the session via MAD.
6. **Write the AAVSO Extended File**.
7. **Plot light curves**: tonight's points overlaid on AAVSO recent
   observations and your prior nights of this target.
8. **Run anomaly assessment**.
9. **Index the session** in the SQLite store so the per-target history
   page can show it.

### How the horizon profile interacts with altitude

Without a horizon profile:
- Each site has a single `min_altitude_deg` (e.g., 45° from JC).
- A target is observable when its altitude exceeds that floor for any
  amount of time during the dark window.

With a horizon profile:
- The system computes the target's *azimuth* per sample as well as its
  altitude.
- The effective floor per sample is `max(min_altitude_deg,
  horizon_at_az)`.
- A target whose best moment puts it behind a tree (altitude high
  enough but azimuth pointing into the tree) gets correctly rejected.

The profile is per-site, optional, and authored as a YAML list of
(azimuth, altitude) silhouette points. The system interpolates linearly
between them and wraps cleanly through azimuth 0°/360°.

### How submissions get organized

- **Run records** persist as JSON in `data/webapp_runs/<run_id>.json`.
  This is the canonical source of truth for everything that happened.
- **Sessions DB** (`data/webapp_runs/sessions.db`) is a SQLite index
  built from the run records. Lets `/data/sessions` and friends do
  fast queries. Rebuildable any time via `mira migrate-runs`.
- **Capture artifacts** (FITS frames, AAVSO file, plot PNGs) live next
  to each other in `captures/<TARGET>/<DATE>/`.
- **Schedule snapshots** are archived to
  `output/<config>/archive/<DATE>/` so re-running tonight's plan
  doesn't trample yesterday's.

See [Storage layout in HANDOFF.md](../HANDOFF.md#storage-layout) for
the full diagram.

---

## What "anomaly" doesn't mean

A few clarifications worth stating explicitly:

- This project does **not** detect new variable stars. It assumes the
  target is already in VSX and has well-characterized expectations.
- It does **not** classify variability type. It surfaces magnitude
  deviations from expectation, which is one signal among many.
- It does **not** correct for atmospheric extinction or transformation
  coefficients. AAVSO accepts un-transformed OSC photometry, but
  precise differential photometry from urban skies has systematic
  uncertainty around 0.05–0.1 mag that the system doesn't try to fix.

For research-grade photometry on faint targets, you want a dedicated
photometric setup with filtered observations and characterized
transforms. This project is for engaged amateur observation that
contributes useful magnitude estimates to AAVSO.
