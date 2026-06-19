#!/usr/bin/env python3.10
"""Batch re-render OpticalNav grid frames with the channel-split RGB plugin.

The original grid renders used the 3-pass channel-split *fallback* (the
``measured_polarized_rgb`` plugin did not exist), whose compose collapsed every
per-wavelength pass to luminance.  That turned all ordinary (non-measured)
materials grey, so the whole grid is effectively greyscale.  With the new
``measured_polarized_rgb`` BSDF compiled, the RGB pass is a single plugin render
that keeps real colour.  This tool re-renders the affected frames.

Key efficiency point: it renders **in-process** in a single loop so Mitsuba's
resident scene cache survives across frames of the same scene (the slow part is
scene load, ~55 s cold vs ~2 s render).  Ordering by (scene, vp, heading)
maximises cache hits.

Resumable: ``--only-gray`` inspects each frame's existing ``rgb.exr`` and skips
ones that are already colour (R != G != B), so re-running continues where it
left off and never re-does good frames.

Run it with the GPU runtime environment loaded, e.g.::

    export LD_LIBRARY_PATH=/usr/lib/wsl/lib:$LD_LIBRARY_PATH
    source build/mitsuba3-optix7/setpath.sh
    python apps/migrations/rerender_optical_nav_grid.py

By default this targets ``shared_office_floor_001``, skips already-colour
frames, disables CPU fallback, and omits ``rgb_raw.npz`` because the OpticalNav
training/export path uses PNG/JPEG plus manifests.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
for _module_path in (
    REPO_ROOT / "modules" / "robomituba_bridge" / "src",
    REPO_ROOT / "modules" / "mitsuba_converter" / "src",
):
    if str(_module_path) not in sys.path:
        sys.path.insert(0, str(_module_path))

from mitsuba_converter import render_timestep_bundle_split_lighting  # noqa: E402
from robomituba_bridge import render_request_from_payload  # noqa: E402

try:
    import OpenEXR  # noqa: E402
    import Imath  # noqa: E402
except Exception:  # noqa: BLE001
    OpenEXR = None


_VP_RE = re.compile(r"vp_(\d+)")
_H_RE = re.compile(r"h_?(\d+)")


def _sort_key(req_path: Path) -> tuple:
    name = req_path.stem
    vp = _VP_RE.search(name)
    h = _H_RE.search(name)
    return (name.split("vp_")[0], int(vp.group(1)) if vp else -1, int(h.group(1)) if h else -1)


def _find_requests(bridge_dir: Path, scene: str | None, include_probe: bool) -> list[Path]:
    out: list[Path] = []
    for job_dir in sorted(bridge_dir.glob("opticalnav-*")):
        if not job_dir.is_dir():
            continue
        if scene and scene not in job_dir.name:
            continue
        if not include_probe and "probe" in job_dir.name:
            continue
        req_dir = job_dir / "requests"
        if not req_dir.is_dir():
            continue
        out.extend(sorted(req_dir.glob("*.json")))
    out.sort(key=_sort_key)
    return out


def _exr_is_gray(exr_path: Path) -> bool | None:
    """True if R==G==B (or near-black) everywhere; None if unreadable/missing."""
    if OpenEXR is None or not exr_path.is_file():
        return None
    try:
        f = OpenEXR.InputFile(str(exr_path))
        dw = f.header()["dataWindow"]
        w = dw.max.x - dw.min.x + 1
        h = dw.max.y - dw.min.y + 1
        pt = Imath.PixelType(Imath.PixelType.FLOAT)
        ch = {c: np.frombuffer(f.channel(c, pt), np.float32).reshape(h, w) for c in "RGB"}
        f.close()
    except Exception:  # noqa: BLE001
        return None
    R, G, B = ch["R"], ch["G"], ch["B"]
    spread = np.maximum.reduce([np.abs(R - G), np.abs(G - B), np.abs(R - B)])
    mx = np.maximum.reduce([R, G, B])
    colored = (spread > 1e-3 * np.maximum(mx, 1e-4)) & (mx > 1e-4)
    return float(colored.mean()) < 0.02  # <2% colored pixels => treat as gray


def _frame_exr(repo_root: Path, payload: dict) -> Path | None:
    """Locate the current rgb.exr for a request payload, if any."""
    job_id = payload.get("job_id")
    frame_id = payload.get("frame_id")
    specs = payload.get("camera_specs") or []
    if not (job_id and frame_id and specs):
        return None
    cam = specs[0].get("camera_id")
    return (
        repo_root / "out" / "bridge_jobs" / job_id / "observations" / frame_id
        / "cameras" / str(cam) / "rgb.exr"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scene", default="shared_office_floor_001", help="Only re-render jobs whose name contains this string.")
    ap.add_argument("--bridge-jobs-dir", default=str(REPO_ROOT / "out" / "bridge_jobs"))
    ap.add_argument("--variant", default="cuda_ad_spectral", help="Mitsuba variant (default: cuda_ad_spectral, matches original).")
    ap.add_argument("--only-gray", action=argparse.BooleanOptionalAction, default=True, help="Skip frames whose rgb.exr is already colour (resumable).")
    ap.add_argument("--include-probe", action="store_true", help="Also re-render probe_* jobs.")
    ap.add_argument("--limit", type=int, default=0, help="Process only the first N frames (debug).")
    ap.add_argument("--dry-run", action="store_true", help="List what would be rendered and exit.")
    ap.add_argument("--write-raw-npz", action="store_true", help="Also write *_raw.npz files (default: off for OpticalNav RGB rerenders).")
    args = ap.parse_args()

    os.environ.setdefault("ROBOMITUBA_DISABLE_CPU_FALLBACK", "1")

    bridge_dir = Path(args.bridge_jobs_dir).resolve()
    requests = _find_requests(bridge_dir, args.scene, args.include_probe)
    if args.limit:
        requests = requests[: args.limit]
    if not requests:
        print(f"[error] no request JSONs under {bridge_dir} (scene={args.scene!r})", file=sys.stderr)
        return 1

    print(f"[scan] {len(requests)} candidate frames (scene={args.scene!r}, include_probe={args.include_probe})")

    # Pre-filter for --only-gray so we report an accurate work count up-front.
    work: list[tuple[Path, dict]] = []
    skipped_color = 0
    for req in requests:
        try:
            payload = json.loads(req.read_text())
        except json.JSONDecodeError:
            continue
        if args.only_gray:
            exr = _frame_exr(REPO_ROOT, payload)
            if exr is not None:
                gray = _exr_is_gray(exr)
                if gray is False:  # already colour
                    skipped_color += 1
                    continue
        settings = dict(payload.get("render_settings") or {})
        settings["write_raw_npz"] = bool(args.write_raw_npz)
        payload["render_settings"] = settings
        work.append((req, payload))

    print(f"[plan] {len(work)} to render, {skipped_color} skipped (already colour)")
    if args.dry_run:
        for req, _ in work[:20]:
            print("   ", req.relative_to(bridge_dir))
        if len(work) > 20:
            print(f"    ... (+{len(work) - 20} more)")
        return 0

    ok = fail = 0
    t0 = time.time()
    for i, (req, payload) in enumerate(work, 1):
        try:
            render_request = render_request_from_payload(payload)
            t = time.time()
            render_timestep_bundle_split_lighting(
                render_request, repo_root=REPO_ROOT, variant=args.variant
            )
            ok += 1
            dt = time.time() - t
            if i % 10 == 0 or dt > 20:
                elapsed = time.time() - t0
                rate = elapsed / i
                eta = rate * (len(work) - i) / 60.0
                print(f"[{i}/{len(work)}] ok={ok} fail={fail} last={dt:.1f}s avg={rate:.1f}s/frame ETA={eta:.0f}min", flush=True)
        except Exception as exc:  # noqa: BLE001
            fail += 1
            print(f"[warn] {req.name}: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)

    print(f"[done] rendered={ok} failed={fail} in {(time.time()-t0)/60:.1f} min")
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
