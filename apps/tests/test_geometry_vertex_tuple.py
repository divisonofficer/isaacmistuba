"""The gate must see a mesh rebuilt with the same faces and a different split."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_ir_geometry_profile as B


def _unit(uid, tri_before, tri_after, v_before, v_after):
    return {"id": uid, "slots": [], "material_slots": [],
            "pbr": {"status": "ok", "appearance_authoritative": True},
            "decimation": {"status": "reduced", "decimated": True,
                           "triangles_before": tri_before, "triangles_after": tri_after,
                           "vertices_before": v_before, "vertices_after": v_after,
                           "target_max_triangles": tri_before,
                           "geometry_validation": {"passed": True}}}


def run(units, tmp):
    man = tmp / "scene_manifest.json"
    man.write_text(json.dumps({"units": units}))
    return B._validate_stage1(man, profile="content_aware_v2")


def test_vertex_tuple_gate():
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    # same faces, different vertex split -- invisible to any triangle check
    out = run([_unit("resplit", 97940, 97940, 293820, 290428)], tmp)
    assert out["vertices_before_total"] == 293820, out
    assert out["vertices_after_total"] == 290428, out
    assert out["face_stable_vertex_changed_count"] == 1, out
    flagged = out["face_stable_vertex_changed_units"][0]
    assert flagged["object_id"] == "resplit" and flagged["triangles"] == 97940, flagged
    print("  same faces + changed vertices -> flagged")

    # an ordinary reduction must not be flagged
    out = run([_unit("reduced", 100000, 40000, 60000, 24000)], tmp)
    assert out["face_stable_vertex_changed_count"] == 0, out
    assert out["retained_vertex_ratio"] == 24000 / 60000, out
    print("  ordinary reduction -> not flagged, vertex ratio reported")

    # a record with no vertex counts (pre-change build) must not crash or flag
    u = _unit("legacy", 5000, 5000, 0, 0)
    u["decimation"].pop("vertices_before"); u["decimation"].pop("vertices_after")
    out = run([u], tmp)
    assert out["face_stable_vertex_changed_count"] == 0, out
    assert out["vertices_before_total"] == 0, out
    print("  legacy record without vertex counts -> tolerated")
    print("OK")



if __name__ == "__main__":
    test_vertex_tuple_gate()
