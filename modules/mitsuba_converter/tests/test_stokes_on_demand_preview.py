from pathlib import Path

import numpy as np

from mitsuba_converter.multimodal import save_polarization_products
from mitsuba_converter.render_daemon import RenderDaemon


def test_core_stokes_preview_is_served_without_writing_observation(tmp_path):
    project = tmp_path / "out" / "opticalnav" / "project"
    sensor_dir = project / "scenes" / "scene" / "observations" / "vp_000001" / "h_000" / "cameras" / "polar_cam"
    sensor_dir.mkdir(parents=True)
    image = np.zeros((4, 5, 15), dtype=np.float32)
    image[:, :, :3] = 0.4
    image[:, :, 3:6] = 1.0
    image[:, :, 6:9] = 0.25
    save_polarization_products(
        image, sensor_dir, {"polar_rgb_preview", "dop"},
        visualization_policy="core_preview_v1",
    )
    daemon = RenderDaemon(repo_root=tmp_path)
    response = daemon._opticalnav_observation_modality_png(
        project, "scene", "vp_000001", "h_000", "dop", sensor_id="polar_cam",
    )
    assert response is not None and response.startswith(b"\x89PNG")
    assert not (sensor_dir / "dop_red_black_colorbar.png").exists()
    # The second response must come from the bounded in-memory cache.
    assert daemon._opticalnav_observation_modality_png(
        project, "scene", "vp_000001", "h_000", "dop", sensor_id="polar_cam",
    ) == response
