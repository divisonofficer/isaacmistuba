from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from mitsuba_converter.material_pipeline.ir_effective_scene import (
    OPAQUE_PBR_DOMAIN,
    SPECULAR_MASKED_PBR_DOMAIN,
    STRUCTURAL_SPECULAR_PBR_DOMAIN,
    materialize_ir_effective_scene,
    validate_ir_effective_scene,
)


def _source_scene(root: Path) -> Path:
    root.mkdir()
    (root / "render_scene.xml").write_text(
        """<scene version="3.0.0">
  <bsdf type="diffuse" id="plastic"/>
  <bsdf type="roughconductor" id="metal"/>
  <bsdf type="dielectric" id="glass"/>
  <bsdf type="blendbsdf" id="nested"><ref id="glass"/><ref id="metal"/></bsdf>
  <shape type="obj" id="cabinet"><ref id="plastic"/></shape>
  <shape type="obj" id="oven_metal"><ref id="metal"/></shape>
  <shape type="obj" id="oven_glass"><ref id="nested"/></shape>
  <shape type="rectangle" id="glass_lamp"><ref id="glass"/><emitter type="area"/></shape>
</scene>""",
        encoding="utf-8",
    )
    index = {"shapes": [
        {"shape_id": "cabinet", "object_id": "cabinet", "material_id": "mat_plastic", "bsdf_ref": "plastic"},
        {"shape_id": "oven_metal", "object_id": "oven", "material_id": "mat_metal", "bsdf_ref": "metal"},
        {"shape_id": "oven_glass", "object_id": "oven", "material_id": "mat_glass", "bsdf_ref": "nested"},
        {"shape_id": "glass_lamp", "object_id": "lamp", "material_id": "mat_glass", "bsdf_ref": "glass"},
    ]}
    policy = {"shape_policies": [
        {"shape_id": row["shape_id"], "material_id": row["material_id"]}
        for row in index["shapes"]
    ]}
    canonical = {"materials": [
        {"material_id": "mat_plastic", "canonical_bsdf": "pplastic", "shape_ids": ["cabinet"]},
        {"material_id": "mat_metal", "canonical_bsdf": "roughconductor", "shape_ids": ["oven_metal"]},
        {"material_id": "mat_glass", "canonical_bsdf": "dielectric", "shape_ids": ["oven_glass", "glass_lamp"]},
    ]}
    authoring = {"objects": [
        {"id": "cabinet", "metadata": {"blender_name": "Cabinet"}},
        {"id": "oven", "metadata": {"blender_name": "Oven"}},
        {"id": "lamp", "metadata": {"blender_name": "Lamp"}},
    ]}
    graph = {"nodes": [{"node_id": "vp_000001", "position": [0, 0, 0], "headings": [{"yaw_deg": 0}]}]}
    for name, payload in (
        ("xml_scene_index.json", index),
        ("render_scene_material_policy.json", policy),
        ("material_canonical.json", canonical),
        ("authoring_map.json", authoring),
        ("viewpoint_graph.json", graph),
    ):
        (root / name).write_text(json.dumps(payload), encoding="utf-8")
    return root


def test_opaque_domain_removes_only_dielectric_shape_part_and_filters_sidecars(tmp_path: Path) -> None:
    source = _source_scene(tmp_path / "source")
    output = tmp_path / "effective"

    contract = materialize_ir_effective_scene(source, output, surface_domain=OPAQUE_PBR_DOMAIN)

    assert contract["surface_domain"] == OPAQUE_PBR_DOMAIN
    assert contract["exclusion"]["excluded_shape_count"] == 1
    assert contract["exclusion"]["emitter_shape_preserved_count"] == 1
    assert contract["exclusion"]["blender_face_selectors"] == [
        {"blender_object": "Oven", "blender_material": "mat_glass", "fallback": "whole_object_if_no_material_slots"}
    ]
    root = ET.parse(output / "render_scene.xml").getroot()
    assert {shape.get("id") for shape in root.findall("./shape")} == {
        "cabinet", "oven_metal", "glass_lamp",
    }
    assert root.find("./bsdf[@id='nested']") is None
    assert root.find("./bsdf[@id='metal']") is not None
    assert root.find("./bsdf[@id='glass']") is not None  # referenced by preserved emitter
    index = json.loads((output / "xml_scene_index.json").read_text())
    policy = json.loads((output / "render_scene_material_policy.json").read_text())
    canonical = json.loads((output / "material_canonical.json").read_text())
    assert {row["shape_id"] for row in index["shapes"]} == {"cabinet", "oven_metal", "glass_lamp"}
    assert {row["shape_id"] for row in policy["shape_policies"]} == {"cabinet", "oven_metal", "glass_lamp"}
    # The preserved emitter may reference glass, but it must not survive in the
    # material sidecar used for renderable PBR surfaces.
    assert {row["material_id"] for row in canonical["materials"]} == {"mat_plastic", "mat_metal"}
    assert validate_ir_effective_scene(output)["effective_scene_digest"] == contract["effective_scene_digest"]


def test_specular_masked_domain_retains_glass_and_resolves_window_object_and_mirror(tmp_path: Path) -> None:
    source = _source_scene(tmp_path / "source")
    xml_path = source / "render_scene.xml"
    xml_path.write_text(
        xml_path.read_text(encoding="utf-8").replace(
            "</scene>",
            '<bsdf type="conductor" id="mirror"/>'
            '<shape type="obj" id="WindowFactory_glazing"><ref id="glass"/></shape>'
            '<shape type="obj" id="bathroom_glass"><ref id="glass"/></shape>'
            '<shape type="obj" id="oven_mirror"><ref id="mirror"/></shape>'
            "</scene>",
        ),
        encoding="utf-8",
    )
    index_path = source / "xml_scene_index.json"
    policy_path = source / "render_scene_material_policy.json"
    canonical_path = source / "material_canonical.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["shapes"].extend([
        {"shape_id": "WindowFactory_glazing", "object_id": "window", "material_id": "mat_glass", "bsdf_ref": "glass"},
        {"shape_id": "bathroom_glass", "object_id": "bottle", "material_id": "mat_glass", "bsdf_ref": "glass"},
        {"shape_id": "oven_mirror", "object_id": "oven", "material_id": "mat_mirror", "bsdf_ref": "mirror"},
    ])
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["shape_policies"].extend(
        {"shape_id": row["shape_id"], "material_id": row["material_id"]}
        for row in index["shapes"][-3:]
    )
    canonical = json.loads(canonical_path.read_text(encoding="utf-8"))
    canonical["materials"][2]["shape_ids"].extend(["WindowFactory_glazing", "bathroom_glass"])
    canonical["materials"].append({
        "material_id": "mat_mirror", "canonical_bsdf": "conductor", "shape_ids": ["oven_mirror"],
    })
    index_path.write_text(json.dumps(index), encoding="utf-8")
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    canonical_path.write_text(json.dumps(canonical), encoding="utf-8")
    authoring_path = source / "authoring_map.json"
    authoring = json.loads(authoring_path.read_text(encoding="utf-8"))
    authoring["objects"].append({"id": "bottle", "metadata": {"blender_name": "Bottle"}})
    authoring_path.write_text(json.dumps(authoring), encoding="utf-8")

    output = tmp_path / "effective"
    contract = materialize_ir_effective_scene(source, output, surface_domain=SPECULAR_MASKED_PBR_DOMAIN)

    assert contract["surface_domain"] == SPECULAR_MASKED_PBR_DOMAIN
    assert contract["exclusion"]["excluded_shape_count"] == 0
    assert contract["exclusion"]["blender_face_selectors"] == []
    regions = json.loads((output / "specular_semantic_regions.json").read_text(encoding="utf-8"))
    assert "WindowFactory_glazing" in regions["shape_classes"]["window_glass"]
    assert "bathroom_glass" in regions["shape_classes"]["object_glass"]
    assert "oven_mirror" in regions["shape_classes"]["mirror"]
    assert "oven_metal" not in regions["shape_classes"]["mirror"]
    assert set(regions["glass_shape_ids"]) == set(regions["shape_classes"]["window_glass"]) | set(regions["shape_classes"]["object_glass"])
    root = ET.parse(output / "render_scene.xml").getroot()
    assert {shape.get("id") for shape in root.findall("./shape")} >= {
        "oven_glass", "WindowFactory_glazing", "bathroom_glass", "oven_mirror",
    }
    assert validate_ir_effective_scene(output)["effective_scene_digest"] == contract["effective_scene_digest"]


def test_first_hit_specular_masks_follow_resolved_shape_classes(tmp_path: Path) -> None:
    import numpy as np
    from mitsuba_converter.material_pipeline.dataset_render import _first_hit_specular_masks

    (tmp_path / "ir_scene_domain.json").write_text(json.dumps({
        "surface_domain": "specular_masked_pbr",
        "specular_semantics": {"ref": "specular_semantic_regions.json"},
    }), encoding="utf-8")
    (tmp_path / "specular_semantic_regions.json").write_text(json.dumps({
        "mask_semantics": "primary_ray_first_geometric_hit_v1",
        "shape_classes": {
            "window_glass": ["window"],
            "object_glass": ["bottle"],
            "mirror": ["mirror"],
            "none": ["wall"],
        },
    }), encoding="utf-8")

    masks = _first_hit_specular_masks(
        tmp_path / "render_scene.xml",
        ["wall", "window", "bottle", "mirror"],
        np.asarray([0, 1, 2, 3, 3, 4]),
        np.asarray([True, True, True, True, False, True]),
    )

    assert masks["window_glass"].tolist() == [False, True, False, False, False, False]
    assert masks["object_glass"].tolist() == [False, False, True, False, False, False]
    assert masks["glass"].tolist() == [False, True, True, False, False, False]
    assert masks["mirror"].tolist() == [False, False, False, True, False, False]


def test_final_pbr_validity_excludes_first_hit_glass_and_mirror(tmp_path: Path) -> None:
    import importlib.util
    cv2 = pytest.importorskip("cv2")
    import numpy as np

    app = Path(__file__).resolve().parents[3] / "apps" / "assemble_ir_dataset.py"
    spec = importlib.util.spec_from_file_location("assemble_ir_dataset", app)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    valid = tmp_path / "valid.png"
    glass = tmp_path / "glass.png"
    mirror = tmp_path / "mirror.png"
    assert cv2.imwrite(str(valid), np.asarray([[255, 255], [255, 0]], np.uint8))
    assert cv2.imwrite(str(glass), np.asarray([[0, 255], [0, 0]], np.uint8))
    assert cv2.imwrite(str(mirror), np.asarray([[0, 0], [255, 0]], np.uint8))

    output, stats = module._write_final_pbr_validity(
        tmp_path, "vp_000001__h_000", blender_validity=valid, glass=glass, mirror=mirror,
    )

    assert module._read_binary_mask(output).tolist() == [[True, False], [False, False]]
    assert stats["excluded_special_pixels"] == 2
    assert stats["final_valid_pixels"] == 1


def test_dataset_assembly_requires_exact_observation_camera_pose(tmp_path: Path) -> None:
    import importlib.util
    import numpy as np

    app = Path(__file__).resolve().parents[3] / "apps" / "assemble_ir_dataset.py"
    spec = importlib.util.spec_from_file_location("assemble_ir_dataset_pose", app)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    matrix = np.eye(4).tolist()
    observation = {
        "camera_to_world": matrix,
        "intrinsics": {"width": 684, "height": 512, "fov_deg": 60.0},
    }
    blender = {
        "pose_source": "observation_manifest", "camera_to_world_mitsuba": np.eye(4).tolist(),
        "width": 684, "height": 512, "fov_deg": 60.0,
    }
    module._validate_camera_contract("frame", observation, blender)
    blender["camera_to_world_mitsuba"][1][3] = 0.01
    with pytest.raises(ValueError, match="camera pose differs"):
        module._validate_camera_contract("frame", observation, blender)


def test_specular_semantic_conflicting_overrides_fail(tmp_path: Path) -> None:
    source = _source_scene(tmp_path / "source")
    (source / "specular_semantic_overrides.json").write_text(json.dumps({
        "shape_classes": {"oven_glass": "window_glass"},
        "material_classes": {"mat_glass": "object_glass"},
    }), encoding="utf-8")

    with pytest.raises(ValueError, match="conflicting specular semantic overrides"):
        materialize_ir_effective_scene(source, tmp_path / "effective", surface_domain=SPECULAR_MASKED_PBR_DOMAIN)


def test_effective_scene_reuses_matching_digest_and_rebuilds_after_source_change(tmp_path: Path) -> None:
    source = _source_scene(tmp_path / "source")
    output = tmp_path / "effective"
    first = materialize_ir_effective_scene(source, output, surface_domain=SPECULAR_MASKED_PBR_DOMAIN)
    second = materialize_ir_effective_scene(source, output, surface_domain=SPECULAR_MASKED_PBR_DOMAIN)
    assert second["effective_scene_digest"] == first["effective_scene_digest"]

    source_xml = source / "render_scene.xml"
    source_xml.write_text(source_xml.read_text(encoding="utf-8").replace("<scene", "<!-- source changed -->\n<scene"), encoding="utf-8")
    third = materialize_ir_effective_scene(source, output, surface_domain=SPECULAR_MASKED_PBR_DOMAIN)
    assert third["source_scene_digest"] != first["source_scene_digest"]


def test_missing_authoring_mapping_is_strict_for_excluded_shape(tmp_path: Path) -> None:
    source = _source_scene(tmp_path / "source")
    authoring = json.loads((source / "authoring_map.json").read_text())
    authoring["objects"] = [row for row in authoring["objects"] if row["id"] != "oven"]
    (source / "authoring_map.json").write_text(json.dumps(authoring), encoding="utf-8")

    with pytest.raises(ValueError, match="cannot map excluded shape"):
        materialize_ir_effective_scene(source, tmp_path / "effective", surface_domain=OPAQUE_PBR_DOMAIN)


def test_opaque_effective_scene_canonicalizes_optional_measured_leaf(tmp_path: Path) -> None:
    source = _source_scene(tmp_path / "source")
    xml = source / "render_scene.xml"
    xml.write_text(
        xml.read_text(encoding="utf-8").replace(
            "</scene>",
            '<bsdf type="measured_polarized" id="optional_measured">'
            '<string name="filename" value="missing.pbrdf"/></bsdf>'
            '<shape type="obj" id="measured_surface"><ref id="optional_measured"/></shape>'
            "</scene>",
        ),
        encoding="utf-8",
    )
    index_path = source / "xml_scene_index.json"
    policy_path = source / "render_scene_material_policy.json"
    canonical_path = source / "material_canonical.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    canonical = json.loads(canonical_path.read_text(encoding="utf-8"))
    index["shapes"].append({
        "shape_id": "measured_surface", "object_id": "cabinet",
        "material_id": "mat_measured", "bsdf_ref": "optional_measured",
    })
    policy["shape_policies"].append({"shape_id": "measured_surface", "material_id": "mat_measured"})
    canonical["materials"].append({
        "material_id": "mat_measured", "canonical_bsdf": "pplastic", "shape_ids": ["measured_surface"],
        "parameters": {},
    })
    index_path.write_text(json.dumps(index), encoding="utf-8")
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    canonical_path.write_text(json.dumps(canonical), encoding="utf-8")

    contract = materialize_ir_effective_scene(source, tmp_path / "effective", surface_domain=OPAQUE_PBR_DOMAIN)
    root = ET.parse(tmp_path / "effective" / "render_scene.xml").getroot()

    assert contract["exclusion"]["canonicalized_measured_bsdf_ids"] == ["optional_measured"]
    assert not any(
        node.get("type") in {"measured", "measured_polarized", "measured_polarized_rgb"}
        for node in root.iter("bsdf")
    )


def test_structural_specular_domain_removes_object_glass_but_keeps_window_and_mirror(tmp_path: Path) -> None:
    source = _source_scene(tmp_path / "source")
    xml_path = source / "render_scene.xml"
    xml_path.write_text(
        xml_path.read_text(encoding="utf-8").replace(
            "</scene>",
            "<bsdf type=\"conductor\" id=\"mirror\"/>"
            "<shape type=\"obj\" id=\"WindowFactory_glazing\"><ref id=\"glass\"/></shape>"
            "<shape type=\"obj\" id=\"bathroom_glass\"><ref id=\"glass\"/></shape>"
            "<shape type=\"obj\" id=\"oven_mirror\"><ref id=\"mirror\"/></shape>"
            "</scene>",
        ),
        encoding="utf-8",
    )
    index_path = source / "xml_scene_index.json"
    policy_path = source / "render_scene_material_policy.json"
    canonical_path = source / "material_canonical.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["shapes"].extend([
        {"shape_id": "WindowFactory_glazing", "object_id": "window", "material_id": "mat_glass", "bsdf_ref": "glass"},
        {"shape_id": "bathroom_glass", "object_id": "bottle", "material_id": "mat_glass", "bsdf_ref": "glass"},
        {"shape_id": "oven_mirror", "object_id": "oven", "material_id": "mat_mirror", "bsdf_ref": "mirror"},
    ])
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["shape_policies"].extend({"shape_id": row["shape_id"], "material_id": row["material_id"]} for row in index["shapes"][-3:])
    canonical = json.loads(canonical_path.read_text(encoding="utf-8"))
    canonical["materials"][2]["shape_ids"].extend(["WindowFactory_glazing", "bathroom_glass"])
    canonical["materials"].append({"material_id": "mat_mirror", "canonical_bsdf": "conductor", "shape_ids": ["oven_mirror"]})
    index_path.write_text(json.dumps(index), encoding="utf-8")
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    canonical_path.write_text(json.dumps(canonical), encoding="utf-8")
    authoring_path = source / "authoring_map.json"
    authoring = json.loads(authoring_path.read_text(encoding="utf-8"))
    authoring["objects"].append({"id": "bottle", "metadata": {"blender_name": "Bottle"}})
    authoring_path.write_text(json.dumps(authoring), encoding="utf-8")


    output = tmp_path / "effective"
    contract = materialize_ir_effective_scene(source, output, surface_domain=STRUCTURAL_SPECULAR_PBR_DOMAIN)

    assert contract["surface_domain"] == STRUCTURAL_SPECULAR_PBR_DOMAIN
    assert contract["exclusion"]["policy"] == "remove_object_glass_shape_part_keep_window_and_mirror"
    assert {row["shape_id"] for row in contract["exclusion"]["excluded_shapes"]} == {"oven_glass", "bathroom_glass", "glass_lamp"}
    root = ET.parse(output / "render_scene.xml").getroot()
    assert {shape.get("id") for shape in root.findall("./shape")} >= {"WindowFactory_glazing", "oven_mirror"}
    assert {shape.get("id") for shape in root.findall("./shape")} .isdisjoint({"oven_glass", "bathroom_glass", "glass_lamp"})
    regions = json.loads((output / "specular_semantic_regions.json").read_text(encoding="utf-8"))
    assert set(regions["removed_object_glass_shape_ids"]) == {"oven_glass", "bathroom_glass", "glass_lamp"}
    assert regions["shape_classes"]["object_glass"] == []
    assert "WindowFactory_glazing" in regions["shape_classes"]["window_glass"]
    assert "oven_mirror" in regions["shape_classes"]["mirror"]
    assert validate_ir_effective_scene(output)["effective_scene_digest"] == contract["effective_scene_digest"]
