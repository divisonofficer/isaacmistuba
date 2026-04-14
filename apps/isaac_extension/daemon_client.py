"""Robomituba Isaac Extension — daemon HTTP client."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# Allow importing from the apps directory when running inside Isaac Sim
_APPS_DIR = Path(__file__).resolve().parent.parent
if str(_APPS_DIR) not in sys.path:
    sys.path.insert(0, str(_APPS_DIR))

from isaac_capture_current_view_request import _http_json  # noqa: E402


def _snapshot_payload(snapshot: Any) -> dict[str, Any]:
    from robomituba_bridge import isaac_state_snapshot_to_payload

    return {"isaac_state": isaac_state_snapshot_to_payload(snapshot)}


def submit_isaac_state_render(
    snapshot: Any,
    daemon_url: str,
    *,
    timeout_s: float = 120.0,
    variant: str | None = None,
) -> dict[str, Any]:
    """POST /isaac/render and wait for completion."""
    payload = _snapshot_payload(snapshot)
    payload["timeout_s"] = timeout_s
    if variant:
        payload["variant"] = variant
    url = f"{daemon_url.rstrip('/')}/isaac/render"
    return _http_json("POST", url, payload, timeout_s=timeout_s + 10.0)


def enqueue_isaac_state_render(
    snapshot: Any,
    daemon_url: str,
    *,
    timeout_s: float = 10.0,
    variant: str | None = None,
) -> dict[str, Any]:
    """POST /isaac/render/submit and return a queued job envelope."""
    payload = _snapshot_payload(snapshot)
    if variant:
        payload["variant"] = variant
    url = f"{daemon_url.rstrip('/')}/isaac/render/submit"
    return _http_json("POST", url, payload, timeout_s=timeout_s)


def get_render_job_status(job_id: str, *, daemon_url: str, timeout_s: float = 10.0) -> dict[str, Any]:
    return _http_json("GET", f"{daemon_url.rstrip('/')}/jobs/{job_id}", timeout_s=timeout_s)


def wait_for_render_job(
    job_id: str,
    *,
    daemon_url: str,
    poll_interval_s: float = 1.0,
    timeout_s: float = 600.0,
) -> dict[str, Any]:
    import time

    deadline = time.monotonic() + timeout_s
    last_status: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        last_status = get_render_job_status(job_id, daemon_url=daemon_url, timeout_s=min(10.0, poll_interval_s + 5.0))
        if last_status.get("status") in {"succeeded", "failed", "cancelled"}:
            return last_status
        time.sleep(poll_interval_s)
    raise TimeoutError(f"Timed out waiting for render job {job_id}. Last status: {last_status}")
