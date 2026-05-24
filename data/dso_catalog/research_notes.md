# DSO catalog — research notes

Catalog v2026-05-24 • 44 targets • regenerate with `mira dso research`.

This is the offline-research view of the catalog — every target, grouped by best-observing season, with external links for deeper reading. For *which targets are observable tonight*, run `mira dso plan` instead.

## Index

| Target | Common | Type | Const | RA (J2000) | Dec | Size | Mosaic |
|---|---|---|---|---|---|---|---|
| [`NGC 1499`](#ngc-1499) | California Nebula | HII | Per | 04h 00m 00.0s | +36° 34' 58.8" | 145' × 40' | yes |
| [`IC 405`](#ic-405) | Flaming Star Nebula | HII | Aur | 05h 16m 16.1s | +34° 22' 01.2" | 37' × 19' |  |
| [`IC 410`](#ic-410) | Tadpoles Nebula | HII | Aur | 05h 22m 55.9s | +33° 30' 00.0" | 40' × 30' |  |
| [`M1`](#m1) | Crab Nebula | SNR | Tau | 05h 34m 31.9s | +22° 00' 50.4" | 6' × 4' |  |
| [`M42`](#m42) | Orion Nebula | HII | Ori | 05h 35m 17.3s | -05° 23' 27.6" | 65' × 60' |  |
| [`NGC 1977`](#ngc-1977) | Running Man Nebula | REF | Ori | 05h 35m 27.8s | -04° 42' 00.0" | 40' × 25' |  |
| [`Sh2-240`](#sh2-240) | Spaghetti Nebula SNR | SNR | Tau | 05h 36m 40.1s | +28° 00' 00.0" | 180' × 180' | yes |
| [`IC 434`](#ic-434) | Horsehead Nebula | HII | Ori | 05h 41m 00.0s | -02° 27' 00.0" | 60' × 10' |  |
| [`NGC 2174`](#ngc-2174) | Monkey Head Nebula | HII | Ori | 06h 06m 30.0s | +20° 30' 00.0" | 40' × 30' |  |
| [`NGC 2237`](#ngc-2237) | Rosette Nebula | HII | Mon | 06h 31m 52.1s | +04° 57' 00.0" | 80' × 80' |  |
| [`NGC 2264`](#ngc-2264) | Christmas Tree / Cone Nebula | HII | Mon | 06h 41m 00.0s | +09° 52' 58.8" | 60' × 30' |  |
| [`Abell 21`](#abell-21) | Medusa Nebula | PN | Gem | 07h 31m 60.0s | +13° 15' 00.0" | 10' × 10' |  |
| [`Abell 31`](#abell-31) | Abell 31 PN | PN | Cnc | 08h 41m 22.1s | +08° 43' 58.8" | 16' × 16' |  |
| [`M97`](#m97) | Owl Nebula | PN | UMa | 11h 14m 48.0s | +55° 01' 01.2" | 3' × 3' |  |
| [`M20`](#m20) | Trifid Nebula | HII | Sgr | 18h 02m 31.9s | -23° 01' 58.8" | 28' × 28' |  |
| [`M8`](#m8) | Lagoon Nebula | HII | Sgr | 18h 03m 40.1s | -24° 22' 58.8" | 90' × 40' |  |
| [`M16`](#m16) | Eagle Nebula / Pillars of Creation | HII | Ser | 18h 18m 48.0s | -13° 48' 00.0" | 30' × 20' |  |
| [`M17`](#m17) | Omega / Swan Nebula | HII | Sgr | 18h 20m 48.0s | -16° 11' 60.0" | 11' × 11' |  |
| [`M57`](#m57) | Ring Nebula | PN | Lyr | 18h 53m 35.0s | +33° 01' 44.4" | 1' × 1' |  |
| [`M27`](#m27) | Dumbbell Nebula | PN | Vul | 19h 59m 36.2s | +22° 43' 15.6" | 8' × 6' |  |
| [`Sh2-101`](#sh2-101) | Tulip Nebula | HII | Cyg | 20h 00m 00.0s | +35° 17' 60.0" | 17' × 12' |  |
| [`NGC 6888`](#ngc-6888) | Crescent Nebula | WR | Cyg | 20h 12m 06.0s | +38° 21' 00.0" | 18' × 13' |  |
| [`IC 1318`](#ic-1318) | Butterfly / Sadr Region | HII | Cyg | 20h 22m 00.0s | +40° 15' 00.0" | 240' × 180' | yes |
| [`NGC 6960`](#ngc-6960) | Western Veil / Witch's Broom | SNR | Cyg | 20h 50m 59.8s | +30° 43' 01.2" | 70' × 6' |  |
| [`NGC 6992`](#ngc-6992) | Eastern Veil | SNR | Cyg | 20h 52m 09.8s | +31° 43' 01.2" | 60' × 8' |  |
| [`IC 5070`](#ic-5070) | Pelican Nebula | HII | Cyg | 20h 54m 40.1s | +44° 22' 01.2" | 60' × 50' |  |
| [`NGC 7000`](#ngc-7000) | North America Nebula | HII | Cyg | 20h 58m 56.9s | +44° 20' 13.2" | 120' × 100' | yes |
| [`NGC 7023`](#ngc-7023) | Iris Nebula | REF | Cep | 21h 01m 31.0s | +68° 09' 28.8" | 18' × 18' |  |
| [`IC 1396`](#ic-1396) | Elephant's Trunk Nebula | HII | Cep | 21h 37m 60.0s | +57° 30' 00.0" | 170' × 140' | yes |
| [`Abell 78`](#abell-78) | Abell 78 | WR | Cyg | 21h 45m 60.0s | +31° 30' 00.0" | 2' × 2' |  |
| [`NGC 7822`](#ngc-7822) | Cederblad 214 region | HII | Cep | 00h 00m 19.9s | +68° 34' 01.2" | 60' × 30' |  |
| [`M31`](#m31) | Andromeda Galaxy | REF | And | 00h 42m 44.4s | +41° 16' 08.4" | 190' × 60' | yes |
| [`NGC 281`](#ngc-281) | Pacman Nebula | HII | Cas | 00h 53m 00.0s | +56° 37' 01.2" | 35' × 30' |  |
| [`Sh2-188`](#sh2-188) | Dust Cap PN | PN | Cas | 01h 16m 43.9s | +58° 17' 60.0" | 10' × 8' |  |
| [`M33`](#m33) | Triangulum Galaxy | REF | Tri | 01h 33m 50.9s | +30° 39' 36.0" | 73' × 45' |  |
| [`M76`](#m76) | Little Dumbbell | PN | Per | 01h 42m 19.9s | +51° 34' 30.0" | 3' × 2' |  |
| [`IC 1805`](#ic-1805) | Heart Nebula | HII | Cas | 02h 34m 19.9s | +61° 28' 01.2" | 150' × 150' | yes |
| [`IC 1848`](#ic-1848) | Soul Nebula | HII | Cas | 02h 50m 00.0s | +60° 25' 58.8" | 100' × 100' | yes |
| [`NGC 7293`](#ngc-7293) | Helix Nebula | PN | Aqr | 22h 29m 38.9s | -20° 50' 13.2" | 25' × 17' |  |
| [`NGC 7380`](#ngc-7380) | Wizard Nebula | HII | Cep | 22h 45m 60.0s | +58° 07' 01.2" | 25' × 25' |  |
| [`Sh2-155`](#sh2-155) | Cave Nebula | HII | Cep | 22h 52m 49.9s | +62° 37' 01.2" | 50' × 30' |  |
| [`NGC 7635`](#ngc-7635) | Bubble Nebula | HII | Cas | 23h 20m 47.0s | +61° 11' 49.2" | 15' × 8' |  |
| [`M52`](#m52) | M52 + Bubble region | HII | Cas | 23h 24m 43.0s | +61° 35' 27.6" | 60' × 30' |  |
| [`NGC 7662`](#ngc-7662) | Blue Snowball | PN | And | 23h 24m 53.0s | +42° 32' 45.6" | 0' × 0' |  |

## Winter (Dec–Feb)

_13 target(s). RA range listed first; suggested observing months in parentheses._

### NGC 1499 — California Nebula

**Emission nebula (HII region)** in **Per** • 145' × 40' • **mosaic candidate**

- **Coords (J2000):** RA `04h 00m 00.0s` (60.0000°) / Dec `+36° 34' 58.8"` (+36.5830°)
- **Recommended budget:** Ha 600m • OIII 600m • SII 480m (total 28.0h)
- **Expected emission:** Ha-dominant; OIII varies (often faint, sometimes strong as in M16/M17 cores); SII for SHO palette
- **Catalog notes:** Two-panel mosaic at 1.6° width; pure Ha can be done single panel cropped
- **Research:** [SIMBAD](https://simbad.cds.unistra.fr/simbad/sim-id?Ident=NGC+1499) • [Aladin](https://aladin.u-strasbg.fr/AladinLite/?target=NGC+1499&fov=2) • [NED](https://ned.ipac.caltech.edu/byname?objname=NGC+1499) • [Telescopius](https://telescopius.com/deep-sky-targets?searched=California+Nebula) • [Astrobin](https://www.astrobin.com/search/?q=California+Nebula) • [Wikipedia](https://en.wikipedia.org/wiki/California_Nebula)

### IC 405 — Flaming Star Nebula

**Emission nebula (HII region)** in **Aur** • 37' × 19' • single frame

- **Coords (J2000):** RA `05h 16m 16.1s` (79.0670°) / Dec `+34° 22' 01.2"` (+34.3670°)
- **Recommended budget:** Ha 540m • OIII 600m • SII 540m (total 28.0h)
- **Expected emission:** Ha-dominant; OIII varies (often faint, sometimes strong as in M16/M17 cores); SII for SHO palette
- **Catalog notes:** Often paired with IC 410 in wider mosaics; single-frame OK
- **Research:** [SIMBAD](https://simbad.cds.unistra.fr/simbad/sim-id?Ident=IC+405) • [Aladin](https://aladin.u-strasbg.fr/AladinLite/?target=IC+405&fov=2) • [NED](https://ned.ipac.caltech.edu/byname?objname=IC+405) • [Telescopius](https://telescopius.com/deep-sky-targets?searched=Flaming+Star+Nebula) • [Astrobin](https://www.astrobin.com/search/?q=Flaming+Star+Nebula) • [Wikipedia](https://en.wikipedia.org/wiki/Flaming_Star_Nebula)

### IC 410 — Tadpoles Nebula

**Emission nebula (HII region)** in **Aur** • 40' × 30' • single frame

- **Coords (J2000):** RA `05h 22m 55.9s` (80.7330°) / Dec `+33° 30' 00.0"` (+33.5000°)
- **Recommended budget:** Ha 540m • OIII 720m • SII 540m (total 30.0h)
- **Expected emission:** Ha-dominant; OIII varies (often faint, sometimes strong as in M16/M17 cores); SII for SHO palette
- **Catalog notes:** Tadpole globules are SHO showstoppers
- **Research:** [SIMBAD](https://simbad.cds.unistra.fr/simbad/sim-id?Ident=IC+410) • [Aladin](https://aladin.u-strasbg.fr/AladinLite/?target=IC+410&fov=2) • [NED](https://ned.ipac.caltech.edu/byname?objname=IC+410) • [Telescopius](https://telescopius.com/deep-sky-targets?searched=Tadpoles+Nebula) • [Astrobin](https://www.astrobin.com/search/?q=Tadpoles+Nebula) • [Wikipedia](https://en.wikipedia.org/wiki/Tadpoles_Nebula)

### M1 — Crab Nebula

**Supernova remnant** in **Tau** • 6' × 4' • single frame

- **Coords (J2000):** RA `05h 34m 31.9s` (83.6330°) / Dec `+22° 00' 50.4"` (+22.0140°)
- **Recommended budget:** Ha 480m • OIII 720m • SII 600m (total 30.0h)
- **Expected emission:** OIII strong in shocked filaments; Ha & SII trace remnant outer shells
- **Catalog notes:** OIII dominant in filaments; SII traces remnant outer shell
- **Research:** [SIMBAD](https://simbad.cds.unistra.fr/simbad/sim-id?Ident=M1) • [Aladin](https://aladin.u-strasbg.fr/AladinLite/?target=M1&fov=2) • [NED](https://ned.ipac.caltech.edu/byname?objname=M1) • [Telescopius](https://telescopius.com/deep-sky-targets?searched=Crab+Nebula) • [Astrobin](https://www.astrobin.com/search/?q=Crab+Nebula) • [Wikipedia](https://en.wikipedia.org/wiki/Crab_Nebula)

### M42 — Orion Nebula

**Emission nebula (HII region)** in **Ori** • 65' × 60' • single frame

- **Coords (J2000):** RA `05h 35m 17.3s` (83.8220°) / Dec `-05° 23' 27.6"` (-5.3910°)
- **Recommended budget:** Ha 240m • OIII 360m • SII 240m • L 60m • R 60m • G 60m • B 60m (total 18.0h)
- **Expected emission:** Ha-dominant; OIII varies (often faint, sometimes strong as in M16/M17 cores); SII for SHO palette
- **Catalog notes:** Trapezium HDR — bracket short subs (10-30s) into the core or it saturates
- **Research:** [SIMBAD](https://simbad.cds.unistra.fr/simbad/sim-id?Ident=M42) • [Aladin](https://aladin.u-strasbg.fr/AladinLite/?target=M42&fov=2) • [NED](https://ned.ipac.caltech.edu/byname?objname=M42) • [Telescopius](https://telescopius.com/deep-sky-targets?searched=Orion+Nebula) • [Astrobin](https://www.astrobin.com/search/?q=Orion+Nebula) • [Wikipedia](https://en.wikipedia.org/wiki/Orion_Nebula)

### NGC 1977 — Running Man Nebula

**Reflection nebula / galaxy** in **Ori** • 40' × 25' • single frame

- **Coords (J2000):** RA `05h 35m 27.8s` (83.8660°) / Dec `-04° 42' 00.0"` (-4.7000°)
- **Recommended budget:** L 240m • R 180m • G 180m • B 180m (total 13.0h)
- **Expected emission:** No narrowband emission — pure reflection; broadband L+RGB. Ha sometimes useful for embedded HII
- **Catalog notes:** Reflection nebula — narrowband not useful; RGB or L+RGB
- **Research:** [SIMBAD](https://simbad.cds.unistra.fr/simbad/sim-id?Ident=NGC+1977) • [Aladin](https://aladin.u-strasbg.fr/AladinLite/?target=NGC+1977&fov=2) • [NED](https://ned.ipac.caltech.edu/byname?objname=NGC+1977) • [Telescopius](https://telescopius.com/deep-sky-targets?searched=Running+Man+Nebula) • [Astrobin](https://www.astrobin.com/search/?q=Running+Man+Nebula) • [Wikipedia](https://en.wikipedia.org/wiki/Running_Man_Nebula)

### Sh2-240 — Spaghetti Nebula SNR

**Supernova remnant** in **Tau** • 180' × 180' • **mosaic candidate**

- **Coords (J2000):** RA `05h 36m 40.1s` (84.1670°) / Dec `+28° 00' 00.0"` (+28.0000°)
- **Recommended budget:** Ha 900m • OIII 1200m • SII 720m (total 47.0h)
- **Expected emission:** OIII strong in shocked filaments; Ha & SII trace remnant outer shells
- **Catalog notes:** Huge faint SNR; 4-panel mosaic + dark skies
- **Research:** [SIMBAD](https://simbad.cds.unistra.fr/simbad/sim-id?Ident=Sh2-240) • [Aladin](https://aladin.u-strasbg.fr/AladinLite/?target=Sh2-240&fov=2) • [NED](https://ned.ipac.caltech.edu/byname?objname=Sh2-240) • [Telescopius](https://telescopius.com/deep-sky-targets?searched=Spaghetti+Nebula+SNR) • [Astrobin](https://www.astrobin.com/search/?q=Spaghetti+Nebula+SNR) • [Wikipedia](https://en.wikipedia.org/wiki/Spaghetti_Nebula_SNR)

### IC 434 — Horsehead Nebula

**Emission nebula (HII region)** in **Ori** • 60' × 10' • single frame

- **Coords (J2000):** RA `05h 41m 00.0s` (85.2500°) / Dec `-02° 27' 00.0"` (-2.4500°)
- **Recommended budget:** Ha 720m • OIII 480m • SII 480m • L 120m • R 120m • G 120m • B 120m (total 36.0h)
- **Expected emission:** Ha-dominant; OIII varies (often faint, sometimes strong as in M16/M17 cores); SII for SHO palette
- **Catalog notes:** Pair with Flame (NGC 2024) in same frame; classic Ha target
- **Research:** [SIMBAD](https://simbad.cds.unistra.fr/simbad/sim-id?Ident=IC+434) • [Aladin](https://aladin.u-strasbg.fr/AladinLite/?target=IC+434&fov=2) • [NED](https://ned.ipac.caltech.edu/byname?objname=IC+434) • [Telescopius](https://telescopius.com/deep-sky-targets?searched=Horsehead+Nebula) • [Astrobin](https://www.astrobin.com/search/?q=Horsehead+Nebula) • [Wikipedia](https://en.wikipedia.org/wiki/Horsehead_Nebula)

### NGC 2174 — Monkey Head Nebula

**Emission nebula (HII region)** in **Ori** • 40' × 30' • single frame

- **Coords (J2000):** RA `06h 06m 30.0s` (91.6250°) / Dec `+20° 30' 00.0"` (+20.5000°)
- **Recommended budget:** Ha 540m • OIII 600m • SII 540m (total 28.0h)
- **Expected emission:** Ha-dominant; OIII varies (often faint, sometimes strong as in M16/M17 cores); SII for SHO palette
- **Catalog notes:** Good SHO target; strong Ha, moderate OIII
- **Research:** [SIMBAD](https://simbad.cds.unistra.fr/simbad/sim-id?Ident=NGC+2174) • [Aladin](https://aladin.u-strasbg.fr/AladinLite/?target=NGC+2174&fov=2) • [NED](https://ned.ipac.caltech.edu/byname?objname=NGC+2174) • [Telescopius](https://telescopius.com/deep-sky-targets?searched=Monkey+Head+Nebula) • [Astrobin](https://www.astrobin.com/search/?q=Monkey+Head+Nebula) • [Wikipedia](https://en.wikipedia.org/wiki/Monkey_Head_Nebula)

### NGC 2237 — Rosette Nebula

**Emission nebula (HII region)** in **Mon** • 80' × 80' • single frame

- **Coords (J2000):** RA `06h 31m 52.1s` (97.9670°) / Dec `+04° 57' 00.0"` (+4.9500°)
- **Recommended budget:** Ha 600m • OIII 720m • SII 600m (total 32.0h)
- **Expected emission:** Ha-dominant; OIII varies (often faint, sometimes strong as in M16/M17 cores); SII for SHO palette
- **Catalog notes:** Fits FOV diagonally; OIII reveals oxygen shell structure
- **Research:** [SIMBAD](https://simbad.cds.unistra.fr/simbad/sim-id?Ident=NGC+2237) • [Aladin](https://aladin.u-strasbg.fr/AladinLite/?target=NGC+2237&fov=2) • [NED](https://ned.ipac.caltech.edu/byname?objname=NGC+2237) • [Telescopius](https://telescopius.com/deep-sky-targets?searched=Rosette+Nebula) • [Astrobin](https://www.astrobin.com/search/?q=Rosette+Nebula) • [Wikipedia](https://en.wikipedia.org/wiki/Rosette_Nebula)

### NGC 2264 — Christmas Tree / Cone Nebula

**Emission nebula (HII region)** in **Mon** • 60' × 30' • single frame

- **Coords (J2000):** RA `06h 41m 00.0s` (100.2500°) / Dec `+09° 52' 58.8"` (+9.8830°)
- **Recommended budget:** Ha 540m • OIII 600m • SII 480m (total 27.0h)
- **Expected emission:** Ha-dominant; OIII varies (often faint, sometimes strong as in M16/M17 cores); SII for SHO palette
- **Catalog notes:** Cone region has interesting SII; combined with cluster
- **Research:** [SIMBAD](https://simbad.cds.unistra.fr/simbad/sim-id?Ident=NGC+2264) • [Aladin](https://aladin.u-strasbg.fr/AladinLite/?target=NGC+2264&fov=2) • [NED](https://ned.ipac.caltech.edu/byname?objname=NGC+2264) • [Telescopius](https://telescopius.com/deep-sky-targets?searched=Christmas+Tree+%2F+Cone+Nebula) • [Astrobin](https://www.astrobin.com/search/?q=Christmas+Tree+%2F+Cone+Nebula) • [Wikipedia](https://en.wikipedia.org/wiki/Christmas_Tree_%2F_Cone_Nebula)

### Abell 21 — Medusa Nebula

**Planetary nebula** in **Gem** • 10' × 10' • single frame

- **Coords (J2000):** RA `07h 31m 60.0s` (113.0000°) / Dec `+13° 15' 00.0"` (+13.2500°)
- **Recommended budget:** Ha 540m • OIII 900m • SII 360m (total 30.0h)
- **Expected emission:** OIII typically dominant; Ha bright in core, often a faint outer halo worth long subs
- **Catalog notes:** OIII-dominant ancient planetary; long subs needed
- **Research:** [SIMBAD](https://simbad.cds.unistra.fr/simbad/sim-id?Ident=Abell+21) • [Aladin](https://aladin.u-strasbg.fr/AladinLite/?target=Abell+21&fov=2) • [NED](https://ned.ipac.caltech.edu/byname?objname=Abell+21) • [Telescopius](https://telescopius.com/deep-sky-targets?searched=Medusa+Nebula) • [Astrobin](https://www.astrobin.com/search/?q=Medusa+Nebula) • [Wikipedia](https://en.wikipedia.org/wiki/Medusa_Nebula)

### Abell 31 — Abell 31 PN

**Planetary nebula** in **Cnc** • 16' × 16' • single frame

- **Coords (J2000):** RA `08h 41m 22.1s` (130.3420°) / Dec `+08° 43' 58.8"` (+8.7330°)
- **Recommended budget:** Ha 480m • OIII 1200m • SII 360m (total 34.0h)
- **Expected emission:** OIII typically dominant; Ha bright in core, often a faint outer halo worth long subs
- **Catalog notes:** Very faint OIII halo; needs dark skies + long integration
- **Research:** [SIMBAD](https://simbad.cds.unistra.fr/simbad/sim-id?Ident=Abell+31) • [Aladin](https://aladin.u-strasbg.fr/AladinLite/?target=Abell+31&fov=2) • [NED](https://ned.ipac.caltech.edu/byname?objname=Abell+31) • [Telescopius](https://telescopius.com/deep-sky-targets?searched=Abell+31+PN) • [Astrobin](https://www.astrobin.com/search/?q=Abell+31+PN) • [Wikipedia](https://en.wikipedia.org/wiki/Abell_31_PN)

## Spring (Mar–May)

_1 target(s). RA range listed first; suggested observing months in parentheses._

### M97 — Owl Nebula

**Planetary nebula** in **UMa** • 3' × 3' • single frame

- **Coords (J2000):** RA `11h 14m 48.0s` (168.7000°) / Dec `+55° 01' 01.2"` (+55.0170°)
- **Recommended budget:** Ha 360m • OIII 720m • SII 240m (total 22.0h)
- **Expected emission:** OIII typically dominant; Ha bright in core, often a faint outer halo worth long subs
- **Catalog notes:** Small but bright OIII; useful narrowband target in galaxy season
- **Research:** [SIMBAD](https://simbad.cds.unistra.fr/simbad/sim-id?Ident=M97) • [Aladin](https://aladin.u-strasbg.fr/AladinLite/?target=M97&fov=2) • [NED](https://ned.ipac.caltech.edu/byname?objname=M97) • [Telescopius](https://telescopius.com/deep-sky-targets?searched=Owl+Nebula) • [Astrobin](https://www.astrobin.com/search/?q=Owl+Nebula) • [Wikipedia](https://en.wikipedia.org/wiki/Owl_Nebula)

## Summer (Jun–Aug)

_16 target(s). RA range listed first; suggested observing months in parentheses._

### M20 — Trifid Nebula

**Emission nebula (HII region)** in **Sgr** • 28' × 28' • single frame

- **Coords (J2000):** RA `18h 02m 31.9s` (270.6330°) / Dec `-23° 01' 58.8"` (-23.0330°)
- **Recommended budget:** Ha 540m • OIII 600m • SII 480m • L 60m • R 60m • G 60m • B 60m (total 31.0h)
- **Expected emission:** Ha-dominant; OIII varies (often faint, sometimes strong as in M16/M17 cores); SII for SHO palette
- **Catalog notes:** Mixed emission+reflection; benefits from both NB and RGB
- **Research:** [SIMBAD](https://simbad.cds.unistra.fr/simbad/sim-id?Ident=M20) • [Aladin](https://aladin.u-strasbg.fr/AladinLite/?target=M20&fov=2) • [NED](https://ned.ipac.caltech.edu/byname?objname=M20) • [Telescopius](https://telescopius.com/deep-sky-targets?searched=Trifid+Nebula) • [Astrobin](https://www.astrobin.com/search/?q=Trifid+Nebula) • [Wikipedia](https://en.wikipedia.org/wiki/Trifid_Nebula)

### M8 — Lagoon Nebula

**Emission nebula (HII region)** in **Sgr** • 90' × 40' • single frame

- **Coords (J2000):** RA `18h 03m 40.1s` (270.9170°) / Dec `-24° 22' 58.8"` (-24.3830°)
- **Recommended budget:** Ha 480m • OIII 540m • SII 480m (total 25.0h)
- **Expected emission:** Ha-dominant; OIII varies (often faint, sometimes strong as in M16/M17 cores); SII for SHO palette
- **Catalog notes:** Low altitude from JC (~25° max) — atmospheric extinction matters; pair with M20
- **Research:** [SIMBAD](https://simbad.cds.unistra.fr/simbad/sim-id?Ident=M8) • [Aladin](https://aladin.u-strasbg.fr/AladinLite/?target=M8&fov=2) • [NED](https://ned.ipac.caltech.edu/byname?objname=M8) • [Telescopius](https://telescopius.com/deep-sky-targets?searched=Lagoon+Nebula) • [Astrobin](https://www.astrobin.com/search/?q=Lagoon+Nebula) • [Wikipedia](https://en.wikipedia.org/wiki/Lagoon_Nebula)

### M16 — Eagle Nebula / Pillars of Creation

**Emission nebula (HII region)** in **Ser** • 30' × 20' • single frame

- **Coords (J2000):** RA `18h 18m 48.0s` (274.7000°) / Dec `-13° 48' 00.0"` (-13.8000°)
- **Recommended budget:** Ha 540m • OIII 600m • SII 540m (total 28.0h)
- **Expected emission:** Ha-dominant; OIII varies (often faint, sometimes strong as in M16/M17 cores); SII for SHO palette
- **Catalog notes:** Pillars are tiny but iconic; longer focal lengths benefit
- **Research:** [SIMBAD](https://simbad.cds.unistra.fr/simbad/sim-id?Ident=M16) • [Aladin](https://aladin.u-strasbg.fr/AladinLite/?target=M16&fov=2) • [NED](https://ned.ipac.caltech.edu/byname?objname=M16) • [Telescopius](https://telescopius.com/deep-sky-targets?searched=Eagle+Nebula+%2F+Pillars+of+Creation) • [Astrobin](https://www.astrobin.com/search/?q=Eagle+Nebula+%2F+Pillars+of+Creation) • [Wikipedia](https://en.wikipedia.org/wiki/Eagle_Nebula_%2F_Pillars_of_Creation)

### M17 — Omega / Swan Nebula

**Emission nebula (HII region)** in **Sgr** • 11' × 11' • single frame

- **Coords (J2000):** RA `18h 20m 48.0s` (275.2000°) / Dec `-16° 11' 60.0"` (-16.2000°)
- **Recommended budget:** Ha 420m • OIII 540m • SII 480m (total 24.0h)
- **Expected emission:** Ha-dominant; OIII varies (often faint, sometimes strong as in M16/M17 cores); SII for SHO palette
- **Catalog notes:** Bright Ha core; SHO produces strong palette
- **Research:** [SIMBAD](https://simbad.cds.unistra.fr/simbad/sim-id?Ident=M17) • [Aladin](https://aladin.u-strasbg.fr/AladinLite/?target=M17&fov=2) • [NED](https://ned.ipac.caltech.edu/byname?objname=M17) • [Telescopius](https://telescopius.com/deep-sky-targets?searched=Omega+%2F+Swan+Nebula) • [Astrobin](https://www.astrobin.com/search/?q=Omega+%2F+Swan+Nebula) • [Wikipedia](https://en.wikipedia.org/wiki/Omega_%2F_Swan_Nebula)

### M57 — Ring Nebula

**Planetary nebula** in **Lyr** • 1' × 1' • single frame

- **Coords (J2000):** RA `18h 53m 35.0s` (283.3960°) / Dec `+33° 01' 44.4"` (+33.0290°)
- **Recommended budget:** Ha 240m • OIII 540m • SII 180m (total 16.0h)
- **Expected emission:** OIII typically dominant; Ha bright in core, often a faint outer halo worth long subs
- **Catalog notes:** Tiny — undersampled at 840mm; do for the outer Ha halo
- **Research:** [SIMBAD](https://simbad.cds.unistra.fr/simbad/sim-id?Ident=M57) • [Aladin](https://aladin.u-strasbg.fr/AladinLite/?target=M57&fov=2) • [NED](https://ned.ipac.caltech.edu/byname?objname=M57) • [Telescopius](https://telescopius.com/deep-sky-targets?searched=Ring+Nebula) • [Astrobin](https://www.astrobin.com/search/?q=Ring+Nebula) • [Wikipedia](https://en.wikipedia.org/wiki/Ring_Nebula)

### M27 — Dumbbell Nebula

**Planetary nebula** in **Vul** • 8' × 6' • single frame

- **Coords (J2000):** RA `19h 59m 36.2s` (299.9010°) / Dec `+22° 43' 15.6"` (+22.7210°)
- **Recommended budget:** Ha 360m • OIII 540m • SII 240m (total 19.0h)
- **Expected emission:** OIII typically dominant; Ha bright in core, often a faint outer halo worth long subs
- **Catalog notes:** Showcase OIII PN; faint outer halo rewards long Ha
- **Research:** [SIMBAD](https://simbad.cds.unistra.fr/simbad/sim-id?Ident=M27) • [Aladin](https://aladin.u-strasbg.fr/AladinLite/?target=M27&fov=2) • [NED](https://ned.ipac.caltech.edu/byname?objname=M27) • [Telescopius](https://telescopius.com/deep-sky-targets?searched=Dumbbell+Nebula) • [Astrobin](https://www.astrobin.com/search/?q=Dumbbell+Nebula) • [Wikipedia](https://en.wikipedia.org/wiki/Dumbbell_Nebula)

### Sh2-101 — Tulip Nebula

**Emission nebula (HII region)** in **Cyg** • 17' × 12' • single frame

- **Coords (J2000):** RA `20h 00m 00.0s` (300.0000°) / Dec `+35° 17' 60.0"` (+35.3000°)
- **Recommended budget:** Ha 600m • OIII 720m • SII 540m (total 31.0h)
- **Expected emission:** Ha-dominant; OIII varies (often faint, sometimes strong as in M16/M17 cores); SII for SHO palette
- **Catalog notes:** Near Cygnus X-1; OIII reveals shock front
- **Research:** [SIMBAD](https://simbad.cds.unistra.fr/simbad/sim-id?Ident=Sh2-101) • [Aladin](https://aladin.u-strasbg.fr/AladinLite/?target=Sh2-101&fov=2) • [NED](https://ned.ipac.caltech.edu/byname?objname=Sh2-101) • [Telescopius](https://telescopius.com/deep-sky-targets?searched=Tulip+Nebula) • [Astrobin](https://www.astrobin.com/search/?q=Tulip+Nebula) • [Wikipedia](https://en.wikipedia.org/wiki/Tulip_Nebula)

### NGC 6888 — Crescent Nebula

**Wolf-Rayet bubble** in **Cyg** • 18' × 13' • single frame

- **Coords (J2000):** RA `20h 12m 06.0s` (303.0250°) / Dec `+38° 21' 00.0"` (+38.3500°)
- **Recommended budget:** Ha 600m • OIII 900m • SII 540m (total 34.0h)
- **Expected emission:** OIII shell is the headline; Ha shows surrounding ISM; SII weaker
- **Catalog notes:** Wolf-Rayet bubble — OIII shell is the headline; needs long subs
- **Research:** [SIMBAD](https://simbad.cds.unistra.fr/simbad/sim-id?Ident=NGC+6888) • [Aladin](https://aladin.u-strasbg.fr/AladinLite/?target=NGC+6888&fov=2) • [NED](https://ned.ipac.caltech.edu/byname?objname=NGC+6888) • [Telescopius](https://telescopius.com/deep-sky-targets?searched=Crescent+Nebula) • [Astrobin](https://www.astrobin.com/search/?q=Crescent+Nebula) • [Wikipedia](https://en.wikipedia.org/wiki/Crescent_Nebula)

### IC 1318 — Butterfly / Sadr Region

**Emission nebula (HII region)** in **Cyg** • 240' × 180' • **mosaic candidate**

- **Coords (J2000):** RA `20h 22m 00.0s` (305.5000°) / Dec `+40° 15' 00.0"` (+40.2500°)
- **Recommended budget:** Ha 540m • OIII 600m • SII 480m (total 27.0h)
- **Expected emission:** Ha-dominant; OIII varies (often faint, sometimes strong as in M16/M17 cores); SII for SHO palette
- **Catalog notes:** Huge complex around Sadr; pick a panel or do 4-panel mosaic
- **Research:** [SIMBAD](https://simbad.cds.unistra.fr/simbad/sim-id?Ident=IC+1318) • [Aladin](https://aladin.u-strasbg.fr/AladinLite/?target=IC+1318&fov=2) • [NED](https://ned.ipac.caltech.edu/byname?objname=IC+1318) • [Telescopius](https://telescopius.com/deep-sky-targets?searched=Butterfly+%2F+Sadr+Region) • [Astrobin](https://www.astrobin.com/search/?q=Butterfly+%2F+Sadr+Region) • [Wikipedia](https://en.wikipedia.org/wiki/Butterfly_%2F_Sadr_Region)

### NGC 6960 — Western Veil / Witch's Broom

**Supernova remnant** in **Cyg** • 70' × 6' • single frame

- **Coords (J2000):** RA `20h 50m 59.8s` (312.7490°) / Dec `+30° 43' 01.2"` (+30.7170°)
- **Recommended budget:** Ha 480m • OIII 720m • SII 480m (total 28.0h)
- **Expected emission:** OIII strong in shocked filaments; Ha & SII trace remnant outer shells
- **Catalog notes:** Western strand of Cygnus Loop; OIII spectacular
- **Research:** [SIMBAD](https://simbad.cds.unistra.fr/simbad/sim-id?Ident=NGC+6960) • [Aladin](https://aladin.u-strasbg.fr/AladinLite/?target=NGC+6960&fov=2) • [NED](https://ned.ipac.caltech.edu/byname?objname=NGC+6960) • [Telescopius](https://telescopius.com/deep-sky-targets?searched=Western+Veil+%2F+Witch%27s+Broom) • [Astrobin](https://www.astrobin.com/search/?q=Western+Veil+%2F+Witch%27s+Broom) • [Wikipedia](https://en.wikipedia.org/wiki/Western_Veil_%2F_Witch%27s_Broom)

### NGC 6992 — Eastern Veil

**Supernova remnant** in **Cyg** • 60' × 8' • single frame

- **Coords (J2000):** RA `20h 52m 09.8s` (313.0410°) / Dec `+31° 43' 01.2"` (+31.7170°)
- **Recommended budget:** Ha 480m • OIII 720m • SII 480m (total 28.0h)
- **Expected emission:** OIII strong in shocked filaments; Ha & SII trace remnant outer shells
- **Catalog notes:** Eastern strand; complementary to 6960
- **Research:** [SIMBAD](https://simbad.cds.unistra.fr/simbad/sim-id?Ident=NGC+6992) • [Aladin](https://aladin.u-strasbg.fr/AladinLite/?target=NGC+6992&fov=2) • [NED](https://ned.ipac.caltech.edu/byname?objname=NGC+6992) • [Telescopius](https://telescopius.com/deep-sky-targets?searched=Eastern+Veil) • [Astrobin](https://www.astrobin.com/search/?q=Eastern+Veil) • [Wikipedia](https://en.wikipedia.org/wiki/Eastern_Veil)

### IC 5070 — Pelican Nebula

**Emission nebula (HII region)** in **Cyg** • 60' × 50' • single frame

- **Coords (J2000):** RA `20h 54m 40.1s` (313.6670°) / Dec `+44° 22' 01.2"` (+44.3670°)
- **Recommended budget:** Ha 540m • OIII 600m • SII 540m (total 28.0h)
- **Expected emission:** Ha-dominant; OIII varies (often faint, sometimes strong as in M16/M17 cores); SII for SHO palette
- **Catalog notes:** Across the dust lane from NGC 7000; fits single frame
- **Research:** [SIMBAD](https://simbad.cds.unistra.fr/simbad/sim-id?Ident=IC+5070) • [Aladin](https://aladin.u-strasbg.fr/AladinLite/?target=IC+5070&fov=2) • [NED](https://ned.ipac.caltech.edu/byname?objname=IC+5070) • [Telescopius](https://telescopius.com/deep-sky-targets?searched=Pelican+Nebula) • [Astrobin](https://www.astrobin.com/search/?q=Pelican+Nebula) • [Wikipedia](https://en.wikipedia.org/wiki/Pelican_Nebula)

### NGC 7000 — North America Nebula

**Emission nebula (HII region)** in **Cyg** • 120' × 100' • **mosaic candidate**

- **Coords (J2000):** RA `20h 58m 56.9s` (314.7370°) / Dec `+44° 20' 13.2"` (+44.3370°)
- **Recommended budget:** Ha 600m • OIII 600m • SII 540m (total 29.0h)
- **Expected emission:** Ha-dominant; OIII varies (often faint, sometimes strong as in M16/M17 cores); SII for SHO palette
- **Catalog notes:** Two-panel mosaic for full nebula; Cygnus Wall alone (~30') fits single frame
- **Research:** [SIMBAD](https://simbad.cds.unistra.fr/simbad/sim-id?Ident=NGC+7000) • [Aladin](https://aladin.u-strasbg.fr/AladinLite/?target=NGC+7000&fov=2) • [NED](https://ned.ipac.caltech.edu/byname?objname=NGC+7000) • [Telescopius](https://telescopius.com/deep-sky-targets?searched=North+America+Nebula) • [Astrobin](https://www.astrobin.com/search/?q=North+America+Nebula) • [Wikipedia](https://en.wikipedia.org/wiki/North_America_Nebula)

### NGC 7023 — Iris Nebula

**Reflection nebula / galaxy** in **Cep** • 18' × 18' • single frame

- **Coords (J2000):** RA `21h 01m 31.0s` (315.3790°) / Dec `+68° 09' 28.8"` (+68.1580°)
- **Recommended budget:** L 360m • R 240m • G 240m • B 240m (total 18.0h)
- **Expected emission:** No narrowband emission — pure reflection; broadband L+RGB. Ha sometimes useful for embedded HII
- **Catalog notes:** Pure reflection — broadband only; embedded in dark dust
- **Research:** [SIMBAD](https://simbad.cds.unistra.fr/simbad/sim-id?Ident=NGC+7023) • [Aladin](https://aladin.u-strasbg.fr/AladinLite/?target=NGC+7023&fov=2) • [NED](https://ned.ipac.caltech.edu/byname?objname=NGC+7023) • [Telescopius](https://telescopius.com/deep-sky-targets?searched=Iris+Nebula) • [Astrobin](https://www.astrobin.com/search/?q=Iris+Nebula) • [Wikipedia](https://en.wikipedia.org/wiki/Iris_Nebula)

### IC 1396 — Elephant's Trunk Nebula

**Emission nebula (HII region)** in **Cep** • 170' × 140' • **mosaic candidate**

- **Coords (J2000):** RA `21h 37m 60.0s` (324.5000°) / Dec `+57° 30' 00.0"` (+57.5000°)
- **Recommended budget:** Ha 600m • OIII 600m • SII 540m (total 29.0h)
- **Expected emission:** Ha-dominant; OIII varies (often faint, sometimes strong as in M16/M17 cores); SII for SHO palette
- **Catalog notes:** Mosaic for full nebula; Trunk itself (~20') fits single frame
- **Research:** [SIMBAD](https://simbad.cds.unistra.fr/simbad/sim-id?Ident=IC+1396) • [Aladin](https://aladin.u-strasbg.fr/AladinLite/?target=IC+1396&fov=2) • [NED](https://ned.ipac.caltech.edu/byname?objname=IC+1396) • [Telescopius](https://telescopius.com/deep-sky-targets?searched=Elephant%27s+Trunk+Nebula) • [Astrobin](https://www.astrobin.com/search/?q=Elephant%27s+Trunk+Nebula) • [Wikipedia](https://en.wikipedia.org/wiki/Elephant%27s_Trunk_Nebula)

### Abell 78 — Abell 78

**Wolf-Rayet bubble** in **Cyg** • 2' × 2' • single frame

- **Coords (J2000):** RA `21h 45m 60.0s` (326.5000°) / Dec `+31° 30' 00.0"` (+31.5000°)
- **Recommended budget:** Ha 720m • OIII 1200m • SII 360m (total 38.0h)
- **Expected emission:** OIII shell is the headline; Ha shows surrounding ISM; SII weaker
- **Catalog notes:** Very faint WR planetary nebula; OIII shell prominent with long subs
- **Research:** [SIMBAD](https://simbad.cds.unistra.fr/simbad/sim-id?Ident=Abell+78) • [Aladin](https://aladin.u-strasbg.fr/AladinLite/?target=Abell+78&fov=2) • [NED](https://ned.ipac.caltech.edu/byname?objname=Abell+78) • [Telescopius](https://telescopius.com/deep-sky-targets?searched=Abell+78) • [Astrobin](https://www.astrobin.com/search/?q=Abell+78)

## Autumn (Sep–Nov)

_14 target(s). RA range listed first; suggested observing months in parentheses._

### NGC 7822 — Cederblad 214 region

**Emission nebula (HII region)** in **Cep** • 60' × 30' • single frame

- **Coords (J2000):** RA `00h 00m 19.9s` (0.0830°) / Dec `+68° 34' 01.2"` (+68.5670°)
- **Recommended budget:** Ha 540m • OIII 600m • SII 540m (total 28.0h)
- **Expected emission:** Ha-dominant; OIII varies (often faint, sometimes strong as in M16/M17 cores); SII for SHO palette
- **Catalog notes:** Includes Ced 214 + Sh2-171; high in autumn skies from JC
- **Research:** [SIMBAD](https://simbad.cds.unistra.fr/simbad/sim-id?Ident=NGC+7822) • [Aladin](https://aladin.u-strasbg.fr/AladinLite/?target=NGC+7822&fov=2) • [NED](https://ned.ipac.caltech.edu/byname?objname=NGC+7822) • [Telescopius](https://telescopius.com/deep-sky-targets?searched=Cederblad+214+region) • [Astrobin](https://www.astrobin.com/search/?q=Cederblad+214+region) • [Wikipedia](https://en.wikipedia.org/wiki/Cederblad_214_region)

### M31 — Andromeda Galaxy

**Reflection nebula / galaxy** in **And** • 190' × 60' • **mosaic candidate**

- **Coords (J2000):** RA `00h 42m 44.4s` (10.6850°) / Dec `+41° 16' 08.4"` (+41.2690°)
- **Recommended budget:** L 240m • R 180m • G 180m • B 180m • Ha 360m (total 19.0h)
- **Expected emission:** No narrowband emission — pure reflection; broadband L+RGB. Ha sometimes useful for embedded HII
- **Catalog notes:** Mosaic for full disk. Ha exposes HII regions in spiral arms — bonus channel
- **Research:** [SIMBAD](https://simbad.cds.unistra.fr/simbad/sim-id?Ident=M31) • [Aladin](https://aladin.u-strasbg.fr/AladinLite/?target=M31&fov=2) • [NED](https://ned.ipac.caltech.edu/byname?objname=M31) • [Telescopius](https://telescopius.com/deep-sky-targets?searched=Andromeda+Galaxy) • [Astrobin](https://www.astrobin.com/search/?q=Andromeda+Galaxy) • [Wikipedia](https://en.wikipedia.org/wiki/Andromeda_Galaxy)

### NGC 281 — Pacman Nebula

**Emission nebula (HII region)** in **Cas** • 35' × 30' • single frame

- **Coords (J2000):** RA `00h 53m 00.0s` (13.2500°) / Dec `+56° 37' 01.2"` (+56.6170°)
- **Recommended budget:** Ha 540m • OIII 600m • SII 480m (total 27.0h)
- **Expected emission:** Ha-dominant; OIII varies (often faint, sometimes strong as in M16/M17 cores); SII for SHO palette
- **Catalog notes:** Bok globules visible in Ha; classic SHO target
- **Research:** [SIMBAD](https://simbad.cds.unistra.fr/simbad/sim-id?Ident=NGC+281) • [Aladin](https://aladin.u-strasbg.fr/AladinLite/?target=NGC+281&fov=2) • [NED](https://ned.ipac.caltech.edu/byname?objname=NGC+281) • [Telescopius](https://telescopius.com/deep-sky-targets?searched=Pacman+Nebula) • [Astrobin](https://www.astrobin.com/search/?q=Pacman+Nebula) • [Wikipedia](https://en.wikipedia.org/wiki/Pacman_Nebula)

### Sh2-188 — Dust Cap PN

**Planetary nebula** in **Cas** • 10' × 8' • single frame

- **Coords (J2000):** RA `01h 16m 43.9s` (19.1830°) / Dec `+58° 17' 60.0"` (+58.3000°)
- **Recommended budget:** Ha 480m • OIII 900m • SII 360m (total 29.0h)
- **Expected emission:** OIII typically dominant; Ha bright in core, often a faint outer halo worth long subs
- **Catalog notes:** Asymmetric PN with bright arc; OIII required
- **Research:** [SIMBAD](https://simbad.cds.unistra.fr/simbad/sim-id?Ident=Sh2-188) • [Aladin](https://aladin.u-strasbg.fr/AladinLite/?target=Sh2-188&fov=2) • [NED](https://ned.ipac.caltech.edu/byname?objname=Sh2-188) • [Telescopius](https://telescopius.com/deep-sky-targets?searched=Dust+Cap+PN) • [Astrobin](https://www.astrobin.com/search/?q=Dust+Cap+PN) • [Wikipedia](https://en.wikipedia.org/wiki/Dust_Cap_PN)

### M33 — Triangulum Galaxy

**Reflection nebula / galaxy** in **Tri** • 73' × 45' • single frame

- **Coords (J2000):** RA `01h 33m 50.9s` (23.4620°) / Dec `+30° 39' 36.0"` (+30.6600°)
- **Recommended budget:** L 360m • R 240m • G 240m • B 240m • Ha 480m (total 26.0h)
- **Expected emission:** No narrowband emission — pure reflection; broadband L+RGB. Ha sometimes useful for embedded HII
- **Catalog notes:** Fits at 1.6°. Ha integration reveals NGC 604 and other HII regions
- **Research:** [SIMBAD](https://simbad.cds.unistra.fr/simbad/sim-id?Ident=M33) • [Aladin](https://aladin.u-strasbg.fr/AladinLite/?target=M33&fov=2) • [NED](https://ned.ipac.caltech.edu/byname?objname=M33) • [Telescopius](https://telescopius.com/deep-sky-targets?searched=Triangulum+Galaxy) • [Astrobin](https://www.astrobin.com/search/?q=Triangulum+Galaxy) • [Wikipedia](https://en.wikipedia.org/wiki/Triangulum_Galaxy)

### M76 — Little Dumbbell

**Planetary nebula** in **Per** • 3' × 2' • single frame

- **Coords (J2000):** RA `01h 42m 19.9s` (25.5830°) / Dec `+51° 34' 30.0"` (+51.5750°)
- **Recommended budget:** Ha 360m • OIII 540m • SII 240m (total 19.0h)
- **Expected emission:** OIII typically dominant; Ha bright in core, often a faint outer halo worth long subs
- **Catalog notes:** Small bipolar PN; OIII bright
- **Research:** [SIMBAD](https://simbad.cds.unistra.fr/simbad/sim-id?Ident=M76) • [Aladin](https://aladin.u-strasbg.fr/AladinLite/?target=M76&fov=2) • [NED](https://ned.ipac.caltech.edu/byname?objname=M76) • [Telescopius](https://telescopius.com/deep-sky-targets?searched=Little+Dumbbell) • [Astrobin](https://www.astrobin.com/search/?q=Little+Dumbbell) • [Wikipedia](https://en.wikipedia.org/wiki/Little_Dumbbell)

### IC 1805 — Heart Nebula

**Emission nebula (HII region)** in **Cas** • 150' × 150' • **mosaic candidate**

- **Coords (J2000):** RA `02h 34m 19.9s` (38.5830°) / Dec `+61° 28' 01.2"` (+61.4670°)
- **Recommended budget:** Ha 600m • OIII 600m • SII 540m (total 29.0h)
- **Expected emission:** Ha-dominant; OIII varies (often faint, sometimes strong as in M16/M17 cores); SII for SHO palette
- **Catalog notes:** Two-panel mosaic; often paired with IC 1848 (Soul) in widefield
- **Research:** [SIMBAD](https://simbad.cds.unistra.fr/simbad/sim-id?Ident=IC+1805) • [Aladin](https://aladin.u-strasbg.fr/AladinLite/?target=IC+1805&fov=2) • [NED](https://ned.ipac.caltech.edu/byname?objname=IC+1805) • [Telescopius](https://telescopius.com/deep-sky-targets?searched=Heart+Nebula) • [Astrobin](https://www.astrobin.com/search/?q=Heart+Nebula) • [Wikipedia](https://en.wikipedia.org/wiki/Heart_Nebula)

### IC 1848 — Soul Nebula

**Emission nebula (HII region)** in **Cas** • 100' × 100' • **mosaic candidate**

- **Coords (J2000):** RA `02h 50m 00.0s` (42.5000°) / Dec `+60° 25' 58.8"` (+60.4330°)
- **Recommended budget:** Ha 600m • OIII 600m • SII 540m (total 29.0h)
- **Expected emission:** Ha-dominant; OIII varies (often faint, sometimes strong as in M16/M17 cores); SII for SHO palette
- **Catalog notes:** Companion to IC 1805 Heart
- **Research:** [SIMBAD](https://simbad.cds.unistra.fr/simbad/sim-id?Ident=IC+1848) • [Aladin](https://aladin.u-strasbg.fr/AladinLite/?target=IC+1848&fov=2) • [NED](https://ned.ipac.caltech.edu/byname?objname=IC+1848) • [Telescopius](https://telescopius.com/deep-sky-targets?searched=Soul+Nebula) • [Astrobin](https://www.astrobin.com/search/?q=Soul+Nebula) • [Wikipedia](https://en.wikipedia.org/wiki/Soul_Nebula)

### NGC 7293 — Helix Nebula

**Planetary nebula** in **Aqr** • 25' × 17' • single frame

- **Coords (J2000):** RA `22h 29m 38.9s` (337.4120°) / Dec `-20° 50' 13.2"` (-20.8370°)
- **Recommended budget:** Ha 600m • OIII 720m • SII 480m (total 30.0h)
- **Expected emission:** OIII typically dominant; Ha bright in core, often a faint outer halo worth long subs
- **Catalog notes:** Low altitude from JC (~25° max) — atmospheric extinction limits OIII
- **Research:** [SIMBAD](https://simbad.cds.unistra.fr/simbad/sim-id?Ident=NGC+7293) • [Aladin](https://aladin.u-strasbg.fr/AladinLite/?target=NGC+7293&fov=2) • [NED](https://ned.ipac.caltech.edu/byname?objname=NGC+7293) • [Telescopius](https://telescopius.com/deep-sky-targets?searched=Helix+Nebula) • [Astrobin](https://www.astrobin.com/search/?q=Helix+Nebula) • [Wikipedia](https://en.wikipedia.org/wiki/Helix_Nebula)

### NGC 7380 — Wizard Nebula

**Emission nebula (HII region)** in **Cep** • 25' × 25' • single frame

- **Coords (J2000):** RA `22h 45m 60.0s` (341.5000°) / Dec `+58° 07' 01.2"` (+58.1170°)
- **Recommended budget:** Ha 540m • OIII 600m • SII 540m (total 28.0h)
- **Expected emission:** Ha-dominant; OIII varies (often faint, sometimes strong as in M16/M17 cores); SII for SHO palette
- **Catalog notes:** Compact HII region; full SHO palette works
- **Research:** [SIMBAD](https://simbad.cds.unistra.fr/simbad/sim-id?Ident=NGC+7380) • [Aladin](https://aladin.u-strasbg.fr/AladinLite/?target=NGC+7380&fov=2) • [NED](https://ned.ipac.caltech.edu/byname?objname=NGC+7380) • [Telescopius](https://telescopius.com/deep-sky-targets?searched=Wizard+Nebula) • [Astrobin](https://www.astrobin.com/search/?q=Wizard+Nebula) • [Wikipedia](https://en.wikipedia.org/wiki/Wizard_Nebula)

### Sh2-155 — Cave Nebula

**Emission nebula (HII region)** in **Cep** • 50' × 30' • single frame

- **Coords (J2000):** RA `22h 52m 49.9s` (343.2080°) / Dec `+62° 37' 01.2"` (+62.6170°)
- **Recommended budget:** Ha 600m • OIII 600m • SII 480m (total 28.0h)
- **Expected emission:** Ha-dominant; OIII varies (often faint, sometimes strong as in M16/M17 cores); SII for SHO palette
- **Catalog notes:** Strong Ha, modest OIII; fits single frame
- **Research:** [SIMBAD](https://simbad.cds.unistra.fr/simbad/sim-id?Ident=Sh2-155) • [Aladin](https://aladin.u-strasbg.fr/AladinLite/?target=Sh2-155&fov=2) • [NED](https://ned.ipac.caltech.edu/byname?objname=Sh2-155) • [Telescopius](https://telescopius.com/deep-sky-targets?searched=Cave+Nebula) • [Astrobin](https://www.astrobin.com/search/?q=Cave+Nebula) • [Wikipedia](https://en.wikipedia.org/wiki/Cave_Nebula)

### NGC 7635 — Bubble Nebula

**Emission nebula (HII region)** in **Cas** • 15' × 8' • single frame

- **Coords (J2000):** RA `23h 20m 47.0s` (350.1960°) / Dec `+61° 11' 49.2"` (+61.1970°)
- **Recommended budget:** Ha 600m • OIII 900m • SII 540m (total 34.0h)
- **Expected emission:** Ha-dominant; OIII varies (often faint, sometimes strong as in M16/M17 cores); SII for SHO palette
- **Catalog notes:** OIII bubble is the highlight; pair with M52 if framing wider
- **Research:** [SIMBAD](https://simbad.cds.unistra.fr/simbad/sim-id?Ident=NGC+7635) • [Aladin](https://aladin.u-strasbg.fr/AladinLite/?target=NGC+7635&fov=2) • [NED](https://ned.ipac.caltech.edu/byname?objname=NGC+7635) • [Telescopius](https://telescopius.com/deep-sky-targets?searched=Bubble+Nebula) • [Astrobin](https://www.astrobin.com/search/?q=Bubble+Nebula) • [Wikipedia](https://en.wikipedia.org/wiki/Bubble_Nebula)

### M52 — M52 + Bubble region

**Emission nebula (HII region)** in **Cas** • 60' × 30' • single frame

- **Coords (J2000):** RA `23h 24m 43.0s` (351.1790°) / Dec `+61° 35' 27.6"` (+61.5910°)
- **Recommended budget:** Ha 540m • OIII 600m • SII 540m (total 28.0h)
- **Expected emission:** Ha-dominant; OIII varies (often faint, sometimes strong as in M16/M17 cores); SII for SHO palette
- **Catalog notes:** Frame to include both M52 open cluster and NGC 7635 Bubble
- **Research:** [SIMBAD](https://simbad.cds.unistra.fr/simbad/sim-id?Ident=M52) • [Aladin](https://aladin.u-strasbg.fr/AladinLite/?target=M52&fov=2) • [NED](https://ned.ipac.caltech.edu/byname?objname=M52) • [Telescopius](https://telescopius.com/deep-sky-targets?searched=M52+%2B+Bubble+region) • [Astrobin](https://www.astrobin.com/search/?q=M52+%2B+Bubble+region) • [Wikipedia](https://en.wikipedia.org/wiki/M52_%2B_Bubble_region)

### NGC 7662 — Blue Snowball

**Planetary nebula** in **And** • 0' × 0' • single frame

- **Coords (J2000):** RA `23h 24m 53.0s` (351.2210°) / Dec `+42° 32' 45.6"` (+42.5460°)
- **Recommended budget:** Ha 240m • OIII 540m • SII 180m (total 16.0h)
- **Expected emission:** OIII typically dominant; Ha bright in core, often a faint outer halo worth long subs
- **Catalog notes:** Tiny PN — undersampled but bright; OIII strong
- **Research:** [SIMBAD](https://simbad.cds.unistra.fr/simbad/sim-id?Ident=NGC+7662) • [Aladin](https://aladin.u-strasbg.fr/AladinLite/?target=NGC+7662&fov=2) • [NED](https://ned.ipac.caltech.edu/byname?objname=NGC+7662) • [Telescopius](https://telescopius.com/deep-sky-targets?searched=Blue+Snowball) • [Astrobin](https://www.astrobin.com/search/?q=Blue+Snowball) • [Wikipedia](https://en.wikipedia.org/wiki/Blue_Snowball)

