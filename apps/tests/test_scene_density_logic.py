"""Density is the scene; visibility is the pose set; unmeasured is not sparse."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# import the statistics module by path: importing the package pulls in usd
# loading, which needs bpy and robomituba_bridge and has nothing to do with
# classifying a room.
import importlib.util
_spec = importlib.util.spec_from_file_location(
    "_ir_scene_statistics",
    Path(__file__).resolve().parents[2]
    / "modules/mitsuba_converter/src/mitsuba_converter/ir_scene_statistics.py")
_stats = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(_stats)
_classify, _visibility_class = _stats._classify, _stats._visibility_class
import review_ir_scene_quality as R


def test_a_wide_pose_sweep_does_not_make_a_furnished_room_sparse():
    # the closet: 42 objects in 2.45 m2, poses that mostly face walls
    assert _classify(17.16, 1.2) == ("dense", "objects_per_m2")
    # the same scene rendered with few poses and with many must agree
    assert _classify(8.09, 6.0)[0] == _classify(8.09, 1.5)[0] == "dense"


def test_visibility_is_reported_separately():
    assert _visibility_class(1.2) == "narrow"
    assert _visibility_class(3.0) == "mixed"
    assert _visibility_class(9.0) == "wide"
    assert _visibility_class(None) == "unknown"


def test_visibility_carries_the_class_when_there_is_no_footprint():
    assert _classify(None, 9.0) == ("dense", "visible_median_fallback")
    assert _classify(None, 1.0) == ("sparse", "visible_median_fallback")
    assert _classify(None, None) == ("unknown", "no_measurement")


def _dataset(tmp, *, poses, paired):
    d = tmp / "ds"; (d).mkdir(parents=True, exist_ok=True)
    (d / "dataset_config.json").write_text(json.dumps({"dataset_fingerprint": "fp0"}))
    rows = []
    for i in range(poses):
        lights = ["a", "b"] if i < paired else ["a"]
        for light in lights:
            rows.append({"viewpoint_id": f"v{i}", "heading_deg": 0.0,
                         "lighting": {"id": light, "anchor_id": "anch"}})
    (d / "index.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return d


def test_unmeasured_is_tier_D_but_never_a_deprecation_candidate(tmp_path, monkeypatch):
    d = _dataset(tmp_path, poses=80, paired=20)
    monkeypatch.setattr(R, "stats_for", lambda fp, ds, root: {})       # no statistics at all
    out = R.review(d, None, {})
    assert out["review_tier"] == "D"
    assert out["deprecation_candidate"] is False
    assert out["density_measured"] is False
    assert any("NOT MEASURED" in line for line in out["rationale"])


def test_a_measured_sparse_scene_still_deprecates(tmp_path, monkeypatch):
    d = _dataset(tmp_path, poses=80, paired=0)
    monkeypatch.setattr(R, "stats_for", lambda fp, ds, root: {"density_class": "sparse"})
    out = R.review(d, None, {})
    assert out["review_tier"] == "D"
    assert out["deprecation_candidate"] is True
    assert out["density_measured"] is True


def test_dense_and_paired_is_tier_A(tmp_path, monkeypatch):
    d = _dataset(tmp_path, poses=80, paired=40)
    monkeypatch.setattr(R, "stats_for", lambda fp, ds, root: {"density_class": "dense"})
    out = R.review(d, None, {})
    assert out["review_tier"] == "A" and out["deprecation_candidate"] is False


def test_generation_path_lifts_a_tier_and_never_lowers_one(tmp_path, monkeypatch):
    d = _dataset(tmp_path, poses=80, paired=4)          # paired ratio 0.05, below the Tier A bar
    monkeypatch.setattr(R, "stats_for", lambda fp, ds, root: {
        "density_class": "dense", "placement_profile": "upstream_residential_v1"})
    out = R.review(d, None, {})
    assert out["review_tier"] == "A" and out["generation_path"] == "native"

    # the same dataset from a constrained profile stays where it was
    monkeypatch.setattr(R, "stats_for", lambda fp, ds, root: {
        "density_class": "dense", "placement_profile": "legacy_clutter_v1"})
    assert R.review(d, None, {})["review_tier"] == "B"

    # and an unrecorded provenance is not a penalty
    monkeypatch.setattr(R, "stats_for", lambda fp, ds, root: {"density_class": "dense"})
    out = R.review(d, None, {})
    assert out["review_tier"] == "B" and out["generation_path"] == "unrecorded"


def test_native_floor_plan_counts_even_without_a_placement_profile(tmp_path, monkeypatch):
    d = _dataset(tmp_path, poses=60, paired=3)
    monkeypatch.setattr(R, "stats_for", lambda fp, ds, root: {
        "density_class": "dense", "floor_plan_mode": "native_solver"})
    out = R.review(d, None, {})
    assert out["generation_path"] == "native" and out["review_tier"] == "A"


def test_native_cannot_rescue_a_sparse_scene(tmp_path, monkeypatch):
    d = _dataset(tmp_path, poses=80, paired=0)
    monkeypatch.setattr(R, "stats_for", lambda fp, ds, root: {
        "density_class": "sparse", "placement_profile": "upstream_residential_v1"})
    out = R.review(d, None, {})
    assert out["review_tier"] == "D" and out["deprecation_candidate"] is True
