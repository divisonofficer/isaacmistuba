#!/usr/bin/env python3
"""Pure-Python tests for the decimation POLICY layer (no bpy required)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mesh_decimation import (  # noqa: E402
    DecimationContext, NoDecimation, RatioThreshold, SemanticContractPolicy,
    resolve_policy, decimate_object)


def ctx(n, **kw):
    return DecimationContext(object_id="o", n_faces=n, **kw)


def test_none_never_decimates():
    d = NoDecimation().decide(ctx(10_000_000))
    assert d.decimate is False and d.target_ratio == 1.0


def test_ratio_threshold_below_min():
    d = RatioThreshold(min_faces=50_000).decide(ctx(40_000))
    assert d.decimate is False


def test_ratio_threshold_above_min():
    d = RatioThreshold(min_faces=50_000, ratio=0.3).decide(ctx(500_000, optical_class="diffuse"))
    assert d.decimate is True and abs(d.target_ratio - 0.3) < 1e-9


def test_optical_is_protected():
    p = RatioThreshold(ratio=0.3, optical_ratio=0.6)
    glass = p.decide(ctx(500_000, optical_class="glass"))
    metal = p.decide(ctx(500_000, optical_class="metal_aluminum"))
    door = p.decide(ctx(500_000, optical_class="diffuse", semantic_type="glass_door"))
    assert glass.target_ratio == 0.6 and metal.target_ratio == 0.6 and door.target_ratio == 0.6


def test_floor_faces_respected():
    # ratio 0.001 would drop 100k -> 100 faces, but floor 2000 lifts it
    p = RatioThreshold(min_faces=1000, ratio=0.001, floor_faces=2000)
    d = p.decide(ctx(100_000))
    assert d.target_ratio >= 2000 / 100_000 - 1e-9


def test_resolve_policy():
    assert resolve_policy("none").name == "none"
    assert resolve_policy("ratio_threshold", ratio=0.1).name == "ratio_threshold"
    try:
        resolve_policy("bogus"); assert False
    except ValueError:
        pass


def test_semantic_is_a_documented_stub():
    try:
        SemanticContractPolicy().decide(ctx(500_000)); assert False
    except NotImplementedError:
        pass


class _FakeMesh:
    def __init__(self, n): self.polygons = list(range(n))


class _FakeObj:
    def __init__(self, n): self.data = _FakeMesh(n)


def test_decimate_object_record_no_bpy():
    # policy=none -> no bpy call, clean record
    rec = decimate_object(_FakeObj(500_000), NoDecimation(), ctx(500_000))
    assert rec["decimated"] is False and rec["faces_before"] == 500_000 and rec["error"] is None


def test_decimate_object_bpy_missing_is_caught():
    # ratio_threshold decides to decimate, apply_decimation imports bpy -> fails,
    # decimate_object must catch and record the error (never abort an import)
    rec = decimate_object(_FakeObj(500_000), RatioThreshold(min_faces=1000, ratio=0.3), ctx(500_000))
    assert rec["decimated"] is False and rec["error"] and rec["faces_after"] == 500_000


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    ok = 0
    for fn in fns:
        try:
            fn(); ok += 1; print(f"  ok  {fn.__name__}")
        except Exception:
            print(f"  XX  {fn.__name__}"); traceback.print_exc()
    print(f"{ok}/{len(fns)} passed")
    raise SystemExit(0 if ok == len(fns) else 1)
