"""Cross-process progress sink for the `mira finish` workflow.

The CLI (`mira finish`) and the webapp run in *separate processes* — they
share no memory. To let the webapp show live phase progress for a finish
run started from either side, both write the same per-run JSON file into a
shared directory; the webapp polls/reads it.

Deliberately Flask-free and dependency-light (json/pathlib/dataclasses/
datetime only) so the CLI can import it without pulling the webapp.

Phase model: `run_finish` calls its `on_step` at the START of each phase.
So we advance lazily — when the next phase starts, the previous one is
marked done; the final phase is closed out by `complete()`. Equal-weight
progress; phases are NOT equal duration (GraXpert steps dominate), so the
fraction is a coarse honest estimate, not a time prediction.
"""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

# Canonical phase ids in pipeline order. "stretch" and "crop" always run;
# the three GraXpert phases are gated by the --no-* flags.
_PHASE_LABELS: dict[str, str] = {
    "background-extraction": "GraXpert background extraction",
    "denoising": "GraXpert AI denoise",
    "deconv-obj": "GraXpert object deconvolution",
    "stretch": "Siril autostretch + saturation",
    "crop": "Edge crop",
}
_GRAXPERT_ORDER = ("background-extraction", "denoising", "deconv-obj")


def phase_label(phase_id: str) -> str:
    return _PHASE_LABELS.get(phase_id, phase_id)


def plan_phases(*, do_bg: bool, do_denoise: bool, do_deconv: bool) -> list[str]:
    """Ordered phase ids for a finish run with the given flags. Mirrors the
    sequence in finishing.run_finish so the UI plan matches reality."""
    phases: list[str] = []
    if do_bg:
        phases.append("background-extraction")
    if do_denoise:
        phases.append("denoising")
    if do_deconv:
        phases.append("deconv-obj")
    phases += ["stretch", "crop"]
    return phases


def default_progress_dir(base: Path | str = "data") -> Path:
    """Shared location both the CLI and the webapp default to."""
    return Path(base) / "finish_progress"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class FinishProgress:
    """Live state of one finish run, serialisable to a shared JSON file."""

    run_id: str
    label: str
    input_path: str
    phase_ids: list[str]
    progress_dir: Path
    status: str = "running"  # running | done | failed
    error: str = ""
    output_path: str = ""
    created_at: str = field(default_factory=_now)
    finished_at: str = ""
    # per-phase: {"id","label","status"(pending|running|done|skipped),"started","ended"}
    phases: list[dict] = field(default_factory=list)
    _cursor: int = -1

    @classmethod
    def create(
        cls,
        *,
        label: str,
        input_path: str,
        phase_ids: list[str],
        progress_dir: Path,
        run_id: str | None = None,
    ) -> "FinishProgress":
        fp = cls(
            run_id=run_id or uuid.uuid4().hex[:12],
            label=label,
            input_path=input_path,
            phase_ids=list(phase_ids),
            progress_dir=Path(progress_dir),
            phases=[
                {"id": pid, "label": phase_label(pid), "status": "pending",
                 "started": "", "ended": ""}
                for pid in phase_ids
            ],
        )
        fp.write()
        return fp

    # --- mutation -----------------------------------------------------

    def _advance(self) -> None:
        """Called at the start of each phase: close the previous running
        phase, open the next pending one."""
        if 0 <= self._cursor < len(self.phases):
            cur = self.phases[self._cursor]
            if cur["status"] == "running":
                cur["status"] = "done"
                cur["ended"] = _now()
        self._cursor += 1
        if 0 <= self._cursor < len(self.phases):
            nxt = self.phases[self._cursor]
            nxt["status"] = "running"
            nxt["started"] = _now()
        self.write()

    def make_on_step(self) -> Callable[[str], None]:
        """An `on_step` callback for finishing.run_finish. Each call marks
        the next phase running (and the prior done). The human message is
        ignored for phase tracking — the plan order is authoritative."""

        def _cb(_message: str) -> None:
            self._advance()

        return _cb

    @property
    def progress(self) -> float:
        if not self.phases:
            return 1.0 if self.status == "done" else 0.0
        done = sum(1 for p in self.phases if p["status"] == "done")
        return done / len(self.phases)

    def complete(self, output_path: str = "") -> None:
        for p in self.phases:
            if p["status"] in ("pending", "running"):
                p["status"] = "done"
                if not p["ended"]:
                    p["ended"] = _now()
        self.status = "done"
        self.output_path = output_path
        self.finished_at = _now()
        self.write()

    def fail(self, error: str) -> None:
        for p in self.phases:
            if p["status"] == "running":
                p["status"] = "failed"
                p["ended"] = _now()
        self.status = "failed"
        self.error = error
        self.finished_at = _now()
        self.write()

    # --- persistence --------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "label": self.label,
            "input_path": self.input_path,
            "status": self.status,
            "error": self.error,
            "output_path": self.output_path,
            "progress": self.progress,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
            "phases": [dict(p) for p in self.phases],
        }

    def write(self) -> None:
        """Atomic write so a polling reader never sees a half-file."""
        self.progress_dir.mkdir(parents=True, exist_ok=True)
        target = self.progress_dir / f"{self.run_id}.json"
        fd, tmp = tempfile.mkstemp(suffix=".json", dir=str(self.progress_dir))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self.to_dict(), fh, indent=2)
            os.replace(tmp, target)
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def load(progress_dir: Path, run_id: str) -> dict | None:
    path = Path(progress_dir) / f"{run_id}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def load_all(progress_dir: Path) -> list[dict]:
    """All finish-run snapshots, newest first. Tolerates partial/garbage
    files (skips them) since writers and readers are different processes."""
    d = Path(progress_dir)
    if not d.is_dir():
        return []
    out: list[dict] = []
    for path in d.glob("*.json"):
        try:
            out.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    out.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return out
