from mitsuba_converter.ir_view_utility import probe_candidates


def _graph():
    return {"nodes": [{"node_id": "vp_0", "position": [2, 2, 0],
                       "headings": [{"yaw_deg": 0}, {"yaw_deg": 180}]}]}


def test_probe_is_deterministic_and_detects_content_direction() -> None:
    authoring = {"regions": [{"geometry": {"bounds": [0, 0, 6, 4]}}],
                 "objects": [{"id": "chair", "type": "landmark",
                              "geometry": {"center": [4, 2], "size_m": [1, 1, 1]},
                              "metadata": {"factory": "OfficeChairFactory", "kind": "furniture"}}]}
    first = probe_candidates(_graph(), authoring, fov_deg=70, ray_count=48)
    assert first == probe_candidates(_graph(), authoring, fov_deg=70, ray_count=48)
    forward = first["candidates"]["vp_0@0.000000"]
    backward = first["candidates"]["vp_0@180.000000"]
    assert forward["visible_object_count"] == 1
    assert forward["nonstructural_fraction"] > backward["nonstructural_fraction"]
    assert backward["utility_class"] in {"sparse_negative", "rejected"}
