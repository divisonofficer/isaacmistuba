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


def test_core_stokes_rgb_channel_bwr_is_served_without_writing_observation(tmp_path):
    project = tmp_path / "out" / "opticalnav" / "project"
    sensor_dir = project / "scenes" / "scene" / "observations" / "vp_000001" / "h_000" / "cameras" / "polar_cam"
    sensor_dir.mkdir(parents=True)
    image = np.zeros((4, 5, 15), dtype=np.float32)
    image[:, :, :3] = 0.4
    image[:, :, 3:6] = 1.0
    image[:, :, 6:9] = np.array([0.3, -0.2, 0.1], dtype=np.float32)
    image[:, :, 9:12] = np.array([-0.1, 0.2, -0.3], dtype=np.float32)
    image[:, :, 12:15] = np.array([0.1, 0.0, -0.1], dtype=np.float32)
    save_polarization_products(
        image, sensor_dir, {"polar_rgb_preview"},
        visualization_policy="core_preview_v1",
    )
    daemon = RenderDaemon(repo_root=tmp_path)
    response = daemon._opticalnav_observation_modality_png(
        project, "scene", "vp_000001", "h_000", "stokes_s3_b_bwr", sensor_id="polar_cam",
    )
    assert response is not None and response.startswith(b"\x89PNG")
    assert not (sensor_dir / "s3_b_bwr_colorbar.png").exists()


def test_core_stokes_serves_every_gallery_product_without_publishing_pngs(tmp_path):
    project = tmp_path / "out" / "opticalnav" / "project"
    sensor_dir = project / "scenes" / "scene" / "observations" / "vp_000001" / "h_000" / "cameras" / "polar_cam"
    sensor_dir.mkdir(parents=True)
    image = np.zeros((4, 5, 15), dtype=np.float32)
    image[:, :, :3] = 0.4
    image[:, :, 3:6] = 1.0
    image[:, :, 6:9] = np.array([0.3, -0.2, 0.1], dtype=np.float32)
    image[:, :, 9:12] = np.array([-0.1, 0.2, -0.3], dtype=np.float32)
    image[:, :, 12:15] = np.array([0.1, 0.0, -0.1], dtype=np.float32)
    save_polarization_products(image, sensor_dir, {"polar_rgb_preview"}, visualization_policy="core_preview_v1")
    daemon = RenderDaemon(repo_root=tmp_path)
    products = [
        "polar_rgb_preview", "stokes_s0_rgb",
        "stokes_s1_r_bwr", "stokes_s1_g_bwr", "stokes_s1_b_bwr",
        "stokes_s2_r_bwr", "stokes_s2_g_bwr", "stokes_s2_b_bwr",
        "stokes_s3_r_bwr", "stokes_s3_g_bwr", "stokes_s3_b_bwr",
        "dop", "aolp",
    ]
    try:
        for product in products:
            response = daemon._opticalnav_observation_modality_png(
                project, "scene", "vp_000001", "h_000", product, sensor_id="polar_cam",
            )
            assert response is not None and response.startswith(b"\x89PNG"), product
    finally:
        daemon._gallery_preview_service.shutdown()

    # Only the compact contract's source data remains in the immutable bundle.
    assert sorted(path.name for path in sensor_dir.iterdir()) == ["polar_rgb_preview.png", "stokes_data.npz"]
