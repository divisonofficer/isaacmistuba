"""Robomituba Isaac Extension — omni.ui panel."""
from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Any

_APPS_DIR = Path(__file__).resolve().parent.parent
if str(_APPS_DIR) not in sys.path:
    sys.path.insert(0, str(_APPS_DIR))

BSDF_OPTIONS = [
    "none",
    "diffuse",
    "roughplastic",
    "conductor",
    "roughconductor",
    "dielectric",
    "principled",
    "pplastic",
    "glossy_black_lacquer",
    "mirror_black_enamel",
]
SUBMIT_MODES = ["blocking", "async"]
MODALITY_OPTIONS = [
    "rgb",
    "depth",
    "albedo",
    "active_nir_intensity",
    "polar_rgb_preview",
    "s1",
    "s2",
    "dop",
    "aolp",
]

DEFAULT_DAEMON_URL = "http://127.0.0.1:8765"
DEFAULT_SCENE_REF = "out/moorelane_full_cam03_rgb_all/scene_curated_shell_furniture_sanitized.xml"
DEFAULT_SCENE_ID = "moorelane"


class RobomitubaPanel:
    """Main extension panel. Call destroy() on extension shutdown."""

    def __init__(self) -> None:
        import omni.ui as ui  # type: ignore

        self._ui = ui
        self._window: Any = None
        self._prim_bsdf_models: dict[str, Any] = {}
        self._modality_models: dict[str, Any] = {}
        self._result_label: Any = None
        self._build()

    def _build(self) -> None:
        ui = self._ui
        self._window = ui.Window("Robomituba Render", width=540, height=760)
        with self._window.frame:
            with ui.ScrollingFrame():
                with ui.VStack(spacing=6):
                    ui.Label("Daemon URL", height=20)
                    self._daemon_url_field = ui.StringField(height=24)
                    self._daemon_url_field.model.set_value(DEFAULT_DAEMON_URL)

                    ui.Label("Base Scene XML (repo-relative)", height=20)
                    self._scene_ref_field = ui.StringField(height=24)
                    self._scene_ref_field.model.set_value(DEFAULT_SCENE_REF)

                    ui.Label("Scene Snapshot Ref (repo-relative, optional)", height=20)
                    self._scene_snapshot_ref_field = ui.StringField(height=24)

                    ui.Label("Shape Map Ref (repo-relative)", height=20)
                    self._shape_map_ref_field = ui.StringField(height=24)

                    ui.Label("Scene ID", height=20)
                    self._scene_id_field = ui.StringField(height=24)
                    self._scene_id_field.model.set_value(DEFAULT_SCENE_ID)

                    ui.Label("Submit Mode", height=20)
                    self._submit_mode_combo = ui.ComboBox(0, *SUBMIT_MODES, width=160, height=24)

                    ui.Spacer(height=6)
                    ui.Label("Modalities", height=20)
                    with ui.VStack(spacing=3):
                        for mod in MODALITY_OPTIONS:
                            with ui.HStack(spacing=8, height=22):
                                cb = ui.CheckBox(width=20, height=20)
                                cb.model.set_value(mod in {"rgb", "depth"})
                                ui.Label(mod, width=180, height=20)
                                self._modality_models[mod] = cb.model

                    ui.Spacer(height=6)
                    refresh_btn = ui.Button("Refresh Stage Objects", height=30)
                    refresh_btn.set_clicked_fn(self._on_refresh)

                    ui.Label("Object BSDF Overrides", height=20)
                    self._prim_scroll = ui.ScrollingFrame(height=260)
                    self._prim_container = self._prim_scroll

                    ui.Spacer(height=8)
                    render_btn = ui.Button("Submit Render", height=36)
                    render_btn.set_clicked_fn(self._on_render)

                    ui.Spacer(height=6)
                    ui.Label("Result", height=20)
                    self._result_label = ui.Label("—", height=80, word_wrap=True)

    def _on_refresh(self) -> None:
        try:
            stage = self._get_stage()
            prims = self._collect_mesh_prim_paths(stage)
            self._rebuild_prim_list(prims)
            self._set_result(f"Loaded {len(prims)} mesh prims from the current stage.")
        except Exception as exc:  # pragma: no cover
            self._set_result(f"Refresh error: {exc}")

    def _on_render(self) -> None:
        self._set_result("Capturing stage and submitting render…")
        threading.Thread(target=self._do_render, daemon=True).start()

    def _do_render(self) -> None:
        try:
            from robomituba_bridge import BsdfOverride
            from stage_capture import capture_isaac_state
            from daemon_client import enqueue_isaac_state_render, submit_isaac_state_render

            stage = self._get_stage()
            daemon_url = self._daemon_url_field.model.get_value_as_string().strip()
            scene_ref = self._scene_ref_field.model.get_value_as_string().strip()
            scene_snapshot_ref = self._scene_snapshot_ref_field.model.get_value_as_string().strip() or None
            shape_map_ref = self._shape_map_ref_field.model.get_value_as_string().strip() or None
            scene_id = self._scene_id_field.model.get_value_as_string().strip() or DEFAULT_SCENE_ID
            submit_mode = SUBMIT_MODES[self._submit_mode_combo.model.get_item_value_model().get_value_as_int()]
            modalities = [name for name, model in self._modality_models.items() if model.get_value_as_bool()]
            if not modalities:
                modalities = ["rgb"]

            bsdf_overrides: dict[str, BsdfOverride] = {}
            for prim_path, (combo_model, _label) in self._prim_bsdf_models.items():
                selected = BSDF_OPTIONS[combo_model.get_item_value_model().get_value_as_int()]
                if selected == "none":
                    continue
                bsdf_overrides[prim_path] = BsdfOverride(bsdf_type=selected)

            needs_assist_light = any(
                modality in {"active_nir_intensity", "polar_rgb_preview", "s1", "s2", "dop", "aolp"}
                for modality in modalities
            )

            snapshot = capture_isaac_state(
                stage,
                scene_id=scene_id,
                mitsuba_scene_ref=scene_ref,
                scene_snapshot_ref=scene_snapshot_ref,
                shape_map_ref=shape_map_ref,
                bsdf_overrides_by_path=bsdf_overrides,
                modalities=modalities,
                submit_mode=submit_mode,
                scene_version="isaac_live",
                illumination_setup="ambient_room",
                assist_light=(
                    {
                        "mode": "camera_aligned_rect",
                        "distance_m": 0.14,
                        "size_world": [4.8, 3.6],
                        "spectrum_mode": "nir_grayscale_proxy",
                        "polarized": True,
                        "polarizer_angle_deg": 0.0,
                        "extras": {"radiance": 40.0},
                    }
                    if needs_assist_light
                    else None
                ),
            )

            if submit_mode == "blocking":
                result = submit_isaac_state_render(snapshot, daemon_url, timeout_s=180.0)
                artifact_lines = [
                    f"✓ {modality}: {', '.join(paths.values())}"
                    for modality, paths in result.get("artifacts", {}).items()
                ]
                manifest_path = result.get("manifest_path")
                header = f"Completed blocking render.\nmanifest: {manifest_path}" if manifest_path else "Completed blocking render."
                self._set_result("\n".join([header, *artifact_lines]).strip())
            else:
                accepted = enqueue_isaac_state_render(snapshot, daemon_url, timeout_s=15.0)
                self._set_result(
                    "\n".join(
                        [
                            f"Queued render job {accepted.get('job_id')}",
                            f"status: {accepted.get('status')}",
                            f"status_url: {accepted.get('status_url')}",
                        ]
                    )
                )
        except Exception as exc:  # pragma: no cover
            self._set_result(f"Error: {exc}")

    def _get_stage(self) -> Any:
        import omni.usd  # type: ignore

        stage = omni.usd.get_context().get_stage()
        if stage is None:
            raise RuntimeError("No USD stage open in Isaac Sim.")
        return stage

    def _collect_mesh_prim_paths(self, stage: Any) -> list[str]:
        from pxr import UsdGeom  # type: ignore

        return [str(prim.GetPath()) for prim in stage.Traverse() if prim.IsA(UsdGeom.Mesh)]

    def _rebuild_prim_list(self, prim_paths: list[str]) -> None:
        ui = self._ui
        self._prim_bsdf_models.clear()
        with self._prim_container:
            self._prim_container.clear()
            with ui.VStack(spacing=2):
                for prim_path in prim_paths:
                    with ui.HStack(height=24, spacing=4):
                        label = ui.Label(prim_path.split("/")[-1], width=180, height=24)
                        combo = ui.ComboBox(0, *BSDF_OPTIONS, width=180, height=24)
                        self._prim_bsdf_models[prim_path] = (combo.model, label)

    def _set_result(self, text: str) -> None:
        if self._result_label is not None:
            self._result_label.text = text

    def destroy(self) -> None:
        if self._window is not None:
            self._window.destroy()
            self._window = None
