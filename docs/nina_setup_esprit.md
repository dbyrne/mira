# NINA setup for the Esprit 120 rig (MeLE Quieter)

The Esprit rig has more moving parts than the Seestar: mount, mono camera
with cooling, autofocus, filter wheel, guider. This doc walks the
end-state configuration of NINA on the MeLE so `mira capture`,
`mira flats`, and `mira dso status` all work.

For the S30 Pro single-machine setup, see [`nina_setup.md`](nina_setup.md).
For the rig-vs-homebase workflow split, see [`rig_workflow.md`](rig_workflow.md).

## Prerequisites

Before opening NINA, you should already have:

- **MeLE Quieter** running Windows, with Remote Desktop enabled.
- **`scripts\bootstrap.ps1 -Rig esprit`** run successfully — Python venv,
  Mira editable install, Siril, ASTAP, Syncthing, PHD2 all in place.
- **Windows-side installers run by hand** (no silent path for these):
  - ASCOM Platform 7+ — <https://ascom-standards.org/>
  - NINA 3.x — <https://nighttime-imaging.eu/>
  - ZWO ASCOM drivers (camera + AM5N + EFW) — <https://astronomy-imaging-camera.com/software-drivers>
  - Pegasus Unity (FocusCube 3 + PocketPowerbox Gen2) — <https://pegasusastro.com/pegasus-unity/>

## NINA Equipment configuration

Connect each device in NINA's **Equipment** tab. Use the ASCOM driver for
each unless noted; click "Connect" after selecting the driver. Verify each
device reports state (cooling, position, current filter, etc.).

### Mount (AM5N)

Equipment → Telescope → **ZWO AM5/AM3 ASCOM Driver** → Connect.

- Set the home position before the first session (NINA → Telescope panel →
  "Set Park Position"). The AM5N's harmonic drive holds position
  off-power, so park is mostly cosmetic for shutdown.
- For polar alignment, use NINA's **Three Point Polar Alignment (TPPA)**
  plugin (install via Plugins → Available) or PoleMaster if you have one.

### Camera (ASI2600MM Pro)

Equipment → Camera → **ZWO ASI Camera** → Connect.

- In the **Camera** tab on the right, set the cooling target. **-10 °C**
  is a safe choice for JC summer; **-15 °C** in cooler months. Wait for
  the camera to reach within 1 °C of target before capturing.
- Confirm the gain setting matches what your scripts expect (Mira's
  Esprit profile defaults to `gain: 100` for narrowband).

### Filter wheel (ZWO EFW 7×36mm)

Equipment → Filter Wheel → **ZWO EFW ASCOM Driver** → Connect.

**Critical: filter position names must match the canonical Mira set exactly.**

`mira doctor --config config/esprit120_jc.yaml` FAILs if any wheel
position label drifts. The DSO ledger keys off these exact names — a
position labelled "H-alpha" instead of `Ha` produces orphan ledger
entries that go unnoticed for hours.

Rename via NINA → Equipment → Filter Wheel → **Filters** tab. Use exactly:

| Slot | Name | Filter |
|---|---|---|
| 1 | `L` | Antlia LRGB-V Luminance |
| 2 | `R` | Antlia LRGB-V Red |
| 3 | `G` | Antlia LRGB-V Green |
| 4 | `B` | Antlia LRGB-V Blue |
| 5 | `V` | Antlia LRGB-V Photometric V (Johnson V — the AAVSO-acceptable one) |
| 6 | `Ha` | Antlia 3nm H-alpha |
| 7 | `OIII` | Antlia 3nm OIII |

You only have 7 positions on the EFW, so `SII` will need to either
displace one of the broadband filters or get used in a separate session.
Pick whichever fits your imaging plan. If you ever add `SII` to a slot,
label it exactly `SII`.

Case matters: `Ha` (not `HA` or `ha`). Run `mira doctor --config
config/esprit120_jc.yaml` after labelling to confirm the check passes.

### Focuser (Pegasus FocusCube 3)

Equipment → Focuser → **PegasusAstro FocusCube** → Connect.

- Set step sizes in **Imaging → Autofocus** (NINA → Options → Imaging →
  Autofocus). Reasonable starting values: step size 30, samples 7,
  exposure 10 s, autofocus-after-temperature 2 °C.
- Run a one-time autofocus per filter to find each filter's offset
  (NINA → Imaging tab → "Autofocus" button). Save offsets in the filter
  wheel config so the focuser nudges automatically when the wheel rotates.

### Guider (ZWO 30mm f/5 + ASI220MM Mini via PHD2)

Equipment → Guider → **PHD2** → Connect (NINA launches PHD2 if it isn't
running already).

Inside PHD2 itself:

1. Profile → New profile → name it "Esprit guider".
2. Camera: ASI220MM Mini. Focal length: 150 mm. Pixel size: 4.0 µm.
3. Mount: ASCOM (point at the same AM5N profile).
4. Run the guiding-assistant calibration on a clear night before
   committing to a long DSO session.

In NINA → Options → Imaging → **Guider**, set "Settle pixels" to 1.5 and
"Settle time" to 10 seconds. After a dither, NINA waits for PHD2 to
report the guide error within 1.5 px for 10 consecutive seconds before
exposing again. Less aggressive than the defaults; less rejected frames.

### Plate solver (ASTAP)

NINA → Options → Plate Solving.

- Plate Solver: **ASTAP**
- ASTAP location: usually auto-detected. If not, point at
  `C:\Program Files\astap\astap_cli.exe`.
- Star database: the D50 catalog (~870 MB) ships via
  `bootstrap.ps1 -WithStarDB`. Verify there are `*.290` files next to
  `astap_cli.exe` — without them ASTAP returns "No solution."

### Plugins (NINA → Plugins → Available)

Required:

- **Advanced API** — exposes the local HTTP API at `http://localhost:1888`
  that `mira capture` drives.
- **Target Scheduler** — imports `nina_targets.csv` from `mira tonight`.

Recommended:

- **Three Point Polar Alignment** — TPPA routine.
- **Touch'N'Stars** — phone-side monitoring during a session.

## File paths

NINA → Options → **Imaging** → "Image File Path Pattern".

Set the **base directory** to a Syncthing-shared path so captures mirror
to homebase as they're written. Example: `C:\mira\captures`. Use this
exact path (or whatever you pick) as `capture_defaults.nina_root` in
`config/esprit120_jc.yaml`.

Recommended file path pattern (so each session lands in its own dir
named for the target):

```
$$TARGETNAME$$_$$DATE$$\$$TARGETNAME$$_$$FILTER$$_$$EXPOSURETIME$$s_$$IMAGECOUNT$$
```

`mira capture` writes its `mira_capture.json` sidecar into the per-session
target dir; the file path pattern above keeps things consistent.

## First-light checklist

Run through these in order:

1. **Polar align** with TPPA (or PoleMaster).
2. **Connect all equipment** in NINA (mount, cam, wheel, focuser, guider).
3. **Set cooling** target; wait for camera to settle.
4. `mira doctor --config config/esprit120_jc.yaml` from a PowerShell on
   the MeLE. Expect:
   - PASS Python, deps, Siril, ASTAP, NINA reachability
   - PASS Filter wheel (all canonical)
   - PASS Darkness tonight (assuming you're imaging during dark hours)
5. **Slew to a bright star** (Vega, Deneb) and run autofocus per filter
   to seed the offsets.
6. **Calibrate PHD2** on a star near the celestial equator + meridian
   (recommended). Save the calibration.
7. **First test capture:** `mira capture --config config/esprit120_jc.yaml
   --ra <ra> --dec <dec> --exposure 5 --gain 100 --filter V --dest
   captures/test_$(Get-Date -Format yyyyMMdd)` — verify the FITS lands in
   the dest dir AND a `mira_capture.json` sidecar is written. The
   "Siril Live Stack (homebase)" hint will print the watch folder.
8. **Verify Syncthing** mirrored the test capture to homebase. The hint
   path should now exist on both sides.

## After a session

On homebase (the captures are already mirrored via Syncthing):

```powershell
mira dso status --config config/esprit120_jc.yaml  # what got imaged
mira stack --lights <session_dir> --out output/<target>_<date>.tif --auto-flats
```

If the session was a V-filter photometry run (variable star with comp
stars), follow up with `mira submit` per [`photometry.md`](photometry.md).

## Troubleshooting

- **`mira doctor` fails "non-canonical name(s)"** → rename the offending
  position in NINA → Equipment → Filter Wheel → Filters. The exact name
  needed is in the FAIL message. Case-sensitive.
- **NINA reports "camera_state=NoState"** → reconnect the camera in NINA.
  See `nina-api-and-seestar-fixes.md` in your memory; same trap can
  produce byte-identical stale frames.
- **Captures land but `mira_capture.json` doesn't write** → `mira capture`
  was invoked without `--filter`. Without it, the sidecar's filter field
  is empty and `mira dso status` won't book the session. Re-capture with
  `--filter <name>` (canonical name from the wheel).
- **ASTAP returns "No solution"** → missing star DB. Run
  `bootstrap.ps1 -WithStarDB` or grab D50 from <https://www.hnsky.org/astap.htm>.
