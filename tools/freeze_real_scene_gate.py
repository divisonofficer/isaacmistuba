#!/usr/bin/env python3
"""Long-running scene-scale gate for the OptiX-7 freeze experiment.

This is deliberately an experimental, standalone process. Run it only against
the separate experimental build and an idle GPU; it never communicates with the
render daemon or writes an observation.
"""

from __future__ import annotations

import argparse
import hashlib
import resource
import time

import drjit as dr
import mitsuba as mi
import numpy as np


def digest(image) -> str:
    dr.eval(image)
    dr.sync_thread()
    return hashlib.sha256(np.asarray(image).tobytes()).hexdigest()[:12]


def rss_mib() -> float:
    # Linux reports ru_maxrss in KiB.
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def pose(index: int) -> mi.ScalarTransform4f:
    """Twenty valid looking-at poses around a central office location."""
    angle = index * (360.0 / 20.0)
    return mi.ScalarTransform4f().look_at(
        mi.ScalarPoint3f(13.0, 10.0, 1.5),
        mi.ScalarPoint3f(13.0 + float(np.cos(np.deg2rad(angle))),
                          10.0 + float(np.sin(np.deg2rad(angle)),), 1.5),
        mi.ScalarVector3f(0, 0, 1),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", required=True)
    parser.add_argument("--poses", type=int, default=20)
    parser.add_argument("--spp", type=int, default=1)
    args = parser.parse_args()

    mi.set_log_level(mi.LogLevel.Error)
    mi.set_variant("cuda_ad_rgb_polarized")

    t = time.perf_counter()
    scene = mi.load_file(args.scene)
    dr.sync_thread()
    print(f"FREEZE_REAL_LOAD_OK seconds={time.perf_counter() - t:.3f} rss_mib={rss_mib():.1f}", flush=True)

    params = mi.traverse(scene)
    keys = [key for key in params.keys() if key.endswith(".to_world") and "Camera" in key]
    if len(keys) != 1:
        raise RuntimeError(f"expected exactly one camera transform, got {keys}")
    camera_key = keys[0]

    @dr.freeze
    def render(scene_arg, seed):
        image = mi.render(scene_arg, spp=args.spp, seed=seed)
        dr.eval(image)
        return image

    # First call is the only allowed record/compile. Camera mutation is outside
    # the frozen function because the historical implementation cannot record
    # params.update() while traversing an evaluated transform.
    params[camera_key] = pose(0)
    params.update()
    record_start = time.perf_counter()
    image = render(scene, mi.UInt32(7))
    first_hash = digest(image)
    record_s = time.perf_counter() - record_start
    print(
        f"FREEZE_REAL_RECORD_OK seconds={record_s:.3f} rss_mib={rss_mib():.1f} hash={first_hash}",
        flush=True,
    )

    warm_s: list[float] = []
    hashes: list[str] = [first_hash]
    for index in range(1, args.poses):
        params[camera_key] = pose(index)
        params.update()
        start = time.perf_counter()
        image = render(scene, mi.UInt32(7 + index))
        hashes.append(digest(image))
        warm_s.append(time.perf_counter() - start)
        print(
            f"FREEZE_REAL_REPLAY pose={index} seconds={warm_s[-1]:.3f} rss_mib={rss_mib():.1f} hash={hashes[-1]}",
            flush=True,
        )

    median = float(np.median(np.asarray(warm_s))) if warm_s else 0.0
    print(
        "FREEZE_REAL_GATE_OK "
        f"poses={args.poses} spp={args.spp} record_s={record_s:.3f} warm_median_s={median:.3f} "
        f"distinct_hashes={len(set(hashes))} rss_mib={rss_mib():.1f}",
        flush=True,
    )


if __name__ == "__main__":
    main()
