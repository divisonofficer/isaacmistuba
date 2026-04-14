from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

from robomituba_bridge.material_mapping import infer_material_kind, texture_for_slot
from robomituba_bridge.paths import resolve_repo_path
from robomituba_bridge.types import MaterialRecord, SceneSnapshot

from .types import SceneIR


@dataclass
class MitsubaSceneBuilder:
    """Builds a Mitsuba scene dict for mi.load_dict().

    MVP: constant emitter + perspective camera + diffuse meshes.
    """

    width: int = 768
    height: int = 768
    spp: int = 64

    def build(self, ir: SceneIR) -> Dict[str, Any]:
        scene = self._empty_scene()

        for i, mesh in enumerate(ir.meshes):
            scene[f'mesh_{i}'] = {
                'type': 'mesh',
                'vertex_positions': mesh.vertices,
                'faces': mesh.faces,
                'bsdf': {'type': 'diffuse', 'reflectance': {'type': 'rgb', 'value': [0.7, 0.7, 0.7]}},
            }

        return scene

    def build_snapshot(
        self,
        snapshot: SceneSnapshot,
        *,
        repo_root: str | Path,
        fallback_ir: SceneIR | None = None,
        render_mode: str = "rgb",
    ) -> Dict[str, Any]:
        scene = self._empty_scene()
        scene["sensor"] = self._sensor_from_snapshot(snapshot)
        self._apply_lights(scene, snapshot, repo_root=repo_root, render_mode=render_mode)

        material_by_id = {material.material_id: material for material in snapshot.materials}
        mesh_records_by_source = {mesh.source_path: mesh for mesh in snapshot.meshes}

        if any(mesh.geometry_path for mesh in snapshot.meshes):
            for index, mesh_record in enumerate(snapshot.meshes):
                if not mesh_record.geometry_path:
                    continue
                material = material_by_id.get(mesh_record.material_id or "")
                scene[f"mesh_{index}"] = self._obj_shape(mesh_record.geometry_path, material, repo_root=repo_root)
        elif fallback_ir is not None:
            for index, mesh in enumerate(fallback_ir.meshes):
                mesh_record = mesh_records_by_source.get(mesh.name)
                material = material_by_id.get(mesh_record.material_id or "") if mesh_record else None
                scene[f"mesh_{index}"] = {
                    "type": "mesh",
                    "vertex_positions": mesh.vertices,
                    "faces": mesh.faces,
                    "bsdf": self._material_to_bsdf(material, repo_root=repo_root),
                }
        else:
            raise RuntimeError("Snapshot did not include renderable geometry or a fallback USD mesh path.")

        return scene

    def _empty_scene(self) -> Dict[str, Any]:
        return {
            "type": "scene",
            "integrator": {"type": "path"},
            "emitter": {"type": "constant", "radiance": {"type": "rgb", "value": [2.0, 2.0, 2.0]}},
            "sensor": {
                "type": "perspective",
                "fov": 45,
                "to_world": self._lookat([0, 1.5, 4], [0, 1.0, 0], [0, 1, 0]),
                "sampler": {"type": "independent", "sample_count": self.spp},
                "film": {"type": "hdrfilm", "width": self.width, "height": self.height},
            },
        }

    def _sensor_from_snapshot(self, snapshot: SceneSnapshot) -> Dict[str, Any]:
        active_camera = None
        if snapshot.frame.active_camera_id:
            active_camera = next(
                (camera for camera in snapshot.cameras if camera.camera_id == snapshot.frame.active_camera_id),
                None,
            )
        if active_camera is None and snapshot.cameras:
            active_camera = snapshot.cameras[0]

        if active_camera is None:
            return self._empty_scene()["sensor"]

        to_world: Dict[str, Any]
        if active_camera.look_at:
            to_world = {
                "type": "lookat",
                "origin": active_camera.look_at["origin"],
                "target": active_camera.look_at["target"],
                "up": active_camera.look_at["up"],
            }
        elif active_camera.transform:
            to_world = {"type": "matrix", "value": active_camera.transform}
        else:
            to_world = self._lookat([0, 1.5, 4], [0, 1.0, 0], [0, 1, 0])

        film = {
            "type": "hdrfilm",
            "width": (active_camera.resolution or [self.width, self.height])[0],
            "height": (active_camera.resolution or [self.width, self.height])[1],
        }
        sensor: Dict[str, Any] = {
            "type": active_camera.projection,
            "fov": active_camera.fov_deg or 45,
            "to_world": to_world,
            "sampler": {"type": "independent", "sample_count": self.spp},
            "film": film,
        }
        return sensor

    def _apply_lights(
        self,
        scene: Dict[str, Any],
        snapshot: SceneSnapshot,
        *,
        repo_root: str | Path,
        render_mode: str,
    ) -> None:
        scene.pop("emitter", None)
        if not snapshot.lights:
            scene["emitter"] = {"type": "constant", "radiance": {"type": "rgb", "value": [2.0, 2.0, 2.0]}}
            return

        emitter_index = 0
        for light in snapshot.lights:
            if light.light_type == "envmap":
                entry: Dict[str, Any] = {"type": "envmap"}
                if light.texture_path:
                    entry["filename"] = str(resolve_repo_path(repo_root, light.texture_path))
                else:
                    entry["scale"] = 1.0
                scene[f"emitter_{emitter_index}"] = entry
                emitter_index += 1
                continue

            radiance = self._scaled_radiance(light.color, light.intensity, light.exposure, render_mode=render_mode)
            if light.light_type == "rectangle":
                entry = {
                    "type": "rectangle",
                    "emitter": {"type": "area", "radiance": {"type": "rgb", "value": radiance}},
                }
                if light.transform:
                    entry["to_world"] = {"type": "matrix", "value": light.transform}
                scene[f"light_{emitter_index}"] = entry
            elif light.light_type == "sphere":
                entry = {
                    "type": "sphere",
                    "radius": light.radius or 0.03,
                    "center": [0.0, 0.0, 0.0],
                    "emitter": {"type": "area", "radiance": {"type": "rgb", "value": radiance}},
                }
                if light.transform:
                    entry["to_world"] = {"type": "matrix", "value": light.transform}
                scene[f"light_{emitter_index}"] = entry
            else:
                if "emitter" not in scene:
                    scene["emitter"] = {"type": "constant", "radiance": {"type": "rgb", "value": radiance}}
            emitter_index += 1

        if "emitter" not in scene and not any(key.startswith("emitter_") or key.startswith("light_") for key in scene):
            scene["emitter"] = {"type": "constant", "radiance": {"type": "rgb", "value": [2.0, 2.0, 2.0]}}

    def _obj_shape(self, geometry_path: str, material: MaterialRecord | None, *, repo_root: str | Path) -> Dict[str, Any]:
        return {
            "type": "obj",
            "filename": str(resolve_repo_path(repo_root, geometry_path)),
            "bsdf": self._material_to_bsdf(material, repo_root=repo_root),
        }

    def _scaled_radiance(
        self,
        color: list[float] | None,
        intensity: float | None,
        exposure: float | None,
        *,
        render_mode: str,
    ) -> list[float]:
        base_color = color or [1.0, 1.0, 1.0]
        multiplier = (intensity or 1.0) * (2.0 ** (exposure or 0.0))
        if render_mode == "nir":
            multiplier *= 0.5
        return [float(channel * multiplier) for channel in base_color]

    def _material_to_bsdf(self, material: MaterialRecord | None, *, repo_root: str | Path) -> Dict[str, Any]:
        if material is None:
            return {"type": "diffuse", "reflectance": {"type": "rgb", "value": [0.7, 0.7, 0.7]}}

        kind = infer_material_kind(material)
        base_color_tex = texture_for_slot(material, "base_color", "albedo", "diffuse")
        roughness_tex = texture_for_slot(material, "roughness")

        if kind == "glass":
            bsdf: Dict[str, Any] = {
                "type": "roughdielectric" if (material.roughness or 0.0) > 0.0 or roughness_tex else "dielectric",
                "int_ior": material.ior or 1.5,
            }
            if bsdf["type"] == "roughdielectric":
                bsdf["alpha"] = self._texture_or_scalar(roughness_tex, material.roughness or 0.03, repo_root=repo_root)
        else:
            bsdf = {"type": "principled"}
            if base_color_tex:
                bsdf["base_color"] = self._bitmap_texture(base_color_tex, repo_root=repo_root)
            else:
                bsdf["base_color"] = {"type": "rgb", "value": material.base_color or [0.7, 0.7, 0.7]}
            if roughness_tex:
                bsdf["roughness"] = self._bitmap_texture(roughness_tex, repo_root=repo_root)
            else:
                bsdf["roughness"] = material.roughness if material.roughness is not None else 0.5
            if kind == "metal":
                bsdf["metallic"] = material.metallic if material.metallic is not None else 1.0
            if kind in {"plastic", "floor"} and material.metallic is not None:
                bsdf["metallic"] = material.metallic

        if material.double_sided:
            return {"type": "twosided", "bsdf": bsdf}
        return bsdf

    def _bitmap_texture(self, repo_relative_path: str, *, repo_root: str | Path) -> Dict[str, Any]:
        return {"type": "bitmap", "filename": str(resolve_repo_path(repo_root, repo_relative_path))}

    def _texture_or_scalar(self, repo_relative_path: str | None, value: float, *, repo_root: str | Path) -> Any:
        if repo_relative_path:
            return self._bitmap_texture(repo_relative_path, repo_root=repo_root)
        return value

    def _lookat(self, origin, target, up):
        # Mitsuba expects Transform4f-like matrix; mi.Transform4f.look_at exists when mi is available.
        # For now keep as a placeholder dict; caller can post-process.
        return {'type': 'lookat', 'origin': origin, 'target': target, 'up': up}
