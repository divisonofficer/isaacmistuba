#!/usr/bin/env python3
"""Pure-Python tests for the decimation POLICY layer (no bpy required)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mesh_decimation import (  # noqa: E402
    DecimationContext, IRSemanticLodPolicy, NoDecimation, RatioThreshold, SemanticContractPolicy,
    resolve_policy, decimate_object, map_material_slot_indices)


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


def test_material_slot_mapping_accepts_blender_suffix_family_shift():
    source = ["shader_hair_shader", "shader_hair_shader.001", "shader_hair_shader.002",
              "shader_hair_shader.003", "shader_hair_shader.004"]
    imported = ["shader_hair_shader.005", "shader_hair_shader.006", "shader_hair_shader.007",
                "shader_hair_shader.008", "shader_hair_shader.009"]
    assert map_material_slot_indices(source, imported) == {index: index for index in range(5)}


def test_material_slot_mapping_rejects_ambiguous_reordering():
    try:
        map_material_slot_indices(["hair", "hair.001"], ["hair.003", "other.004"])
    except ValueError as exc:
        assert "unambiguously" in str(exc)
    else:
        raise AssertionError("changed repeated material family must be rejected")


def test_material_slot_mapping_allows_only_a_source_subset_when_requested():
    assert map_material_slot_indices(["used", "unused"], ["used"], allow_source_subset=True) == {0: 0}


def _mslots(*pairs):
    return [{"name": n, "optical_class": oc} for n, oc in pairs]


def test_semantic_below_min_faces_keeps_full():
    d = SemanticContractPolicy(min_faces=50_000).decide(ctx(40_000, semantic_type="plant"))
    assert d.decimate is False and d.target_ratio == 1.0


def test_semantic_foliage_background_is_aggressive():
    # cactus/dirt in a container, background decoration -> organic_mass, deep cut
    d = SemanticContractPolicy().decide(ctx(
        2_000_000, factory="PlantContainerFactory", semantic_type="plant",
        optical_class="diffuse",
        material_slots=_mslots(("cactus", "diffuse"), ("dirt", "diffuse")),
        bbox_max=(0.4, 0.4, 0.4)))
    assert d.decimate is True and d.target_ratio <= 0.10


def test_semantic_structural_landmark_is_protected():
    # cabinet is a structural landmark -> rigid_planar + landmark step -> keep full
    d = SemanticContractPolicy().decide(ctx(
        500_000, factory="SingleCabinetFactory", semantic_type="wall",
        optical_class="diffuse", material_slots=_mslots(("wood", "diffuse")),
        bbox_max=(1.2, 1.2, 1.2)))
    assert d.target_ratio >= 0.5


def test_semantic_navcritical_glass_floor():
    # navigation-critical glass door: optical slot floored >= 30%
    d = SemanticContractPolicy().decide(ctx(
        900_000, factory="DoorFactory", semantic_type="glass_door",
        optical_class="glass", material_slots=_mslots(("glass", "glass")),
        bbox_max=(2.0, 2.0, 0.1)))
    assert d.target_ratio >= 0.30


def test_semantic_import_failure_degrades_to_keep():
    p = SemanticContractPolicy()
    p._engine = None
    # force the lazy import to fail by pointing at a bogus attr path
    import mesh_decimation as _md
    orig = p._load
    p._load = lambda: (_ for _ in ()).throw(ImportError("boom"))
    d = p.decide(ctx(2_000_000, semantic_type="plant"))
    p._load = orig
    assert d.decimate is False and d.target_ratio == 1.0


class _FakeMesh:
    def __init__(self, n): self.polygons = list(range(n))


class _FakeObj:
    def __init__(self, n): self.data = _FakeMesh(n)

def test_ir_semantic_lod_ladder_never_exceeds_thirty_percent():
    policy = IRSemanticLodPolicy(min_faces=50_000)
    assert policy.decide(ctx(49_999)).target_ratio == 1.0
    assert policy.decide(ctx(100_000)).target_ratio == 0.30
    assert policy.decide(ctx(300_000)).target_ratio == 0.10
    assert policy.decide(ctx(1_500_000)).target_ratio == 0.03
    assert policy.decide(ctx(6_000_000)).target_ratio == 0.01



def test_decimate_object_record_no_bpy():
    # policy=none -> no bpy call, clean record
    rec = decimate_object(_FakeObj(500_000), NoDecimation(), ctx(500_000))
    assert rec["decimated"] is False and rec["faces_before"] == 500_000 and rec["error"] is None


def test_decimate_object_bpy_missing_is_caught():
    # ratio_threshold decides to decimate, apply_decimation imports bpy -> fails,
    # decimate_object must catch and record the error (never abort an import)
    rec = decimate_object(_FakeObj(500_000), RatioThreshold(min_faces=1000, ratio=0.3), ctx(500_000))
    assert rec["decimated"] is False and rec["error"] and rec["faces_after"] == 500_000

def test_strict_decimation_rejects_no_effect(monkeypatch=None):
    import mesh_decimation as module
    original = module.apply_decimation
    module.apply_decimation = lambda obj, decision: len(obj.data.polygons)
    try:
        try:
            decimate_object(_FakeObj(500_000), RatioThreshold(min_faces=1_000, ratio=0.3), ctx(500_000), strict=True)
        except RuntimeError as exc:
            assert "no_effect" in str(exc)
        else:
            raise AssertionError("strict no-effect decimation must fail")
    finally:
        module.apply_decimation = original


def test_strict_decimation_tolerates_empty_gltf_fallback(monkeypatch=None):
    import mesh_decimation as module
    original = module.apply_decimation
    module.apply_decimation = lambda obj, decision: len(obj.data.polygons)
    try:
        def empty_gltf(_obj, _target):
            raise RuntimeError("gltfpack import expected one mesh object, got 0")
        rec = decimate_object(
            _FakeObj(500_000), RatioThreshold(min_faces=1_000, ratio=0.3),
            ctx(500_000), strict=True, fallback=empty_gltf,
        )
        assert rec["status"] == "kept_fallback_unavailable"
        assert rec["decimated"] is False
        assert rec["fallback"]["status"] == "unavailable_empty_import"
        assert rec["error"] is None
    finally:
        module.apply_decimation = original



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


class _Poly:
    def __init__(self, slot): self.material_index = slot


class _SlotMesh:
    def __init__(self, slots): self.polygons = [_Poly(s) for s in slots]
    def copy(self): return _SlotMesh([p.material_index for p in self.polygons])


class _SlotObj:
    def __init__(self, slots, size):
        self.data, self.dimensions = _SlotMesh(slots), size


def _decimate_losing_slot_1(allow: float, size):
    """A 140k-face shelf figurine whose decimation keeps only slot 0 (slot 1 had a few faces)."""
    import mesh_decimation as module
    original = module.apply_decimation

    def collapse(obj, decision):
        obj.data = _SlotMesh([0] * 4_000)
        return 4_000
    module.apply_decimation = collapse
    try:
        obj = _SlotObj([0] * 139_000 + [1] * 1_000, size)
        return obj, decimate_object(obj, RatioThreshold(min_faces=1_000, ratio=0.03), ctx(140_000),
                                    allow_slot_loss_max_extent=allow)
    finally:
        module.apply_decimation = original


def test_small_object_keeps_decimated_mesh_when_slot_loss_is_allowed():
    obj, rec = _decimate_losing_slot_1(0.5, (0.13, 0.03, 0.07))
    assert rec["status"] == "reduced_material_slots_lost" and rec["decimated"] is True
    assert rec["lost_material_slots"] == [1] and rec["material_slot_loss_allowed"] is True
    assert rec["triangles_after"] == 4_000 and len(obj.data.polygons) == 4_000


def test_slot_loss_still_restores_by_default_and_for_large_objects():
    for allow, size in ((0.0, (0.13, 0.03, 0.07)), (0.5, (1.2, 0.8, 0.9))):
        obj, rec = _decimate_losing_slot_1(allow, size)
        assert rec["status"] == "kept_source_material_slots_lost" and rec["decimated"] is False
        assert len(obj.data.polygons) == 140_000 and rec["material_slot_loss_allowed"] is False
