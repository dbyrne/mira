# archived? -- Is the raw data sitting in the transient mele_nina Syncthing
# mirror safely archived ELSEWHERE, so it's safe to delete off the MeLE?
#
# A mele_nina frame counts as SAFE only when the same file (by hardlink/inode)
# also lives under captures/<target>/ (the permanent homebase archive, outside
# the synced folder) AND a copy exists on the D: backup. Deleting off the MeLE
# propagates the delete to mele_nina (receiveonly, no versioning) -- but a
# hardlinked archive survives it, and D: is the independent copy.
#
# Run:  powershell -File scripts\archived_check.ps1
$ErrorActionPreference = 'Continue'
python -c @"
import os, glob
from collections import defaultdict
cap = r'C:\mira\captures'
mele = os.path.join(cap, 'mele_nina')
dmir = r'D:\mira\captures'

# inode -> archive rel-paths (under captures/, excluding mele_nina + _-prefixed)
arch = defaultdict(list)
for f in glob.glob(os.path.join(cap, '**', '*.fit*'), recursive=True):
    rel = os.path.relpath(f, cap); parts = rel.split(os.sep)
    if parts[0] == 'mele_nina' or any(p.startswith('_') for p in parts):
        continue
    try: arch[os.stat(f).st_ino].append(rel)
    except OSError: pass

stats = defaultdict(lambda: [0, 0, set()])   # mele top folder -> [safe, total, targets]
for f in glob.glob(os.path.join(mele, '**', '*.fit*'), recursive=True):
    top = os.path.relpath(f, mele).split(os.sep)[0]
    s = stats[top]; s[1] += 1
    try: ino = os.stat(f).st_ino
    except OSError: continue
    paths = arch.get(ino, [])
    if paths and any(os.path.exists(os.path.join(dmir, p)) for p in paths):
        s[0] += 1
        for p in paths: s[2].add(os.path.dirname(p))

print('mele_nina archival status   (SAFE = hardlinked into captures/<target>/ AND on D:)')
print('  D: backup mounted: %s\n' % os.path.isdir(dmir))
if not stats:
    print('  (no FITS in mele_nina)')
for top in sorted(stats):
    safe, total, tg = stats[top]
    tag = ('SAFE to delete off MeLE' if total and safe == total
           else 'PARTIAL - do NOT delete yet' if safe else 'NOT archived')
    arts = ('-> ' + '; '.join(sorted(tg))) if tg else ''
    print('  %-16s %4d/%-4d  %-46s [%s]' % (top, safe, total, arts, tag))
print('\n  SAFE folders are on homebase + D:; deleting them off the MeLE is recoverable.')
"@
