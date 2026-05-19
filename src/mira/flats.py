"""Per-filter flat-field calibration: bracket -> capture -> master.

First-class productization of the 2026-05-19 ad-hoc flat session. The hard
rules learned that night are baked in as core guards, not options:

* **Freshness.** NINA's image-history can return a STALE frame when the
  camera/connection degrades (the `NoState` trap): two "captures" returned
  byte-identical stats. Every frame is checked: its Filename must differ
  from the prior one, else it is not counted.
* **Is it actually a flat?** A frame with stars is sky, not a flat (the
  tablet/paper wasn't covering the aperture). Frames with > MAX_STARS are
  rejected.
* **Repeatability before committing.** A hand-placed diffuse source can
  fluctuate; the level is pinned only after two shots at the chosen
  exposure agree within REPEAT_SPREAD. Non-monotonic / unstable response
  aborts the filter rather than banking bad flats.
* **Opaque positions auto-skip.** A blocking filter ("Dark") never
  illuminates; detected by a still-near-bias median at the longest
  bracket exposure and skipped, not wasted on a 25-frame series.

The flat *source* is manual (paper taped over the aperture) and stays put
for the whole multi-filter run; the wheel is driven automatically. Pure
bracket math + an injected client -> unit-tested without NINA.
"""
from __future__ import annotations

import glob
import json
import math
import os
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

# Empirical defaults from the 2026-05-19 S30 Pro session.
TARGET_ADU_DEFAULT = 30000.0
ADU_TOL = 0.08            # fine bracket accepts within +-8% of target
MIN_EXP_DEFAULT = 0.005   # camera floor; below this exposure can't go shorter
MAX_EXP_DEFAULT = 30.0
FRAMES_DEFAULT = 25
MAX_STARS = 3             # > this => seeing sky, not a flat
SAT_ADU = 60000.0         # 16-bit; at/above this the frame is clipped
REPEAT_SPREAD = 0.05      # two confirm shots must agree within 5%
WIDE_FACTOR = 10.0 ** 0.5  # ~3.16x geometric step for the wide scan
FINE_MAX_ITERS = 6


class _Client(Protocol):
    def available_filters(self) -> list[dict[str, Any]]: ...
    def current_filter(self) -> dict[str, Any] | None: ...
    def set_filter(self, filter_ref: str | int, *, wait: bool = ...,
                   timeout_s: float = ...) -> bool: ...
    def wait_camera_idle(self, timeout_s: float = ..., poll_s: float = ...) -> bool: ...
    def capture(self, *, duration: float, gain: int | None = ..., save: bool = ...,
                solve: bool = ..., target_name: str = ..., timeout_s: float = ...) -> dict: ...
    def image_history(self, all_images: bool = ...) -> list[dict[str, Any]]: ...


@dataclass
class FilterFlatResult:
    filter_name: str
    status: str = ""               # "ok" | "skipped_opaque" | "bracket_failed"
                                   # | "unstable" | "too_bright" | "no_frames"
    exposure_s: float = 0.0
    median_adu: float = 0.0
    n_good: int = 0
    n_rejected: int = 0
    master_path: str = ""
    note: str = ""


@dataclass
class FlatsRunResult:
    results: list[FilterFlatResult] = field(default_factory=list)
    out_root: str = ""


def solve_exposure(
    samples: list[tuple[float, float]], target_adu: float,
    *, min_exp: float, max_exp: float,
) -> float:
    """Predict the exposure that yields `target_adu` from measured
    (exposure, median) samples. Sensor response is linear with an additive
    offset: median ~= bias + k*exposure. With >=2 samples, least-squares
    fit that line and invert; with 1, assume bias 0 (proportional). Result
    is clamped to [min_exp, max_exp]."""
    pts = [(e, m) for e, m in samples if e > 0 and math.isfinite(m)]
    if not pts:
        return min_exp
    if len(pts) == 1:
        e, m = pts[0]
        k = m / e if e else 0.0
        est = target_adu / k if k > 0 else max_exp
    else:
        n = len(pts)
        sx = sum(e for e, _ in pts)
        sy = sum(m for _, m in pts)
        sxx = sum(e * e for e, _ in pts)
        sxy = sum(e * m for e, m in pts)
        denom = n * sxx - sx * sx
        if abs(denom) < 1e-12:
            est = max_exp
        else:
            k = (n * sxy - sx * sy) / denom
            bias = (sy - k * sx) / n
            est = (target_adu - bias) / k if k > 1e-9 else max_exp
    return float(min(max(est, min_exp), max_exp))


def _read_last(client: _Client) -> dict[str, Any]:
    hist = client.image_history()
    return hist[-1] if hist else {}


def _find_capture_file(
    root: Path, filename: str | None, after_mtime: float
) -> str | None:
    """Resolve the FITS this capture wrote. Prefer an exact basename match
    against the image-history Filename (how NINA ties history to the saved
    file — deterministic, collision-free). Fall back to newest-by-mtime
    only if the name can't be matched (defensive; real NINA always names
    them)."""
    files = glob.glob(os.path.join(str(root), "**", "*.fit*"), recursive=True)
    if filename:
        base = os.path.basename(str(filename))
        for p in files:
            if os.path.basename(p) == base:
                return p
    cands = [p for p in files if os.path.getmtime(p) > after_mtime]
    return max(cands, key=os.path.getmtime) if cands else None


def shoot(
    client: _Client, *, exposure_s: float, gain: int | None,
    nina_root: Path, settle_s: float = 0.0, target_name: str = "FLAT",
) -> tuple[bool, float, int, str | None, float]:
    """One validated exposure. Returns
    (fresh, median, stars, newest_file_path, t0). `fresh` is False when the
    image-history Filename did not change (the stale-frame trap) -- callers
    must treat a non-fresh frame as no data, never as a flat."""
    hist = client.image_history()
    before = hist[-1].get("Filename") if hist else None
    t0 = time.time()
    client.wait_camera_idle(20.0)
    client.capture(duration=exposure_s, gain=gain, save=True, solve=False,
                   target_name=target_name, timeout_s=max(exposure_s * 2 + 60, 40))
    if settle_s:
        time.sleep(settle_s)
    last = _read_last(client)
    fn = last.get("Filename")
    fresh = fn is not None and fn != before
    try:
        med = float(last.get("Median"))
    except (TypeError, ValueError):
        med = float("nan")
    try:
        stars = int(last.get("Stars"))
    except (TypeError, ValueError):
        stars = 9999
    newest = _find_capture_file(nina_root, fn, t0 - 1.0) if fresh else None
    return fresh, med, stars, newest, t0


def _valid_flat(fresh: bool, med: float, stars: int, lo: float, hi: float) -> bool:
    return fresh and stars <= MAX_STARS and math.isfinite(med) and lo <= med <= hi


def bracket_filter(
    client: _Client, *, gain: int | None, target_adu: float,
    nina_root: Path, min_exp: float, max_exp: float,
    emit: Callable[[str], None],
) -> tuple[str, float, float]:
    """Wide geometric scan then fine refine + repeatability gate. Returns
    (status, exposure, median). status: 'ok' | 'skipped_opaque' |
    'too_bright' | 'bracket_failed' | 'unstable'."""
    # --- wide scan: geometric exposures across the whole range ---
    samples: list[tuple[float, float]] = []
    e = min_exp
    exps: list[float] = []
    while e <= max_exp + 1e-9:
        exps.append(round(e, 6))
        e *= WIDE_FACTOR
    if exps[-1] < max_exp:
        exps.append(max_exp)
    for ex in exps:
        fresh, med, stars, _, _ = shoot(client, exposure_s=ex, gain=gain,
                                        nina_root=nina_root)
        emit(f"  wide {ex:.4g}s -> fresh={fresh} median={med:.0f} stars={stars}")
        if fresh and math.isfinite(med):
            samples.append((ex, med))
    if not samples:
        return "bracket_failed", 0.0, 0.0
    longest_med = samples[-1][1]
    shortest_med = samples[0][1]
    # Opaque: even the longest exposure barely rises above bias.
    if longest_med < max(0.05 * target_adu, 2000.0):
        return "skipped_opaque", 0.0, longest_med
    # Already clipped at the shortest exposure -> can't go dimmer.
    if shortest_med >= SAT_ADU:
        return "too_bright", min_exp, shortest_med

    # --- fine refine: linear-model predict, measure, repeat ---
    # Saturated samples (the clipped plateau) carry no slope information and
    # would flatten the fit -> only feed unsaturated points to the solver.
    def _fit_samples() -> list[tuple[float, float]]:
        u = [(e, m) for e, m in samples if m < 0.9 * SAT_ADU]
        return u or samples

    lo, hi = (1.0 - ADU_TOL) * target_adu, (1.0 + ADU_TOL) * target_adu
    exp = solve_exposure(_fit_samples(), target_adu, min_exp=min_exp,
                         max_exp=max_exp)
    chosen = 0.0
    for _ in range(FINE_MAX_ITERS):
        fresh, med, stars, _, _ = shoot(client, exposure_s=exp, gain=gain,
                                        nina_root=nina_root)
        emit(f"  fine {exp:.4g}s -> fresh={fresh} median={med:.0f} stars={stars}")
        if fresh and math.isfinite(med):
            samples.append((exp, med))
            if lo <= med <= hi:
                chosen = exp
                break
        exp = solve_exposure(_fit_samples(), target_adu, min_exp=min_exp,
                             max_exp=max_exp)
    if chosen <= 0.0:
        return "bracket_failed", exp, 0.0

    # --- repeatability gate: two confirm shots must agree ---
    confirm: list[float] = []
    for _ in range(2):
        fresh, med, stars, _, _ = shoot(client, exposure_s=chosen, gain=gain,
                                        nina_root=nina_root)
        emit(f"  confirm {chosen:.4g}s -> fresh={fresh} median={med:.0f}")
        if not _valid_flat(fresh, med, stars, lo * 0.8, hi * 1.2):
            return "unstable", chosen, med
        confirm.append(med)
    spread = (max(confirm) - min(confirm)) / (sum(confirm) / len(confirm))
    if spread > REPEAT_SPREAD:
        emit(f"  UNSTABLE: confirm spread {spread*100:.1f}% > {REPEAT_SPREAD*100:.0f}%")
        return "unstable", chosen, sum(confirm) / len(confirm)
    return "ok", chosen, sum(confirm) / len(confirm)


def capture_series(
    client: _Client, *, exposure_s: float, gain: int | None, target_adu: float,
    frames: int, dest_dir: Path, nina_root: Path,
    emit: Callable[[str], None],
) -> tuple[int, int]:
    """Capture `frames` validated flats at the locked exposure into
    `dest_dir`. Idempotent (dedupe by NINA filename). Returns
    (n_good, n_rejected)."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    lo, hi = 0.6 * target_adu, 1.5 * target_adu
    good = sum(1 for _ in dest_dir.glob("*.fit*"))
    rejected = 0
    for i in range(1, frames + 1):
        fresh, med, stars, src, _ = shoot(client, exposure_s=exposure_s,
                                          gain=gain, nina_root=nina_root)
        ok = _valid_flat(fresh, med, stars, lo, hi)
        if ok and src and not (dest_dir / os.path.basename(src)).exists():
            try:
                shutil.copy2(src, dest_dir)
                good += 1
            except OSError as exc:
                ok, rejected = False, rejected + 1
                emit(f"  {i}/{frames} copy failed: {exc}")
                continue
        else:
            rejected += 1
        if i == 1 or i % 5 == 0 or not ok:
            emit(f"  {i}/{frames} fresh={fresh} median={med:.0f} stars={stars} "
                 f"{'OK' if ok else 'REJECT'}")
    return good, rejected


def _siril_master_script(flats_dir: Path, work_dir: Path) -> str:
    from .siril import _outarg, _q
    # siril-cli overrides its CWD to its own configured default (e.g.
    # `~/Pictures` on Windows) at startup, ignoring the subprocess cwd we
    # pass — so relative paths in the script resolve from the wrong place.
    # Always emit absolute paths.
    flats_dir = Path(flats_dir).resolve()
    work_dir = Path(work_dir).resolve()
    return "\n".join([
        "requires 1.2.0",
        "setext fit",
        f"cd {_q(flats_dir)}",
        f"convert flat -out={_outarg(work_dir)}",
        f"cd {_q(work_dir)}",
        "stack flat rej 3 3 -norm=mul -out=flat_stacked",
        "load flat_stacked",
        # master_flat.fit is the CANONICAL master `mira stack` feeds Siril
        # via `calibrate -flat=`; the tif/png are human previews only.
        f"save {_q(Path('master_flat'))}",
        f"savetif32 {_q(Path('master_flat'))} -astro",
        "autostretch",
        f"savepng {_q(Path('master_flat_preview'))}",
        "close",
    ]) + "\n"


def build_master(
    flats_dir: Path, out_dir: Path, *, metadata: dict[str, Any],
    siril_runner: Callable[..., str] | None = None,
) -> str:
    """Stack the raw flats into a master (Siril convert -> rej stack
    -norm=mul, the validated recipe), write master_flat.tif/.fit + preview
    + metadata.json into `out_dir`. `siril_runner` is injectable for tests;
    default is mira.siril.run_siril. Returns the master path ('' on
    failure)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    work = out_dir / "_siril_work"
    work.mkdir(parents=True, exist_ok=True)
    if siril_runner is None:
        from .siril import run_siril as siril_runner  # type: ignore
    siril_runner(_siril_master_script(flats_dir, work), work_dir=work,
                 timeout_s=600.0)
    for name in ("master_flat.fit", "master_flat.tif", "master_flat_preview.png"):
        src = work / name
        if src.exists():
            shutil.move(str(src), str(out_dir / name))
    # The .fit is the canonical master (Siril `calibrate -flat=`); fall
    # back to the .tif only if Siril somehow produced no FITS.
    if (out_dir / "master_flat.fit").exists():
        master = str(out_dir / "master_flat.fit")
    elif (out_dir / "master_flat.tif").exists():
        master = str(out_dir / "master_flat.tif")
    else:
        master = ""
    (out_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    shutil.rmtree(work, ignore_errors=True)
    return master


CAPTURE_SIDECAR = "mira_capture.json"


def write_capture_sidecar(dest_dir: Path, **fields: Any) -> None:
    """Persist capture provenance (filter, gain, exposure, ...) next to the
    copied subs. NINA's API-capture FITS carry GAIN but NOT a FILTER
    keyword (verified 2026-05-19 — same lossy path as the missing-WCS
    issue), so the filter cannot be recovered from the lights themselves.
    This sidecar is the only reliable filter↔lights link, and
    `resolve_master_for_lights` keys off it. Best-effort: a write failure
    must not abort a capture run."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    fields.setdefault("written_utc", datetime.now(timezone.utc).isoformat())
    try:
        (dest_dir / CAPTURE_SIDECAR).write_text(
            json.dumps(fields, indent=2), encoding="utf-8"
        )
    except OSError:
        pass


def resolve_master_for_lights(
    lights_dir: Path, flats_root: Path
) -> tuple[Path | None, str]:
    """Find the master flat matching a `mira capture`-produced lights dir.
    Returns (master_flat.fit path, reason) or (None, why-not). Keys off the
    capture sidecar (the FITS have no FILTER keyword); picks the newest
    `<filter>_g<gain>_<YYYYMMDD>/master_flat.fit` under `flats_root`. Never
    guesses — an unresolved match returns None so the caller can hard-abort
    rather than silently stack without the right flat."""
    sc = Path(lights_dir) / CAPTURE_SIDECAR
    if not sc.exists():
        return None, (
            f"no {CAPTURE_SIDECAR} in {lights_dir}; NINA FITS carry no FILTER "
            "keyword so the filter can't be inferred. Capture with "
            "`mira capture --filter <name>`, or pass --flats manually."
        )
    try:
        meta = json.loads(sc.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"unreadable {CAPTURE_SIDECAR}: {exc}"
    filt = str(meta.get("filter") or "").strip()
    if not filt:
        return None, (
            f"{CAPTURE_SIDECAR} records no filter (captured without --filter); "
            "cannot match a per-filter master."
        )
    gain = meta.get("gain")
    gain_tag = "default" if gain is None else str(gain)
    root = Path(flats_root)
    cands = [
        c for c in root.glob(f"{filt}_g{gain_tag}_*")
        if (c / "master_flat.fit").exists()
    ]
    if not cands:
        return None, (
            f"no master flat for filter='{filt}' gain={gain_tag} under {root} "
            f"(looked for {filt}_g{gain_tag}_*/master_flat.fit — run "
            "`mira flats` for this filter/gain first)."
        )
    chosen = max(cands, key=lambda c: c.name)  # newest trailing YYYYMMDD
    return chosen / "master_flat.fit", f"matched {chosen.name}"


def run_flats(
    client: _Client,
    *,
    filters: list[str] | None,
    gain: int | None,
    target_adu: float = TARGET_ADU_DEFAULT,
    frames: int = FRAMES_DEFAULT,
    out_root: Path,
    nina_root: Path,
    min_exp: float = MIN_EXP_DEFAULT,
    max_exp: float = MAX_EXP_DEFAULT,
    on_step: Callable[[str], None] | None = None,
    siril_runner: Callable[..., str] | None = None,
) -> FlatsRunResult:
    """For each requested filter (default: every wheel position): drive the
    wheel, bracket the exposure, capture a validated series, build the
    master. Opaque positions are auto-detected and skipped. The flat source
    (taped paper) is assumed in place for the whole run."""
    def emit(m: str) -> None:
        if on_step is not None:
            on_step(m)

    out_root = Path(out_root)
    run = FlatsRunResult(out_root=str(out_root))
    wheel = client.available_filters()
    names = [str(f.get("Name")) for f in wheel]
    want = filters if filters is not None else names
    date = datetime.now(timezone.utc).strftime("%Y%m%d")

    for name in want:
        if name not in names:
            run.results.append(FilterFlatResult(
                filter_name=name, status="bracket_failed",
                note="filter not present on wheel"))
            emit(f"[{name}] NOT on wheel ({names}); skipped")
            continue
        emit(f"[{name}] selecting filter...")
        if not client.set_filter(name, wait=True):
            run.results.append(FilterFlatResult(
                filter_name=name, status="bracket_failed",
                note="filter wheel did not confirm move"))
            emit(f"[{name}] wheel move NOT confirmed; skipped")
            continue
        emit(f"[{name}] bracketing (target {target_adu:.0f} ADU)...")
        status, exp, med = bracket_filter(
            client, gain=gain, target_adu=target_adu, nina_root=nina_root,
            min_exp=min_exp, max_exp=max_exp, emit=emit)
        res = FilterFlatResult(filter_name=name, status=status,
                               exposure_s=exp, median_adu=med)
        if status != "ok":
            note = {
                "skipped_opaque": "opaque position (no illumination) — likely a "
                                  "dark/blocking filter; not a flat target",
                "too_bright": "saturated even at the minimum exposure — dim the "
                              "flat source",
                "unstable": "illumination not repeatable — re-seat the paper / "
                            "steady the light",
                "bracket_failed": "could not converge on a target-ADU exposure",
            }.get(status, status)
            res.note = note
            run.results.append(res)
            emit(f"[{name}] {status}: {note}")
            continue
        gain_tag = "default" if gain is None else str(gain)
        fdir = out_root / f"{name}_g{gain_tag}_{date}"
        raw = fdir / "raw"
        emit(f"[{name}] exposure {exp:.4g}s @ ~{med:.0f} ADU; "
             f"capturing {frames} frames...")
        good, rej = capture_series(
            client, exposure_s=exp, gain=gain, target_adu=target_adu,
            frames=frames, dest_dir=raw, nina_root=nina_root, emit=emit)
        res.n_good, res.n_rejected = good, rej
        if good < 3:
            res.status, res.note = "no_frames", (
                f"only {good} valid frames captured — master not built")
            run.results.append(res)
            emit(f"[{name}] too few good frames ({good}); master skipped")
            continue
        meta = {
            "filter": name, "gain": gain, "exposure_s": exp,
            "target_adu": target_adu, "measured_median_adu": med,
            "n_frames": good, "n_rejected": rej,
            "captured_utc": datetime.now(timezone.utc).isoformat(),
            "scope": "Seestar S30 Pro", "recipe": "siril convert + rej stack -norm=mul",
            "reusable": "sealed optical system — valid for future captures at this "
                        "filter/gain until focus/optics change",
        }
        emit(f"[{name}] building master from {good} frames...")
        master = build_master(raw, fdir, metadata=meta, siril_runner=siril_runner)
        res.master_path = master
        res.status = "ok" if master else "no_frames"
        res.note = "" if master else "Siril produced no master"
        run.results.append(res)
        emit(f"[{name}] DONE -> {master or '(master build failed)'}")

    return run
