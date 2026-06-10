# Emission targets — rig fit matrix

One row per image-book target, one column per rig; cell = that book's fit class (`fits` / `tight` / `small` / `EW-overflow` / `overflow`, `—` = not in that book). **Verdict = the most resolution that still frames it** (Esprit 120 → Esprit 80 → S30); read the cells when you'd rather trade sampling for context. `small` means the rig can shoot it but it's a feature for a longer FL; `EW-overflow` is the S30's fixed-frame casualty class (no rotator — E–W extent vs the 2.20° axis). Books: `esprit_emission_book/`, `esprit80_emission_book/`, `s30_emission_book/`. Shared exclusions (too low from JC): M8, M20, M16, M17.

| Target | Common | Size | Peak | maxAlt | Esprit 120 (1.60°×1.07°, rotates) | Esprit 80 (3.37°×2.25°, rotates) | S30 Pro (3.91°×2.20°, FIXED N–S) | Verdict |
|---|---|---|---|---|---|---|---|---|
| IC 1318 | Sadr / Butterfly | 180'×170' | Jul | 89° | — | — | EW-overflow | **2-panel / crop (overflows all)** |
| NGC 6888 | Crescent | 18'×12' | Jul | 88° | fits | small | small | **Esprit 120** |
| Sh2-101 | Tulip | 16'×9' | Jul | 85° | fits | small | small | **Esprit 120** |
| M57 | Ring | 1.4'×1.0' | Jul | 82° | fits | — | — | **Esprit 120** |
| NGC 6820 | Sh2-86 | 40'×30' | Jul | 72° | fits | fits | — | **Esprit 120** |
| M27 | Dumbbell | 8'×6' | Jul | 72° | fits | small | small | **Esprit 120** |
| Sh2-119 | Clamshell | 90'×90' | Aug | 87° | — | fits | fits | **Esprit 80** |
| IC 5070 | Pelican | 60'×50' | Aug | 86° | fits | fits | — | **Esprit 120** |
| NGC 7000 | North America | 120'×100' | Aug | 86° | — | fits | fits | **Esprit 80** |
| IC 5146 | Cocoon | 12'×12' | Aug | 83° | fits | small | small | **Esprit 120** |
| NGC 6992 | Eastern Veil | 60'×8' | Aug | 81° | fits | fits | — | **Esprit 120** |
| NGC 6960 | Western Veil | 70'×8' | Aug | 80° | fits | fits | — | **Esprit 120** |
| Cygnus Loop | Veil (full loop) | 180'×170' | Aug | 80° | — | — | EW-overflow | **2-panel / crop (overflows all)** |
| Sh2-132 | Lion | 40'×30' | Aug | 75° | fits | fits | fits | **Esprit 120** |
| IC 1396A | Elephant's Trunk | 20'×10' | Aug | 73° | fits | — | — | **Esprit 120** |
| IC 1396 | Elephant's Trunk (full) | 170'×140' | Aug | 73° | — | tight | tight | **Esprit 80 (tight)** |
| Sh2-129 | Flying Bat (+OU4 Squid) | 150'×120' | Aug | 71° | — | fits | tight | **Esprit 80** |
| NGC 7380 | Wizard | 25'×20' | Sep | 73° | fits | fits | — | **Esprit 120** |
| Sh2-157 | Lobster Claw | 60'×30' | Sep | 71° | fits | fits | fits | **Esprit 120** |
| NGC 7635 | Bubble | 22'×15' | Sep | 70° | fits | small | — | **Esprit 120** |
| Sh2-155 | Cave | 50'×30' | Sep | 68° | fits | fits | fits | **Esprit 120** |
| NGC 7822 | Sh2-171 | 60'×60' | Sep | 63° | tight | fits | fits | **Esprit 120 (tight)** |
| NGC 281 | Pacman | 35'×30' | Oct | 74° | fits | fits | small | **Esprit 120** |
| IC 1805 | Heart | 100'×90' | Oct | 69° | — | fits | fits | **Esprit 80** |
| NGC 1499 | California | 145'×40' | Nov | 86° | — | fits | EW-overflow | **Esprit 80** |
| IC 1848 | Soul | 60'×40' | Nov | 70° | — | fits | fits | **Esprit 80** |
| IC 405 | Flaming Star | 37'×19' | Dec | 84° | fits | fits | tight | **Esprit 120** |
| IC 410 | Tadpoles | 40'×30' | Dec | 83° | fits | fits | — | **Esprit 120** |
| Simeis 147 | Spaghetti (Sh2-240) | 180'×180' | Dec | 77° | — | — | EW-overflow | **2-panel / crop (overflows all)** |
| IC 443 | Jellyfish | 50'×40' | Dec | 72° | fits | fits | fits | **Esprit 120** |
| M1 | Crab | 6'×4' | Dec | 71° | fits | small | small | **Esprit 120** |
| NGC 2174 | Monkey Head | 40'×30' | Dec | 70° | fits | fits | fits | **Esprit 120** |
| NGC 2264 | Christmas Tree / Cone | 40'×20' | Dec | 59° | fits | fits | fits | **Esprit 120** |
| NGC 2237 | Rosette | 80'×70' | Dec | 54° | tight | fits | fits | **Esprit 120 (tight)** |
| NGC 2024 | Flame | 30'×30' | Dec | 47° | fits | — | — | **Esprit 120** |
| IC 434 | Horsehead | 60'×10' | Dec | 47° | fits | fits | fits | **Esprit 120** |
| M42 | Orion Nebula | 85'×60' | Dec | 44° | tight | fits | fits | **Esprit 120 (tight)** |
| Abell 21 | Medusa | 10'×10' | Jan | 63° | fits | small | — | **Esprit 120** |
| IC 2177 | Seagull | 150'×50' | Jan | 39° | — | fits | fits | **Esprit 80** |
| NGC 2359 | Thor's Helmet | 10'×8' | Jan | 36° | fits | small | small | **Esprit 120** |
