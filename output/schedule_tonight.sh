#!/usr/bin/env bash
# Tonight's scheduled two-target run:
#   M92 (broadband IR, 10s)  -> first half of the night
#   NGC 6888 Crescent (LP, 60s) -> from 00:15 (adds onto last night's ngc6888_20260530
#                                  for the multi-night combine; matched LP / gain 80 / 60s)
cd /c/mira || exit 1
echo "==== schedule start $(date '+%Y-%m-%d %H:%M:%S') ===="

# 1) M92 first half -- same recipe as M13 (bright globular, moon/cloud-tolerant)
mira capture --ra 259.28 --dec 43.14 --exposure 10 --gain 80 --filter IR \
  --dither-arcsec 30 --dither-every 1 --dest captures/m92_20260531 --platesolve-center &
M92=$!
echo "[$(date '+%H:%M:%S')] M92 capturing (pid $M92)"

# 2) wait until 00:15 (next occurrence).  Change HANDOFF_MIN for a different time
#    (e.g. 30 = 00:30, which clears the house fully -- see notes).
HANDOFF_MIN=15
H=$(date +%H); M=$(date +%M)
SINCE=$(( 10#$H*3600 + 10#$M*60 )); TGT=$(( 0*3600 + HANDOFF_MIN*60 ))
if [ $TGT -gt $SINCE ]; then SLP=$(( TGT - SINCE )); else SLP=$(( 86400 - SINCE + TGT )); fi
echo "[$(date '+%H:%M:%S')] Crescent handoff in ${SLP}s"
sleep "$SLP"

# 3) stop M92, start Crescent (its platesolve-center fails soft -> blind dither if the
#    low field won't solve; self-stops at dawn via --sun-max, then parks)
echo "[$(date '+%H:%M:%S')] stopping M92 -> Crescent"
kill -INT "$M92" 2>/dev/null; sleep 25; kill "$M92" 2>/dev/null; sleep 10
mira capture --ra 303.0 --dec 38.35 --exposure 60 --gain 80 --filter LP \
  --dither-arcsec 30 --dither-every 1 --dest captures/ngc6888_20260531 --platesolve-center --park-at-end
echo "[$(date '+%H:%M:%S')] done -- Crescent ended (dawn/alt/stop) at $(date '+%H:%M:%S')"
