"""Thin client for NINA's Advanced API plugin (ninaAPI).

Route prefix is ``/v2/api`` (NOT ``/api/v2`` — an earlier version of this
file had it backwards, so every call 404'd against a live plugin). Verified
against ninaAPI v2.2.15.x on port 1888.

Mount-control endpoints and their UNITS were taken from the plugin source
(christian-photo/ninaAPI ``Mount.cs`` / ``api_spec.yaml``), not guessed —
moving a physical telescope on a wrong unit assumption is unacceptable:

- ``GET /equipment/mount/slew?ra=&dec=&center=&waitForResult=`` — ra/dec are
  **degrees, J2000** (note: ``mount/info`` *reports* RA in *hours* — the
  asymmetry is real and is exactly why this is centralized here).
- ``GET /equipment/mount/tracking?mode=`` — 0 Sidereal, 1 Lunar, 2 Solar,
  3 King, 4 Stopped.
- ``GET /equipment/mount/unpark`` / ``/equipment/mount/slew/stop``
- ``GET /equipment/mount/info`` — read-back; RA in hours, Dec in degrees.

The exact JSON schema can change between plugin versions. Surface raw
values and failure modes; never assert strict contracts.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import requests

DEFAULT_API_PREFIX = "/v2/api"
# NINA TrackingMode enum (from api_spec.yaml).
TRACKING_SIDEREAL = 0
TRACKING_STOPPED = 4


@dataclass
class NinaStatus:
    reachable: bool
    error: str = ""
    sequence_running: bool = False
    current_target: str = ""
    target_progress: str = ""
    last_image_hfr: float | None = None
    equipment: dict[str, str] = field(default_factory=dict)
    raw_payloads: dict[str, Any] = field(default_factory=dict)


@dataclass
class SlewResult:
    """Outcome of a slew / pre-position. `ok` means the mount reported a
    position within `tolerance_deg` of the request — never inferred from
    the slew call's own 'started' reply, always confirmed by read-back."""
    ok: bool
    message: str
    requested_ra_deg: float
    requested_dec_deg: float
    actual_ra_deg: float | None = None
    actual_dec_deg: float | None = None
    separation_deg: float | None = None
    steps: list[str] = field(default_factory=list)


def angular_separation_deg(
    ra1_deg: float, dec1_deg: float, ra2_deg: float, dec2_deg: float
) -> float:
    """Great-circle separation (haversine). Correct across the RA wrap and
    at high declination, where a naive sqrt(dRA^2+dDec^2) would lie."""
    ra1, dec1, ra2, dec2 = map(math.radians, (ra1_deg, dec1_deg, ra2_deg, dec2_deg))
    d_ra = ra2 - ra1
    d_dec = dec2 - dec1
    a = (
        math.sin(d_dec / 2) ** 2
        + math.cos(dec1) * math.cos(dec2) * math.sin(d_ra / 2) ** 2
    )
    return math.degrees(2 * math.asin(min(1.0, math.sqrt(a))))


class NinaClient:
    def __init__(
        self,
        base_url: str = "http://localhost:1888",
        timeout: float = 3.0,
        api_prefix: str = DEFAULT_API_PREFIX,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.api_prefix = "/" + api_prefix.strip("/")

    # -- low-level ---------------------------------------------------------

    def _get(
        self, path: str, params: dict[str, Any] | None = None, timeout: float | None = None
    ) -> dict[str, Any]:
        response = requests.get(
            f"{self.base_url}{self.api_prefix}{path}",
            params=params,
            timeout=timeout or self.timeout,
        )
        response.raise_for_status()
        return response.json()

    # -- monitoring (consumed by the webapp) ------------------------------

    def status(self) -> NinaStatus:
        """Best-effort health/monitoring snapshot. Reachability is decided
        by /version (always present on a live plugin); everything else is
        opportunistic and degrades to blanks rather than raising."""
        result = NinaStatus(reachable=False)
        try:
            version = self._get("/version")
            result.raw_payloads["version"] = version
            result.reachable = True
        except requests.RequestException as exc:
            result.error = f"NINA API unreachable: {exc}"
            return result
        except ValueError as exc:
            result.error = f"NINA API parse error: {exc}"
            return result

        try:
            seq = self._get("/sequence/state")
            result.raw_payloads["sequence"] = seq
            resp = seq.get("Response")
            running = False
            if isinstance(resp, list):
                running = any(
                    isinstance(c, dict) and str(c.get("Status", "")).upper() == "RUNNING"
                    for c in resp
                )
            result.sequence_running = running
        except (requests.RequestException, ValueError, KeyError, TypeError):
            pass

        for kind, path in (
            ("Camera", "/equipment/camera/info"),
            ("Telescope", "/equipment/mount/info"),
            ("Focuser", "/equipment/focuser/info"),
            ("FilterWheel", "/equipment/filterwheel/info"),
        ):
            try:
                info = self._get(path)
                response = info.get("Response", {}) if isinstance(info, dict) else {}
                connected = response.get("Connected")
                if connected is not None:
                    result.equipment[kind] = "connected" if connected else "disconnected"
            except (requests.RequestException, ValueError, KeyError, TypeError):
                continue

        try:
            image_stats = self._get("/image/history", params={"count": 1})
            result.raw_payloads["image_history"] = image_stats
            resp = image_stats.get("Response")
            entry = resp[-1] if isinstance(resp, list) and resp else {}
            hfr = entry.get("HFR") if isinstance(entry, dict) else None
            if hfr is not None:
                result.last_image_hfr = float(hfr)
        except (requests.RequestException, ValueError, KeyError, TypeError, IndexError):
            pass

        return result

    def push_schedule(self, csv_path: str) -> dict[str, Any]:
        """Best-effort push of a Target Scheduler CSV. Endpoint availability
        varies by plugin version; we report whatever comes back."""
        endpoint = "/sequence/load"
        try:
            response = requests.get(
                f"{self.base_url}{self.api_prefix}{endpoint}",
                params={"path": csv_path},
                timeout=self.timeout,
            )
            try:
                body = response.json()
            except ValueError:
                body = {"text": response.text[:200]}
            return {
                "ok": response.status_code < 400,
                "status_code": response.status_code,
                "message": str(body),
                "endpoint_tried": f"{self.api_prefix}{endpoint}",
            }
        except requests.RequestException as exc:
            return {
                "ok": False,
                "status_code": None,
                "message": f"NINA unreachable: {exc}",
                "endpoint_tried": f"{self.api_prefix}{endpoint}",
            }

    # -- mount control -----------------------------------------------------

    def mount_info(self) -> dict[str, Any]:
        """Raw /equipment/mount/info Response dict. RA is in HOURS here."""
        return self._get("/equipment/mount/info").get("Response", {}) or {}

    def _mount_radec_deg(self) -> tuple[float | None, float | None, bool, bool]:
        info = self.mount_info()
        # A versioned plugin can return "N/A"/null for RA/Dec — never let a
        # non-numeric value raise; that would break preposition()'s
        # abort-safely-no-slew guarantee. (`mount_info` may still raise
        # requests.RequestException / ValueError on transport / non-JSON;
        # preposition handles those.)
        def _f(v: Any) -> float | None:
            try:
                return float(v) if v is not None else None
            except (TypeError, ValueError):
                return None

        ra_h = _f(info.get("RightAscension"))
        dec_deg = _f(info.get("Declination"))
        ra_deg = ra_h * 15.0 if ra_h is not None else None
        return ra_deg, dec_deg, bool(info.get("Connected")), bool(info.get("AtPark"))

    def unpark(self, timeout: float = 30.0) -> dict[str, Any]:
        return self._get("/equipment/mount/unpark", timeout=timeout)

    def set_tracking(self, mode: int = TRACKING_SIDEREAL) -> dict[str, Any]:
        return self._get("/equipment/mount/tracking", params={"mode": mode})

    def stop_slew(self) -> dict[str, Any]:
        return self._get("/equipment/mount/slew/stop")

    def slew(
        self,
        ra_deg: float,
        dec_deg: float,
        *,
        center: bool = True,
        wait: bool = True,
        timeout: float = 180.0,
    ) -> dict[str, Any]:
        """Issue the slew. `ra_deg`/`dec_deg` are J2000 DEGREES (the plugin
        converts via Angle.ByDegree). `center=True` uses NINA's plate-solve
        Center for accuracy; `wait=True` blocks server-side until done, so
        the HTTP timeout must be generous."""
        return self._get(
            "/equipment/mount/slew",
            params={
                "ra": ra_deg,
                "dec": dec_deg,
                "center": str(bool(center)).lower(),
                "waitForResult": str(bool(wait)).lower(),
            },
            timeout=timeout,
        )

    def preposition(
        self,
        ra_deg: float,
        dec_deg: float,
        *,
        center: bool = True,
        set_sidereal: bool = True,
        tolerance_deg: float = 1.0,
        slew_timeout: float = 180.0,
    ) -> SlewResult:
        """Safely pre-position the mount: unpark → slew (plate-solve center)
        → sidereal tracking → **confirm by read-back**. Aborts on the first
        failed step and NEVER retries a slew (a wild mount should stop, not
        be re-flung). `ok` is true only if the mount's reported position is
        within `tolerance_deg` of the request.

        This is not invoked automatically anywhere — moving hardware is an
        explicit, supervised action by the caller.
        """
        out = SlewResult(
            ok=False, message="", requested_ra_deg=ra_deg, requested_dec_deg=dec_deg
        )

        # ValueError covers a non-JSON body from _get(); TypeError guards
        # any remaining bad-shape access. Either way: abort, no slew.
        try:
            ra_now, dec_now, connected, at_park = self._mount_radec_deg()
        except (requests.RequestException, ValueError, TypeError) as exc:
            out.message = f"Mount not reachable / bad reply: {exc}"
            return out
        if not connected:
            out.message = "Mount reports not connected; aborting (no slew issued)."
            return out
        out.steps.append(
            f"pre: connected, at_park={at_park}, "
            f"pos=({ra_now:.3f},{dec_now:.3f})deg" if ra_now is not None else "pre: connected"
        )

        if at_park:
            try:
                self.unpark()
                out.steps.append("unpark: requested")
            except (requests.RequestException, ValueError, TypeError) as exc:
                out.message = f"Unpark failed: {exc}; aborting."
                return out

        try:
            reply = self.slew(
                ra_deg, dec_deg, center=center, wait=True, timeout=slew_timeout
            )
            resp = reply.get("Response", reply) if isinstance(reply, dict) else reply
            out.steps.append(f"slew: {resp}")
        except (requests.RequestException, ValueError, TypeError) as exc:
            out.message = f"Slew request failed: {exc}. Mount state unknown — check NINA."
            return out

        if set_sidereal:
            try:
                self.set_tracking(TRACKING_SIDEREAL)
                out.steps.append("tracking: sidereal requested")
            except (requests.RequestException, ValueError, TypeError) as exc:
                out.steps.append(f"tracking: FAILED ({exc})")

        # The decisive check: where did it actually end up?
        try:
            ra_act, dec_act, _, _ = self._mount_radec_deg()
        except (requests.RequestException, ValueError, TypeError) as exc:
            out.message = f"Slew issued but read-back failed: {exc}. Verify in NINA."
            return out
        out.actual_ra_deg, out.actual_dec_deg = ra_act, dec_act
        if ra_act is None or dec_act is None:
            out.message = "Slew issued but mount did not report a position. Verify in NINA."
            return out

        sep = angular_separation_deg(ra_deg, dec_deg, ra_act, dec_act)
        out.separation_deg = sep
        out.steps.append(f"readback: pos=({ra_act:.3f},{dec_act:.3f})deg sep={sep:.3f}deg")
        if sep <= tolerance_deg:
            out.ok = True
            out.message = f"On target: {sep:.3f}deg from request (<= {tolerance_deg}deg)."
        else:
            out.message = (
                f"Slew reported done but mount is {sep:.3f}deg off "
                f"(> {tolerance_deg}deg). NOT retrying. Check alignment/park "
                "state and inspect the mount before re-issuing."
            )
        return out

    # -- camera / imaging --------------------------------------------------

    def camera_state(self) -> str:
        """Best-effort CameraState ('Idle'|'Exposing'|...). Empty string if
        unreachable / unparseable (callers poll, don't assert)."""
        try:
            info = self._get("/equipment/camera/info").get("Response", {}) or {}
            return str(info.get("CameraState", "")) if isinstance(info, dict) else ""
        except (requests.RequestException, ValueError, TypeError):
            return ""

    def wait_camera_idle(self, timeout_s: float = 60.0, poll_s: float = 1.0) -> bool:
        """Block until the camera reports Idle. True if it did, False on
        timeout. Read errors during polling are swallowed (transient)."""
        import time

        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self.camera_state() == "Idle":
                return True
            time.sleep(poll_s)
        return self.camera_state() == "Idle"

    def capture(
        self,
        *,
        duration: float,
        gain: int | None = None,
        save: bool = True,
        solve: bool = False,
        target_name: str = "",
        timeout_s: float = 120.0,
    ) -> dict[str, Any]:
        """Synchronous single exposure (waitForResult=true). The image bytes
        are omitted (omitImage=true) — callers read frame stats via
        image-history, not the response. Lets _get exceptions propagate;
        the caller (e.g. tuning.run_tune) records per-frame failure."""
        params: dict[str, Any] = {
            "duration": duration,
            "save": str(bool(save)).lower(),
            "solve": str(bool(solve)).lower(),
            "waitForResult": "true",
            "omitImage": "true",
        }
        if gain is not None:
            params["gain"] = int(gain)
        if target_name:
            params["targetName"] = target_name
        return self._get("/equipment/camera/capture", params=params, timeout=timeout_s)

    def image_history(self, all_images: bool = True) -> list[dict[str, Any]]:
        """The plugin's image-history list (Stars/HFR/Max/Mean/Median/
        ExposureTime/Gain/Filename per frame). Empty list on any error —
        callers degrade gracefully rather than crash a tuning run."""
        try:
            resp = self._get(
                "/image-history", params={"all": str(bool(all_images)).lower()}
            ).get("Response")
            return [e for e in resp if isinstance(e, dict)] if isinstance(resp, list) else []
        except (requests.RequestException, ValueError, TypeError):
            return []

    def latest_image_stats(self) -> dict[str, Any] | None:
        """Stats for the most recent frame, or None if history is empty."""
        hist = self.image_history()
        return hist[-1] if hist else None

    # -- focuser / autofocus ----------------------------------------------

    def run_autofocus(
        self,
        *,
        timeout_s: float = 600.0,
        poll_s: float = 5.0,
        min_wait_s: float = 20.0,
    ) -> dict[str, Any]:
        """Trigger NINA's autofocus run and block until it finishes.

        `/equipment/focuser/auto-focus` is fire-and-forget (the plugin returns
        "Autofocus started" immediately and the run happens on a background
        task). We detect completion by polling `/equipment/focuser/last-af`
        and watching for a report file newer than the one that existed before
        we started. Returns that fresh report. Raises TimeoutError if AF
        hasn't completed within `timeout_s`. `min_wait_s` is a floor (AF
        always takes at least ~20s; polling sooner just wastes calls)."""
        import time

        def _last_af_signature() -> Any:
            try:
                rep = self._get("/equipment/focuser/last-af", timeout=10.0).get("Response")
                if isinstance(rep, dict):
                    return rep.get("Timestamp") or rep.get("Time") or rep.get("Date") or rep
                return rep
            except (requests.RequestException, ValueError, TypeError):
                return None

        baseline = _last_af_signature()
        self._get("/equipment/focuser/auto-focus", timeout=30.0)
        time.sleep(min_wait_s)
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            cur = _last_af_signature()
            if cur is not None and cur != baseline:
                return self._get("/equipment/focuser/last-af", timeout=10.0)
            time.sleep(poll_s)
        raise TimeoutError(f"autofocus did not complete within {timeout_s:.0f}s")

    # -- filter wheel ------------------------------------------------------

    def filter_wheel_info(self) -> dict[str, Any]:
        """Raw FilterWheel `Response` (Connected/IsMoving/SelectedFilter/
        AvailableFilters), or {} if unreachable/absent."""
        try:
            info = self._get("/equipment/filterwheel/info")
            resp = info.get("Response", {}) if isinstance(info, dict) else {}
            return resp if isinstance(resp, dict) else {}
        except (requests.RequestException, ValueError, TypeError):
            return {}

    def available_filters(self) -> list[dict[str, Any]]:
        """[{'Name':..,'Id':..}, ...] in wheel order, or [] if no wheel."""
        fs = self.filter_wheel_info().get("AvailableFilters")
        return [f for f in fs if isinstance(f, dict)] if isinstance(fs, list) else []

    def current_filter(self) -> dict[str, Any] | None:
        """The SelectedFilter dict ({'Name','Id'}), or None."""
        sel = self.filter_wheel_info().get("SelectedFilter")
        return sel if isinstance(sel, dict) else None

    def set_filter(
        self, filter_ref: str | int, *, wait: bool = True, timeout_s: float = 60.0
    ) -> bool:
        """Move the wheel to `filter_ref` (a filter Name or Id). Resolves the
        name against AvailableFilters, issues change-filter, then (if `wait`)
        polls until IsMoving is false AND SelectedFilter matches. Returns
        True on confirmed move, False otherwise. Never raises — a wheel that
        won't move must not crash an unattended flat run."""
        import time

        filters = self.available_filters()
        target = None
        for f in filters:
            if str(filter_ref) in (str(f.get("Id")), str(f.get("Name"))):
                target = f
                break
        if target is None:
            return False
        fid = target.get("Id")
        try:
            self._get(
                "/equipment/filterwheel/change-filter",
                params={"filterId": fid},
                timeout=timeout_s,
            )
        except (requests.RequestException, ValueError, TypeError):
            return False
        if not wait:
            return True
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            info = self.filter_wheel_info()
            sel = info.get("SelectedFilter") or {}
            if not info.get("IsMoving", False) and str(sel.get("Id")) == str(fid):
                return True
            time.sleep(0.5)
        sel = (self.filter_wheel_info().get("SelectedFilter") or {})
        return str(sel.get("Id")) == str(fid)
