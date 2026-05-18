"""Headless Siril driver.

Siril is the *imaging* (pretty-picture) and optional *calibration* backend.
It is deliberately isolated from the core package: nothing in the
photometry / queue path imports this except the opt-in
`--siril-calibrate` pre-step in `mira submit`. Stacking destroys per-frame
time resolution, so it must never sit on the photometry path implicitly.

Everything here shells out to `siril-cli` with a generated `.ssf` script.
Script *generation* is pure (testable without Siril); the *runner* is a
thin subprocess wrapper (mockable in tests).

Verified against Siril 1.4.3 command syntax.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

# Where siril-cli typically lands on Windows when not on PATH. The env var
# wins so a user with a portable install can point at it explicitly.
_ENV_OVERRIDE = "MIRA_SIRIL_CLI"
_WINDOWS_GUESSES = (
    r"C:\Program Files\Siril\bin\siril-cli.exe",
    r"C:\Program Files (x86)\Siril\bin\siril-cli.exe",
)

# Source extensions Siril reads that are already de-Bayered / not CFA, so
# passing -debayer would be wrong. Everything else (raw, FITS-CFA, SER) is
# assumed OSC and debayered by default for the imaging path.
_NON_CFA_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"}
_SIRIL_READABLE = _NON_CFA_EXTS | {
    ".fit", ".fits", ".fts", ".cr2", ".cr3", ".nef", ".arw",
    ".dng", ".raw", ".xisf", ".ser",
}


class SirilNotFound(RuntimeError):
    """siril-cli could not be located."""


class SirilError(RuntimeError):
    """siril-cli ran but exited non-zero or the expected output is missing."""


@dataclass
class SirilResult:
    output_path: Path
    preview_path: Path | None
    n_input_frames: int
    log_tail: str


def find_siril_cli() -> Path:
    """Locate siril-cli: $MIRA_SIRIL_CLI, then PATH, then known Windows
    install dirs. Raises SirilNotFound with an actionable message."""
    override = os.environ.get(_ENV_OVERRIDE)
    if override:
        p = Path(override)
        if p.is_file():
            return p
        raise SirilNotFound(
            f"{_ENV_OVERRIDE}={override} is set but is not a file."
        )
    for name in ("siril-cli", "siril-cli.exe"):
        found = shutil.which(name)
        if found:
            return Path(found)
    for guess in _WINDOWS_GUESSES:
        p = Path(guess)
        if p.is_file():
            return p
    raise SirilNotFound(
        "siril-cli not found. Install Siril (https://siril.org), then "
        f"either add its bin/ to PATH or set {_ENV_OVERRIDE} to the "
        "full path of siril-cli.exe."
    )


def discover_frames(directory: Path) -> list[Path]:
    """Siril-readable frames in `directory` (non-recursive), sorted. Sort
    order is the capture order for the imaging path and irrelevant for
    calibration (calibrate is per-frame), so a plain name sort is fine."""
    if not directory.is_dir():
        raise SirilError(f"Not a directory: {directory}")
    frames = sorted(
        p for p in directory.iterdir()
        if p.is_file() and p.suffix.lower() in _SIRIL_READABLE
    )
    return frames


def _q(path: Path) -> str:
    """Quote a path for a Siril *positional* path arg (cd, load, save*).
    Siril strips the quotes for these; forward slashes so Windows
    backslashes aren't read as escapes.

    A `"` or newline in the path would break the generated script or inject
    extra Siril commands. Inputs are local CLI args from a trusting single
    user, but reject these explicitly rather than emit a corrupt script."""
    s = str(path).replace("\\", "/")
    if '"' in s or "\n" in s or "\r" in s:
        raise SirilError(
            f"Path contains a quote or newline, unsafe for a Siril script: {path!r}"
        )
    return '"' + s + '"'


def _outarg(path: Path) -> str:
    """Path for a Siril `-out=` option. Unlike positional args, Siril does
    NOT strip quotes here — a quoted value becomes a literal directory name
    with quotes in it. So this is bare + forward-slashed. Siril `-out=`
    paths must not contain spaces; the work dir is a tempfile path (normally
    space-free), and run_siril fails early with an actionable message if the
    chosen temp location does contain a space."""
    return str(path).replace("\\", "/")


def _should_debayer(frames: list[Path], debayer: bool | None) -> bool:
    if debayer is not None:
        return debayer
    # Auto: if every frame is an already-color format, don't debayer;
    # otherwise assume OSC CFA data.
    return not all(f.suffix.lower() in _NON_CFA_EXTS for f in frames)


def build_stack_script(
    *,
    work_dir: Path,
    lights_dir: Path,
    result_stem: Path,
    preview_path: Path | None,
    darks_dir: Path | None = None,
    flats_dir: Path | None = None,
    biases_dir: Path | None = None,
    debayer: bool,
    stretch: bool,
) -> str:
    """Generate the imaging .ssf script: convert -> (build & apply masters)
    -> register -> rejection stack -> save linear result (+ optional
    stretched preview). `result_stem` is a path without extension; Siril
    appends the FITS extension, and we savetif/savepng alongside it.

    Master frames: bias is stacked nonorm; flats are bias-calibrated then
    stacked with multiplicative norm; darks are stacked nonorm. Lights are
    calibrated with whatever masters were supplied (-cc=dark cosmetic
    correction only when a dark is present).
    """
    lines = [
        "requires 1.2.0",
        "setext fit",
    ]

    def convert(name: str, src: Path, extra: str = "") -> None:
        # Individual-file sequence (NOT -fitseq). -fitseq transcodes into a
        # single container and mangles NINA 16-bit-unsigned FITS ("bitpix
        # set as 20" / numerical-overflow on read). Per-frame conversion
        # writes light_NNNNN.fit + a `<name>_.seq` index; Siril resolves the
        # short name (`register light`, `stack r_light`) to it. The earlier
        # "no .seq without -fitseq" was the m3 dir's mixed-size JPG/PNG
        # contamination erroring convert, not a real need for -fitseq.
        lines.append(f"cd {_q(src)}")
        lines.append(f"convert {name} {extra}-out={_outarg(work_dir)}".rstrip())
        lines.append(f"cd {_q(work_dir)}")

    light_master = ""

    if biases_dir is not None:
        convert("bias", biases_dir)
        lines.append("stack bias rej 3 3 -nonorm -out=bias_stacked")
    if flats_dir is not None:
        convert("flat", flats_dir)
        if biases_dir is not None:
            lines.append("calibrate flat -bias=bias_stacked")
            lines.append("stack pp_flat rej 3 3 -norm=mul -out=pp_flat_stacked")
            light_master += " -flat=pp_flat_stacked"
        else:
            lines.append("stack flat rej 3 3 -norm=mul -out=flat_stacked")
            light_master += " -flat=flat_stacked"
    if darks_dir is not None:
        convert("dark", darks_dir)
        lines.append("stack dark rej 3 3 -nonorm -out=dark_stacked")
        light_master += " -dark=dark_stacked -cc=dark"
    if biases_dir is not None and darks_dir is None:
        light_master += " -bias=bias_stacked"

    # Lights. Convert exactly ONCE: a second `convert` into the same
    # sequence name corrupts the FITSEQ (Siril reports a bitpix mismatch /
    # "numerical overflow" on read). With masters, `calibrate` does the
    # debayering; with no masters, debayer at convert time instead.
    if light_master:
        convert("light", lights_dir)
        cfa = " -cfa -equalize_cfa" if debayer else ""
        deb = " -debayer" if debayer else ""
        lines.append(f"calibrate light{light_master}{cfa}{deb}")
        reg_seq = "pp_light"
    else:
        convert("light", lights_dir, extra="-debayer " if debayer else "")
        reg_seq = "light"

    lines.append(f"register {reg_seq}")
    # Stack into a bare work-dir name (cwd is work_dir): -out= can't carry a
    # quoted/space-bearing path. Then load it and save to the real (possibly
    # space-bearing) destination via quoted positional args.
    lines.append(
        f"stack r_{reg_seq} rej 3 3 -norm=addscale -output_norm -out=result"
    )
    lines.append("load result")
    lines.append(f"cd {_q(result_stem.parent)}")
    # save* take a STEM — Siril appends the extension (passing "x.tif"
    # yields "x.tif.tif"). cwd is the destination dir, so bare names land
    # the files exactly at result_stem.with_suffix(...). Linear 32-bit TIFF
    # is the science-faithful artifact; the PNG is a stretched preview only.
    lines.append(f"savetif32 {_q(Path(result_stem.name))} -astro")
    if preview_path is not None:
        if stretch:
            lines.append("autostretch")
        lines.append(f"savepng {_q(Path(preview_path.with_suffix('').name))}")
    lines.append("close")
    return "\n".join(lines) + "\n"


def build_calibrate_script(
    *,
    work_dir: Path,
    lights_dir: Path,
    out_prefix: str,
    darks_dir: Path | None = None,
    flats_dir: Path | None = None,
    biases_dir: Path | None = None,
) -> str:
    """Generate the calibrate-ONLY .ssf for the photometry pre-step.

    Deliberately omits register, stack, AND debayer: photometry needs the
    individual frames with their original geometry and per-frame timestamps
    intact. Output is the sequence `{out_prefix}light_NNNNN.fit` in
    work_dir. Whether Siril preserves the NINA WCS without flipping the
    image is verified by the caller, not assumed here.
    """
    lines = ["requires 1.2.0", "setext fit"]

    def convert(name: str, src: Path) -> None:
        # Individual-file sequence, NOT -fitseq: the same NINA 16-bit-unsigned
        # FITS corruption that broke the stack path ("bitpix set as 20" /
        # numerical overflow) applies here too. `convert` writes
        # <name>_NNNNN.fit + <name>_.seq; `calibrate <name>` resolves the
        # short name and (without -fitseq) emits per-frame pp_<name>_NNNNN.fit,
        # which is what photometry needs (individual frames, not a cube).
        lines.append(f"cd {_q(src)}")
        lines.append(f"convert {name} -out={_outarg(work_dir)}")
        lines.append(f"cd {_q(work_dir)}")

    master = ""
    if biases_dir is not None:
        convert("bias", biases_dir)
        lines.append("stack bias rej 3 3 -nonorm -out=bias_stacked")
    if flats_dir is not None:
        convert("flat", flats_dir)
        if biases_dir is not None:
            lines.append("calibrate flat -bias=bias_stacked")
            lines.append("stack pp_flat rej 3 3 -norm=mul -out=pp_flat_stacked")
            master += " -flat=pp_flat_stacked"
        else:
            lines.append("stack flat rej 3 3 -norm=mul -out=flat_stacked")
            master += " -flat=flat_stacked"
    if darks_dir is not None:
        convert("dark", darks_dir)
        lines.append("stack dark rej 3 3 -nonorm -out=dark_stacked")
        master += " -dark=dark_stacked -cc=dark"
    if biases_dir is not None and darks_dir is None:
        master += " -bias=bias_stacked"

    convert("light", lights_dir)
    lines.append(f"calibrate light{master} -prefix={out_prefix}")
    lines.append("close")
    return "\n".join(lines) + "\n"


def run_siril(
    script: str,
    *,
    work_dir: Path,
    timeout_s: float = 1800.0,
    cli_path: Path | None = None,
) -> str:
    """Write `script` to a temp .ssf, run siril-cli headless, return the
    captured log. Raises SirilError on non-zero exit (with the log tail).

    siril-cli writes progress to stdout prefixed with `log:`; on error it
    still exits non-zero, so the exit code is the source of truth.
    """
    cli = cli_path or find_siril_cli()
    # Siril `-out=` can't carry a space (see _outarg). The work dir comes
    # from tempfile, which honors $TMP/$TEMP — fail early and actionably if
    # that resolves somewhere with a space, instead of a cryptic mid-script
    # SirilError.
    if " " in str(work_dir):
        raise SirilError(
            f"Work directory contains a space ({work_dir}); Siril `-out=` "
            "cannot handle it. Set TMP/TEMP to a space-free path and retry."
        )
    work_dir.mkdir(parents=True, exist_ok=True)
    fd, script_path = tempfile.mkstemp(suffix=".ssf", dir=str(work_dir))
    try:
        with os.fdopen(fd, "w", encoding="ascii", newline="\n") as fh:
            fh.write(script)
        try:
            proc = subprocess.run(
                [str(cli), "-s", script_path],
                capture_output=True,
                text=True,
                timeout=timeout_s,
                cwd=str(work_dir),
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise SirilError(
                f"Siril timed out after {timeout_s:.0f}s. Large sequences "
                "can exceed this; raise timeout_s or reduce the frame count."
            ) from exc
        log = (proc.stdout or "") + (proc.stderr or "")
        if proc.returncode != 0:
            tail = "\n".join(log.strip().splitlines()[-25:])
            raise SirilError(
                f"siril-cli exited {proc.returncode}.\n--- last lines ---\n{tail}"
            )
        return log
    finally:
        try:
            os.unlink(script_path)
        except OSError:
            pass
