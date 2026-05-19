"""`mira doctor` — one preflight that verifies the whole rig.

Run this on a cold laptop before a session (and at the end of
bootstrap.ps1). It is the single highest-value field tool: it turns the
hard-won failure modes from this project's history into automated checks
with actionable fixes, so a problem surfaces *before* you are cold and
far from WiFi instead of mid-capture.

Design rules:
- **Never raises.** Every check is wrapped; an exception becomes a FAIL
  line, because this is exactly the tool you run when things are broken.
- **ASCII only.** A Windows cp1252 console raises UnicodeEncodeError on
  fancy glyphs (this killed `submit` once); the report uses [PASS]/
  [WARN]/[FAIL], no box-drawing or em-dashes.
- **Pure helpers are separated** from I/O so they unit-test without a
  rig (darkness math, version compare, the summarizer/formatter).
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"

# Siril version the script generation in siril.py is verified against. A
# newer Siril can silently change CLI syntax (-out=, savetif32), so a
# mismatch is a WARN, not a hard pass.
TESTED_SIRIL_VERSION = "1.4.3"
MIN_FREE_GB_DEFAULT = 25.0  # a deep dithered run is ~19 GB of subs


@dataclass
class Check:
    name: str
    status: str  # PASS | WARN | FAIL
    detail: str = ""
    fix: str = ""


# --------------------------------------------------------------------------
# pure helpers (unit-tested without a rig)
# --------------------------------------------------------------------------
def parse_version(text: str) -> tuple[int, ...]:
    """First dotted-number run in `text` as an int tuple. '' -> ()."""
    import re

    m = re.search(r"(\d+(?:\.\d+)+)", text or "")
    return tuple(int(p) for p in m.group(1).split(".")) if m else ()


def night_darkness_minutes(
    lat: float, lon: float, max_sun_alt_deg: float,
    start_utc: datetime, hours: int = 24, step_min: int = 15,
) -> int:
    """Minutes in the next `hours` where the Sun is at/below
    `max_sun_alt_deg` at (lat, lon). 0 => no usable darkness (the
    high-latitude-summer trap, e.g. Fairbanks May-Aug)."""
    from .observability import sun_altitude_deg

    n = 0
    steps = int(hours * 60 / step_min)
    for i in range(steps):
        t = start_utc + timedelta(minutes=i * step_min)
        if sun_altitude_deg(t, lat, lon) <= max_sun_alt_deg:
            n += 1
    return n * step_min


def summarize(checks: list[Check]) -> tuple[str, int]:
    """Overall verdict + process exit code. Any FAIL -> FAIL/1; else any
    WARN -> WARN/0; else READY/0. WARN does not fail the exit code so
    bootstrap can proceed past optional-tool warnings."""
    if any(c.status == FAIL for c in checks):
        return "RIG NOT READY", 1
    if any(c.status == WARN for c in checks):
        return "RIG USABLE (with warnings)", 0
    return "RIG READY", 0


def format_report(checks: list[Check]) -> str:
    lines = ["", "mira doctor", "=" * 60]
    for c in checks:
        lines.append(f"[{c.status}] {c.name}")
        if c.detail:
            lines.append(f"       {c.detail}")
        if c.fix and c.status != PASS:
            lines.append(f"       fix: {c.fix}")
    verdict, _ = summarize(checks)
    lines += ["-" * 60, verdict, ""]
    return "\n".join(lines)


def _safe(fn: Callable[[], Check]) -> Check:
    try:
        return fn()
    except Exception as exc:  # a check must never crash doctor
        return Check(getattr(fn, "_cname", "check"), FAIL,
                     f"check raised: {exc!r}")


# --------------------------------------------------------------------------
# individual checks
# --------------------------------------------------------------------------
def check_python() -> Check:
    v = sys.version_info
    ok = (v.major, v.minor) >= (3, 11)
    return Check("Python >= 3.11",
                 PASS if ok else FAIL,
                 f"running {v.major}.{v.minor}.{v.micro}",
                 "install Python 3.11+ and recreate the venv")


def check_core_imports() -> Check:
    missing = []
    for mod in ("astropy", "photutils", "scipy", "numpy", "flask",
                "requests", "yaml"):
        try:
            __import__(mod)
        except Exception:
            missing.append(mod)
    if missing:
        return Check("Core dependencies", FAIL,
                     f"cannot import: {', '.join(missing)}",
                     "pip install -r requirements-lock.txt && pip install -e . --no-deps")
    return Check("Core dependencies", PASS, "all core imports OK")


def check_numpy_graxpert() -> Check:
    """GraXpert pins numpy<2.3; >=2.3 silently breaks `mira finish` AI
    steps (we hit numpy 2.4 -> downgraded to 2.2.6)."""
    try:
        import numpy
    except Exception as exc:
        return Check("numpy GraXpert-compatible", FAIL, f"numpy import failed: {exc}")
    ver = parse_version(numpy.__version__)
    if ver >= (2, 3):
        return Check("numpy GraXpert-compatible", WARN,
                     f"numpy {numpy.__version__} >= 2.3",
                     "pip install 'numpy==2.2.6' — GraXpert (mira finish) "
                     "needs numpy<2.3; capture/photometry are unaffected")
    return Check("numpy GraXpert-compatible", PASS, f"numpy {numpy.__version__}")


def check_siril() -> Check:
    try:
        from .siril import SirilNotFound, find_siril_cli
    except Exception as exc:
        return Check("Siril (stack/finish)", WARN, f"siril module load failed: {exc}")
    try:
        cli = find_siril_cli()
    except Exception as exc:
        return Check("Siril (stack/finish)", WARN, str(exc),
                     "install Siril 1.4.3 and add bin/ to PATH or set "
                     "MIRA_SIRIL_CLI; only needed for `mira stack`/`finish`")
    try:
        out = subprocess.run([str(cli), "-v"], capture_output=True,
                              text=True, timeout=20)
        txt = (out.stdout or "") + (out.stderr or "")
    except Exception as exc:
        return Check("Siril (stack/finish)", WARN, f"{cli} did not run: {exc}")
    ver = parse_version(txt)
    tested = parse_version(TESTED_SIRIL_VERSION)
    if ver and ver != tested:
        return Check("Siril (stack/finish)", WARN,
                     f"Siril {'.'.join(map(str, ver))} (script gen verified "
                     f"against {TESTED_SIRIL_VERSION})",
                     "stacking may still work; if it fails, pin Siril "
                     f"{TESTED_SIRIL_VERSION}")
    return Check("Siril (stack/finish)", PASS, f"{cli} ({TESTED_SIRIL_VERSION})")


def _find_astap() -> str | None:
    env = os.environ.get("MIRA_ASTAP_CLI")
    if env and Path(env).is_file():
        return env
    for name in ("astap_cli", "astap_cli.exe", "astap", "astap.exe"):
        w = shutil.which(name)
        if w:
            return w
    for guess in (r"C:\Program Files\astap\astap_cli.exe",
                  r"C:\Program Files\astap\astap.exe"):
        if Path(guess).is_file():
            return guess
    return None


def check_astap() -> Check:
    """ASTAP offline solve is effectively required on this rig: NINA's
    API/snapshot captures save no WCS, so photometry depends on the
    offline `astap_cli -fov 0 ... -update` recipe."""
    cli = _find_astap()
    if not cli:
        return Check("ASTAP (offline plate solve)", WARN,
                     "astap_cli not found",
                     "install ASTAP + a star database; set MIRA_ASTAP_CLI "
                     "or add to PATH. Needed for WCS on NINA captures "
                     "(submit/photometry).")
    db = list(Path(cli).parent.glob("*.290")) + \
        list(Path(cli).parent.glob("*.1476")) + \
        list(Path(cli).parent.glob("[dghvDGHV]*.[0-9]*"))
    if not db:
        return Check("ASTAP (offline plate solve)", WARN,
                     f"{cli} found but no star database beside it",
                     "download an ASTAP star DB (e.g. D50/H18) into the "
                     "ASTAP folder; without it solves fail 'No solution'")
    return Check("ASTAP (offline plate solve)", PASS,
                 f"{cli} (+star DB)")


def check_graxpert() -> Check:
    try:
        from .finishing import find_graxpert
        inv = find_graxpert()
        return Check("GraXpert (mira finish)", PASS, " ".join(inv))
    except Exception as exc:
        return Check("GraXpert (mira finish)", WARN, str(exc),
                     "pip install 'mira[finishing]' (optional; only `mira "
                     "finish` AI steps need it)")


def _port_open(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def check_nina(nina_url: str) -> tuple[Check, str | None]:
    """Returns (check, working_url). Probes the given URL; if it's the
    default localhost:1888 and dead, also tries 1889 (the ninaAPI port
    can land on either). Flags the `NoState` camera tell (degraded
    connection that returned byte-identical 'captures' once)."""
    from .webapp.nina_client import NinaClient

    urls = [nina_url]
    if "localhost:1888" in nina_url or "127.0.0.1:1888" in nina_url:
        urls.append(nina_url.replace("1888", "1889"))
    for url in urls:
        try:
            client = NinaClient(base_url=url)
            st = client.status()
            if not st.reachable:
                continue
            cam = client.camera_state()
            eq = ", ".join(f"{k}={v}" for k, v in sorted(st.equipment.items())) \
                or "no equipment reported"
            if cam == "NoState":
                return (Check("NINA Advanced API", WARN,
                              f"reachable at {url} but camera_state=NoState "
                              f"(degraded connection); {eq}",
                              "reconnect the camera in NINA; NoState has "
                              "produced stale/identical frames"), url)
            return (Check("NINA Advanced API", PASS,
                          f"reachable at {url}; {eq}"), url)
        except Exception:
            continue
    return (Check("NINA Advanced API", WARN,
                  f"not reachable at {', '.join(urls)}",
                  "start NINA, enable the Advanced API plugin, connect "
                  "equipment; doctor can't verify capture without it"), None)


def check_filter_wheel(working_url: str | None) -> Check:
    if not working_url:
        return Check("Filter wheel", WARN, "skipped (NINA not reachable)")
    try:
        from .webapp.nina_client import NinaClient

        fs = NinaClient(base_url=working_url).available_filters()
        if not fs:
            return Check("Filter wheel", WARN,
                         "no filter wheel reported",
                         "connect the S30 Pro filter wheel in NINA if you "
                         "want per-filter flats / `--filter`")
        names = ", ".join(str(f.get("Name")) for f in fs)
        return Check("Filter wheel", PASS, f"positions: {names}")
    except Exception as exc:
        return Check("Filter wheel", WARN, f"query failed: {exc}")


def check_darkness(config_path: str, when: datetime | None = None) -> Check:
    from .config import load_config

    cfg = load_config(config_path)
    now = when or datetime.now(timezone.utc)
    worst: tuple[str, int] | None = None
    details = []
    for site in cfg.sites:
        mins = night_darkness_minutes(
            site.observer.latitude_deg, site.observer.longitude_deg,
            site.observing_window.max_sun_altitude_deg, now, hours=24)
        details.append(f"{site.name}: {mins} min dark / next 24h")
        if worst is None or mins < worst[1]:
            worst = (site.name, mins)
    if worst and worst[1] == 0:
        return Check("Darkness tonight", FAIL,
                     "; ".join(details),
                     f"no astronomical darkness at {worst[0]} in the next "
                     "24h (high-latitude season?). Use a different site/date.")
    if worst and worst[1] < 60:
        return Check("Darkness tonight", WARN, "; ".join(details),
                     "very short dark window; expect a thin queue")
    return Check("Darkness tonight", PASS, "; ".join(details))


def check_disk_space(path: str, min_free_gb: float = MIN_FREE_GB_DEFAULT) -> Check:
    p = Path(path)
    while not p.exists() and p != p.parent:
        p = p.parent
    free_gb = shutil.disk_usage(p).free / 1e9
    if free_gb < min_free_gb:
        return Check("Capture disk space", WARN,
                     f"{free_gb:.0f} GB free at {p}",
                     f"a deep dithered run is ~19 GB; free up space "
                     f"(want >= {min_free_gb:.0f} GB)")
    return Check("Capture disk space", PASS, f"{free_gb:.0f} GB free at {p}")


def check_config(config_path: str) -> Check:
    from .config import load_config

    cfg = load_config(config_path)
    bad = [s.name for s in cfg.sites
           if not (-90 <= s.observer.latitude_deg <= 90)
           or not (-180 <= s.observer.longitude_deg <= 180)]
    if bad:
        return Check("Config", FAIL, f"invalid lat/lon for site(s): {bad}",
                     "fix observer latitude/longitude in the YAML")
    sites = ", ".join(s.name for s in cfg.sites)
    return Check("Config", PASS, f"{config_path}: {len(cfg.sites)} site(s) [{sites}]")


def check_writable(paths: tuple[str, ...] = ("output", "data")) -> Check:
    bad = []
    for d in paths:
        try:
            Path(d).mkdir(parents=True, exist_ok=True)
            probe = Path(d) / ".doctor_write_test"
            probe.write_text("x", encoding="ascii")
            probe.unlink()
        except Exception as exc:
            bad.append(f"{d} ({exc})")
    if bad:
        return Check("Writable dirs", FAIL, "; ".join(bad),
                     "ensure output/ and data/ are writable")
    return Check("Writable dirs", PASS, f"{', '.join(paths)} writable")


def run_doctor(
    *, config_path: str = "config/s30_pro_jc.yaml",
    nina_url: str = "http://localhost:1888",
    captures_root: str = "captures",
    when: datetime | None = None,
) -> list[Check]:
    """Assemble all checks. Order: environment first (no rig needed),
    then rig/NINA, then site/darkness."""
    checks: list[Check] = [
        _safe(check_python),
        _safe(check_core_imports),
        _safe(check_numpy_graxpert),
        _safe(check_siril),
        _safe(check_astap),
        _safe(check_graxpert),
        _safe(lambda: check_config(config_path)),
        _safe(lambda: check_writable()),
        _safe(lambda: check_disk_space(captures_root)),
    ]
    nina_check, working_url = check_nina(nina_url)
    checks.append(nina_check)
    checks.append(_safe(lambda: check_filter_wheel(working_url)))
    checks.append(_safe(lambda: check_darkness(config_path, when)))
    return checks
