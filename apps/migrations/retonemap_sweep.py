#!/usr/bin/env python3
"""Re-tonemap existing OpticalNav sweep renders in place (no re-render).

The original ``rgb.png`` previews were produced by a per-frame percentile
auto-exposure (divide by the 99.2nd percentile, then hard-clip).  That made
frames with a light source in view too dark (the percentile latched onto the
emitter) and over-amplified dark frames (tiny percentile → big gain → noise),
and left every frame on a different exposure.

Because each frame's HDR ``rgb.exr`` is preserved, we can recompute the PNGs
without re-rendering.  This tool runs a two-pass scene-global pass:

  * pass 1 — sample positive luminance from every frame's EXR and derive one
    global ``(exposure, white)`` via ``compute_global_tone_params``;
  * pass 2 — extended-Reinhard tonemap each EXR with that single exposure and
    overwrite ``rgb.png`` (so the webui preview and downstream pipeline see the
    corrected, mutually-consistent images).

This reads EXRs only (numpy + an EXR backend) — it does NOT need the Mitsuba GPU
runtime.

    python apps/migrations/retonemap_sweep.py --scene indoor_seed2
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
for _module_path in (
    REPO_ROOT / "modules" / "robomituba_bridge" / "src",
    REPO_ROOT / "modules" / "mitsuba_converter" / "src",
):
    if str(_module_path) not in sys.path:
        sys.path.insert(0, str(_module_path))

from mitsuba_converter import (  # noqa: E402
    compute_global_tone_params,
    luminance,
    read_exr_rgb,
    save_rgb_radiance_preview,
)


def _find_rgb_exrs(bridge_dir: Path, scene: str | None, include_probe: bool) -> list[Path]:
    out: list[Path] = []
    for job_dir in sorted(bridge_dir.glob("opticalnav-*")):
        if not job_dir.is_dir():
            continue
        if scene and scene not in job_dir.name:
            continue
        if not include_probe and "probe" in job_dir.name:
            continue
        out.extend(sorted(job_dir.glob("observations/*/cameras/*/rgb.exr")))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scene", default=None, help="substring filter on job dir name (e.g. indoor_seed2)")
    ap.add_argument("--bridge-dir", default=str(REPO_ROOT / "out" / "bridge_jobs"))
    ap.add_argument("--include-probe", action="store_true", help="also retonemap probe_* jobs")
    ap.add_argument("--limit", type=int, default=0, help="process at most N frames (0 = all)")
    ap.add_argument("--exposure", type=float, default=None, help="override global exposure (skip pass 1)")
    ap.add_argument("--white", type=float, default=None, help="override white point (skip pass 1)")
    ap.add_argument("--exposure-percentile", type=float, default=0.90)
    ap.add_argument("--white-percentile", type=float, default=0.999)
    ap.add_argument("--sample-stride", type=int, default=4, help="pass-1 pixel subsample stride")
    ap.add_argument("--dry-run", action="store_true", help="compute params + log, do not overwrite PNGs")
    args = ap.parse_args()

    bridge_dir = Path(args.bridge_dir)
    exrs = _find_rgb_exrs(bridge_dir, args.scene, args.include_probe)
    if args.limit:
        exrs = exrs[: args.limit]
    if not exrs:
        print(f"[retonemap] no rgb.exr found (scene={args.scene!r}, dir={bridge_dir})")
        return 1
    print(f"[retonemap] {len(exrs)} frame(s) matched")

    if args.exposure is not None and args.white is not None:
        tone = {"tone_exposure": float(args.exposure), "tone_white": float(args.white)}
        print(f"[retonemap] using override exposure={tone['tone_exposure']:.4g} white={tone['tone_white']:.4g}")
    else:
        t0 = time.perf_counter()
        samples: list[np.ndarray] = []
        for i, exr in enumerate(exrs):
            try:
                rgb = read_exr_rgb(exr)
            except Exception as exc:  # noqa: BLE001
                print(f"[retonemap] WARN pass1 skip {exr}: {exc}")
                continue
            lum = luminance(rgb)[:: args.sample_stride, :: args.sample_stride].reshape(-1)
            samples.append(lum.astype(np.float32))
            if (i + 1) % 200 == 0:
                print(f"[retonemap] pass1 scanned {i + 1}/{len(exrs)}")
        tone = compute_global_tone_params(
            samples,
            exposure_percentile=args.exposure_percentile,
            white_percentile=args.white_percentile,
        )
        print(
            f"[retonemap] global tone: exposure={tone['tone_exposure']:.4g} "
            f"white={tone['tone_white']:.4g} (pass1 {time.perf_counter() - t0:.1f}s)"
        )

    if args.dry_run:
        print("[retonemap] dry-run: not overwriting PNGs")
        return 0

    t1 = time.perf_counter()
    written = 0
    failed = 0
    for i, exr in enumerate(exrs):
        png = exr.with_name("rgb.png")
        try:
            rgb = read_exr_rgb(exr)
            save_rgb_radiance_preview(
                rgb, png, exposure=tone["tone_exposure"], white=tone["tone_white"]
            )
            written += 1
        except Exception as exc:  # noqa: BLE001
            print(f"[retonemap] WARN pass2 skip {exr}: {exc}")
            failed += 1
        if (i + 1) % 200 == 0:
            print(f"[retonemap] pass2 wrote {written}/{len(exrs)}")
    print(
        f"[retonemap] done: wrote {written}, failed {failed} "
        f"(pass2 {time.perf_counter() - t1:.1f}s)"
    )
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
