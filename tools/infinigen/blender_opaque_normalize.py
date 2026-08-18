"""Stage A — opaque-PBR normalization inside Blender (bpy).

Replaces every glass/mirror material SURFACE (geometry kept) with a fresh OPAQUE
Principled BSDF chosen by ``opaque_substitutions.json`` (Infinigen glass uses Glass/Mix
shaders, NOT Principled, so we rebuild the surface rather than edit sockets), then
RE-BAKES the affected objects' base_color/roughness/metallic/normal atlases so the
substituted surfaces have real tier-0 baked GT. Writes a separate
``scene_manifest_opaque.json`` + ``opaque_substitutions_applied.json`` +
``*.opaque.png`` atlases so the original (OOD) scene is untouched.

Run via the bundled-Blender launcher (it creates missing SONAME compat links):
  python tools/infinigen/run_bundled_blender.py -b scene.blend \
    --python tools/infinigen/blender_opaque_normalize.py -- \
    --substitutions .../opaque_substitutions.json \
    --import-dir out/infinigen_imports/kr_20260730_single_room_kitchen \
    [--bake-res 512 --bake-samples 12 --limit N --reuse-existing]
"""
import json
import hashlib
import sys
from pathlib import Path

import bpy  # type: ignore

# reuse the export bake pipeline (import-safe: functions + guarded main)
sys.path.insert(0, str(Path(__file__).resolve().parent))
import blender_export_scene as bex  # noqa: E402

# canonical.bsdf -> the manifest optical_class the import binding maps to that opaque BSDF
_BSDF_TO_OPTICAL = {"pplastic": "diffuse", "roughconductor": "metal_aluminum"}
_CHANNEL_TOKEN = {"base_color": "albedo", "roughness": "roughness",
                  "metallic": "metallic", "normal": "normal"}


def _argv():
    a = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    def opt(name, default=None):
        return a[a.index(name) + 1] if name in a else default
    return {
        "substitutions": opt("--substitutions"),
        "import_dir": Path(opt("--import-dir")),
        "bake_res": int(opt("--bake-res", "512")),
        "max_bake_res": int(opt("--max-bake-res", "4096")),
        "max_unbaked_ratio": float(opt("--max-unbaked-ratio", "0.001")),
        "bake_samples": int(opt("--bake-samples", "12")),
        "limit": int(opt("--limit", "0")),
        "only_unit": opt("--only-unit"),
        "reuse_existing": "--reuse-existing" in a,
        "suffix": opt("--suffix", ".opaque"),
    }


def remap_material_opaque(mat, canon):
    """Rebuild a material's surface as an opaque Principled BSDF from canonical params."""
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bc = canon["base_color"]
    bsdf.inputs["Base Color"].default_value = (float(bc[0]), float(bc[1]), float(bc[2]), 1.0)
    bsdf.inputs["Metallic"].default_value = float(canon["metallic"])
    bsdf.inputs["Roughness"].default_value = float(canon["roughness"])
    for name, val in (("Transmission Weight", 0.0), ("Transmission", 0.0),
                      ("Alpha", 1.0), ("IOR", 1.5)):
        if name in bsdf.inputs:
            bsdf.inputs[name].default_value = val
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    nt.update_tag()
    mat.update_tag()
    try:
        mat.blend_method = "OPAQUE"
    except Exception:  # noqa: BLE001
        pass


def assign_unit_opaque_materials(obj, uid, canon_by_source):
    """Assign fresh, per-unit opaque materials to targeted slots.

    Infinigen commonly shares one glass material datablock across multiple instances.
    Substitution palettes are intentionally per unit, so mutating that shared material
    globally both loses the per-unit choice and can leave Cycles using a stale evaluated
    shader.  A fresh material datablock per targeted unit/slot avoids both failure modes.
    """
    assigned = 0
    face_counts = {}
    polygon_counts = {}
    for polygon in obj.data.polygons:
        polygon_counts[polygon.material_index] = polygon_counts.get(polygon.material_index, 0) + 1
    for index, slot in enumerate(obj.material_slots):
        source = slot.material
        if source is None or source.name not in canon_by_source:
            continue
        face_counts[source.name] = face_counts.get(source.name, 0) + polygon_counts.get(index, 0)
        digest = hashlib.sha1(f"{uid}:{index}:{source.name}".encode("utf-8")).hexdigest()[:10]
        opaque = bpy.data.materials.new(name=f"{source.name}__opaque_{digest}")
        remap_material_opaque(opaque, canon_by_source[source.name])
        slot.material = opaque
        assigned += 1
    bpy.context.view_layer.update()
    return assigned, face_counts


def main():
    args = _argv()
    doc = json.loads(Path(args["substitutions"]).read_text())
    subs = doc["substitutions"]
    units_affected = {}
    for e in subs:
        units_affected.setdefault(e["unit_id"], {})[e["material_name"]] = e["canonical"]

    manifest = json.loads((args["import_dir"] / "scene_manifest.json").read_text())
    unit_by_id = {u["id"]: u for u in manifest["units"]}
    tex_dir = args["import_dir"] / "textures"
    tex_dir.mkdir(exist_ok=True)

    ordered = list(units_affected.items())
    if args["only_unit"]:
        ordered = [(uid, mats) for uid, mats in ordered if uid == args["only_unit"]]
        if not ordered:
            raise ValueError(f"--only-unit not found in substitutions: {args['only_unit']}")
    if args["limit"]:
        ordered = ordered[:args["limit"]]

    baked_units = bake_fail = obj_missing = material_missing = 0
    for i, (uid, canon_by_mat) in enumerate(ordered):
        unit = unit_by_id.get(uid)
        if unit is None:
            continue
        obj = bpy.data.objects.get(unit.get("blender_name") or "")
        if obj is None:
            obj_missing += 1
            print(f"[opaque] OBJ MISSING for unit {uid} (blender_name={unit.get('blender_name')})", flush=True)
            continue
        assigned, target_face_counts = assign_unit_opaque_materials(obj, uid, canon_by_mat)
        if assigned != len(canon_by_mat):
            material_missing += len(canon_by_mat) - assigned
            print(
                f"[opaque] MATERIAL SLOT MISMATCH for {uid}: assigned={assigned} "
                f"expected={len(canon_by_mat)} targets={sorted(canon_by_mat)}",
                flush=True,
            )
        try:
            bpy.context.view_layer.objects.active = obj
            obj.select_set(True)
        except Exception:  # noqa: BLE001
            pass
        sfx = args["suffix"]
        outs = {ch: str(tex_dir / f"{uid}_{tok}{sfx}.png") for ch, tok in _CHANNEL_TOKEN.items()}
        coverage_out = str(tex_dir / f"{uid}_coverage{sfx}.png")
        res, samp = args["bake_res"], args["bake_samples"]
        if not bex._ensure_uv(obj):
            raise RuntimeError(f"{uid}: strict opaque export could not create a valid UV atlas")
        if args["reuse_existing"]:
            ok = {channel: Path(path).is_file() for channel, path in outs.items()}
            coverage = bex._coverage_validation(
                obj, coverage_out, max_unbaked_ratio=args["max_unbaked_ratio"]
            ) if Path(coverage_out).is_file() else {
                "attempted": True, "passed": False, "reason": "missing_coverage_mask",
            }
            effective_res = int((coverage.get("resolution") or [res])[0])
        else:
            # Property bakes do not use lighting or neighboring geometry.  Isolating
            # the object keeps Cycles from synchronizing the full scene per channel.
            with bex._render_isolate(obj):
                effective_res, coverage = bex._bake_coverage_adaptive(
                    obj,
                    coverage_out,
                    res,
                    args["max_bake_res"],
                    args["max_unbaked_ratio"],
                )
                if not coverage.get("passed"):
                    raise RuntimeError(
                        f"{uid}: strict opaque UV coverage failed: "
                        f"{coverage.get('reason', 'unknown')}"
                    )
                ok = {}
                ok["base_color"] = bool(bex._bake_albedo(obj, outs["base_color"], effective_res, samp))
                ok["roughness"] = bool(bex._bake_roughness(obj, outs["roughness"], effective_res, samp))
                ok["metallic"] = bool(bex._bake_metallic(obj, outs["metallic"], effective_res, samp))
                ok["normal"] = bool(bex._bake_normal(obj, outs["normal"], effective_res, samp))
        validations = {}
        for channel in ("base_color", "roughness", "metallic"):
            if ok[channel]:
                _spatial, validations[channel] = bex._pbr_texture_validation(outs[channel], channel)
            else:
                validations[channel] = {"attempted": True, "result": "bake_failed"}
        if ok["normal"]:
            _spatial, validations["normal"] = bex._normal_bake_validation(outs["normal"])
        else:
            validations["normal"] = {"attempted": True, "result": "bake_failed"}
        invalid_channels = [
            channel for channel, valid in ok.items()
            if not valid or validations[channel].get("result") not in {"spatial", "constant"}
        ]
        if not coverage.get("passed") or invalid_channels:
            raise RuntimeError(
                f"{uid}: strict opaque PBR bake failed channels={invalid_channels} "
                f"coverage={coverage.get('reason')}"
            )
        baked_units += 1
        bake_fail += sum(1 for v in ok.values() if not v)

        # Export the exact same UV-bearing mesh consumed by the new atlases.  This
        # removes the former assumption that Smart UV Project will be identical in
        # a later process.
        original_matrix = obj.matrix_world.copy()
        bmin, bmax = bex._world_bbox(obj)
        cx = (bmin[0] + bmax[0]) * 0.5
        cy = (bmin[1] + bmax[1]) * 0.5
        offset = bex.Vector((-cx, -cy, -bmin[2]))
        obj.matrix_world = bex.Matrix.Translation(offset) @ original_matrix
        obj_path = args["import_dir"] / str(unit.get("mesh_obj") or "")
        glb_path = args["import_dir"] / str(unit.get("mesh_glb") or "")
        if not unit.get("mesh_obj") or not unit.get("mesh_glb"):
            raise RuntimeError(f"{uid}: strict opaque export requires OBJ and GLB paths")
        bex._export_obj(obj, str(obj_path))
        mtl_path = obj_path.with_suffix(".mtl")
        for channel, key in (
            ("base_color", "map_Kd"), ("roughness", "map_Pr"),
            ("metallic", "map_Pm"), ("normal", "norm"),
        ):
            rel = Path(outs[channel]).relative_to(args["import_dir"]).as_posix()
            mtl_rel = Path("..") / rel
            bex._patch_mtl_map(str(mtl_path), mtl_rel.as_posix(), key)
        with bex._gltf_pbr_materials(
            obj,
            manifest.get("materials") or {},
            base_color_path=outs["base_color"],
            roughness_path=outs["roughness"],
            metallic_path=outs["metallic"],
            normal_path=outs["normal"],
        ):
            bex._export_glb(obj, str(glb_path))
        glb_validation = bex._glb_mesh_contract(str(glb_path))
        obj.matrix_world = original_matrix
        if not glb_validation.get("valid"):
            raise RuntimeError(f"{uid}: strict opaque GLB failed: {glb_validation.get('issues')}")

        # Update this unit in-manifest. No constant/inpainting fallback is permitted:
        # every substituted multi-material surface is represented by validated atlases.
        target_slots = [
            slot for slot in unit.get("material_slots", []) if slot.get("name") in canon_by_mat
        ]
        rep = canon_by_mat[target_slots[0]["name"]]
        for slot in unit.get("material_slots", []):
            if slot.get("name") in canon_by_mat:
                canon = canon_by_mat[slot["name"]]
                slot["optical_class"] = _BSDF_TO_OPTICAL.get(canon["bsdf"], "diffuse")
                slot["opaque_substituted"] = True
                slot["opaque_substitution_face_count"] = target_face_counts.get(slot["name"], 0)
                slot["opaque_substitution_active"] = target_face_counts.get(slot["name"], 0) > 0
        pbr = unit.setdefault("pbr", {})
        chd = pbr.setdefault("channels", {})
        for cch, tok in _CHANNEL_TOKEN.items():
            rel = f"textures/{uid}_{tok}{sfx}.png"
            chd[cch] = {
                "mode": "texture", "ref": rel, "source": "opaque_baked_strict",
                "colorspace": "srgb" if cch == "base_color" else "raw",
                "resolution": [effective_res, effective_res],
                "bake_validation": validations[cch],
            }
            unit[f"baked_{tok}"] = rel
        coverage_rel = f"textures/{uid}_coverage{sfx}.png"
        pbr["coverage"] = {"ref": coverage_rel, **coverage}
        unit["baked_coverage"] = coverage_rel
        unit["glb_validation"] = glb_validation
        unit["glb_sha256"] = bex._sha256_file(str(glb_path))
        unit["optical_class"] = _BSDF_TO_OPTICAL.get(rep["bsdf"], unit.get("optical_class"))
        unit["opaque_normalized"] = True
        unit["opaque_replacement_active"] = any(count > 0 for count in target_face_counts.values())
        print(f"[opaque] ({i+1}/{len(ordered)}) baked {uid} ok={ok}", flush=True)

    applied_doc = dict(doc)
    applied_entries = []
    manifest_units = {u["id"]: u for u in manifest["units"]}
    for entry in subs:
        applied = dict(entry)
        unit = manifest_units.get(entry["unit_id"], {})
        slot = next(
            (s for s in unit.get("material_slots", []) if s.get("name") == entry["material_name"]),
            {},
        )
        face_count = int(slot.get("opaque_substitution_face_count", 0))
        applied["surface_face_count"] = face_count
        applied["applied"] = face_count > 0
        if face_count == 0:
            applied["application_note"] = "unused_material_slot"
        applied_entries.append(applied)
    applied_doc["substitutions"] = applied_entries
    applied_doc["applied_substitution_count"] = sum(1 for e in applied_entries if e["applied"])
    applied_doc["unused_material_slot_count"] = sum(1 for e in applied_entries if not e["applied"])
    applied_out = args["import_dir"] / "opaque_substitutions_applied.json"
    applied_out.write_text(json.dumps(applied_doc, ensure_ascii=False, indent=2))

    manifest["opaque_normalized"] = True
    manifest["opaque_substitutions_applied"] = len(ordered)
    manifest["opaque_substitution_slot_count"] = len(applied_entries)
    manifest["opaque_active_substitution_count"] = applied_doc["applied_substitution_count"]
    manifest["opaque_substitutions_ref"] = applied_out.name
    out_manifest = args["import_dir"] / "scene_manifest_opaque.json"
    out_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(
        f"[opaque] baked_units={baked_units} bake_fail={bake_fail} "
        f"obj_missing={obj_missing} material_missing={material_missing}",
        flush=True,
    )
    print(
        f"[opaque] applied_slots={applied_doc['applied_substitution_count']} "
        f"unused_slots={applied_doc['unused_material_slot_count']} wrote {applied_out}",
        flush=True,
    )
    print(f"[opaque] wrote {out_manifest}", flush=True)
    print("[opaque] DONE", flush=True)


if __name__ == "__main__":
    main()
