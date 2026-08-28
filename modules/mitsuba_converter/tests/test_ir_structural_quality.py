from __future__ import annotations
import cv2
import numpy as np
from mitsuba_converter.ir_structural_quality import audit_manifest

def _texture(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    assert cv2.imwrite(str(path), np.full((2048, 2048), value, np.uint16))

def test_quality_gate_accepts_dielectric_rough_floor(tmp_path):
    for channel, value in (("base_color", 30000), ("roughness", 35000), ("normal_gl", 45000)):
        _texture(tmp_path / f"floor/{channel}.png", value)
    binding = {"unit_id":"room.floor", "slot_index":0, "role":"floor", "material_id":"floor_tile", "metallic":0,
      "projection":"object_meter_repeat_v2", "resolved_maps":{k:str(tmp_path/f"floor/{k}.png") for k in ("base_color","roughness","normal_gl")}}
    report=audit_manifest({"bindings":[binding]}, registry_root=tmp_path)
    assert report["status"] == "passed"

def test_quality_gate_rejects_mirror_like_floor(tmp_path):
    for channel, value in (("base_color", 30000), ("roughness", 1), ("normal_gl", 45000)):
        _texture(tmp_path / f"floor/{channel}.png", value)
    binding = {"unit_id":"room.floor", "slot_index":0, "role":"floor", "material_id":"floor_tile", "metallic":0,
      "projection":"object_meter_repeat_v2", "resolved_maps":{k:str(tmp_path/f"floor/{k}.png") for k in ("base_color","roughness","normal_gl")}}
    report=audit_manifest({"bindings":[binding]}, registry_root=tmp_path)
    assert report["status"] == "failed"
    assert any("floor_near_mirror" in x for x in report["failures"])


def test_quality_gate_allows_reviewed_metal_panel_but_not_metal_floor(tmp_path):
    for channel, value in (("base_color", 30000), ("roughness", 1), ("normal_gl", 45000), ("metallic", 65535)):
        _texture(tmp_path / f"panel/{channel}.png", value)
    maps = {key: str(tmp_path / f"panel/{key}.png") for key in ("base_color", "roughness", "normal_gl", "metallic")}
    panel = {"unit_id": "room.panel", "slot_index": 0, "role": "panel", "material_id": "metal_panel",
             "metallic": {"mode": "texture", "map": "metallic"}, "projection": "object_meter_repeat_v3", "resolved_maps": maps}
    assert audit_manifest({"bindings": [panel]}, registry_root=tmp_path)["status"] == "passed"
    floor = {**panel, "unit_id": "room.floor", "role": "floor"}
    report = audit_manifest({"bindings": [floor]}, registry_root=tmp_path)
    assert any("metallic_structural_role_not_allowed" in x for x in report["failures"])
