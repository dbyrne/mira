"""Post-stack finishing: turn a linear stacked master into a presentable
image, reproducibly.

Pipeline (the recipe validated on-sky 2026-05-17/18, M51):
  GraXpert background-extraction -> denoising -> deconv-obj   (linear)
  -> Siril autostretch -linked + saturation                  (-> nonlinear)
  -> edge crop (trim under-sampled stack borders)

GraXpert is an **optional** dependency. It is deliberately NOT in the core
install: it pins numpy<2.3 and pulls heavy ML deps, so forcing it on every
Mira user would be hostile. Install with `pip install 'mira[finishing]'`
or point $MIRA_GRAXPERT at it. Without GraXpert, `--no-bg --no-denoise
--no-deconv` still works (Siril stretch + crop only).

Script generation / arg construction is pure (unit-tested); the GraXpert
and Siril runners are subprocess wrappers (mocked in tests).
"""
from __future__ import annotations

import importlib.util
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .siril import SirilError, _q, run_siril

_ENV_OVERRIDE = "MIRA_GRAXPERT"
_GX_COMMANDS = ("background-extraction", "denoising", "deconv-obj", "deconv-stellar")


class GraXpertNotFound(RuntimeError):
    """GraXpert could not be located."""


class GraXpertError(RuntimeError):
    """GraXpert ran but failed or produced no output."""


@dataclass
class FinishResult:
    output_path: Path
    preview_path: Path | None
    steps: list[str] = field(default_factory=list)
    log_tail: str = ""


def find_graxpert(override: str | None = None) -> list[str]:
    """Return the argv prefix that invokes GraXpert.

    Priority: explicit `override` / $MIRA_GRAXPERT (an executable path OR a
    shell-style string like 'python -m graxpert.main'), then a `graxpert`
    console script on PATH, then `<python> -m graxpert.main` if the package
    is importable. Raises GraXpertNotFound with an actionable message.
    """
    cand = override or os.environ.get(_ENV_OVERRIDE)
    if cand:
        # A real executable path wins even if it contains spaces
        # (e.g. C:\Program Files\GraXpert\graxpert.exe) — check that
        # BEFORE splitting, or a normal Windows install path gets
        # shredded into bogus tokens. Only fall back to shlex.split for
        # the genuine multi-token form ('python -m graxpert.main').
        if Path(cand).is_file() or shutil.which(cand):
            return [cand]
        parts = shlex.split(cand)
        if len(parts) > 1:
            return parts  # trust the user's command form
        raise GraXpertNotFound(
            f"{_ENV_OVERRIDE}={cand!r} is not an executable on disk or PATH "
            "and is not a multi-token command."
        )
    exe = shutil.which("graxpert") or shutil.which("graxpert.exe")
    if exe:
        return [exe]
    if importlib.util.find_spec("graxpert") is not None:
        return [sys.executable, "-m", "graxpert.main"]
    raise GraXpertNotFound(
        "GraXpert not found. Install it with `pip install 'mira[finishing]'` "
        "(note: graxpert pins numpy<2.3 and is heavy), or set "
        f"{_ENV_OVERRIDE} to its executable or to 'python -m graxpert.main'. "
        "Or skip the AI steps: --no-bg --no-denoise --no-deconv."
    )


def build_graxpert_args(
    invocation: list[str],
    command: str,
    in_path: Path,
    out_stem: Path,
    *,
    gpu: bool = False,
) -> list[str]:
    """argv for one GraXpert step. `out_stem` has no extension — GraXpert
    appends `.fits`. `-cli` forces headless (no GUI window)."""
    if command not in _GX_COMMANDS:
        raise ValueError(f"unknown GraXpert command {command!r}; expected {_GX_COMMANDS}")
    return [
        *invocation,
        "-cmd", command,
        str(in_path),
        "-output", str(out_stem),
        "-gpu", "true" if gpu else "false",
        "-cli",
    ]


def run_graxpert_step(
    invocation: list[str],
    command: str,
    in_path: Path,
    out_stem: Path,
    *,
    gpu: bool = False,
    timeout_s: float = 2400.0,
) -> Path:
    """Run one GraXpert step; return the produced `<out_stem>.fits`.
    Raises GraXpertError on non-zero exit, timeout, or missing output."""
    args = build_graxpert_args(invocation, command, in_path, out_stem, gpu=gpu)
    try:
        proc = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout_s, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise GraXpertError(
            f"GraXpert {command} timed out after {timeout_s:.0f}s "
            "(first run also downloads AI models; raise timeout or pre-warm)."
        ) from exc
    log = (proc.stdout or "") + (proc.stderr or "")
    produced = Path(str(out_stem) + ".fits")
    if proc.returncode != 0 or not produced.exists():
        tail = "\n".join(log.strip().splitlines()[-15:])
        raise GraXpertError(
            f"GraXpert {command} failed (exit {proc.returncode}; expected "
            f"{produced.name}).\n--- log tail ---\n{tail}"
        )
    return produced


def autocrop_box(
    image: np.ndarray, *, max_frac: float = 0.16, drop_below: float = 0.80
) -> tuple[int, int, int, int]:
    """(left, top, right, bottom) trimming under-sampled stack borders.

    Edges whose row/column median luminance falls below
    `drop_below`×(central median) are trimmed, but never more than
    `max_frac` of a dimension per side. Deterministic — unit-tested.
    Honest limit: a gentle/coloured border can sit above the threshold and
    survive; the CLI exposes a fixed-margin override for that case.
    """
    if image.ndim == 2:
        lum = image
    elif image.shape[-1] in (3, 4):
        lum = image[..., :3].mean(axis=-1)
    else:  # channel-first
        lum = image.mean(axis=0)
    lum = np.asarray(lum, dtype=float)
    h, w = lum.shape
    ref = float(np.median(lum[int(h * 0.35):int(h * 0.65), int(w * 0.35):int(w * 0.65)]))
    thr = drop_below * ref
    rm = np.median(lum, axis=1)
    cm = np.median(lum, axis=0)

    def _first(v: np.ndarray) -> int:
        i = 0
        while i < len(v) and v[i] < thr:
            i += 1
        return i

    def _last(v: np.ndarray) -> int:
        i = len(v) - 1
        while i >= 0 and v[i] < thr:
            i -= 1
        return i + 1

    top = min(_first(rm), int(max_frac * h))
    bot = max(_last(rm), int((1.0 - max_frac) * h))
    left = min(_first(cm), int(max_frac * w))
    right = max(_last(cm), int((1.0 - max_frac) * w))
    if right <= left:
        left, right = 0, w
    if bot <= top:
        top, bot = 0, h
    return left, top, right, bot


def fixed_margin_box(image: np.ndarray, frac: float) -> tuple[int, int, int, int]:
    """Symmetric crop removing `frac` of each side (0.0–0.45)."""
    frac = max(0.0, min(0.45, frac))
    if image.ndim == 2:
        h, w = image.shape
    elif image.shape[-1] in (3, 4):
        h, w = image.shape[:2]
    else:
        h, w = image.shape[1], image.shape[2]
    return int(w * frac), int(h * frac), int(w * (1 - frac)), int(h * (1 - frac))


def build_stretch_script(
    out_dir: Path, in_path: Path, out_stem: str, *, saturation: float
) -> str:
    """Siril script: load the (GraXpert-processed) linear image, linked
    autostretch, optional saturation, save 16-bit TIFF + PNG as bare
    `out_stem` in `out_dir`. `cd` is explicit because siril-cli ignores the
    process cwd; bare save stems because Siril's save* append the extension
    and don't strip quotes from option args (positional paths are fine)."""
    lines = [
        "requires 1.2.0",
        f"cd {_q(out_dir)}",
        f"load {_q(in_path)}",
        "autostretch -linked",
    ]
    if saturation and saturation > 0:
        lines.append(f"satu {saturation:.2f}")
    lines.append(f"savetif {_q(Path(out_stem))} -deflate")
    lines.append(f"savepng {_q(Path(out_stem))}")
    lines.append("close")
    return "\n".join(lines) + "\n"


def run_finish(
    input_path: Path,
    out_path: Path,
    *,
    do_bg: bool = True,
    do_denoise: bool = True,
    do_deconv: bool = True,
    saturation: float = 0.20,
    crop: str = "auto",
    gpu: bool = False,
    graxpert_path: str | None = None,
    graxpert_timeout_s: float = 2400.0,
    siril_cli_path: Path | None = None,
    on_step=None,
) -> FinishResult:
    """GraXpert (bg→denoise→deconv, each optional) → Siril stretch+satu →
    crop. `crop` is "auto", "none", or a float string/number = fixed
    per-side fraction. Returns FinishResult; writes `out_path` (by its
    extension) plus a sibling `.png`/`.tif`.

    Raises GraXpertNotFound only if an AI step is requested but GraXpert is
    absent — the Siril-only path (`--no-*`) needs no GraXpert.
    """
    from PIL import Image  # local: keep CLI startup light

    input_path = Path(input_path).resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"input not found: {input_path}")
    out_path = Path(out_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    def _emit(msg: str) -> None:
        if on_step is not None:
            on_step(msg)

    steps: list[str] = []
    work = Path(tempfile.mkdtemp(prefix="mira_finish_"))
    try:
        current = input_path
        wanted = [
            (flag, cmd, tag)
            for flag, cmd, tag in (
                (do_bg, "background-extraction", "bg"),
                (do_denoise, "denoising", "dn"),
                (do_deconv, "deconv-obj", "dc"),
            )
            if flag
        ]
        if wanted:
            invocation = find_graxpert(graxpert_path)
            for _flag, cmd, tag in wanted:
                _emit(f"GraXpert {cmd} (slow; first run downloads models)…")
                current = run_graxpert_step(
                    invocation, cmd, current, work / f"gx_{tag}",
                    gpu=gpu, timeout_s=graxpert_timeout_s,
                )
                steps.append(f"graxpert:{cmd}")

        _emit("Siril autostretch -linked + saturation…")
        script = build_stretch_script(work, current, "stretched", saturation=saturation)
        log = run_siril(script, work_dir=work, cli_path=siril_cli_path)
        steps.append("siril:autostretch-linked")
        if saturation and saturation > 0:
            steps.append(f"siril:satu={saturation:.2f}")
        stretched = work / "stretched.png"
        stretched_tif = work / "stretched.tif"
        if not stretched.exists():
            raise SirilError(
                "Siril stretch produced no PNG.\n"
                + "\n".join(log.strip().splitlines()[-12:])
            )

        _emit("cropping stack-edge borders…")
        png = Image.open(stretched).convert("RGB")
        arr = np.asarray(png)
        if crop == "none":
            box = (0, 0, png.width, png.height)
        elif crop == "auto":
            box = autocrop_box(arr)
        else:
            box = fixed_margin_box(arr, float(crop))
        steps.append(f"crop:{box}")

        png_out = out_path if out_path.suffix.lower() == ".png" else out_path.with_suffix(".png")
        tif_out = out_path if out_path.suffix.lower() in (".tif", ".tiff") else out_path.with_suffix(".tif")
        png.crop(box).save(png_out)
        if stretched_tif.exists():
            Image.open(stretched_tif).crop(box).save(tif_out)
        preview = png_out

        return FinishResult(
            output_path=tif_out if tif_out.exists() else png_out,
            preview_path=preview,
            steps=steps,
            log_tail="\n".join(log.strip().splitlines()[-8:]),
        )
    finally:
        shutil.rmtree(work, ignore_errors=True)
