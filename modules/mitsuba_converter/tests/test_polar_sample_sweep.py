import io
import json
from types import SimpleNamespace

import numpy as np
from PIL import Image

from mitsuba_converter.render_daemon import RenderDaemon, _bind_graph_sweep_task_record


def _graph(scene_id: str) -> dict:
    nodes = [
        {
            "node_id": f"vp_{index:03d}",
            "position": [float(index), 0.0, 0.0],
            "headings": [{"heading_id": "h_000", "yaw_deg": 0.0, "sensor_observations": {}, "extras": {}}],
            "clearance_m": 1.0,
            "tags": [],
            "extras": {},
        }
        for index in range(12)
    ]
    return {"scene_id": scene_id, "graph_id": "graph-1", "node_heading_count": 1, "nodes": nodes, "edges": [], "metadata": {"revision": "r7"}}


def test_polar_sample_plan_writes_immutable_ten_view_manifest(tmp_path, monkeypatch):
    scene_id = "scene_a"
    project = tmp_path / "out" / "opticalnav" / "project"
    scene_dir = project / "scenes" / scene_id
    scene_dir.mkdir(parents=True)
    (scene_dir / "viewpoint_graph.json").write_text(json.dumps(_graph(scene_id)), encoding="utf-8")
    daemon = RenderDaemon(repo_root=tmp_path, render_fn=lambda *_args, **_kwargs: None)
    responses = []
    monkeypatch.setattr(daemon, "_send_json", lambda _handler, status, body: responses.append((status, body)))

    daemon._handle_opticalnav_polar_sample_plan(object(), project, scene_id, {"submission_group_id": "polar-sample-test"})

    status, body = responses[-1]
    assert int(status) == 200, body
    assert len(body["view_keys"]) == 10
    assert len({(item["node_id"], item["heading_id"]) for item in body["view_keys"]}) == 10
    manifest = project / body["selection_manifest_ref"]
    saved = json.loads(manifest.read_text(encoding="utf-8"))
    assert saved["graph_revision"] == "r7"
    assert saved["seed"] == 20260811
    assert saved["sensor_ids"] == ["polar_cam"]
    assert saved["polar_color_mode"] == "rgb_stokes_12"
    assert saved["variants"] == ["perturbed", "perturbed_active_polar"]
    assert saved["expected_capture_count"] == 20


def test_selection_manifest_ref_is_bound_to_graph_sweep_task(monkeypatch):
    monkeypatch.setattr("mitsuba_converter.render_daemon.render_request_to_payload", lambda _request: {})
    request = SimpleNamespace(extras={})
    sweep_request = SimpleNamespace(node_id="vp_001", heading_id="h_000", request=request)
    _key, record = _bind_graph_sweep_task_record(
        sweep_request, {"phase": "per_view", "phase_index": 0},
        logical_key="logical", task_id="task", ordinal=0,
        project_id="project", scene_id="scene", run_id="run",
        scene_version_id_value="scene-v", render_version_id="render-v",
        scene_variant_key="perturbed_active_polar", render_variant="cuda_ad_rgb_polarized",
        submission_group_id="polar-sample-test", variant_sequence_index=1,
        variant_sequence_total=2, previous_variant_batch_id="passive-batch",
        selection_manifest_ref="graph_render_batches/polar-sample-test.polar-sample-selection.json",
    )
    assert request.extras["polar_sample_selection_manifest_ref"].endswith(".json")
    assert record["metadata"]["polar_sample_selection_manifest_ref"] == request.extras["polar_sample_selection_manifest_ref"]
    assert record["previous_variant_batch_id"] == "passive-batch"


def test_gallery_stokes_preview_reads_legacy_camera_bundle_without_mutating_it(tmp_path):
    """Historical polar bundles use cameras/polar_cam, not sensors/polar_cam."""
    project = tmp_path / "out" / "opticalnav" / "project"
    bundle = (
        project / "scenes" / "scene_a" / "observations" / "versions" / "rv_test"
        / "perturbed" / "vp_001" / "h_330" / "cameras" / "polar_cam"
    )
    bundle.mkdir(parents=True)
    np.savez_compressed(
        bundle / "stokes_data.npz",
        s0=np.full((2, 2, 3), 0.4, dtype=np.float32),
        s1=np.array([[[1.0, 0.0, -1.0]] * 2] * 2, dtype=np.float32),
    )
    daemon = RenderDaemon(repo_root=tmp_path, render_fn=lambda *_args, **_kwargs: None)

    png = daemon._opticalnav_observation_modality_png(
        project, "scene_a", "vp_001", "h_330", "stokes_s1_rgb",
        sensor_id="polar_cam", variant="perturbed", render_version_id="rv_test",
    )

    assert png is not None
    assert Image.open(io.BytesIO(png)).size == (2, 2)
    # The gallery response was synthesized, not added to an immutable bundle.
    assert not (bundle / "s1_rgb_preview.png").exists()
