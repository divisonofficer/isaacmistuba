"""Stage 0 — extract raw material slots (Tier-0) from the daemon's sidecars.

The render daemon (`_generate_opticalnav_render_scene_xml`) already writes
`render_scene_material_policy.json` (per-shape strategy + embedded extracted_material)
and `xml_scene_index.json` next to each scene. This stage does NO estimation: it just
groups those per-shape policy records by `material_id` and repackages the raw fields
we trust — authoring scalars (`.blend`) and extracted asset textures/factors (glb/obj)
— into one flat, greppable `material_slots.json`. Keeping extraction separate means the
canonicalization semantics can be re-run and diffed without touching the daemon.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Optional

SLOTS_SCHEMA_VERSION = "robomituba-material-slots-v1"

# Fields copied verbatim from a policy record's embedded `extracted_material`.
_EXTRACTED_KEYS = (
    "source", "surface_shader_id",
    "base_color_factor", "base_color_texture_ref",
    "normal_texture_ref", "roughness_texture_ref", "metallic_texture_ref",
    "metallic_roughness_texture_ref",
    "roughness_factor", "metallic_factor", "opacity_factor",
)


def _scene_dir(scene: Path) -> Path:
    """Accept either a scene directory or a render_scene.xml path."""
    return scene.parent if scene.is_file() else scene


def extract_material_slots(scene: Path) -> dict:
    """Read the daemon sidecars in `scene` (dir or render_scene.xml) and return the
    versioned material-slots document. Groups shape_policies by material_id; the first
    policy seen for a material_id sets its authoring/extracted fields (they are shared
    across shapes of the same material), and every shape_id is accumulated."""
    scene_dir = _scene_dir(scene)
    policy_path = scene_dir / "render_scene_material_policy.json"
    if not policy_path.is_file():
        raise FileNotFoundError(
            f"render_scene_material_policy.json not found in {scene_dir} — run the "
            f"render-scene sync first (it is produced by _generate_opticalnav_render_scene_xml)."
        )
    policy = json.loads(policy_path.read_text())
    scene_id = policy.get("scene_id") or scene_dir.name

    by_mid: dict[str, dict] = {}
    unassigned = 0
    for sp in policy.get("shape_policies", []):
        mid = sp.get("material_id")
        shape_id = sp.get("shape_id")
        if not mid:
            unassigned += 1
            continue
        slot = by_mid.get(mid)
        if slot is None:
            slot = _new_slot(mid, sp)
            by_mid[mid] = slot
        if shape_id and shape_id not in slot["shape_ids"]:
            slot["shape_ids"].append(shape_id)

    materials = sorted(by_mid.values(), key=lambda s: s["material_id"])
    return {
        "version": SLOTS_SCHEMA_VERSION,
        "scene_id": scene_id,
        "summary": {
            "material_count": len(materials),
            "shape_count": sum(len(s["shape_ids"]) for s in materials),
            "unassigned_shapes": unassigned,
        },
        "materials": materials,
    }


def _new_slot(material_id: str, sp: Mapping[str, Any]) -> dict:
    fb = sp.get("analytic_fallback") or {}
    extracted = sp.get("extracted_material") or {}
    measured = sp.get("measured_candidate") or None
    return {
        "material_id": material_id,
        "shape_ids": [],
        "analytic_strategy": sp.get("analytic_strategy") or fb.get("bsdf_strategy"),
        "optical_class": fb.get("optical_class"),
        "measured_role": sp.get("measured_role"),
        # Authoring scalars come from the .blend/authoring map (authority for
        # metallic/roughness per the provenance fix); keep them separate from the
        # asset-exported factors so canonicalize can pick the right authority.
        "authoring": {
            "base_color_factor": fb.get("base_color_factor"),
            "roughness": fb.get("roughness"),
            "metallic": fb.get("metallic"),
        },
        "extracted": {k: extracted.get(k) for k in _EXTRACTED_KEYS},
        "measured_candidate": ({
            "kind": measured.get("kind"),
            "dataset_id": measured.get("dataset_id"),
            "material_id": measured.get("material_id"),
            "bsdf_strategy": measured.get("bsdf_strategy"),
            "channels_dir": measured.get("channels_dir"),
        } if measured else None),
    }


def load_material_slots(scene: Path) -> Optional[dict]:
    """Load a previously written material_slots.json from the scene dir, or None."""
    p = _scene_dir(scene) / "material_slots.json"
    return json.loads(p.read_text()) if p.is_file() else None


def write_material_slots(scene: Path, doc: dict) -> Path:
    out = _scene_dir(scene) / "material_slots.json"
    out.write_text(json.dumps(doc, indent=2))
    return out
