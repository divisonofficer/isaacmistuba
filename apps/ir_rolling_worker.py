"""Long-lived stdio worker used by :mod:`render_ir_dataset_queue`.

The worker intentionally owns a single Mitsuba scene phase (``passive`` or
``flash_direct``).  Queue state and publication remain in the parent process;
this module only materializes a lease below ``.rolling_frames`` and reports a
small JSON result on stdout.  Keeping the scene process alive eliminates the
old 100-frame-batch process boundary without allowing concurrent workers to
write a shared index.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


class _Session:
    """Immutable scene setup plus mutable camera/render parameters for one phase."""

    def __init__(self, args: Any, renderer: ModuleType) -> None:
        self.args = args
        self.renderer = renderer
        self.phase = str(args.worker_phase)
        self.work_root = Path(args.out).resolve()
        self.staging_root = Path(args.rolling_staging_root).resolve()
        self.staging_root.mkdir(parents=True, exist_ok=True)
        if self.phase not in {"passive", "flash_direct"}:
            raise ValueError(f"unsupported rolling worker phase: {self.phase!r}")
        if args.render_full_path_active:
            raise ValueError("--worker-stdio does not support --render-full-path-active")

        source_scene_dir = Path(args.scene_dir).resolve()
        if (source_scene_dir / "ir_scene_domain.json").is_file():
            self.effective_contract = renderer.validate_ir_effective_scene(source_scene_dir)
            if self.effective_contract.get("surface_domain") != args.surface_domain:
                raise ValueError("prepared effective scene domain does not match worker --surface-domain")
            self.scene_dir = source_scene_dir
        else:
            # The queue normally passes a prepared immutable effective scene,
            # but keeping this path deterministic makes the worker useful for
            # a direct one-GPU diagnostic invocation as well.
            self.scene_dir = (args.effective_scene_dir or (self.work_root / "ir_effective_scene")).resolve()
            self.effective_contract = renderer.materialize_ir_effective_scene(
                source_scene_dir, self.scene_dir, surface_domain=args.surface_domain, reuse_existing=True,
            )
        self.canonical = json.loads((self.scene_dir / "material_canonical.json").read_text(encoding="utf-8"))
        graph = json.loads((self.scene_dir / "viewpoint_graph.json").read_text(encoding="utf-8"))
        self.nodes = {str(node["node_id"]): node for node in graph["nodes"]}

        self.render_input_audit = renderer._render_scene_audit(
            self.scene_dir / "render_scene.xml", self.effective_contract,
            polarized=bool(args.polar), observation_variant=str(args.observation_variant),
        )
        self.render_input_audit["texture_policy"] = {
            "max_resolution": int(args.texture_max_resolution),
            "cache_dir": str(args.texture_cache_dir) if args.texture_cache_dir is not None else None,
            "source_atlas_immutable": True,
        }
        self.render_input_audit["observation_sampling"] = {
            "rgb_spp": int(args.rgb_spp),
            "nir_ambient_spp": int(args.nir_ambient_spp),
            "nir_direct_spp": int(args.nir_direct_spp),
            "max_depth": int(args.max_depth),
        }

        render_scene_xml = self.scene_dir / "render_scene.xml"
        if int(args.texture_max_resolution) > 0:
            capped = self.work_root / f"scene_texture_max{args.texture_max_resolution}.xml"
            self.work_root.mkdir(parents=True, exist_ok=True)
            shutil.copy2(render_scene_xml, capped)
            source_cap = renderer.cap_scene_texture_resolution(
                capped, max_resolution=args.texture_max_resolution,
                cache_dir=args.texture_cache_dir, fail_on_unbounded=True,
            )
            self.render_input_audit["texture_policy"]["source_cap"] = {
                key: source_cap.get(key)
                for key in (
                    "texture_profile", "texture_refs", "downsampled_refs", "original_refs",
                    "original_gt_profile_refs", "missing_refs", "audit_ok", "rewritten", "skipped",
                )
            }
            render_scene_xml = capped

        import mitsuba as mi

        self.mi = mi
        self.variant = renderer._resolve_observation_variant(
            list(mi.variants()), polarized=bool(args.polar), requested=str(args.observation_variant),
        )
        mi.set_variant(self.variant)
        self.render_input_audit["observation_mitsuba_variant"] = self.variant
        self.render_input_audit["observation_variant_requested"] = str(args.observation_variant)

        flash_value = (
            args.nir_radiance / (4.0 * args.nir_half**2)
            if args.nir_flash_model == "area" else args.nir_radiance
        )
        if self.phase == "passive":
            xml_name, has_flash, flash_only, integrator = "scene_band_passive.xml", False, False, "path"
        else:
            xml_name, has_flash, flash_only, integrator = "scene_band_flash_direct.xml", True, True, "direct"
        self.xml_path = self.work_root / xml_name
        band_build = renderer.build_band_scene(
            render_scene_xml, self.canonical, self.xml_path, metadata_scene=self.scene_dir,
            band=args.band, nir_dir=(args.nir_cache_dir or self.work_root / f"nir_band_{args.band}"),
            nir_flash=has_flash, nir_flash_half_m=args.nir_half,
            nir_flash_initial_radiance=flash_value, nir_flash_model=args.nir_flash_model,
            nir_flash_beam_width_deg=args.nir_flash_beam_width,
            nir_flash_cutoff_angle_deg=args.nir_flash_cutoff_angle,
            max_depth=args.max_depth, integrator=integrator, force_analytic=True,
            polarized=args.polar, enforce_bsdf_contract=False, flash_only=flash_only,
        )
        renderer._resize_sensor(self.xml_path, args.width, args.height)
        band_build["texture_cap"] = renderer.cap_scene_texture_resolution(
            self.xml_path, max_resolution=args.texture_max_resolution,
            cache_dir=args.texture_cache_dir, fail_on_unbounded=args.texture_max_resolution > 0,
        )
        self.render_input_audit["band_scene_builds"] = [band_build]
        _atomic_json(self.work_root / "render_input_audit.json", self.render_input_audit)

        load_started = time.perf_counter()
        self.scene = mi.load_file(str(self.xml_path))
        self.params = mi.traverse(self.scene)
        self.keys = {
            "camera": next(key for key in self.params.keys() if key.endswith(".to_world") and "nir_flash" not in key),
            "fov": next((key for key in self.params.keys() if key.endswith(".x_fov")), None),
            "weights": [key for key in self.params.keys() if renderer.WEIGHT_RE.match(key)],
            "flash_tw": next((key for key in self.params.keys() if "nir_flash" in key and key.endswith(".to_world")), None),
        }
        self.scene_load_s = round(time.perf_counter() - load_started, 6)

    def _label(self, spec: str) -> tuple[dict[str, Any], np.ndarray]:
        node_id, separator, yaw_text = str(spec).strip().partition("@")
        if not separator or node_id not in self.nodes:
            raise ValueError(f"invalid worker viewpoint: {spec!r}")
        yaw = float(yaw_text)
        camera = self.renderer._camera(self.nodes[node_id], yaw)
        frame_id = f"{node_id}__h_{int(round(yaw)) % 360:03d}"
        camera_meta = self.renderer._camera_metadata(camera, self.args.fov, self.args.width, self.args.height)
        label: dict[str, Any] = {
            "schema": "robomituba.ir_frame.v3", "frame_id": frame_id,
            "surface_domain": str(self.effective_contract["surface_domain"]),
            "ir_scene_domain_ref": str((self.scene_dir / "ir_scene_domain.json").resolve()),
            "effective_scene_digest": str(self.effective_contract["effective_scene_digest"]),
            "viewpoint_id": node_id, "heading_deg": yaw,
            "camera_to_world": np.asarray(camera).tolist(),
            "intrinsics": camera_meta["intrinsics"], "extrinsics": camera_meta["extrinsics"],
            "camera_conventions": camera_meta["conventions"],
            "render_config": {
                "observation_spp": int(self.args.spp),
                "observation_spp_by_pass": {
                    "rgb": int(self.args.rgb_spp), "nir_ambient": int(self.args.nir_ambient_spp),
                    "nir_flash_direct": int(self.args.nir_direct_spp),
                },
                "max_depth": int(self.args.max_depth), "gt_subpixel": int(self.args.subpixel),
                "polarized": bool(self.args.polar),
                "mitsuba_runtime": os.environ.get("ROBOMITUBA_MITSUBA_RUNTIME", "unspecified"),
                "observation_mitsuba_variant": self.variant,
                "observation_variant_requested": str(self.args.observation_variant),
                "observation_protocol": "ambient_path_plus_flash_direct",
                "full_path_active_qc": False,
                "depth_convention": "camera_z", "range_convention": "euclidean_camera_ray",
                "gt_storage": self.args.gt_storage,
                "gt_artifact_layout": self.renderer._GT_ARTIFACT_LAYOUT if self.args.gt_storage == "png16" else "per_frame_legacy_v1",
                "gt_artifact_contract_ref": "gt_artifact_contract.json",
                "effective_scene_digest": str(self.effective_contract["effective_scene_digest"]),
                "specular_mask_policy": (self.effective_contract.get("specular_semantics") or {}).get("mask_semantics"),
                "nir_emitter": {
                    "product_model": "Advanced Illumination SL223-850IC", "nominal_wavelength_nm": 850,
                    "material_carrier_band_nm": int(self.args.band), "model": self.args.nir_flash_model,
                    "offset_y_m": float(self.args.nir_flash_offset_y), "aperture_diameter_m": 0.0079,
                    "beam_width_deg": float(self.args.nir_flash_beam_width),
                    "cutoff_angle_deg": float(self.args.nir_flash_cutoff_angle),
                },
            },
            "observation_paths": {}, "gt_paths": {}, "mask_paths": {},
            "material_canonical_ref": str((self.scene_dir / "material_canonical.json").resolve()),
            "opaque_substitutions_ref": (
                str((self.scene_dir / "opaque_substitutions_applied.json").resolve())
                if (self.scene_dir / "opaque_substitutions_applied.json").is_file() else None
            ),
        }
        return label, camera

    def _render(self, camera: np.ndarray, *, band: float, spp: int) -> tuple[np.ndarray, dict[str, np.ndarray], dict[str, float]]:
        total_started = time.perf_counter()
        sensor_to_world, light_to_world = self.renderer._render_rig_transforms(
            camera, offset_y_m=self.args.nir_flash_offset_y,
            area_half_m=self.args.nir_half if self.args.nir_flash_model == "area" else None,
        )
        self.params[self.keys["camera"]] = self.mi.Transform4f(sensor_to_world)
        if self.keys["fov"]:
            self.params[self.keys["fov"]] = float(self.args.fov)
        for key in self.keys["weights"]:
            self.params[key] = self.mi.Float(band)
        if self.keys["flash_tw"]:
            self.params[self.keys["flash_tw"]] = self.mi.Transform4f(light_to_world)
        self.params.update()
        update_s = time.perf_counter() - total_started
        self.renderer._sync_gpu()
        render_started = time.perf_counter()
        image = np.asarray(self.mi.render(self.scene, spp=int(spp), seed=7))
        render_s = time.perf_counter() - render_started
        sync_started = time.perf_counter()
        self.renderer._sync_gpu()
        timing = {
            "params_update_s": round(update_s, 6), "spp": int(spp),
            "mi_render_s": round(render_s, 6),
            "post_render_sync_s": round(time.perf_counter() - sync_started, 6),
            "total_s": round(time.perf_counter() - total_started, 6),
        }
        if self.args.polar:
            rgb, dop, aolp = self.renderer._stokes(image)
            return rgb, {"dop": dop, "aolp": aolp}, timing
        return image[..., :3].astype(np.float32), {}, timing

    def _replace_stage(self, source: Path, target: Path) -> None:
        if target.exists():
            shutil.rmtree(target)
        source.replace(target)

    def render_passive(self, spec: str, lease_id: str) -> dict[str, Any]:
        label, camera = self._label(spec)
        frame_id = label["frame_id"]
        target = self.staging_root / frame_id
        temporary = self.staging_root / f".{frame_id}.{lease_id}.passive.tmp"
        if temporary.exists():
            shutil.rmtree(temporary)
        temporary.mkdir(parents=True)
        rgb, _, rgb_timing = self._render(camera, band=0.0, spp=self.args.rgb_spp)
        ambient_rgb, _, ambient_timing = self._render(camera, band=1.0, spp=self.args.nir_ambient_spp)
        ambient = (ambient_rgb * self.renderer.LUMINANCE).sum(2).astype(np.float32)
        rgb_path = temporary / "rgb.exr"
        ambient_path = temporary / "nir_ambient.exr"
        self.renderer._write_exr(rgb_path, rgb)
        self.renderer._write_exr(ambient_path, ambient)
        payload = {
            "schema": "robomituba.ir_rolling_passive.v1", "frame_id": frame_id,
            "effective_scene_digest": self.effective_contract["effective_scene_digest"],
            "render_config": label["render_config"],
            # Persist final staging paths, not the temporary directory names:
            # resume validation happens after the atomic directory rename.
            "observation_paths": {
                "rgb": str((target / "rgb.exr").resolve()),
                "nir_ambient": str((target / "nir_ambient.exr").resolve()),
            },
            "render_timings_s": {"rgb": rgb_timing, "nir_ambient": ambient_timing},
            "completed_at": time.time(),
        }
        _atomic_json(temporary / "passive.json", payload)
        self._replace_stage(temporary, target)
        return {
            "frame_id": frame_id, "status": "passive_complete", "timings": payload["render_timings_s"],
            "rgb_max": float(rgb.max()), "ambient_max": float(ambient.max()),
        }

    def render_flash_direct(self, spec: str, lease_id: str) -> dict[str, Any]:
        label, camera = self._label(spec)
        frame_id = label["frame_id"]
        frame_dir = self.staging_root / frame_id
        passive_path = frame_dir / "passive.json"
        if not passive_path.is_file():
            raise FileNotFoundError(f"flash lease lacks passive staging: {frame_id}")
        passive = json.loads(passive_path.read_text(encoding="utf-8"))
        if passive.get("effective_scene_digest") != self.effective_contract["effective_scene_digest"]:
            raise RuntimeError(f"passive staging digest mismatch: {frame_id}")
        expected = label["render_config"]["observation_spp_by_pass"]
        actual = (passive.get("render_config") or {}).get("observation_spp_by_pass")
        if actual != expected:
            raise RuntimeError(f"passive staging sampling mismatch: {frame_id}")
        rgb_path = frame_dir / "rgb.exr"
        ambient_path = frame_dir / "nir_ambient.exr"
        if not rgb_path.is_file() or not ambient_path.is_file():
            raise FileNotFoundError(f"passive staging artifact missing: {frame_id}")
        flash_rgb, polar, flash_timing = self._render(camera, band=1.0, spp=self.args.nir_direct_spp)
        flash = (flash_rgb * self.renderer.LUMINANCE).sum(2).astype(np.float32)
        # Do not depend on OpenCV in the OptiX7 Python environment.  Mitsuba
        # owns EXR I/O already and preserves the scalar float32 carrier.
        ambient = np.asarray(self.mi.Bitmap(str(ambient_path)), np.float32)
        if ambient.ndim == 3:
            ambient = ambient[..., 0]
        active = ambient + flash
        paths = {
            "rgb": rgb_path, "nir_ambient": ambient_path,
            "nir_flash_direct": frame_dir / "nir_flash_direct.exr",
            "nir_active": frame_dir / "nir_active.exr", "nir_dflash": frame_dir / "nir_dflash.exr",
        }
        self.renderer._write_exr(paths["nir_flash_direct"], flash)
        self.renderer._write_exr(paths["nir_active"], active)
        self.renderer._write_exr(paths["nir_dflash"], flash)
        for name, values in polar.items():
            path = frame_dir / f"{name}.exr"
            self.renderer._write_exr(path, values)
            paths[name] = path
        label["observation_paths"] = {key: str(path.resolve()) for key, path in paths.items()}
        label["render_timings_s"] = {
            **dict(passive["render_timings_s"]), "nir_flash_direct": flash_timing,
            "observation_render_total_s": round(
                sum(item["total_s"] for item in (*dict(passive["render_timings_s"]).values(), flash_timing)), 6,
            ),
        }
        _atomic_json(frame_dir / "frame.json", label)
        _atomic_json(frame_dir / "complete.json", {
            "schema": "robomituba.ir_rolling_complete.v1", "frame_id": frame_id,
            "effective_scene_digest": self.effective_contract["effective_scene_digest"],
            "lease_id": lease_id, "completed_at": time.time(),
        })
        return {
            "frame_id": frame_id, "status": "complete", "timings": label["render_timings_s"],
            "flash_max": float(flash.max()), "active_max": float(active.max()),
        }

    def close(self) -> None:
        try:
            del self.scene, self.params
        finally:
            self.renderer._free_gpu()


def run_worker_stdio(args: Any, renderer: ModuleType) -> int:
    """Serve JSON-lines lease commands until the parent sends ``shutdown``."""
    try:
        session = _Session(args, renderer)
    except Exception as exc:
        print(json.dumps({"type": "fatal", "phase": args.worker_phase, "error": repr(exc)}), flush=True)
        return 2
    print(json.dumps({
        "type": "ready", "phase": session.phase, "variant": session.variant,
        "scene_load_s": session.scene_load_s,
        "audit_path": str((session.work_root / "render_input_audit.json").resolve()),
    }), flush=True)
    processed = 0
    try:
        for raw in sys.stdin:
            try:
                command = json.loads(raw)
                operation = command.get("op")
                if operation == "shutdown":
                    print(json.dumps({"type": "stopped", "phase": session.phase, "processed": processed}), flush=True)
                    return 0
                if operation != "render":
                    raise ValueError(f"unknown worker operation: {operation!r}")
                lease_id = str(command.get("lease_id") or "")
                viewpoints = command.get("viewpoints")
                if not lease_id or not isinstance(viewpoints, list) or not viewpoints:
                    raise ValueError("render command requires non-empty lease_id and viewpoints")
                results = []
                for spec in viewpoints:
                    frame_started = time.perf_counter()
                    if session.phase == "passive":
                        result = session.render_passive(str(spec), lease_id)
                    else:
                        result = session.render_flash_direct(str(spec), lease_id)
                    results.append(result)
                    # Report after the frame has been atomically staged, not
                    # only after the whole lease.  This makes a four-frame
                    # lease observable in real time while keeping manifest
                    # publication parent-owned.
                    print(json.dumps({
                        "type": "frame_complete", "phase": session.phase,
                        "lease_id": lease_id, "frame": result,
                        "worker_frame_wall_s": round(time.perf_counter() - frame_started, 6),
                    }), flush=True)
                    processed += 1
                    if processed % int(args.gpu_cleanup_interval) == 0:
                        renderer._free_gpu()
                print(json.dumps({
                    "type": "lease_complete", "phase": session.phase, "lease_id": lease_id,
                    "frames": results,
                }), flush=True)
            except Exception as exc:
                print(json.dumps({
                    "type": "lease_error", "phase": session.phase,
                    "lease_id": str((locals().get("command") or {}).get("lease_id") or ""),
                    "error": repr(exc),
                }), flush=True)
    finally:
        session.close()
    return 0
