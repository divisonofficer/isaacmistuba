#!/usr/bin/env python3
"""Small OptiX-7 / Dr.Jit-freeze isolation gate.

This is intentionally independent of the render daemon.  Run it with the
experimental Mitsuba build on an otherwise idle GPU, one ``--case`` at a time:

    CUDA_VISIBLE_DEVICES=2 PYTHONPATH=<build>/python <python> \
        tools/freeze_isolation_gate.py --case polar_diffuse_closure_constant

Each case is a single process because early historical freeze implementations
can terminate the interpreter while recording.  The parent shell can therefore
classify a crash without risking the production daemon.
"""

from __future__ import annotations

import argparse
import hashlib
import time

import drjit as dr
import mitsuba as mi
import numpy as np


CASES = (
    "rgb_diffuse_closure_constant",
    "rgb_diffuse_explicit_constant",
    "polar_diffuse_closure_constant",
    "polar_diffuse_explicit_constant",
    "polar_dielectric_closure_constant",
    "polar_dielectric_explicit_constant",
    "polar_dielectric_closure_dynamic_seed",
    "polar_dielectric_explicit_dynamic_seed",
    "polar_dielectric_explicit_dynamic_pose",
    "polar_dielectric_explicit_external_pose",
    "polar_pplastic_textured_explicit",
)


def _scene(bsdf: str, roughness_file: str | None = None):
    t = mi.ScalarTransform4f()
    if bsdf == "diffuse":
        material = {"type": "diffuse", "reflectance": 0.5}
    elif bsdf == "pplastic_textured":
        material = {
            "type": "pplastic",
            "diffuse_reflectance": 0.5,
            "alpha": {
                "type": "bitmap",
                "filename": roughness_file,
                "raw": True,
            },
        }
    else:
        material = {"type": "dielectric"}
    return mi.load_dict(
        {
            "type": "scene",
            "integrator": {"type": "path", "max_depth": 3, "rr_depth": 2},
            "sensor": {
                "type": "perspective",
                "fov": 45,
                "film": {
                    "type": "hdrfilm",
                    "width": 32,
                    "height": 32,
                    "rfilter": {"type": "box"},
                },
                "sampler": {"type": "independent", "sample_count": 1},
                "to_world": t.look_at(
                    mi.ScalarPoint3f(0, 0, 3),
                    mi.ScalarPoint3f(0, 0, 0),
                    mi.ScalarVector3f(0, 1, 0),
                ),
            },
            "emitter": {
                "type": "constant",
                "radiance": {"type": "rgb", "value": [0.3, 0.3, 0.3]},
            },
            "object": {"type": "sphere", "radius": 0.75, "bsdf": material},
        }
    )


def _digest(image) -> str:
    dr.eval(image)
    dr.sync_thread()
    return hashlib.sha256(np.asarray(image).tobytes()).hexdigest()[:12]


def run(case: str) -> None:
    polarized = case.startswith("polar_")
    mi.set_log_level(mi.LogLevel.Error)
    mi.set_variant("cuda_ad_rgb_polarized" if polarized else "cuda_ad_rgb")
    bsdf = (
        "pplastic_textured"
        if "pplastic" in case
        else ("dielectric" if "dielectric" in case else "diffuse")
    )
    explicit = "_explicit_" in case
    dynamic_seed = case.endswith("dynamic_seed")
    roughness_a = "/bean/ir_pbr_assets/cc0_structural_v1/polyhaven/concrete_wall_005/roughness.jpg"
    roughness_b = "/bean/ir_pbr_assets/cc0_office_surfaces_v1/ambientcg/ambientcg_carpet_016/roughness.jpg"
    scene = _scene(bsdf, roughness_a if bsdf == "pplastic_textured" else None)

    if case == "polar_pplastic_textured_explicit":
        # PR #1843-specific gate: bitmap alpha must load, evaluate in an
        # unfrozen render, replay as an explicitly traversed Scene, and affect
        # the polarized result when the roughness atlas changes.
        unfrozen = mi.render(scene, spp=1, seed=7)
        unfrozen_hash = _digest(unfrozen)

        @dr.freeze
        def render(scene_arg, seed):
            result = mi.render(scene_arg, spp=1, seed=seed)
            dr.eval(result)
            return result

        frozen_first = render(scene, mi.UInt32(7))
        frozen_second = render(scene, mi.UInt32(7))
        alternate = _scene("pplastic_textured", roughness_b)
        frozen_alternate = render(alternate, mi.UInt32(7))
        hashes = [_digest(frozen_first), _digest(frozen_second), _digest(frozen_alternate)]
        print(
            "FREEZE_GATE_OK",
            f"case={case}",
            f"variant={mi.variant()}",
            f"unfrozen_equals_frozen={unfrozen_hash == hashes[0]}",
            f"warm_equals_first={hashes[0] == hashes[1]}",
            f"roughness_dynamic={hashes[0] != hashes[2]}",
            f"hashes={unfrozen_hash},{','.join(hashes)}",
            f"shape={dr.shape(frozen_first)}",
        )
        return

    if case == "polar_dielectric_explicit_dynamic_pose":
        # This is the production-relevant gate: a single frozen render graph
        # receives a new camera transform instead of baking the first heading
        # into the recorded graph.
        def pose(origin):
            return mi.Transform4f().look_at(
                mi.Point3f(*origin), mi.Point3f(0, 0, 0), mi.Vector3f(0, 1, 0)
            )

        @dr.freeze
        def render(scene_arg, camera_to_world, seed):
            params = mi.traverse(scene_arg)
            params["sensor.to_world"] = camera_to_world
            params.update()
            result = mi.render(scene_arg, spp=1, seed=seed)
            dr.eval(result)
            return result

        first = render(scene, pose((0, 0, 3)), mi.UInt32(7))
        second = render(scene, pose((3, 0, 0)), mi.UInt32(7))
        hashes = [_digest(first), _digest(second)]
        print(
            "FREEZE_GATE_OK",
            f"case={case}",
            f"variant={mi.variant()}",
            "dynamic_seed=False",
            f"hashes={','.join(hashes)}",
            f"pose_dynamic={hashes[0] != hashes[1]}",
            f"shape={dr.shape(first)}",
        )
        return

    if case == "polar_dielectric_explicit_external_pose":
        def pose(origin):
            return mi.ScalarTransform4f().look_at(
                mi.ScalarPoint3f(*origin),
                mi.ScalarPoint3f(0, 0, 0),
                mi.ScalarVector3f(0, 1, 0),
            )

        @dr.freeze
        def render(scene_arg, seed):
            result = mi.render(scene_arg, spp=1, seed=seed)
            dr.eval(result)
            return result

        params = mi.traverse(scene)
        params["sensor.to_world"] = pose((0, 0, 3))
        params.update()
        t0 = time.perf_counter()
        first = render(scene, mi.UInt32(7))
        dr.sync_thread()
        first_s = time.perf_counter() - t0
        params["sensor.to_world"] = pose((3, 0, 0))
        params.update()
        t1 = time.perf_counter()
        second = render(scene, mi.UInt32(7))
        dr.sync_thread()
        second_s = time.perf_counter() - t1
        hashes = [_digest(first), _digest(second)]
        print(
            "FREEZE_GATE_OK",
            f"case={case}",
            f"variant={mi.variant()}",
            "dynamic_seed=False",
            f"hashes={','.join(hashes)}",
            f"pose_dynamic={hashes[0] != hashes[1]}",
            f"first_s={first_s:.4f}",
            f"second_s={second_s:.4f}",
            f"shape={dr.shape(first)}",
        )
        return

    # The dummy CUDA value lets the early freeze frontend infer its backend
    # without making an integer Python seed part of the frozen input layout.
    if explicit:
        if dynamic_seed:
            @dr.freeze
            def render(scene_arg, seed):
                result = mi.render(scene_arg, spp=1, seed=seed)
                dr.eval(result)
                return result

            first = render(scene, mi.UInt32(7))
            second = render(scene, mi.UInt32(11))
        else:
            @dr.freeze
            def render(scene_arg, backend_token):
                result = mi.render(scene_arg, spp=1, seed=7)
                dr.eval(result)
                return result

            token = mi.Float(0)
            first = render(scene, token)
            second = render(scene, token)
    else:
        if dynamic_seed:
            @dr.freeze
            def render(seed):
                result = mi.render(scene, spp=1, seed=seed)
                dr.eval(result)
                return result

            first = render(mi.UInt32(7))
            second = render(mi.UInt32(11))
        else:
            @dr.freeze
            def render(backend_token):
                result = mi.render(scene, spp=1, seed=7)
                dr.eval(result)
                return result

            token = mi.Float(0)
            first = render(token)
            second = render(token)

    hashes = [_digest(first), _digest(second)]
    print(
        "FREEZE_GATE_OK",
        f"case={case}",
        f"variant={mi.variant()}",
        f"dynamic_seed={dynamic_seed}",
        f"hashes={','.join(hashes)}",
        f"shape={dr.shape(first)}",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=CASES, required=True)
    args = parser.parse_args()
    run(args.case)


if __name__ == "__main__":
    main()
