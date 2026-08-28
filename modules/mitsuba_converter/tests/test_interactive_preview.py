from __future__ import annotations

import threading

import numpy as np

from mitsuba_converter.interactive_preview import (
	DrJitFrozenRenderer,
    InteractivePreviewSession,
    LivePreviewConfig,
    _jpeg,
    live_preview_cold_start_estimate,
    live_preview_config_with_overrides,
    live_preview_config_with_spp,
    normalize_live_frozen_bsdfs,
)


def test_preview_jpeg_is_encoded() -> None:
    data = _jpeg(np.ones((4, 4, 3), dtype=np.float32), 80)
    assert data.startswith(b"\xff\xd8")


def test_latest_pose_replaces_the_previous_pose_and_clamps_pitch() -> None:
    # Avoid starting a renderer thread; this only exercises the thread-safe
    # latest-pose mailbox used by the WebSocket reader.
    session = object.__new__(InteractivePreviewSession)
    session._lock = threading.Condition()
    session.config = LivePreviewConfig()
    session._latest_pose = None
    session._sequence = 0
    session.update_pose({"x": 1, "pitch_deg": 300})
    session.update_pose({"x": 2, "yaw_deg": 90})
    assert session._sequence == 2
    assert session._latest_pose == {
        "x": 2.0, "y": 1.5, "z": 0.0,
        "yaw_deg": 90.0, "pitch_deg": 0.0, "fov_deg": 70.0,
    }


def test_live_preview_spp_override_is_bounded(monkeypatch) -> None:
    monkeypatch.setenv("ROBOMITUBA_LIVE_PREVIEW_SPP", "1")
    assert live_preview_config_with_spp(None).spp == 1
    assert live_preview_config_with_spp("256").spp == 256
    for value in ("0", "3", "512", "fast"):
        try:
            live_preview_config_with_spp(value)
        except ValueError as exc:
            assert "..., 256" in str(exc)
        else:
            raise AssertionError(f"{value!r} must be rejected")


def test_live_preview_resolution_override_accepts_only_presets(monkeypatch) -> None:
    monkeypatch.setenv("ROBOMITUBA_LIVE_PREVIEW_SPP", "1")
    config = live_preview_config_with_overrides("4", "256", "192")
    assert (config.spp, config.width, config.height) == (4, 256, 192)
    for width, height in (("256", "256"), ("1024", "720"), ("fast", "192")):
        try:
            live_preview_config_with_overrides("1", width, height)
        except ValueError as exc:
            assert "resolution" in str(exc)
        else:
            raise AssertionError(f"{width}x{height} must be rejected")


def test_live_preview_renderer_override_is_per_session(monkeypatch) -> None:
    monkeypatch.setenv("ROBOMITUBA_LIVE_PREVIEW_RENDERER", "frozen")
    assert live_preview_config_with_overrides("1", None, None, "classic").renderer_mode == "classic"
    try:
        live_preview_config_with_overrides("1", None, None, "invalid")
    except ValueError as exc:
        assert "renderer" in str(exc)
    else:
        raise AssertionError("invalid renderer must be rejected")


def test_live_preview_cold_start_estimate_scales_with_xml_textures(tmp_path) -> None:
    scene = tmp_path / "scene.xml"
    scene.write_text(
        "<scene><shape type='obj'/><texture type='bitmap'/><texture type='bitmap'/></scene>",
        encoding="utf-8",
    )
    estimate = live_preview_cold_start_estimate(scene, LivePreviewConfig(width=640, height=360, spp=8, renderer_mode="frozen"))
    assert estimate["texture_count"] == 2
    assert estimate["shape_count"] == 1
    assert estimate["first_frame_lower_s"] < estimate["first_frame_upper_s"]
    assert estimate["record_upper_s"] >= estimate["record_lower_s"] >= 1


def test_frozen_xml_normalizes_only_the_explicit_bsdf_allowlist(tmp_path) -> None:
    scene = tmp_path / "scene.xml"
    scene.write_text(
        """<scene version='3.0.0'>
        <bsdf type='twosided' id='plastic'><bsdf type='roughplastic'><float name='alpha' value='0.2'/></bsdf></bsdf>
        <bsdf type='conductor' id='metal'/>
        <bsdf type='dielectric' id='glass'/>
        </scene>""",
        encoding="utf-8",
    )
    xml, counts = normalize_live_frozen_bsdfs(scene)
    assert 'type="twosided"' not in xml
    assert 'type="roughplastic"' not in xml
    assert 'type="conductor"' not in xml
    assert xml.count('type="pplastic"') == 1
    assert xml.count('type="roughconductor"') == 1
    assert counts == {"pplastic": 1, "roughconductor": 1, "dielectric": 0, "normalmap": 0}


def test_frozen_xml_retains_normalmap_and_normalizes_its_base_bsdf(tmp_path) -> None:
    scene = tmp_path / "scene.xml"
    scene.write_text(
        """<scene version='3.0.0'>
        <bsdf type='twosided' id='paint'><bsdf type='normalmap'><texture name='normalmap' type='bitmap'/><bsdf type='roughplastic'/></bsdf></bsdf>
        <bsdf type='normalmap' id='glass'><texture name='normalmap' type='bitmap'/><bsdf type='dielectric'/></bsdf>
        </scene>""",
        encoding="utf-8",
    )
    xml, counts = normalize_live_frozen_bsdfs(scene)
    assert 'type="twosided"' not in xml
    assert xml.count('type="normalmap"') == 2
    assert 'name="normalmap"' in xml
    assert 'type="pplastic"' in xml
    assert 'type="dielectric"' in xml
    assert counts == {"pplastic": 1, "roughconductor": 0, "dielectric": 0, "normalmap": 1}


def test_frozen_xml_retains_blendbsdf_and_normalizes_both_children(tmp_path) -> None:
    scene = tmp_path / "scene.xml"
    scene.write_text(
        """<scene version='3.0.0'><bsdf type='blendbsdf' id='mixed'>
        <float name='weight' value='0.5'/><bsdf type='roughplastic'/><bsdf type='conductor'/>
        </bsdf></scene>""",
        encoding="utf-8",
    )
    xml, counts = normalize_live_frozen_bsdfs(scene)
    assert 'type="blendbsdf"' in xml
    assert 'name="weight"' in xml
    assert 'type="pplastic"' in xml
    assert 'type="roughconductor"' in xml
    assert counts == {"pplastic": 1, "roughconductor": 1, "dielectric": 0, "normalmap": 0}


def test_frozen_xml_rejects_unapproved_bsdf(tmp_path) -> None:
    scene = tmp_path / "scene.xml"
    scene.write_text("<scene version='3.0.0'><bsdf type='diffuse'/></scene>", encoding="utf-8")
    try:
        normalize_live_frozen_bsdfs(scene)
    except RuntimeError as exc:
        assert "allowed" in str(exc)
    else:
        raise AssertionError("unapproved BSDF must disable frozen live mode")


def test_upstream_frozen_renderer_marks_record_then_replay(monkeypatch) -> None:
	class FakeRender:
		def __init__(self):
			self.n_recordings = 0
		def __call__(self, scene, sensor):
			self.n_recordings += 1 if self.n_recordings < 2 else 0
			return "image"

	class FakeDr:
		class JitBackend:
			CUDA = "cuda"
		def has_backend(self, backend): return backend == "cuda"
		def freeze(self, function, **kwargs): return FakeRender()
		def eval(self, image): assert image == "image"

	class FakeMi:
		def render(self, scene, sensor, spp): return "unused"

	import sys
	monkeypatch.setitem(sys.modules, "drjit", FakeDr())
	monkeypatch.setitem(sys.modules, "mitsuba", FakeMi())
	adapter = DrJitFrozenRenderer("scene", "sensor", 1)
	assert adapter.render(1) == "image"
	assert adapter.last_stage == "record"
	assert adapter.render(2) == "image"
	assert adapter.last_stage == "record"
	assert adapter.render(3) == "image"
	assert adapter.last_stage == "replay"
