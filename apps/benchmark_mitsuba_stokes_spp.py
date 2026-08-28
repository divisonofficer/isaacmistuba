"""Direct, synchronized Mitsuba Stokes SPP scaling probe (no OpticalNav wrapper).

The probe deliberately separates throughput measurements (the same seed for
each repetition) from Monte-Carlo variance measurements (multiple seeds).  It
therefore catches three otherwise easy-to-confuse cases: an ignored SPP,
an effective sample cap, and a large compile/launch cost that dominates a
small sampling cost.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
for _path in (REPO_ROOT / "modules" / "mitsuba_converter" / "src", REPO_ROOT / "modules" / "robomituba_bridge" / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--spps", default="1,64,512,1024")
    parser.add_argument("--seed", type=int, default=17011)
    parser.add_argument("--repeats", type=int, default=1,
                        help="Synchronized same-seed samples per SPP after one warm-up")
    parser.add_argument("--variance-spps", default="",
                        help="Comma-separated SPPs for multi-seed Stokes variance")
    parser.add_argument("--variance-seeds", type=int, default=0,
                        help="Number of distinct seeds for each --variance-spps entry")
    parser.add_argument("--kernel-history", action="store_true",
                        help="Emit Dr.Jit kernel-history summaries for timed calls")
    parser.add_argument("--mitsuba-info", action="store_true",
                        help="Emit Mitsuba's native 'Starting render job' effective-SPP log")
    parser.add_argument("--disable-vcall-loop-recording", action="store_true",
                        help="A/B native Dr.Jit VCallRecord+LoopRecord flags (diagnostic only)")
    parser.add_argument("--sampler-controlled", action="store_true", help="Set the supplied sensor sampler and pass spp=0")
    parser.add_argument("--integrator-render", action="store_true", help="Call scene.integrator().render instead of mi.render")
    parser.add_argument("--scene-sampler-controlled", action="store_true", help="Set scene sensor sampler and pass spp=0")
    args = parser.parse_args()

    import drjit as dr
    import mitsuba as mi
    mi.set_variant("cuda_ad_rgb_polarized")
    if args.mitsuba_info:
        mi.set_log_level(mi.LogLevel.Info)
    if args.disable_vcall_loop_recording:
        dr.set_flag(dr.JitFlag.VCallRecord, False)
        dr.set_flag(dr.JitFlag.LoopRecord, False)
    from mitsuba_converter.multimodal import camera_to_world_to_lookat

    payload = json.loads(args.manifest.read_text(encoding="utf-8"))
    camera = next(item for item in payload["camera_specs"] if item.get("camera_id") == "polar_cam")
    c2w = np.asarray(camera["camera_to_world"], dtype=np.float64).reshape(4, 4)
    origin, target, up = camera_to_world_to_lookat(c2w)
    scene = mi.load_file(str(payload["artifacts"][0]["scene_ref"]))
    sensor = mi.load_dict({
        "type": "perspective", "fov": float(camera["fov_deg"]),
        "to_world": mi.ScalarTransform4f.look_at(origin=list(origin), target=list(target), up=list(up)),
        "film": {"type": "hdrfilm", "width": 512, "height": 512},
        "sampler": {"type": "independent", "sample_count": 1},
    })
    def _optional_int(obj: object, name: str) -> int | None:
        try:
            value = getattr(obj, name)()
            return int(value)
        except Exception:
            return None

    print(json.dumps({
        "probe": "prepared_config",
        "variant": mi.variant(),
        "resolution": [512, 512],
        "external_sensor_sampler_spp": _optional_int(sensor.sampler(), "sample_count"),
        "external_sensor_samples_per_wavefront": _optional_int(sensor.sampler(), "samples_per_wavefront"),
        "scene_sensor_sampler_spp": _optional_int(scene.sensors()[0].sampler(), "sample_count"),
        "scene_sensor_samples_per_wavefront": _optional_int(scene.sensors()[0].sampler(), "samples_per_wavefront"),
        "integrator": str(scene.integrator()),
        "vcall_record": bool(dr.flag(dr.JitFlag.VCallRecord)),
        "loop_record": bool(dr.flag(dr.JitFlag.LoopRecord)),
    }), flush=True)

    # Materialize once so loading/JIT startup cannot enter any measured interval.
    renderer = scene.integrator().render if args.integrator_render else mi.render
    warm = renderer(scene, sensor=sensor, spp=1, seed=args.seed)
    dr.eval(warm); dr.sync_thread()
    samples: dict[int, np.ndarray] = {}
    if args.repeats < 1:
        parser.error("--repeats must be >= 1")
    if args.variance_seeds < 0:
        parser.error("--variance-seeds must be >= 0")

    def _history_summary() -> dict[str, object] | None:
        if not args.kernel_history:
            return None
        try:
            history = dr.kernel_history()
            return {
                "kernel_count": len(history),
                "kernels": [
                    {
                        key: (entry[key] if isinstance(entry[key], (str, int, float, bool, type(None))) else str(entry[key]))
                        for key in ("type", "size", "backend", "execution_time", "jit_time")
                        if key in entry
                    }
                    for entry in history
                ],
            }
        except Exception as exc:
            return {"kernel_history_error": str(exc)}

    for raw in str(args.spps).split(","):
        spp = int(raw.strip())
        if args.sampler_controlled:
            sensor.sampler().set_sample_count(spp)
        if args.scene_sampler_controlled:
            scene.sensors()[0].sampler().set_sample_count(spp)
        controlled = args.sampler_controlled or args.scene_sampler_controlled
        # The Stokes wrapper is a native C++ SamplingIntegrator, not the
        # Python ADIntegrator class exposing ``prepare``. Its own INFO log is
        # authoritative (``--mitsuba-info``); this derived value is the
        # expected one from that implementation: one wavefront per pass.
        # The scene has no samples_per_pass property, so requested spp is the
        # native effective spp for this probe.
        prepared: dict[str, object] = {
            "expected_effective_spp": spp if not controlled else 0,
            "expected_wavefront_size": int(512 * 512 * spp),
        }
        # Warm every SPP separately. This leaves the timed samples representative
        # of the resident-worker steady state while preserving an optional kernel
        # history for a later cold-vs-warm diagnostic.
        warm = renderer(scene, sensor=sensor, spp=0 if controlled else spp, seed=args.seed)
        dr.eval(warm); dr.sync_thread()
        for repetition in range(args.repeats):
            dr.sync_thread()
            began = time.perf_counter()
            if args.kernel_history:
                dr.set_flag(dr.JitFlag.KernelHistory, True)
            image = renderer(scene, sensor=sensor, spp=0 if controlled else spp, seed=args.seed)
            dr.eval(image); dr.sync_thread()
            elapsed = time.perf_counter() - began
            history = _history_summary()
            if args.kernel_history:
                dr.set_flag(dr.JitFlag.KernelHistory, False)
            array = np.asarray(image, dtype=np.float32)
            samples[spp] = array
            record: dict[str, object] = {
                "probe": "throughput", "spp": spp, "repetition": repetition + 1,
                "render_sync_s": elapsed, "sampler_controlled": args.sampler_controlled,
                "scene_sampler_controlled": args.scene_sampler_controlled,
                "integrator_render": args.integrator_render, "shape": list(array.shape),
                "sha256": hashlib.sha256(array.tobytes()).hexdigest(),
                **prepared,
            }
            if history is not None:
                record["kernel_history"] = history
            print(json.dumps(record), flush=True)
    reference_spp = min(samples)
    reference = samples[reference_spp].astype(np.float64)
    for spp, array in samples.items():
        if spp == reference_spp:
            continue
        delta = reference - array.astype(np.float64)
        print(json.dumps({"comparison": f"{reference_spp}-{spp}", "exact_equal": bool(np.array_equal(reference, array)), "max_abs": float(np.max(np.abs(delta))), "rmse": float(np.sqrt(np.mean(delta * delta)))}), flush=True)

    variance_spps = [int(item.strip()) for item in args.variance_spps.split(",") if item.strip()]
    if variance_spps and args.variance_seeds < 2:
        parser.error("--variance-spps requires --variance-seeds >= 2")
    for spp in variance_spps:
        # Welford's online estimator keeps RAM bounded to two Stokes tensors.
        mean: np.ndarray | None = None
        m2: np.ndarray | None = None
        for sample_index in range(args.variance_seeds):
            seed = args.seed + 10_000 + sample_index
            image = renderer(scene, sensor=sensor, spp=spp, seed=seed)
            dr.eval(image); dr.sync_thread()
            array = np.asarray(image, dtype=np.float64)
            if mean is None:
                mean = array
                m2 = np.zeros_like(array)
            else:
                delta = array - mean
                mean += delta / float(sample_index + 1)
                m2 += delta * (array - mean)
        assert mean is not None and m2 is not None
        # Report RGB Stokes separately; the first three image channels are the
        # RGB preview carrier and must not dilute the physical S0--S3 result.
        variance = m2 / float(args.variance_seeds - 1)
        channels = {"s0": variance[..., 3:6], "s1": variance[..., 6:9],
                    "s2": variance[..., 9:12], "s3": variance[..., 12:15]}
        print(json.dumps({
            "probe": "seed_variance", "spp": spp, "seeds": args.variance_seeds,
            "mean_variance": {name: float(np.mean(value)) for name, value in channels.items()},
            "median_variance": {name: float(np.median(value)) for name, value in channels.items()},
        }), flush=True)


if __name__ == "__main__":
    main()
