"""Thin client for NINA's Advanced API plugin.

The Advanced API plugin exposes REST endpoints under a configurable base
URL (default http://localhost:1888). This module wraps a few endpoints
we care about for live monitoring. Failures are returned as structured
status dicts so the UI can render "NINA not connected" gracefully.

Plugin docs: https://github.com/christian-photo/ninaAPI

The exact JSON schema can change between plugin versions. Treat the
parsed shapes as best-effort; surface raw values and failure modes
instead of asserting strict contracts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import requests


@dataclass
class NinaStatus:
    reachable: bool
    error: str = ""
    sequence_running: bool = False
    current_target: str = ""
    target_progress: str = ""  # e.g. "23/60 frames"
    last_image_hfr: float | None = None
    equipment: dict[str, str] = field(default_factory=dict)  # camera/mount/focuser → "connected"/"not connected"
    raw_payloads: dict[str, Any] = field(default_factory=dict)  # for debugging


class NinaClient:
    def __init__(self, base_url: str = "http://localhost:1888", timeout: float = 3.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def status(self) -> NinaStatus:
        result = NinaStatus(reachable=False)
        try:
            sequence = self._get("/api/v2/sequence")
            result.raw_payloads["sequence"] = sequence
            running = bool(sequence.get("Response", {}).get("IsRunning", False))
            result.sequence_running = running
            current_target = sequence.get("Response", {}).get("CurrentTarget") or {}
            result.current_target = str(current_target.get("Name", "") or "")
            done = current_target.get("ExposuresDone")
            total = current_target.get("ExposuresTotal")
            if done is not None and total is not None:
                result.target_progress = f"{done}/{total} frames"
            result.reachable = True
        except requests.RequestException as exc:
            result.error = f"Sequence endpoint unreachable: {exc}"
            return result
        except (ValueError, KeyError) as exc:
            result.error = f"Sequence endpoint parse error: {exc}"

        try:
            equipment = self._get("/api/v2/equipment")
            result.raw_payloads["equipment"] = equipment
            response = equipment.get("Response", {}) if isinstance(equipment, dict) else {}
            for kind in ("Camera", "Telescope", "Focuser", "FilterWheel", "Rotator", "Guider", "Dome"):
                info = response.get(kind) or {}
                connected = info.get("Connected")
                if connected is None:
                    continue
                result.equipment[kind] = "connected" if connected else "disconnected"
        except (requests.RequestException, ValueError, KeyError):
            pass  # equipment is best-effort

        try:
            image_stats = self._get("/api/v2/image/last")
            result.raw_payloads["image_last"] = image_stats
            stats = image_stats.get("Response", {}).get("ImageStatistics") or {}
            hfr = stats.get("HFR")
            if hfr is not None:
                result.last_image_hfr = float(hfr)
        except (requests.RequestException, ValueError, KeyError, TypeError):
            pass  # last-image is best-effort

        return result

    def _get(self, path: str) -> dict[str, Any]:
        response = requests.get(f"{self.base_url}{path}", timeout=self.timeout)
        response.raise_for_status()
        return response.json()
