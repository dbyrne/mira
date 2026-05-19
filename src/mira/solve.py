"""Bulk offline plate-solve via ASTAP.

NINA's API-driven captures don't write WCS into the FITS header (the
mira capture loop calls /equipment/camera/capture with solve=false to
keep per-sub latency low). Photometry and any WCS-aware downstream tool
needs the lights solved before they're useful — and so does the
linear stacked output (Siril inherits WCS from the reference frame).

`astap_cli -update` adds the WCS to a FITS in place. With a RA/Dec hint
from `mira_capture.json`, each solve takes 1-3s; blind solves take
20-60s. This module orchestrates the bulk run, skips frames that
already have WCS (idempotent — safe to re-run after a partial
session), and parallelizes via a small thread pool.
"""
from __future__ import annotations

import concurrent.futures
import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from astropy.io import fits

CAPTURE_SIDECAR = "mira_capture.json"
DEFAULT_RADIUS_DEG = 5.0      # generous when we have a hint; solves in <3s
BLIND_RADIUS_DEG = 180.0      # full sky fallback
DEFAULT_FOV_DEG = 4.6         # S30 Pro at 30mm/f5 with IMX585
DEFAULT_TIMEOUT_S = 120.0


class AstapNotFound(RuntimeError):
    pass


@dataclass
class SolveResult:
    path: str
    status: str  # "solved" | "already_solved" | "failed"
    note: str = ""


@dataclass
class SolveRunResult:
    solved: list[SolveResult] = field(default_factory=list)
    already_solved: list[SolveResult] = field(default_factory=list)
    failed: list[SolveResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.solved) + len(self.already_solved) + len(self.failed)


def find_astap_cli() -> str:
    """Return the astap_cli executable path. Mirrors doctor._find_astap so
    the precedence is identical: MIRA_ASTAP_CLI env > PATH > standard
    Windows install location. Raises AstapNotFound if absent."""
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
    raise AstapNotFound(
        "astap_cli not found. Install ASTAP and set MIRA_ASTAP_CLI or add "
        "it to PATH. Run `mira doctor` to verify."
    )


def has_wcs(fits_path: Path) -> bool:
    """Header-only check for a celestial WCS: CTYPE1 + CRVAL1 in at least
    one HDU. Cheap (astropy reads only the header). False on read error."""
    try:
        with fits.open(fits_path, mode="readonly") as hdul:
            for hdu in hdul:
                hdr = hdu.header
                if hdr.get("CTYPE1") and "CRVAL1" in hdr:
                    return True
    except (OSError, fits.verify.VerifyError, ValueError):
        return False
    return False


def _as_float(x: Any) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def load_hints_from_sidecar(lights_dir: Path) -> tuple[float | None, float | None]:
    """Pull (ra_deg, dec_deg) from `mira_capture.json` in lights_dir.
    Returns (None, None) if the sidecar is missing or unreadable — caller
    falls back to blind solve."""
    sc = Path(lights_dir) / CAPTURE_SIDECAR
    if not sc.exists():
        return None, None
    try:
        meta = json.loads(sc.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, None
    return _as_float(meta.get("ra_deg")), _as_float(meta.get("dec_deg"))


def solve_one(
    fits_path: Path,
    *,
    astap_cli: str,
    ra_hint_deg: float | None,
    dec_hint_deg: float | None,
    fov_deg: float = DEFAULT_FOV_DEG,
    radius_deg: float = DEFAULT_RADIUS_DEG,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    runner: Callable[..., subprocess.CompletedProcess] | None = None,
) -> SolveResult:
    """Run `astap_cli -update` on one FITS. With RA/Dec hints, uses a
    small search radius (fast); without, falls back to a blind solve.
    `runner` is injectable so tests can mock subprocess. Returns a
    SolveResult — never raises for solve-time errors."""
    args = [astap_cli, "-f", str(fits_path), "-update", "-z", "0"]
    if ra_hint_deg is not None and dec_hint_deg is not None:
        args += [
            "-ra", f"{ra_hint_deg / 15.0:.6f}",          # ASTAP takes hours
            "-spd", f"{90.0 + dec_hint_deg:.6f}",        # 90 + dec
            "-fov", f"{fov_deg:.4f}",
            "-r", f"{radius_deg:.4f}",
        ]
    else:
        args += ["-fov", "0", "-r", f"{BLIND_RADIUS_DEG:.4f}"]
    run = runner or subprocess.run
    try:
        proc = run(args, capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return SolveResult(str(fits_path), "failed",
                           f"timed out after {timeout_s:.0f}s")
    except OSError as exc:
        return SolveResult(str(fits_path), "failed",
                           f"astap_cli launch failed: {exc}")
    if proc.returncode != 0:
        tail = ((proc.stdout or "") + (proc.stderr or "")).strip().splitlines()
        return SolveResult(
            str(fits_path), "failed",
            f"exit {proc.returncode}: {tail[-1] if tail else '(no output)'}",
        )
    # ASTAP can exit 0 with "no solution found" written to stdout if the
    # star DB is missing or the hint is way off. Verify by re-reading the
    # header — `-update` is supposed to have written WCS keywords.
    if not has_wcs(fits_path):
        return SolveResult(
            str(fits_path), "failed",
            "astap_cli exited 0 but no WCS in FITS — DB missing or hint wrong?",
        )
    return SolveResult(str(fits_path), "solved")


def run_solve_dir(
    lights_dir: Path,
    *,
    astap_cli: str | None = None,
    force: bool = False,
    workers: int = 4,
    fov_deg: float = DEFAULT_FOV_DEG,
    radius_deg: float = DEFAULT_RADIUS_DEG,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    ra_hint_deg: float | None = None,
    dec_hint_deg: float | None = None,
    on_step: Callable[[str], None] | None = None,
    runner: Callable[..., subprocess.CompletedProcess] | None = None,
) -> SolveRunResult:
    """Solve every FITS in `lights_dir`. Skips already-solved frames
    unless `force`. If RA/Dec hints aren't passed explicitly, reads them
    from `mira_capture.json` — falls back to blind solve when neither is
    available. Parallelizes across `workers` astap_cli invocations."""
    def emit(m: str) -> None:
        if on_step is not None:
            on_step(m)

    lights_dir = Path(lights_dir)
    cli = astap_cli or find_astap_cli()

    if ra_hint_deg is None or dec_hint_deg is None:
        ra_h, dec_h = load_hints_from_sidecar(lights_dir)
        if ra_hint_deg is None:
            ra_hint_deg = ra_h
        if dec_hint_deg is None:
            dec_hint_deg = dec_h

    if ra_hint_deg is None or dec_hint_deg is None:
        emit("no RA/Dec hint available — falling back to blind solve (slow)")
    else:
        emit(f"hint RA={ra_hint_deg:.3f}\xb0 Dec={dec_hint_deg:.3f}\xb0, "
             f"search r={radius_deg}\xb0, FOV={fov_deg}\xb0")

    frames = sorted(p for p in lights_dir.glob("*.fit*") if p.is_file())
    if not frames:
        emit(f"no FITS files in {lights_dir}")
        return SolveRunResult()

    todo: list[Path] = []
    result = SolveRunResult()
    for f in frames:
        if not force and has_wcs(f):
            result.already_solved.append(SolveResult(str(f), "already_solved"))
        else:
            todo.append(f)

    emit(f"{len(frames)} frames: {len(result.already_solved)} already solved, "
         f"{len(todo)} to solve")

    if not todo:
        return result

    def _one(p: Path) -> SolveResult:
        return solve_one(
            p, astap_cli=cli,
            ra_hint_deg=ra_hint_deg, dec_hint_deg=dec_hint_deg,
            fov_deg=fov_deg, radius_deg=radius_deg, timeout_s=timeout_s,
            runner=runner,
        )

    if workers <= 1:
        for i, f in enumerate(todo, 1):
            r = _one(f)
            (result.solved if r.status == "solved" else result.failed).append(r)
            if i == 1 or i % 10 == 0 or r.status == "failed":
                emit(f"  {i}/{len(todo)}: {r.status} {Path(r.path).name}"
                     f"{' — ' + r.note if r.note else ''}")
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(_one, f): f for f in todo}
            i = 0
            for fut in concurrent.futures.as_completed(futures):
                i += 1
                r = fut.result()
                (result.solved if r.status == "solved" else result.failed).append(r)
                if i == 1 or i % 10 == 0 or r.status == "failed":
                    emit(f"  {i}/{len(todo)}: {r.status} "
                         f"{Path(r.path).name}"
                         f"{' — ' + r.note if r.note else ''}")
    return result
