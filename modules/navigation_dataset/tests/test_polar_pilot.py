from navigation_dataset.exporters.compact_bundle import build_polar_observation_triad_index
from navigation_dataset.polar_pilot import (
    build_pilot_contract,
    score_preview,
    select_pilot_views,
    with_polar_pilot_variant,
)


def _graph():
    nodes = []
    for index in range(12):
        nodes.append({
            "node_id": f"vp_{index:03d}", "position": [float(index), 0.0, 0.0],
            "headings": [{"heading_id": "h_000", "yaw_deg": 0}, {"heading_id": "h_090", "yaw_deg": 90}],
        })
    return {
        "scene_id": "infinigen_apartment_20260811", "nodes": nodes,
        "edges": [{"source": f"vp_{index:03d}", "target": f"vp_{index + 1:03d}"} for index in range(11)],
    }


def test_pilot_selection_is_deterministic_and_has_one_heading_per_node():
    scores = {(f"vp_{index:03d}", "h_090"): 1.0 for index in range(12)}
    first = select_pilot_views(_graph(), count=10, seed=20260811, heading_scores=scores)
    assert first == select_pilot_views(_graph(), count=10, seed=20260811, heading_scores=scores)
    assert len(first) == 10
    assert len({row["node_id"] for row in first}) == 10
    assert {row["heading_id"] for row in first} == {"h_090"}
    contract = build_pilot_contract(scene_id="infinigen_apartment_20260811", graph_revision="r1", views=first)
    assert contract["expected_capture_count"] == 30
    assert contract["active_polar_assist_light"]["polarized"] is True
    assert contract["active_polar_assist_light"]["polarizer_angle_deg"] == 0.0


def test_triad_index_requires_all_three_variants():
    paths = [
        "scenes/room/observations/vp_001/h_000/sensors/polar/stokes_core_v1.npz",
        "scenes/room/observations_perturbed/vp_001/h_000/sensors/polar/stokes_core_v1.npz",
        "scenes/room/observations_perturbed_active_polar/vp_001/h_000/sensors/polar/stokes_core_v1.npz",
        "scenes/room/observations/vp_002/h_000/sensors/polar/stokes_core_v1.npz",
    ]
    index = build_polar_observation_triad_index(paths)
    assert index["triad_count"] == 1
    assert index["triads"][0]["vp_id"] == "vp_001"
    assert index["incomplete"]["base"] == [{"scene_id": "room", "vp_id": "vp_002", "heading_id": "h_000"}]


def test_preview_score_prefers_non_flat_image(tmp_path):
    from PIL import Image

    flat = tmp_path / "flat.png"
    textured = tmp_path / "textured.png"
    Image.new("RGB", (32, 32), color=(128, 128, 128)).save(flat)
    image = Image.new("RGB", (32, 32), color=(0, 0, 0))
    for x in range(16, 32):
        for y in range(32):
            image.putpixel((x, y), (255, 255, 255))
    image.save(textured)
    assert score_preview(textured) > score_preview(flat)


def test_active_polar_variant_is_isolated_and_camera_assist_ready():
    from robomituba_bridge import RenderRequest, SceneState

    request = RenderRequest(
        request_id="request", job_id="job", frame_id="frame", timestamp="2026-08-24T00:00:00Z",
        scene_state=SceneState(
            job_id="job", scene_id="infinigen_apartment_20260811", frame_id="frame",
            timestamp="2026-08-24T00:00:00Z", scene_snapshot_ref="snapshot.json", mitsuba_scene_ref="scene.xml",
        ),
    )
    passive = with_polar_pilot_variant(request, "perturbed")
    active = with_polar_pilot_variant(request, "perturbed_active_polar")
    assert passive.assist_light is None
    assert active.assist_light is not None
    assert active.assist_light.spectrum_mode == "rgb_white"
    assert active.assist_light.polarizer_angle_deg == 0.0
    assert active.extras["polar_active"] is True
    assert active.render_settings["polar_color_mode"] == "rgb_stokes_12"
    assert "perturbed-active-polar" in active.job_id
    assert active.scene_state.job_id == active.job_id
    assert passive.extras["overlay_digest"] == active.extras["overlay_digest"]
