# Rigs — current state

*The single source of truth for what hardware exists and how it's configured.
Last full pass: 2026-06-11. The `astrophotography_rig_plan_v7/v8` docs are
**planning history** — when they disagree with this file, this file wins.
(Biggest delta: the planned Askar 65PHQ second OTA became a Sky-Watcher
Esprit 80 ED, bought on clearance.)*

## Fleet at a glance

| | **S30 Pro** | **Esprit 80 ED** | **Esprit 120 EDX** |
|---|---|---|---|
| OTA | ZWO Seestar S30 Pro (sealed all-in-one) | Sky-Watcher Esprit 80 ED, 400mm f/5 FPL-53 triplet (pre-EDX clearance unit) | Sky-Watcher Esprit 120 EDX, 840mm f/7 triplet |
| Camera | built-in IMX585 OSC | shared ASI2600MM Pro train ↓ | shared ASI2600MM Pro train ↓ |
| FOV / scale | **3.91°×2.20° @ 3.66″/px** (measured — eff. fl ≈ 163mm, *not* nominal 150) | **3.37°×2.25° @ 1.94″/px** | **1.60°×1.07° @ 0.92″/px** |
| Frame rotation | **fixed** (no rotator; long axis ≈ N–S, ~4° tilt) | manual at setup — suggested PA per target in its book | manual at setup |
| Mount | wedge → **EQ mode** (no field rotation; long subs fine) | ZWO AM7 on Apertura Anchor pier | same AM7/pier (one mount, tubes swap) |
| Control | NINA on the laptop (single-machine) | NINA on the MeLE Quieter 4C | NINA on the MeLE Quieter 4C |
| Filters | LP dual-band (Ha+OIII) / IR-cut broadband wheel | shared EFW: Antlia LRGB-**V** + SHO 3nm | same shared EFW |
| Photometry reach / band | mag ~12, AAVSO **TG** (OSC) | mag ~15, Johnson **V** | mag ~16, Johnson **V** |
| mira config | `config/s30_pro_jc.yaml` | `config/esprit80_jc.yaml` | `config/esprit120_jc.yaml` |
| Image book | `output/books/s30_emission_book/` | `output/books/esprit80_emission_book/` | `output/books/esprit_emission_book/` |
| Role | wide-field scout: LP emission giants, broadband galaxies, AAVSO TG, trips | the in-between field: dark-site trips, LRGB dust/reflection, medium-large emission single-frame, rotation rescues (California) | science rig: narrowband features (<25′), V-band photometry, deepest reach |

Cross-rig target arbitration: `output/books/rig_fit_matrix.md`.

## The shared mono train (Esprit 80 ⇄ 120 swap model)

One camera train serves both Esprits: **ASI2600MM Pro + ZWO EFW (Antlia
LRGB-V + Ha/OIII/SII 3nm) at 55mm back-focus**, one guide module (ZWO 30F5 +
ASI220MM Mini) that transfers between tubes via **Vixen finder shoe**, one
AM7 + pier, one MeLE running NINA.

**Back-focus with filters:** 55mm is the *in-air* spec; a filter in the
converging beam pushes focus back by ~thickness/3. Antlia 36mm substrate =
1.85mm (uniform across the line — that's what makes the wheel parfocal) →
target **≈55.6mm: run a 0.5mm M48 shim** in the spacer stack. One shim
covers every slot, travels with the camera stack between both OTAs (same
55mm flattener convention), and matters more at the 80's f/5 than the
120's forgiving f/7. Verify with corner stars / NINA's Aberration
Inspector and iterate ±0.5mm — the arithmetic aims, the corners judge.

**Train stack (with the ZWO CAA rotator, added 2026-06-12):**
flattener (M48 male) → **ZWO M54–M48 flanged adapter, 2.0mm** (M48F→M54M;
NOT included with the CAA or camera — purchased separately 2026-06-12) →
**CAA 16.5mm** (scope side = fixed M54 female half with the USB-C port;
camera side = rotating half wearing the M48 accessory plate) → **EFW
20mm** → **ASI2600MM 17.5mm** = **56.0mm** — 0.38mm over the 55.62
filter-corrected ideal, inside f/5 tolerance; the 0.5mm filter shim is
OMITTED in this build (no budget). Bench check: flattener-seating
shoulder → camera flange = **38.5mm** by caliper. If first-light corners
object: thinner ~1mm third-party ring + shim back in. USB-C half faces
the sky and never rotates; EFW+camera ride the rotating half. (CAA box
contents for the record: M54 + M48 camera-side male plates + hex wrench
+ a 21mm M54 extension for EFW-less trains — nothing for an M48 scope
side.)

**CAA assembly gotcha (caught on the bench 2026-06-12):** threading
anything onto the camera-side plate makes the unpowered rotor spin with
your hand — the joint parks several mm proud of seating (we measured a
7mm phantom gap; 43mm CAA+EFW vs 36.5 expected). Fix: **unbolt the
output plate (hex wrench), thread the EFW fully home onto the plate on
the bench, then bolt the assembly back onto the rotor** — or power the
CAA via USB-C (energized stepper holds) + grip the ring while
threading. Scope-side joints are on the fixed half and don't have this
problem. Acceptance: CAA+EFW calipers ~36–36.5mm seated.
CAA rotates EFW+camera together → sensor/filter dust rotates with the
train, so **flats stay valid at any angle** (only *flattener* dust doesn't
rotate — keep that glass clean). Cabling: EFW into the 2600's rear USB
hub so one USB3 + one power lead leave the rotating section, service-loop
sized for full travel, **rotation limits set in the ASCOM driver** (PA is
mod-180; limited travel costs nothing). NINA: Rotator device + per-target
PA in sequences — the trip-book PA suggestions are now automated, not
setup-time commitments.

**Narrowband bandpass shift:** the 3nm filters are fine on both tubes —
f/5 cone-averaged blue-shift ≈ 0.3–0.5nm (worst corner marginal ray
~1.5nm) vs the ±1.5nm half-band + the manufacturer's fast-beam CWL
offset; f/7 is negligible. Revisit only if a reducer ever pushes below
~f/4 (high-speed filter territory). Note: emission-line corner loss from
CWL shift is NOT flat-correctable (flats are continuum) — at f/5 it's
percent-level, ignore. Swapping OTAs is ~10 minutes: tube +
rings + top rail move as a unit; train, guiding, and cabling stay dialed.
The V slot is a real Johnson-V photometric filter — `mira submit` emits
true `V` from either Esprit (vs the S30's OSC→TG convention).

## S30 Pro specifics

- **Effective focal length is 163mm**, confirmed repeatedly by plate solves
  (3.66–3.67″/px). Use `-focal=163` everywhere (solving, Siril `platesolve`);
  the nominal 150mm underestimates the FOV math by ~9%.
- **Gain 80 = HCG knee** (Cloudy Nights consensus for the Seestar's IMX585
  scale). Flats must match gain — current masters are LP_g80 era.
- **Filter slots**: `LP` = dual-band Ha+OIII → emission targets, moon-tolerant.
  `IR` = IR-*cut* broadband (not IR-pass) → galaxies/clusters/star fields,
  moon-strict. Don't leave LP in for broadband targets.
- **Sealed system** → master flats reusable session-to-session per
  filter/gain (paper-over-aperture to shoot them).
- **Dew control built in** — no straps/shields needed (Esprits only).
- Hard-won operational gotchas (full stories in NINA docs + memory):
  - `--park-at-end` can drop the Seestar's entire NINA connection → it's
    default OFF; opt in only on the **last** run of the night.
  - **Never let NINA `MoveAxis` the S30** (TPPA crashes it → restart). Use
    TPPA Manual Mode or the Seestar app's native alignment.
  - NINA **Center works** (fixed 2026-05-30: `-focal=163` + ~10s solve
    exposure) → use `--platesolve-center`. Manual *sync* is additive — avoid.
  - Target Scheduler dither silently no-ops without a guider → connect
    NINA's **Direct Guider**. (`mira capture` dithers via mount-slew itself.)
  - `StartExposure: not supported` = device not imaging-ready (check the
    phone app isn't holding it), not a NINA/parameter bug.
  - File access: guest SMB `\\SeeStar.local\EMMC Images`; device sleeps
    mid-copy and robocopy `/Z` preallocates (file size ≠ transfer done).
    Planetary RAW AVI needs the custom `avi_reader.py` parser and
    auto-exposes for the whole scene (planets saturate).

## Esprit 80 ED specifics

- Pre-EDX clearance unit; classic Esprit flattener at the 55mm back-focus
  convention. Solar perk: with the Daystar Quark (4.3×) → f/21.5 / 1720mm,
  inside the Quark's happy range.
- **Flats: paper mode only.** The Wanderer Cover V4-EC 190mm is sized for
  the 120's dew shield and does not clamp the 80's. Shoot flats in the field
  at dawn **before touching focus or rotation**
  (`mira flats --filters L,R,G,B --gain 100`).
- **Top accessory rail**: Sky-Watcher **255mm Universal D-plate** bolted
  across the tube-ring tops, carrying up to **3 Vixen guide-scope shoes**
  (guide module forward + spares/balance positions).
  - Shoe→plate joint is a through-bolt sandwich in the plate's slots:
    M4 flat-head countersunk (×20–25) → shoe countersink → slot →
    **12mm-OD M4 fender washer** (the 13mm underside pocket self-centers
    it; stock 8.7mm washers pull through) → nyloc. Two screws per shoe =
    no rotation.
  - Plate→rings screws: 1/4″-20×3/4″ purchased, **PENDING the ring-tap
    thread test** — pull a carry-handle screw first; if the taps are M6
    (Sky-Watcher default), use M6×16 instead. Never wrench a 1/4-20 into
    an M6 tap.
  - Under-plate screw tails/nuts at the forward overhang must clear the
    **sliding dew shield**.
- First deployment: Catskills trip (`output/trips/catskills_jun20/`) —
  Iris+Ghost LRGB. No baked LRGB-combine flow yet; the trip kit's
  `combine_lrgb.py` (WCS-reproject filter masters onto the L grid) is the
  current pattern.

## Esprit 120 EDX specifics

- AM7 runs the 120's ~30 lb imaging payload at ~68% utilization, no
  counterweights.
- **Wanderer Cover V4-EC 190mm**: motorized cover + EL flat panel + dew
  heater. `mira flats` auto-drives it (close, light, capture, light off;
  cover doubles as dust cap). Masters valid only until focus/rotation/dust
  change — refocus → re-shoot flats.
- **Top accessory rail**: Sky-Watcher **355mm Universal D-plate** across the
  ring tops carrying guide scope (forward) + **MeLE on its Buckeye bracket**
  (mid) + Pegasus Powerbox (aft). Bracket→plate uses the narrow ~30mm
  pedestal pair; MeLE→bracket uses the wide ~80mm slot banks (annotated
  photos: `output/site/buckeye_mounting*.png`).
- Pegasus FocusCube autofocus; PHD2 guiding via the shared 30F5/220MM.
- Medium-term role is **narrowband astrophotography first** (NINA Target
  Scheduler directly, not `mira tonight`); `esprit120_jc.yaml` exists for
  the photometry nights.
- Filter wheel labels must be canonical (`Ha/OIII/SII/L/R/G/B/V` +
  `Dark`) — `mira doctor` hard-fails otherwise, by design.

## Calibration matrix

| | Flat source | Master reuse | Notes |
|---|---|---|---|
| S30 Pro | paper over aperture | **session-to-session** (sealed optics) | masters keyed `<filter>_g<gain>` under `data/flats/` |
| Esprit 80 | paper (no panel fit) | until focus/rotation change | field flats at dawn pre-teardown |
| Esprit 120 | Wanderer EL panel (auto) | until focus/rotation/dust change | per-filter brightness via ASCOM driver |

Auto-resolve chain: `mira capture` writes the `mira_capture.json` sidecar
(NINA FITS carry **no FILTER keyword**) → `mira stack --auto-flats` resolves
the newest matching master → hard-aborts on any miss.

## Sites + field operations

- **Jersey City backyard** (Bortle 8–9): both piers; the house blocks part
  of the sky — altitude alone is not enough, the horizon profile
  (`config/horizon_balcony_jc.yaml`) is load-bearing.
- **Dark-site trips**: kit + plan pattern under `output/trips/<trip>/`.
  Field networking (no site WiFi): travel router (one LAN for laptop + MeLE
  + Seestar) or direct Ethernet + Seestar AP — and mind the Windows
  Public-profile firewall trap. Details in the trip plan's Field network
  section.

## Open hardware items (2026-06-11)

1. Esprit 80 ring-tap thread test (M6 vs 1/4-20) → buys the right
   plate→ring screws.
2. M4 fender washers (12mm, stainless) + nylocs on order for the shoe
   sandwich.
3. MeLE Syncthing "plans" share still points at a pre-reorg path → repoint
   to `output/runs/esprit120_jc/tonight`.
4. Travel router purchase/test before the next no-WiFi trip.
