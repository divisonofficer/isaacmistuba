"""Robomituba Isaac Extension — omni.ui panel."""
from __future__ import annotations

import asyncio
import os
import sys
import threading
import time
import webbrowser
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
SUBMIT_MODES = ["async", "blocking"]
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
DEFAULT_SCENE_REF = "out/moorelane_full_cam03_rgb_all/scene_full_sanitized_direct.xml"
DEFAULT_SCENE_ID = "moorelane"
RANGER_ACTIONS = [
    ("Forward", "forward"),
    ("Left", "left"),
    ("Stop", "stop"),
    ("Right", "right"),
    ("Backward", "backward"),
    ("Spin Left", "spin_left"),
    ("Spin Right", "spin_right"),
    ("Strafe Left", "strafe_left"),
    ("Strafe Right", "strafe_right"),
    ("Park", "park"),
]

_RUNTIME_SYNC_WATCH_FILES = (
    "__init__.py",
    "daemon_client.py",
    "extension.py",
    "material_override_layer.py",
    "stage_capture.py",
    "ui_panel.py",
)


def _runtime_extension_sync_status() -> dict[str, Any]:
    runtime_root = Path(__file__).resolve().parent
    repo_root_env = (
        os.environ.get("ROBOMITUBA_WINDOWS_REPO_ROOT")
        or os.environ.get("ROBOMITUBA_ROOT")
    )
    if not repo_root_env:
        return {
            "status": "unknown",
            "message": "Runtime sync status unknown: ROBOMITUBA_ROOT is not set.",
            "runtime_root": str(runtime_root),
            "source_root": None,
            "out_of_sync_files": [],
        }
    source_root = Path(repo_root_env) / "apps" / "isaac_extension"
    try:
        if runtime_root.samefile(source_root):
            return {
                "status": "live_source",
                "message": f"Runtime source: using repo extension directly ({source_root}).",
                "runtime_root": str(runtime_root),
                "source_root": str(source_root),
                "out_of_sync_files": [],
            }
    except Exception:
        pass
    if not source_root.exists():
        return {
            "status": "unknown",
            "message": f"Runtime sync status unknown: source extension not found at {source_root}.",
            "runtime_root": str(runtime_root),
            "source_root": str(source_root),
            "out_of_sync_files": [],
        }
    out_of_sync: list[str] = []
    for name in _RUNTIME_SYNC_WATCH_FILES:
        runtime_file = runtime_root / name
        source_file = source_root / name
        if not runtime_file.exists() or not source_file.exists():
            out_of_sync.append(name)
            continue
        try:
            if runtime_file.read_bytes() != source_file.read_bytes():
                out_of_sync.append(name)
        except Exception:
            out_of_sync.append(name)
    if out_of_sync:
        return {
            "status": "stale",
            "message": (
                "Runtime copy is stale. Restart Isaac using launch_isaac_with_robomituba.bat "
                f"to resync extension files. Changed: {', '.join(out_of_sync[:3])}"
                + (" ..." if len(out_of_sync) > 3 else "")
            ),
            "runtime_root": str(runtime_root),
            "source_root": str(source_root),
            "out_of_sync_files": out_of_sync,
        }
    return {
        "status": "synced",
        "message": f"Runtime copy synced from {source_root}.",
        "runtime_root": str(runtime_root),
        "source_root": str(source_root),
        "out_of_sync_files": [],
    }


class RobomitubaPanel:
    """Main extension panel. Call destroy() on extension shutdown."""

    def __init__(self) -> None:
        import omni.ui as ui  # type: ignore

        self._ui = ui
        self._window: Any = None
        self._session_window: Any = None
        self._optical_window: Any = None
        self._capture_window: Any = None
        self._jobs_window: Any = None
        self._runtime_sync_status = _runtime_extension_sync_status()
        self._runtime_sync_label: Any = None
        self._status_labels: dict[str, Any] = {}
        self._selection_inspector_label: Any = None
        self._optical_chain_label: Any = None
        self._optical_preview_container: Any = None
        self._optical_metadata_label: Any = None
        self._object_tree_container: Any = None
        self._scene_health_label: Any = None
        self._session_selection_label: Any = None
        self._session_job_summary_label: Any = None
        self._job_queue_container: Any = None
        self._timeline_label: Any = None
        self._capture_gallery_container: Any = None
        self._latest_capture_preview_container: Any = None
        self._operator_snapshot_label: Any = None
        self._override_source_label: Any = None
        self._override_layer_label: Any = None
        self._validation_label: Any = None
        self._scene_validation_label: Any = None
        self._material_scope_combo: Any = None
        self._material_scope_combo_model: Any = None
        self._material_grid_container: Any = None
        self._scene_records: list[dict[str, Any]] = []
        self._scene_combo: Any = None
        self._scene_combo_model: Any = None
        self._scene_picker_container: Any = None
        self._robot_picker_container: Any = None
        self._modality_models: dict[str, Any] = {}
        self._result_label: Any = None
        self._stop_event = threading.Event()
        self._last_logged_progress: tuple[str, str, str] | None = None
        self._selection_label: Any = None
        self._selected_bsdf_combo: Any = None
        self._daemon_material_records: list[dict[str, Any]] = []
        self._daemon_material_combo: Any = None
        self._daemon_material_combo_model: Any = None
        self._daemon_material_combo_changed_sub: Any = None
        self._daemon_material_picker_container: Any = None
        self._selected_daemon_material_label: Any = None
        self._last_selection_signature: tuple[str, ...] = ()
        self._last_viewport_camera_sync_key: tuple[str, tuple[Any, ...]] | None = None
        self._last_viewport_camera_sync_at: float = 0.0
        self._scene_state_dirty = True
        self._material_state_dirty = False
        self._stage_notice_registration: Any = None
        self._robot_records: list[dict[str, Any]] = []
        self._robot_combo: Any = None
        self._robot_combo_model: Any = None
        self._robot_list_label: Any = None
        self._keyboard_input: Any = None
        self._keyboard_device: Any = None
        self._keyboard_subscription: Any = None
        self._operator_health: dict[str, Any] = {}
        self._isaac_commands: list[dict[str, Any]] = []
        self._render_jobs: list[dict[str, Any]] = []
        self._capture_records: list[dict[str, Any]] = []
        self._object_inventory: list[dict[str, Any]] = []
        self._selected_optical_material: dict[str, Any] = {}
        self._last_operator_poll: dict[str, float] = {}
        self._operator_refresh_requested = False
        self._selection_refresh_requested = False
        self._material_picker_refresh_requested = False
        self._pending_selection_paths: list[str] = []
        self._pending_material_selected_key: str | None = None
        self._operator_refresh_lock = threading.Lock()
        self._ui_update_subscription: Any = None
        self._build()

    def _build(self) -> None:
        ui = self._ui
        self._session_window = ui.Window("RoboMitsuba Session", width=520, height=720)
        self._window = self._session_window
        with self._session_window.frame:
            with ui.VStack(spacing=8):
                self._build_status_strip()
                with ui.ScrollingFrame():
                    self._build_session_column()

        self._optical_window = ui.Window("RoboMitsuba Optical Inspector", width=1080, height=860)
        with self._optical_window.frame:
            with ui.ScrollingFrame():
                self._build_selection_material_column()
        self._set_window_visible(self._optical_window, False)
        self._dock_optical_with_property_panel()

        self._jobs_window = ui.Window("RoboMitsuba Jobs", width=540, height=640)
        with self._jobs_window.frame:
            with ui.ScrollingFrame():
                self._build_jobs_column()
        self._set_window_visible(self._jobs_window, False)

        self._capture_window = ui.Window("RoboMitsuba Capture Browser", width=540, height=620)
        with self._capture_window.frame:
            with ui.ScrollingFrame():
                self._build_capture_column()
        self._set_window_visible(self._capture_window, False)

        self._rebuild_scene_picker()
        self._do_refresh_scenes()
        self._setup_stage_dirty_tracking()
        self._attach_material_override_layer()
        self._setup_ui_update_subscription()
        threading.Thread(target=self._poll_remote_commands_loop, daemon=True).start()
        threading.Thread(target=self._poll_selection_loop, daemon=True).start()
        threading.Thread(target=self._poll_viewport_camera_loop, daemon=True).start()
        threading.Thread(target=self._poll_operator_state_loop, daemon=True).start()
        self._rebuild_daemon_material_picker()
        self._refresh_control_status()
        threading.Thread(target=self._do_refresh_daemon_materials, daemon=True).start()

    def _build_status_strip(self) -> None:
        ui = self._ui
        with ui.VStack(spacing=4, height=114):
            ui.Label("RoboMitsuba Session", height=22)
            with ui.HStack(spacing=6, height=34):
                self._status_chip("daemon", "Daemon", "unknown", width=118)
                self._status_chip("scene", "Scene", "-", width=118)
                self._status_chip("sync", "Sync", "dirty", width=118)
                self._status_chip("queue", "Queue", "idle", width=118)
            runtime_sync_message = str(self._runtime_sync_status.get("message") or "").strip()
            self._runtime_sync_label = ui.Label(runtime_sync_message or "Runtime sync: not checked", height=48, word_wrap=True)

    def _set_window_visible(self, window: Any, visible: bool) -> None:
        if window is None:
            return
        try:
            window.visible = visible
        except Exception:
            pass

    def _window_is_visible(self, window: Any) -> bool:
        if window is None:
            return False
        try:
            return bool(window.visible)
        except Exception:
            return True

    def _show_optical_window(self) -> None:
        self._set_window_visible(self._optical_window, True)
        self._dock_optical_with_property_panel()
        self._refresh_selection_label(self._selected_prim_paths())

    def _dock_optical_with_property_panel(self) -> None:
        async def _dock_when_ready() -> None:
            try:
                import omni.kit.app  # type: ignore
                import omni.ui as ui  # type: ignore

                for _ in range(8):
                    await omni.kit.app.get_app().next_update_async()
                    property_window = ui.Workspace.get_window("Property")
                    optical_window = ui.Workspace.get_window("RoboMitsuba Optical Inspector")
                    if property_window is not None and optical_window is not None:
                        optical_window.dock_in(property_window, ui.DockPosition.BOTTOM, 0.68)
                        return
            except Exception:
                return

        try:
            asyncio.ensure_future(_dock_when_ready())
        except Exception:
            pass

    def _show_jobs_window(self) -> None:
        self._set_window_visible(self._jobs_window, True)
        self._rebuild_job_queue()
        self._refresh_timeline()

    def _show_capture_window(self) -> None:
        self._set_window_visible(self._capture_window, True)
        self._rebuild_capture_gallery()

    def _build_main_columns(self) -> None:
        ui = self._ui
        with ui.HStack(spacing=12):
            with ui.ScrollingFrame(width=350):
                self._build_session_column()
            with ui.ScrollingFrame(width=450):
                self._build_selection_material_column()
            with ui.ScrollingFrame(width=390):
                self._build_pipeline_column()

    def _build_session_column(self) -> None:
        ui = self._ui
        with ui.VStack(spacing=12, width=490):
            with self._card("Scene / Session Rail"):
                with ui.VStack(spacing=8):
                    ui.Label("Daemon URL", height=18)
                    self._daemon_url_field = ui.StringField(height=24)
                    self._daemon_url_field.model.set_value(DEFAULT_DAEMON_URL)
                    self._operator_snapshot_label = ui.Label("Daemon: waiting\nWorker: unknown\nGPU: unavailable", height=76, word_wrap=True)
                    self._scene_picker_container = ui.VStack(height=58)
                    with self._scene_picker_container:
                        pass
                    with ui.HStack(spacing=6, height=30):
                        refresh_scenes_btn = ui.Button("Refresh", width=96, height=28)
                        refresh_scenes_btn.set_clicked_fn(self._on_refresh_scenes)
                        load_scene_btn = ui.Button("Load", width=86, height=28)
                        load_scene_btn.set_clicked_fn(self._on_load_scene)
                        connect_btn = ui.Button("Connect", width=96, height=28)
                        connect_btn.set_clicked_fn(self._on_connect)
                    with ui.HStack(spacing=6, height=30):
                        sync_btn = ui.Button("Sync Session", width=134, height=28)
                        sync_btn.set_clicked_fn(self._on_sync)
                        prepare_btn = ui.Button("Prepare", width=134, height=28)
                        prepare_btn.set_clicked_fn(self._on_prepare_render_ready)
                        render_btn = ui.Button("Render View", width=112, height=28)
                        render_btn.set_clicked_fn(self._on_render)
                    with ui.HStack(spacing=6, height=30):
                        optical_btn = ui.Button("Optical", width=96, height=28)
                        optical_btn.set_clicked_fn(self._show_optical_window)
                        jobs_btn = ui.Button("Jobs", width=82, height=28)
                        jobs_btn.set_clicked_fn(self._show_jobs_window)
                        captures_btn = ui.Button("Captures", width=104, height=28)
                        captures_btn.set_clicked_fn(self._show_capture_window)
                    with ui.CollapsableFrame("Advanced refs", height=0, collapsed=True):
                        with ui.VStack(spacing=4):
                            ui.Label("Base Scene XML", height=18)
                            self._scene_ref_field = ui.StringField(height=22)
                            self._scene_ref_field.model.set_value(DEFAULT_SCENE_REF)
                            ui.Label("Scene Snapshot Ref", height=18)
                            self._scene_snapshot_ref_field = ui.StringField(height=22)
                            ui.Label("Shape Map Ref", height=18)
                            self._shape_map_ref_field = ui.StringField(height=22)
                            ui.Label("Scene ID", height=18)
                            self._scene_id_field = ui.StringField(height=22)
                            self._scene_id_field.model.set_value(DEFAULT_SCENE_ID)
            with self._card("Scene Health"):
                with ui.VStack(spacing=6):
                    self._scene_health_label = ui.Label(
                        "Session: inactive\nRender readiness: not checked\nShape map: unknown\nOptical overrides: unavailable",
                        height=112,
                        word_wrap=True,
                    )
            with self._card("Selected Prim / Material"):
                with ui.VStack(spacing=8):
                    self._session_selection_label = ui.Label(
                        "Select a prim in the Isaac Stage tree to choose its optical material.",
                        height=54,
                        word_wrap=True,
                    )
                    material_btn = ui.Button("Choose Optical Material", height=32)
                    material_btn.set_clicked_fn(self._show_optical_window)
            with self._card("Queue Summary"):
                with ui.VStack(spacing=6):
                    self._session_job_summary_label = ui.Label(
                        "Queue: idle\nLatest job: none\nOpen Jobs for the full timeline.",
                        height=78,
                        word_wrap=True,
                    )
            with self._card("Render"):
                with ui.VStack(spacing=8):
                    with ui.HStack(spacing=8, height=28):
                        ui.Label("Submit", width=58, height=24)
                        self._submit_mode_combo = ui.ComboBox(0, *SUBMIT_MODES, width=126, height=24)
                    ui.Label("Modalities", height=18)
                    self._build_modality_grid()
            with self._card("Operation Log"):
                with ui.VStack(spacing=6):
                    self._result_label = ui.Label("-", height=130, word_wrap=True)

    def _build_selection_material_column(self) -> None:
        ui = self._ui
        with ui.VStack(spacing=12):
            with self._card("Selected Prim"):
                with ui.VStack(spacing=8):
                    self._selection_label = ui.Label("No selected prims synced yet.", height=22, word_wrap=True)
                    self._selection_inspector_label = ui.Label("Select a prim in the Isaac Stage tree.", height=96, word_wrap=True)
                    self._override_source_label = ui.Label("Resolved Mitsuba material: none", height=44, word_wrap=True)
                    self._override_layer_label = ui.Label("Override layer: not attached", height=34, word_wrap=True)
                    sync_selection_btn = ui.Button("Sync Selection", width=132, height=28)
                    sync_selection_btn.set_clicked_fn(self._on_sync_selection)
            with self._card("Optical Material Inspector"):
                with ui.VStack(spacing=8):
                    self._optical_chain_label = ui.Label(
                        "Isaac visual material: none\nSemantic mapping: none\nMitsuba override: none\nResolved optical material: scene default",
                        height=82,
                        word_wrap=True,
                    )
                    self._optical_preview_container = ui.VStack(height=132)
                    with self._optical_preview_container:
                        ui.Label("Material preview: unavailable", height=36, word_wrap=True)
                    self._optical_metadata_label = ui.Label(
                        "Type: unknown\nTags: -\nPolarization: unknown\nNIR response: unknown",
                        height=76,
                        word_wrap=True,
                    )
                    self._material_grid_container = ui.VStack(height=560)
                    with self._material_grid_container:
                        ui.Label("Material library previews: refresh materials.", height=36, word_wrap=True)
                    self._selected_daemon_material_label = ui.Label("Candidate optical material: refresh library", height=34, word_wrap=True)
                    self._daemon_material_picker_container = ui.VStack(height=28)
                    with self._daemon_material_picker_container:
                        pass
                    with ui.HStack(spacing=6, height=30):
                        refresh_materials_btn = ui.Button("Refresh Materials", width=142, height=28)
                        refresh_materials_btn.set_clicked_fn(self._on_refresh_daemon_materials)
                        open_material_browser_btn = ui.Button("Open Browser", width=126, height=28)
                        open_material_browser_btn.set_clicked_fn(self._on_open_material_browser)
                    with ui.HStack(spacing=6, height=30):
                        self._material_scope_combo = ui.ComboBox(0, "selected", "selected + children", "same visual material", "same semantic class", width=194, height=24)
                        self._material_scope_combo_model = self._material_scope_combo.model
                        apply_daemon_material_btn = ui.Button("Apply Preset", width=116, height=28)
                        apply_daemon_material_btn.set_clicked_fn(self._on_apply_daemon_material)
                    with ui.HStack(spacing=6, height=30):
                        self._selected_bsdf_combo = ui.ComboBox(0, *BSDF_OPTIONS, width=194, height=24)
                        apply_selected_btn = ui.Button("Apply BSDF", width=116, height=28)
                        apply_selected_btn.set_clicked_fn(self._on_apply_selected_override)
                        reset_material_btn = ui.Button("Reset", width=76, height=28)
                        reset_material_btn.set_clicked_fn(self._on_reset_usd_material_override)
                    self._validation_label = ui.Label("Validation: waiting for stage selection.", height=66, word_wrap=True)
            with self._card("Selection Validation"):
                with ui.VStack(spacing=6):
                    self._scene_validation_label = ui.Label(
                        "Selected prim: waiting\nScene validation: not checked\nMissing materials: unavailable\nExport issues: not checked",
                        height=96,
                        word_wrap=True,
                    )

    def _build_jobs_column(self) -> None:
        ui = self._ui
        with ui.VStack(spacing=12, width=510):
            with self._card("Job Queue + Timeline"):
                with ui.VStack(spacing=8):
                    self._job_queue_container = ui.VStack(height=220)
                    with self._job_queue_container:
                        ui.Label("No active jobs yet.", height=34, word_wrap=True)
                    self._timeline_label = ui.Label("Timeline: waiting for render activity.", height=110, word_wrap=True)
            with self._card("Bridge Pipeline"):
                with ui.VStack(spacing=6):
                    for label, state in (
                        ("Isaac connected", "waiting"),
                        ("USD export", "not checked"),
                        ("Shape map", "not checked"),
                        ("Material metadata", "waiting"),
                        ("Pose sync", "waiting"),
                        ("Render request", "idle"),
                        ("Capture attach", "not checked"),
                    ):
                        self._pipeline_row(label, state)
            with self._card("Render Log Tail"):
                with ui.VStack(spacing=6):
                    ui.Label("Detailed daemon log tail is unavailable in this V1 pane.", height=42, word_wrap=True)

    def _build_capture_column(self) -> None:
        ui = self._ui
        with ui.VStack(spacing=12, width=510):
            with self._card("Latest Capture"):
                with ui.VStack(spacing=8):
                    self._latest_capture_preview_container = ui.VStack(height=132)
                    with self._latest_capture_preview_container:
                        ui.Label("Latest capture preview: none", height=36, word_wrap=True)
                    with ui.HStack(spacing=6, height=30):
                        open_latest_btn = ui.Button("Open Latest", width=116, height=28)
                        open_latest_btn.set_clicked_fn(self._on_open_latest_capture)
                        jobs_btn = ui.Button("Jobs", width=80, height=28)
                        jobs_btn.set_clicked_fn(self._show_jobs_window)
            with self._card("Capture Gallery"):
                with ui.VStack(spacing=8):
                    self._capture_gallery_container = ui.VStack(height=360)
                    with self._capture_gallery_container:
                        ui.Label("No captures for the selected scene.", height=36, word_wrap=True)

    def _build_pipeline_column(self) -> None:
        self._build_jobs_column()

    def _card(self, title: str, width: int | None = None) -> Any:
        kwargs: dict[str, Any] = {"height": 0, "collapsed": False}
        if width is not None:
            kwargs["width"] = width
        return self._ui.CollapsableFrame(title, **kwargs)

    def _status_chip(self, key: str, label: str, state: str, *, width: int = 160) -> Any:
        chip = self._ui.Label(f"{label}: {state}", width=width, height=36, word_wrap=True)
        self._status_labels[key] = chip
        return chip

    def _pipeline_row(self, label: str, state: str, rerun_label: str | None = None) -> None:
        ui = self._ui
        with ui.HStack(spacing=6, height=24):
            ui.Label(label, width=160, height=22)
            ui.Label(state, width=90, height=22)
            if rerun_label:
                ui.Button(rerun_label, width=78, height=22)
            else:
                ui.Label("-", width=24, height=22)

    def _build_modality_grid(self) -> None:
        ui = self._ui
        rows = [MODALITY_OPTIONS[:5], MODALITY_OPTIONS[5:]]
        with ui.VStack(spacing=3):
            for row in rows:
                with ui.HStack(spacing=8, height=24):
                    for mod in row:
                        with ui.HStack(spacing=2, width=56, height=22):
                            cb = ui.CheckBox(width=18, height=18)
                            cb.model.set_value(mod in {"rgb", "depth"})
                            ui.Label(mod, width=34, height=18)
                            self._modality_models[mod] = cb.model

    def _build_robot_direction_pad(self) -> None:
        ui = self._ui
        rows = [
            [("Spin L", "spin_left"), ("Forward", "forward"), ("Spin R", "spin_right")],
            [("Left", "left"), ("Stop", "stop"), ("Right", "right")],
            [("Strafe L", "strafe_left"), ("Back", "backward"), ("Strafe R", "strafe_right")],
            [(None, None), ("Park", "park"), (None, None)],
        ]
        with ui.VStack(spacing=4):
            for row in rows:
                with ui.HStack(spacing=4, height=28):
                    for label, action in row:
                        if label is None:
                            ui.Spacer(width=86)
                            continue
                        btn = ui.Button(label, width=86, height=26)
                        btn.set_clicked_fn(lambda a=action: self._on_robot_action(a))

    def _on_render(self) -> None:
        self._set_result("Syncing state and rendering the current viewport…")
        scene_id = self._current_scene_id()
        threading.Thread(target=self._run_tracked_command, args=("render_current_view", scene_id, self._do_render), daemon=True).start()

    def _on_connect(self) -> None:
        self._set_result("Opening active Isaac scene session…")
        scene_id = self._current_scene_id()
        threading.Thread(target=self._run_tracked_command, args=("connect_session", scene_id, self._do_connect), daemon=True).start()

    def _on_sync(self) -> None:
        self._set_result("Syncing current stage state to daemon…")
        scene_id = self._current_scene_id()
        threading.Thread(target=self._run_tracked_command, args=("sync_session", scene_id, self._do_sync), daemon=True).start()

    def _on_refresh_scenes(self) -> None:
        self._set_result("Refreshing daemon scene catalog…")
        self._do_refresh_scenes()

    def _on_load_scene(self) -> None:
        self._set_result("Loading scene from daemon…")
        scene_id = self._current_scene_id()
        threading.Thread(target=self._run_tracked_command, args=("load_scene", scene_id, self._do_load_scene), daemon=True).start()

    def _on_open_latest_capture(self) -> None:
        self._set_result("Opening latest capture…")
        scene_id = self._current_scene_id()
        threading.Thread(target=self._run_tracked_command, args=("open_latest_capture", scene_id, self._do_open_latest_capture), daemon=True).start()

    def _on_prepare_render_ready(self) -> None:
        self._set_result("Preparing render-ready files from the current Isaac stage…")
        scene_id = self._current_scene_id()
        threading.Thread(target=self._run_tracked_command, args=("prepare_render_ready", scene_id, self._do_prepare_render_ready), daemon=True).start()

    def _on_open_material_browser(self) -> None:
        scene_id = self._current_scene_id()
        daemon_url = self._daemon_url_field.model.get_value_as_string().strip() or DEFAULT_DAEMON_URL
        if scene_id:
            webbrowser.open(f"{daemon_url}/scenes/{scene_id}#material-browser")
        else:
            webbrowser.open(f"{daemon_url}/scenes")

    def _on_sync_selection(self) -> None:
        try:
            self._push_selection_to_daemon()
        except Exception as exc:  # pragma: no cover
            self._set_result(f"Selection sync error: {exc}")

    def _on_refresh_daemon_materials(self) -> None:
        self._set_result("Refreshing render daemon materials…")
        threading.Thread(target=self._do_refresh_daemon_materials, daemon=True).start()

    def _on_apply_daemon_material(self) -> None:
        self._set_result("Applying render daemon material to the selected Isaac prims…")
        threading.Thread(target=self._do_apply_daemon_material, daemon=True).start()

    def _on_apply_selected_override(self) -> None:
        self._set_result("Applying BSDF override to the selected Isaac prims…")
        threading.Thread(target=self._do_apply_selected_override, args=(False,), daemon=True).start()

    def _on_clear_selected_override(self) -> None:
        self._set_result("Clearing BSDF override from the selected Isaac prims…")
        threading.Thread(target=self._do_apply_selected_override, args=(True,), daemon=True).start()

    def _on_reset_usd_material_override(self) -> None:
        self._set_result("Resetting RoboMitsuba material override on the selected scope…")
        threading.Thread(target=self._do_reset_usd_material_override, daemon=True).start()

    def _selected_robot_record(self) -> dict[str, Any] | None:
        if not self._robot_records or self._robot_combo_model is None:
            return None
        try:
            index = int(self._robot_combo_model.get_item_value_model().get_value_as_int())
        except Exception:
            return None
        if index < 0 or index >= len(self._robot_records):
            return None
        return self._robot_records[index]

    def _selected_robot_path(self) -> str | None:
        selected = self._selected_robot_record()
        return str(selected.get("prim_path")) if selected is not None else None

    def _refresh_robot_list_label(self) -> None:
        if self._robot_list_label is None:
            return
        if not self._robot_records:
            self._robot_list_label.text = "No RangerMini robots in the stage."
            return
        lines = []
        for item in self._robot_records[:6]:
            x, y, z = item.get("translation") or [0.0, 0.0, 0.0]
            lines.append(f"{item.get('name')}: ({x:.2f}, {y:.2f}, {z:.2f}) mode={item.get('motion_mode')}")
        if len(self._robot_records) > 6:
            lines.append(f"+{len(self._robot_records) - 6} more")
        self._robot_list_label.text = "\n".join(lines)

    def _rebuild_robot_picker(self, *, selected_path: str | None = None) -> None:
        ui = self._ui
        if selected_path is None:
            selected = self._selected_robot_record()
            if selected is not None:
                selected_path = str(selected.get("prim_path"))
        labels = [f"{item['name']} @ {item['prim_path']}" for item in self._robot_records] or ["(no RangerMini robots)"]
        if self._robot_picker_container is None:
            return
        with self._robot_picker_container:
            self._robot_picker_container.clear()
            self._robot_combo = ui.ComboBox(0, *labels, width=360, height=24)
            self._robot_combo_model = self._robot_combo.model
            if selected_path and self._robot_records:
                for index, item in enumerate(self._robot_records):
                    if str(item.get("prim_path")) == selected_path:
                        self._robot_combo_model.get_item_value_model().set_value(index)
                        break
        self._refresh_robot_list_label()

    def _refresh_robot_records(self, *, selected_path: str | None = None) -> None:
        try:
            try:
                from isaac_extension.ranger_mini_stage import list_ranger_mini_robots
            except ImportError:  # pragma: no cover - Isaac runtime fallback
                from ranger_mini_stage import list_ranger_mini_robots
            self._robot_records = list_ranger_mini_robots(self._get_stage())
            self._rebuild_robot_picker(selected_path=selected_path)
        except Exception:
            pass

    def _on_refresh_robots(self) -> None:
        self._refresh_robot_records(selected_path=self._selected_robot_path())
        self._set_result(f"Found {len(self._robot_records)} RangerMini robot(s) in the stage.")

    def _on_focus_robot(self) -> None:
        prim_path = self._selected_robot_path()
        if not prim_path:
            self._set_result("No RangerMini robot is selected.")
            return
        self._select_robot_prim(prim_path, focus=True, push_to_daemon=True)
        self._set_result(f"Focused {prim_path}")

    def _on_spawn_robot(self) -> None:
        self._set_result("Spawning RangerMini in the current stage…")
        self._do_spawn_robot()

    def _do_spawn_robot(self) -> None:
        try:
            try:
                from isaac_extension.ranger_mini_stage import spawn_ranger_mini
            except ImportError:  # pragma: no cover - Isaac runtime fallback
                from ranger_mini_stage import spawn_ranger_mini
            stage = self._get_stage()
            existing = len(self._robot_records)
            print(f"[RobomitubaPanel] spawn requested existing={existing}")
            result = spawn_ranger_mini(stage)
            print(f"[RobomitubaPanel] spawn completed result={result}")
            prim_path = str(result.get("prim_path") or "")
            self._refresh_robot_records(selected_path=prim_path or None)
            if prim_path:
                self._select_robot_prim(prim_path, focus=True, push_to_daemon=True)
            self._set_result(f"Spawned RangerMini at {result.get('prim_path')}")
        except Exception as exc:  # pragma: no cover
            print(f"[RobomitubaPanel] spawn failed error={exc}")
            self._set_result(f"Spawn robot error: {exc}")

    def _on_robot_action(self, action: str) -> None:
        self._do_robot_action(action)

    def _do_robot_action(self, action: str) -> None:
        try:
            try:
                from isaac_extension.ranger_mini_stage import command_robot
            except ImportError:  # pragma: no cover - Isaac runtime fallback
                from ranger_mini_stage import command_robot
            prim_path = self._selected_robot_path()
            if not prim_path:
                raise RuntimeError("No RangerMini robot is selected.")
            result = command_robot(self._get_stage(), prim_path, action)
            self._refresh_robot_records(selected_path=prim_path)
            self._set_result(f"{action} -> {result.get('prim_path')}")
        except Exception as exc:  # pragma: no cover
            self._set_result(f"Robot control error: {exc}")

    def _select_robot_prim(self, prim_path: str, *, focus: bool = False, push_to_daemon: bool = False) -> None:
        if not prim_path:
            return
        try:
            import omni.usd  # type: ignore

            selection = omni.usd.get_context().get_selection()
            selection.set_selected_prim_paths([str(prim_path)], False)
        except Exception:
            return
        self._refresh_selection_label([str(prim_path)])
        self._last_selection_signature = None
        if push_to_daemon:
            try:
                self._push_selection_to_daemon()
            except Exception:
                pass
        if focus:
            self._focus_stage_selection()

    def _focus_stage_selection(self) -> None:
        try:
            from omni.kit.viewport.utility import get_active_viewport  # type: ignore

            viewport = get_active_viewport()
            for attr_name in ("frame_viewport_selection", "focus_on_selected", "frame_selection"):
                callback = getattr(viewport, attr_name, None)
                if callable(callback):
                    callback()
                    return
        except Exception:
            pass

    def _setup_keyboard_shortcuts(self) -> None:
        try:
            import carb.input  # type: ignore
            import omni.appwindow  # type: ignore

            app_window = omni.appwindow.get_default_app_window()
            if app_window is None:
                return
            keyboard = app_window.get_keyboard()
            if keyboard is None:
                return
            input_iface = carb.input.acquire_input_interface()
            self._keyboard_input = input_iface
            self._keyboard_device = keyboard
            self._keyboard_subscription = input_iface.subscribe_to_keyboard_events(keyboard, self._on_keyboard_event)
        except Exception:
            self._keyboard_input = None
            self._keyboard_device = None
            self._keyboard_subscription = None

    def _on_keyboard_event(self, event: Any, *args: Any) -> bool:
        del args
        try:
            import carb.input  # type: ignore
        except Exception:
            return True

        event_type = getattr(event, "type", None)
        key = getattr(event, "input", None)
        is_press = event_type in {
            getattr(carb.input.KeyboardEventType, "KEY_PRESS", None),
            getattr(carb.input.KeyboardEventType, "KEY_REPEAT", None),
        }
        is_release = event_type == getattr(carb.input.KeyboardEventType, "KEY_RELEASE", None)
        if not is_press and not is_release:
            return True

        action = None
        if key == getattr(carb.input.KeyboardInput, "UP", None):
            action = "forward" if is_press else "stop"
        elif key == getattr(carb.input.KeyboardInput, "DOWN", None):
            action = "backward" if is_press else "stop"
        elif key == getattr(carb.input.KeyboardInput, "LEFT", None):
            action = "left" if is_press else "stop"
        elif key == getattr(carb.input.KeyboardInput, "RIGHT", None):
            action = "right" if is_press else "stop"
        elif key == getattr(carb.input.KeyboardInput, "Q", None) and is_press:
            action = "spin_left"
        elif key == getattr(carb.input.KeyboardInput, "E", None) and is_press:
            action = "spin_right"
        elif key == getattr(carb.input.KeyboardInput, "SPACE", None) and is_press:
            action = "stop"
        elif key == getattr(carb.input.KeyboardInput, "P", None) and is_press:
            action = "park"

        if action is not None and self._selected_robot_path():
            self._do_robot_action(action)
        return True

    def _selected_scene_record(self) -> dict[str, Any] | None:
        if not self._scene_records or self._scene_combo_model is None:
            return None
        try:
            index = int(self._scene_combo_model.get_item_value_model().get_value_as_int())
        except Exception:
            return None
        if index < 0 or index >= len(self._scene_records):
            return None
        return self._scene_records[index]

    def _populate_fields_from_scene(self, scene_record: dict[str, Any]) -> None:
        self._scene_id_field.model.set_value(str(scene_record.get("scene_id") or DEFAULT_SCENE_ID))
        self._scene_ref_field.model.set_value(str(scene_record.get("mitsuba_scene_ref") or ""))
        self._scene_snapshot_ref_field.model.set_value(str(scene_record.get("scene_snapshot_ref") or ""))
        self._shape_map_ref_field.model.set_value(str(scene_record.get("shape_map_ref") or ""))

    def _current_scene_id(self) -> str | None:
        selected = self._selected_scene_record()
        if selected is not None and selected.get("scene_id"):
            return str(selected.get("scene_id"))
        value = self._scene_id_field.model.get_value_as_string().strip()
        return value or None

    def _selected_prim_paths(self) -> list[str]:
        try:
            try:
                from isaac_extension.stage_capture import capture_selected_prim_paths
            except ImportError:  # pragma: no cover - Isaac runtime fallback
                from stage_capture import capture_selected_prim_paths
            return capture_selected_prim_paths()
        except Exception:
            return []

    def _mark_scene_state_dirty(self, *, reason: str | None = None) -> None:
        self._scene_state_dirty = True
        self._refresh_control_status()
        if reason:
            self._log_progress("sync_state", self._current_scene_id(), "running", "state_dirty", reason, "isaac_stage", None)

    def _mark_material_state_dirty(self, *, reason: str | None = None) -> None:
        self._material_state_dirty = True
        self._refresh_control_status()
        if reason:
            self._log_progress("sync_state", self._current_scene_id(), "running", "material_dirty", reason, "isaac_stage", None)

    def _clear_sync_dirty_flags(self, *, clear_state: bool = True, clear_material: bool = True) -> None:
        if clear_state:
            self._scene_state_dirty = False
        if clear_material:
            self._material_state_dirty = False
        self._refresh_control_status()

    def _setup_stage_dirty_tracking(self) -> None:
        try:
            from pxr import Tf, Usd  # type: ignore

            stage = self._get_stage()
            if stage is None:
                return
            if self._stage_notice_registration is not None:
                try:
                    self._stage_notice_registration.Revoke()
                except Exception:
                    pass
            self._stage_notice_registration = Tf.Notice.Register(Usd.Notice.ObjectsChanged, self._on_stage_objects_changed, stage)
        except Exception:
            self._stage_notice_registration = None

    def _attach_material_override_layer(self) -> None:
        try:
            try:
                from isaac_extension.material_override_layer import attach_existing_override_layer, default_override_layer_path
            except ImportError:  # pragma: no cover - Isaac runtime fallback
                from material_override_layer import attach_existing_override_layer, default_override_layer_path

            stage = self._get_stage()
            scene_id = self._current_scene_id() or DEFAULT_SCENE_ID
            layer = attach_existing_override_layer(stage, scene_id=scene_id)
            layer_path = str(default_override_layer_path(stage, scene_id=scene_id))
            if self._override_layer_label is not None:
                status = "attached" if layer is not None else "ready"
                self._override_layer_label.text = f"Override layer: {status} · {layer_path}"
        except Exception:
            pass

    def _on_stage_objects_changed(self, notice: Any, _sender: Any) -> None:
        try:
            resynced = [str(path) for path in notice.GetResyncedPaths() if str(path)]
            changed = [str(path) for path in notice.GetChangedInfoOnlyPaths() if str(path)]
        except Exception:
            self._mark_scene_state_dirty(reason="Stage changes detected in Isaac.")
            return
        changed_paths = resynced or changed
        if not changed_paths:
            return
        self._mark_scene_state_dirty(reason=f"Stage edits detected ({len(changed_paths)} path(s)).")

    def _refresh_selection_label(self, prim_paths: list[str]) -> None:
        self._refresh_session_selection_summary(prim_paths)
        if self._selection_label is None:
            return
        if not prim_paths:
            self._selection_label.text = "No selected prims synced yet."
            self._refresh_selected_daemon_material_status(prim_paths)
            self._refresh_selection_inspector(prim_paths)
            return
        preview = ", ".join(path.split("/")[-1] or path for path in prim_paths[:3])
        if len(prim_paths) > 3:
            preview = f"{preview} +{len(prim_paths) - 3}"
        self._selection_label.text = f"Selected prims: {preview}"
        self._refresh_selection_inspector(prim_paths)

    def _refresh_session_selection_summary(self, prim_paths: list[str]) -> None:
        if self._session_selection_label is None:
            return
        if not prim_paths:
            self._session_selection_label.text = (
                "Select a prim in the Isaac Stage tree to choose its optical material."
            )
            return
        first = prim_paths[0]
        name = first.rsplit("/", 1)[-1] or first
        suffix = f" +{len(prim_paths) - 1}" if len(prim_paths) > 1 else ""
        self._session_selection_label.text = (
            f"Selected: {name}{suffix}\n"
            "Optical Inspector is open for material preview, picker, apply, and reset."
        )

    def _refresh_control_status(self) -> None:
        if not self._status_labels:
            return
        daemon_url = ""
        try:
            daemon_url = self._daemon_url_field.model.get_value_as_string().strip()
        except Exception:
            daemon_url = DEFAULT_DAEMON_URL
        scene_id = self._current_scene_id()
        daemon_state = "connected" if self._scene_records else ("configured" if daemon_url else "disconnected")
        if self._material_state_dirty:
            sync_state = "materials dirty"
        elif self._scene_state_dirty:
            sync_state = "stage dirty"
        else:
            sync_state = "clean"
        labels = {
            "daemon": f"Daemon: {daemon_state}",
            "scene": f"Scene: {scene_id or '-'}",
            "sync": f"Sync: {sync_state}",
            "queue": (
                f"Queue: {self._operator_health.get('worker_state', 'idle')} "
                f"({self._operator_health.get('queue_length', 0)} waiting)"
            ),
        }
        for key, text in labels.items():
            label = self._status_labels.get(key)
            if label is not None:
                label.text = text

    def _refresh_selection_inspector(self, prim_paths: list[str]) -> None:
        if self._selection_inspector_label is None:
            return
        if not prim_paths:
            self._selection_inspector_label.text = "Select a prim in the Isaac Stage tree."
            self._selected_optical_material = {}
            self._refresh_optical_material_panel([])
            if self._override_source_label is not None:
                self._override_source_label.text = "Resolved Mitsuba material: none"
            if self._validation_label is not None:
                self._validation_label.text = "Validation: no selected prim."
            if self._scene_validation_label is not None:
                self._scene_validation_label.text = (
                    "Selected prim: none\n"
                    "Scene validation: not checked\n"
                    "Missing materials: unavailable\n"
                    "Export issues: not checked"
                )
            return
        path = prim_paths[0]
        try:
            stage = self._get_stage()
            prim = stage.GetPrimAtPath(path)
            type_name = prim.GetTypeName() if prim and prim.IsValid() else "invalid"
            is_mesh = self._prim_is_mesh(prim)
            visual_material = self._bound_visual_material_path(prim)
            semantic = self._semantic_label(prim)
            export_status = "mesh/exportable" if is_mesh else "non-mesh or group"
            self._selection_inspector_label.text = "\n".join(
                [
                    f"Prim: {path}",
                    f"Type: {type_name} · {export_status}",
                    f"Visual material: {visual_material or 'none'}",
                    f"Semantic: {semantic or 'none'}",
                ]
            )
            try:
                from isaac_extension.material_override_layer import resolve_material_override
            except ImportError:  # pragma: no cover - Isaac runtime fallback
                from material_override_layer import resolve_material_override
            resolved = resolve_material_override(stage, path, scene_id=self._current_scene_id() or DEFAULT_SCENE_ID)
            if self._override_source_label is not None:
                source = resolved.source if resolved.source_path is None else f"{resolved.source} @ {resolved.source_path}"
                self._override_source_label.text = f"Resolved Mitsuba material: {resolved.label}\nSource: {source}"
            if self._override_layer_label is not None:
                self._override_layer_label.text = f"Override layer: {resolved.layer_path or 'unknown'}"
            if self._validation_label is not None:
                warnings = []
                if not is_mesh:
                    warnings.append("selected prim is not a Mesh; apply scope may expand to child meshes")
                if resolved.source == "none":
                    warnings.append("no explicit Mitsuba override")
                self._validation_label.text = "Validation: " + ("; ".join(warnings) if warnings else "selected prim is ready")
            if self._scene_validation_label is not None:
                selected_status = "mesh/exportable" if is_mesh else "non-mesh or group"
                self._scene_validation_label.text = "\n".join(
                    [
                        f"Selected prim: {selected_status}",
                        "Scene validation: not checked",
                        "Missing materials: unavailable",
                        "Export issues: not checked",
                    ]
                )
            self._refresh_optical_material_panel(prim_paths)
        except Exception as exc:
            self._selection_inspector_label.text = f"Inspector error: {exc}"
            self._refresh_optical_material_panel(prim_paths)

    def _prim_is_mesh(self, prim: Any) -> bool:
        try:
            from pxr import UsdGeom  # type: ignore

            return bool(prim and prim.IsValid() and prim.IsA(UsdGeom.Mesh))
        except Exception:
            return False

    def _bound_visual_material_path(self, prim: Any) -> str | None:
        if not prim or not prim.IsValid():
            return None
        try:
            try:
                from isaac_extension.material_override_layer import bound_visual_material_path
            except ImportError:  # pragma: no cover - Isaac runtime fallback
                from material_override_layer import bound_visual_material_path

            return bound_visual_material_path(prim)
        except Exception:
            return None

    def _semantic_label(self, prim: Any) -> str | None:
        if not prim or not prim.IsValid():
            return None
        for name in ("semantic:class", "semantic:label", "Semantics:semanticType", "Semantics:semanticData"):
            try:
                attr = prim.GetAttribute(name)
                if attr and attr.Get():
                    return str(attr.Get())
            except Exception:
                continue
        return None

    def _selected_material_scope(self) -> str:
        labels = ["selected", "children", "same_visual", "same_semantic"]
        try:
            index = int(self._material_scope_combo_model.get_item_value_model().get_value_as_int())
            return labels[index]
        except Exception:
            return "selected"

    def _expanded_material_scope_paths(self, stage: Any, prim_paths: list[str]) -> list[str]:
        try:
            try:
                from isaac_extension.material_override_layer import expand_material_scope
            except ImportError:  # pragma: no cover - Isaac runtime fallback
                from material_override_layer import expand_material_scope

            return expand_material_scope(stage, prim_paths, scope=self._selected_material_scope())
        except Exception:
            return prim_paths

    def _daemon_material_label(self, record: dict[str, Any]) -> str:
        group = str(record.get("group_display_name") or record.get("dataset_id") or "Material")
        name = str(record.get("display_name") or record.get("material_id") or "material")
        return f"{group} / {name}"

    def _rebuild_daemon_material_picker(self, *, selected_key: str | None = None) -> None:
        ui = self._ui
        if self._daemon_material_picker_container is None:
            return
        labels = [self._daemon_material_label(item) for item in self._daemon_material_records] or ["(refresh material library)"]
        with self._daemon_material_picker_container:
            self._daemon_material_picker_container.clear()
            self._daemon_material_combo = ui.ComboBox(0, *labels, width=470, height=24)
            self._daemon_material_combo_model = self._daemon_material_combo.model
            if selected_key and self._daemon_material_records:
                for index, item in enumerate(self._daemon_material_records):
                    if str(item.get("key")) == selected_key:
                        self._daemon_material_combo_model.get_item_value_model().set_value(index)
                        break
            try:
                self._daemon_material_combo_changed_sub = self._daemon_material_combo_model.add_item_changed_fn(
                    lambda *_args: self._refresh_candidate_optical_material_status()
                )
            except Exception:
                self._daemon_material_combo_changed_sub = None
        self._rebuild_daemon_material_grid()

    def _rebuild_daemon_material_grid(self) -> None:
        ui = self._ui
        if self._material_grid_container is None:
            return
        selected = self._selected_daemon_material_record()
        selected_key = str(selected.get("key")) if selected else ""
        columns = 8
        card_width = 118
        image_size = 88
        row_height = 132
        with self._material_grid_container:
            self._material_grid_container.clear()
            if not self._daemon_material_records:
                ui.Label("Material library previews: refresh materials.", height=36, word_wrap=True)
                return
            with ui.ScrollingFrame(height=548):
                with ui.VStack(spacing=8):
                    for start in range(0, len(self._daemon_material_records), columns):
                        row = self._daemon_material_records[start : start + columns]
                        with ui.HStack(spacing=8, height=row_height):
                            for offset, material in enumerate(row):
                                index = start + offset
                                key = str(material.get("key") or "")
                                title = str(material.get("display_name") or material.get("material_id") or "material")
                                prefix = "[selected] " if key and key == selected_key else ""
                                with ui.VStack(spacing=3, width=card_width, height=row_height - 4):
                                    local_path = None
                                    try:
                                        try:
                                            from isaac_extension.daemon_client import material_preview_local_path
                                        except ImportError:  # pragma: no cover - Isaac runtime fallback
                                            from daemon_client import material_preview_local_path
                                        local_path = material_preview_local_path(
                                            material,
                                            repo_root=os.environ.get("ROBOMITUBA_WINDOWS_REPO_ROOT")
                                            or os.environ.get("ROBOMITUBA_ROOT")
                                            or "",
                                        )
                                    except Exception:
                                        local_path = None
                                    if self._is_isaac_image_path(local_path):
                                        try:
                                            ui.Image(local_path, width=image_size, height=image_size)
                                        except Exception:
                                            ui.Label(self._material_swatch_hint(material), height=image_size, word_wrap=True)
                                    else:
                                        ui.Label(self._material_swatch_hint(material), height=image_size, word_wrap=True)
                                    btn = ui.Button((prefix + title)[:32], height=28)
                                    btn.set_clicked_fn(lambda i=index: self._select_daemon_material_index(i))
                            for _ in range(columns - len(row)):
                                ui.Spacer(width=card_width)

    def _select_daemon_material_index(self, index: int) -> None:
        if index < 0 or index >= len(self._daemon_material_records):
            return
        if self._daemon_material_combo_model is not None:
            try:
                self._daemon_material_combo_model.get_item_value_model().set_value(index)
            except Exception:
                pass
        self._refresh_candidate_optical_material_status()
        self._rebuild_daemon_material_grid()

    def _selected_daemon_material_record(self) -> dict[str, Any] | None:
        if not self._daemon_material_records or self._daemon_material_combo_model is None:
            return None
        try:
            index = int(self._daemon_material_combo_model.get_item_value_model().get_value_as_int())
        except Exception:
            return None
        if index < 0 or index >= len(self._daemon_material_records):
            return None
        return self._daemon_material_records[index]

    def _refresh_candidate_optical_material_status(self) -> None:
        material = self._selected_daemon_material_record()
        if self._selected_daemon_material_label is not None:
            if material is None:
                self._selected_daemon_material_label.text = "Candidate optical material: refresh material library"
            else:
                self._selected_daemon_material_label.text = f"Candidate optical material: {self._daemon_material_label(material)}"
        self._refresh_material_preview(material)

    def _refresh_material_preview(self, material: dict[str, Any] | None) -> None:
        ui = self._ui
        if self._optical_preview_container is None:
            return
        if self._optical_window is not None and not self._window_is_visible(self._optical_window):
            return
        with self._optical_preview_container:
            self._optical_preview_container.clear()
            local_path = None
            if material:
                try:
                    try:
                        from isaac_extension.daemon_client import material_preview_local_path
                    except ImportError:  # pragma: no cover - Isaac runtime fallback
                        from daemon_client import material_preview_local_path
                    local_path = material_preview_local_path(material, repo_root=os.environ.get("ROBOMITUBA_WINDOWS_REPO_ROOT") or os.environ.get("ROBOMITUBA_ROOT") or "")
                except Exception:
                    local_path = None
            if self._is_isaac_image_path(local_path):
                try:
                    ui.Image(local_path, width=132, height=112)
                except Exception:
                    ui.Label(f"Preview image:\n{local_path}", height=70, word_wrap=True)
            elif material:
                swatch = self._material_swatch_hint(material)
                ui.Label(f"Preview sphere: cached image unavailable\n{swatch}", height=70, word_wrap=True)
            else:
                ui.Label("Material preview: select or refresh an optical material.", height=52, word_wrap=True)

    def _refresh_optical_material_panel(self, prim_paths: list[str]) -> None:
        material = self._selected_daemon_material_record()
        path = prim_paths[0] if prim_paths else None
        visual_material = "none"
        semantic = "none"
        resolved_label = "scene default"
        resolved_source = "none"
        override_source = "none"
        inheritance = "not bound"
        tags: list[str] = []
        if path:
            try:
                stage = self._get_stage()
                prim = stage.GetPrimAtPath(path)
                visual = self._bound_visual_material_path(prim)
                semantic_value = self._semantic_label(prim)
                visual_material = visual or "none"
                semantic = semantic_value or "none"
                inheritance = "inherited/bound" if visual else "not bound"
                try:
                    from isaac_extension.material_override_layer import resolve_material_override
                except ImportError:  # pragma: no cover - Isaac runtime fallback
                    from material_override_layer import resolve_material_override
                resolved = resolve_material_override(stage, path, scene_id=self._current_scene_id() or DEFAULT_SCENE_ID)
                resolved_label = resolved.label or "scene default"
                resolved_source = resolved.source or "none"
                override_source = resolved.source if resolved.source != "none" else "none"
            except Exception:
                pass
        if material:
            mat_type = str(material.get("bsdf_type") or material.get("kind") or "unknown")
            category = str(material.get("category") or "")
            caps = material.get("capabilities") if isinstance(material.get("capabilities"), dict) else {}
            tags = [item for item in (category, mat_type, "polarized" if caps.get("polarization") else "") if item]
        else:
            mat_type = "unknown"
            caps = {}
        if self._optical_chain_label is not None:
            self._optical_chain_label.text = "\n".join(
                [
                    f"Isaac visual material: {visual_material} ({inheritance})",
                    f"Semantic mapping: {semantic}",
                    f"Mitsuba override: {override_source}",
                    f"Resolved optical material: {resolved_label} ({resolved_source})",
                ]
            )
        if self._optical_metadata_label is not None:
            roughness = self._material_roughness_hint(material)
            polar = "supported" if caps.get("polarization") else ("unknown" if not caps else "not advertised")
            nir = "available" if caps.get("nir") else ("medium/unknown" if mat_type in {"measured", "measured_polarized"} else "unknown")
            self._optical_metadata_label.text = "\n".join(
                [
                    f"Type: {mat_type}",
                    f"Roughness: {roughness}",
                    f"Tags: {', '.join(tags) if tags else '-'}",
                    f"Polarization: {polar}",
                    f"NIR response: {nir}",
                ]
            )
        self._refresh_candidate_optical_material_status()

    def _material_roughness_hint(self, material: dict[str, Any] | None) -> str:
        if not material:
            return "unknown"
        for key in ("roughness", "alpha", "alpha_u"):
            value = material.get(key)
            if value not in (None, ""):
                return str(value)
        desc = str(material.get("description") or "").lower()
        if "rough" in desc:
            return "rough"
        if "mirror" in desc or "gloss" in desc:
            return "low"
        return "unknown"

    def _material_swatch_hint(self, material: dict[str, Any]) -> str:
        name = str(material.get("display_name") or material.get("material_id") or "material")
        mat_type = str(material.get("bsdf_type") or material.get("kind") or "unknown")
        category = str(material.get("category") or "optical")
        return f"{name} · {category} · {mat_type}"

    def _is_isaac_image_path(self, path: str | None) -> bool:
        if not path:
            return False
        value = str(path)
        if value.startswith("\\\\"):
            return False
        return (len(value) > 1 and value[1] == ":") or Path(value).exists()

    def _do_refresh_daemon_materials(self) -> None:
        try:
            try:
                from isaac_extension.daemon_client import get_material_library
            except ImportError:  # pragma: no cover - Isaac runtime fallback
                from daemon_client import get_material_library

            daemon_url = self._daemon_url_field.model.get_value_as_string().strip()
            payload = get_material_library(daemon_url=daemon_url, timeout_s=10.0)
            records: list[dict[str, Any]] = []
            for group in payload.get("groups") or []:
                if not isinstance(group, dict):
                    continue
                dataset_id = str(group.get("dataset_id") or "")
                group_name = str(group.get("display_name") or dataset_id)
                strategy = str(group.get("mitsuba_strategy") or "")
                for material in group.get("materials") or []:
                    if not isinstance(material, dict):
                        continue
                    kind = str(material.get("kind") or ("curated" if dataset_id == "curated" else "measured"))
                    status = str(material.get("status") or "")
                    native_file = str(material.get("native_file") or "")
                    if kind == "curated":
                        pass
                    elif status != "available" or not native_file:
                        continue
                    else:
                        kind = "measured"
                    material_id = str(material.get("material_id") or "")
                    if not material_id:
                        continue
                    record = {
                        "key": f"{dataset_id}:{material_id}",
                        "kind": kind,
                        "dataset_id": dataset_id,
                        "group_display_name": group_name,
                        "material_id": material_id,
                        "display_name": str(material.get("display_name") or material_id),
                        "native_file": native_file,
                        "bsdf_type": "measured" if strategy == "measured" else "measured_polarized",
                        "category": str(material.get("category") or group.get("category") or ""),
                        "description": str(material.get("description") or ""),
                        "status": status,
                        "capabilities": dict(group.get("capabilities") or {}),
                        "preview_path": str(material.get("preview_path") or material.get("preview_png") or ""),
                    }
                    records.append(record)
            selected = self._selected_daemon_material_record()
            selected_key = str(selected.get("key")) if selected else None
            self._daemon_material_records = records
            self._request_material_picker_refresh(selected_key)
            self._set_result(f"Loaded {len(records)} render daemon material(s).")
        except Exception as exc:  # pragma: no cover
            if self._selected_daemon_material_label is not None:
                self._selected_daemon_material_label.text = f"Selected material override: unavailable ({exc})"
            self._set_result(f"Material library refresh error: {exc}")

    def _format_override_detail(self, detail: dict[str, Any] | str | None) -> str:
        if detail is None:
            return "scene/default"
        if isinstance(detail, str):
            return detail
        bsdf_type = str(detail.get("bsdf_type") or "unknown")
        if bsdf_type == "curated":
            extras = detail.get("extras") if isinstance(detail.get("extras"), dict) else {}
            return str(extras.get("curated_display_name") or detail.get("material_id") or "curated")
        dataset_id = detail.get("dataset_id")
        material_id = detail.get("material_id")
        if dataset_id or material_id:
            return f"{bsdf_type}: {dataset_id or 'dataset'}/{material_id or 'material'}"
        return bsdf_type

    def _refresh_selected_daemon_material_status(self, prim_paths: list[str] | None = None) -> None:
        if self._selected_daemon_material_label is None:
            return
        prim_paths = list(prim_paths if prim_paths is not None else self._selected_prim_paths())
        if not prim_paths:
            self._selected_daemon_material_label.text = "Selected material override: no selected prim"
            return
        try:
            try:
                from isaac_extension.daemon_client import get_isaac_session
            except ImportError:  # pragma: no cover - Isaac runtime fallback
                from daemon_client import get_isaac_session
            daemon_url = self._daemon_url_field.model.get_value_as_string().strip()
            payload = get_isaac_session(daemon_url=daemon_url, timeout_s=2.0)
            session = payload.get("session") if isinstance(payload.get("session"), dict) else {}
            details = session.get("material_override_details") if isinstance(session.get("material_override_details"), dict) else {}
            simple = session.get("material_overrides") if isinstance(session.get("material_overrides"), dict) else {}
            first = prim_paths[0]
            detail = details.get(first) if first in details else simple.get(first)
            label = self._format_override_detail(detail)
            suffix = ""
            if len(prim_paths) > 1:
                applied = sum(1 for path in prim_paths if path in details or path in simple)
                suffix = f" ({applied}/{len(prim_paths)} selected have overrides)"
            self._selected_daemon_material_label.text = f"Selected material override: {label}{suffix}"
        except Exception as exc:
            self._selected_daemon_material_label.text = f"Selected material override: unknown ({exc})"

    def _push_selection_to_daemon(self) -> None:
        try:
            from isaac_extension.daemon_client import update_isaac_selection
        except ImportError:  # pragma: no cover - Isaac runtime fallback
            from daemon_client import update_isaac_selection

        daemon_url = self._daemon_url_field.model.get_value_as_string().strip()
        prim_paths = self._selected_prim_paths()
        signature = tuple(prim_paths)
        if signature == self._last_selection_signature:
            return
        self._last_selection_signature = signature
        self._request_selection_refresh(prim_paths)
        if daemon_url:
            update_isaac_selection(prim_paths, daemon_url=daemon_url, timeout_s=2.0)

    def _poll_selection_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._push_selection_to_daemon()
            except Exception:
                pass
            time.sleep(1.0)

    def _poll_viewport_camera_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._push_viewport_camera_to_daemon()
            except Exception:
                pass
            time.sleep(0.1)

    def _push_viewport_camera_to_daemon(self) -> None:
        try:
            from isaac_extension.daemon_client import sync_active_viewport_camera_to_daemon
        except ImportError:  # pragma: no cover - Isaac runtime fallback
            from daemon_client import sync_active_viewport_camera_to_daemon

        daemon_url = self._daemon_url_field.model.get_value_as_string().strip()
        if not daemon_url:
            return
        scene_id = self._current_scene_id()
        if not scene_id:
            return
        try:
            from isaac_extension.daemon_client import capture_active_viewport_camera_signature
        except ImportError:  # pragma: no cover - Isaac runtime fallback
            from daemon_client import capture_active_viewport_camera_signature

        signature = capture_active_viewport_camera_signature()
        if signature is None:
            return
        sync_key = (scene_id, signature)
        now = time.monotonic()
        if sync_key == self._last_viewport_camera_sync_key and now - self._last_viewport_camera_sync_at < 0.25:
            return
        self._last_viewport_camera_sync_key = sync_key
        self._last_viewport_camera_sync_at = now
        sync_active_viewport_camera_to_daemon(
            daemon_url=daemon_url,
            timeout_s=0.08,
            modalities=["rgb"],
        )

    def _poll_operator_state_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                now = time.monotonic()
                daemon_url = self._daemon_url()
                if now - self._last_operator_poll.get("health", 0.0) >= 1.0:
                    self._operator_health = self._fetch_operator_health(daemon_url)
                    self._last_operator_poll["health"] = now
                if now - self._last_operator_poll.get("jobs", 0.0) >= 2.0:
                    self._isaac_commands = self._fetch_isaac_commands(daemon_url)
                    self._render_jobs = self._fetch_render_jobs(daemon_url)
                    self._last_operator_poll["jobs"] = now
                if now - self._last_operator_poll.get("inventory", 0.0) >= 3.0:
                    self._object_inventory = self._fetch_object_inventory(daemon_url)
                    self._last_operator_poll["inventory"] = now
                scene_id = self._current_scene_id()
                if scene_id and now - self._last_operator_poll.get("captures", 0.0) >= 5.0:
                    self._capture_records = self._fetch_scene_captures(daemon_url, scene_id)
                    self._last_operator_poll["captures"] = now
                self._request_operator_console_refresh()
            except Exception:
                pass
            time.sleep(0.5)

    def _setup_ui_update_subscription(self) -> None:
        try:
            import omni.kit.app  # type: ignore

            stream = omni.kit.app.get_app().get_update_event_stream()
            self._ui_update_subscription = stream.create_subscription_to_pop(
                self._on_ui_update_tick,
                name="robomituba_operator_console_refresh",
            )
        except Exception:
            self._ui_update_subscription = None

    def _request_operator_console_refresh(self) -> None:
        with self._operator_refresh_lock:
            self._operator_refresh_requested = True

    def _request_selection_refresh(self, prim_paths: list[str]) -> None:
        with self._operator_refresh_lock:
            self._pending_selection_paths = list(prim_paths)
            self._selection_refresh_requested = True

    def _request_material_picker_refresh(self, selected_key: str | None) -> None:
        with self._operator_refresh_lock:
            self._pending_material_selected_key = selected_key
            self._material_picker_refresh_requested = True

    def _on_ui_update_tick(self, _event: Any) -> None:
        with self._operator_refresh_lock:
            requested = self._operator_refresh_requested
            self._operator_refresh_requested = False
            selection_requested = self._selection_refresh_requested
            selection_paths = list(self._pending_selection_paths)
            self._selection_refresh_requested = False
            material_requested = self._material_picker_refresh_requested
            material_selected_key = self._pending_material_selected_key
            self._material_picker_refresh_requested = False
        if requested and not self._stop_event.is_set():
            self._refresh_operator_console()
        if selection_requested and not self._stop_event.is_set():
            if selection_paths:
                self._set_window_visible(self._optical_window, True)
            self._refresh_selection_label(selection_paths)
        if material_requested and not self._stop_event.is_set():
            self._rebuild_daemon_material_picker(selected_key=material_selected_key)
            self._refresh_candidate_optical_material_status()

    def _daemon_url(self) -> str:
        try:
            return self._daemon_url_field.model.get_value_as_string().strip() or DEFAULT_DAEMON_URL
        except Exception:
            return DEFAULT_DAEMON_URL

    def _fetch_operator_health(self, daemon_url: str) -> dict[str, Any]:
        try:
            try:
                from isaac_extension.daemon_client import get_health
            except ImportError:  # pragma: no cover - Isaac runtime fallback
                from daemon_client import get_health
            return get_health(daemon_url=daemon_url, timeout_s=1.5)
        except Exception as exc:
            return {"status": "unavailable", "error": str(exc)}

    def _fetch_isaac_commands(self, daemon_url: str) -> list[dict[str, Any]]:
        try:
            try:
                from isaac_extension.daemon_client import list_isaac_commands
            except ImportError:  # pragma: no cover - Isaac runtime fallback
                from daemon_client import list_isaac_commands
            return list_isaac_commands(daemon_url=daemon_url, timeout_s=2.0)[:30]
        except Exception:
            return []

    def _fetch_render_jobs(self, daemon_url: str) -> list[dict[str, Any]]:
        try:
            try:
                from isaac_extension.daemon_client import list_render_jobs
            except ImportError:  # pragma: no cover - Isaac runtime fallback
                from daemon_client import list_render_jobs
            return list_render_jobs(daemon_url=daemon_url, limit=40, timeout_s=2.0)
        except Exception:
            return []

    def _fetch_scene_captures(self, daemon_url: str, scene_id: str) -> list[dict[str, Any]]:
        try:
            try:
                from isaac_extension.daemon_client import list_scene_captures
            except ImportError:  # pragma: no cover - Isaac runtime fallback
                from daemon_client import list_scene_captures
            return list_scene_captures(scene_id, daemon_url=daemon_url, timeout_s=2.5)[:12]
        except Exception:
            return []

    def _fetch_object_inventory(self, daemon_url: str) -> list[dict[str, Any]]:
        try:
            try:
                from isaac_extension.daemon_client import get_isaac_session_inventory
            except ImportError:  # pragma: no cover - Isaac runtime fallback
                from daemon_client import get_isaac_session_inventory
            return get_isaac_session_inventory(daemon_url=daemon_url, timeout_s=2.0)
        except Exception:
            return []

    def _refresh_operator_console(self) -> None:
        self._refresh_control_status()
        self._refresh_operator_snapshot()
        self._refresh_scene_health()
        self._refresh_session_job_summary()
        if self._window_is_visible(self._jobs_window):
            self._rebuild_job_queue()
            self._refresh_timeline()
        if self._window_is_visible(self._capture_window):
            self._rebuild_capture_gallery()

    def _refresh_operator_snapshot(self) -> None:
        if self._operator_snapshot_label is None:
            return
        health = self._operator_health
        gpu_text = "GPU: unavailable"
        gpus = health.get("gpus")
        if isinstance(gpus, list) and gpus:
            first = gpus[0] if isinstance(gpus[0], dict) else {}
            gpu_text = f"GPU: {first.get('util_pct', '?')}% · {first.get('mem_used_mb', '?')}/{first.get('mem_total_mb', '?')} MB"
        active = health.get("active_isaac_command")
        active_text = "Active command: none"
        if isinstance(active, dict):
            active_text = f"Active command: {active.get('command_type')} · {active.get('progress_stage') or active.get('status')}"
        self._operator_snapshot_label.text = "\n".join(
            [
                f"Daemon: {health.get('status', 'unknown')} · {self._daemon_url()}",
                f"Worker: {health.get('worker_state', 'unknown')} · queue {health.get('queue_length', 0)}",
                active_text,
                gpu_text,
            ]
        )

    def _refresh_scene_health(self) -> None:
        if self._scene_health_label is None:
            return
        health = self._operator_health
        session_state = "active" if health.get("isaac_connected") else "inactive"
        scene_id = self._current_scene_id() or health.get("isaac_scene_id") or "-"
        selected = self._selected_prim_paths()
        override_count = sum(1 for item in self._object_inventory if item.get("override_bsdf"))
        shape_count = sum(int(item.get("shape_count") or 0) for item in self._object_inventory if int(item.get("depth") or 0) == 0)
        dirty_bits = []
        if self._scene_state_dirty:
            dirty_bits.append("stage dirty")
        if self._material_state_dirty:
            dirty_bits.append("materials dirty")
        sync_state = ", ".join(dirty_bits) if dirty_bits else "clean"
        active_stage = health.get("active_stage")
        active_cmd = health.get("active_isaac_command")
        if not active_stage and isinstance(active_cmd, dict):
            active_stage = active_cmd.get("progress_stage")
        self._scene_health_label.text = "\n".join(
            [
                f"Session: {session_state} · scene {scene_id}",
                f"Sync: {sync_state}",
                f"Render readiness: {active_stage or 'idle'}",
                f"Optical overrides: {override_count}",
                f"Shape coverage: {shape_count or 'unknown'} shapes",
                f"Selected prims: {len(selected)}",
            ]
        )

    def _rebuild_object_tree(self) -> None:
        ui = self._ui
        if self._object_tree_container is None:
            return
        selected = set(self._selected_prim_paths())
        with self._object_tree_container:
            self._object_tree_container.clear()
            if not self._object_inventory:
                ui.Label("No session inventory yet. Connect and sync to inspect object hierarchy.", height=48, word_wrap=True)
                return
            rows = sorted(
                self._object_inventory,
                key=lambda item: tuple(str(item.get("path") or "").split("/")),
            )[:16]
            for item in rows:
                path = str(item.get("path") or item.get("prim_path") or "")
                depth = int(item.get("depth") or max(0, path.count("/") - 1))
                name = str(item.get("name") or path.rsplit("/", 1)[-1] or path)
                marker = ">" if path in selected else " "
                override = " M" if item.get("override_bsdf") else ""
                shapes = int(item.get("shape_count") or 0)
                label = f"{marker} {'  ' * min(depth, 4)}{name}{override} · shapes {shapes}"
                btn = ui.Button(label[:64], height=22)
                btn.set_clicked_fn(lambda p=path: self._select_inventory_prim(p))

    def _refresh_session_job_summary(self) -> None:
        if self._session_job_summary_label is None:
            return
        rows = self._job_rows_for_console()
        active = next((row for row in rows if row.get("status") == "running"), None)
        queued = sum(1 for row in rows if row.get("status") == "queued")
        failed = next((row for row in rows if row.get("status") == "failed"), None)
        latest = rows[0] if rows else None
        if active:
            latest_text = f"Running: {active.get('title')} · {active.get('stage') or active.get('status')}"
        elif failed:
            latest_text = f"Needs attention: {failed.get('title')} · failed"
        elif latest:
            latest_text = f"Latest: {latest.get('title')} · {latest.get('status') or 'unknown'}"
        else:
            latest_text = "Latest: none"
        self._session_job_summary_label.text = "\n".join(
            [
                f"Worker: {self._operator_health.get('worker_state', 'idle')} · queued {queued}",
                latest_text,
                "Open Jobs for queue, timeline, and pipeline detail.",
            ]
        )

    def _select_inventory_prim(self, prim_path: str) -> None:
        if prim_path:
            self._select_robot_prim(prim_path, focus=False, push_to_daemon=True)

    def _rebuild_job_queue(self) -> None:
        ui = self._ui
        if self._job_queue_container is None:
            return
        rows = self._job_rows_for_console()
        with self._job_queue_container:
            self._job_queue_container.clear()
            if not rows:
                ui.Label("No active or recent jobs.", height=34, word_wrap=True)
                return
            for row in rows[:8]:
                tone = self._status_glyph(row.get("status"))
                title = str(row.get("title") or row.get("id") or "job")
                stage = str(row.get("stage") or row.get("status") or "")
                scene = str(row.get("scene_id") or "-")
                ui.Label(f"{tone} {title} · {stage} · {scene}", height=22, word_wrap=True)

    def _job_rows_for_console(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        active = self._operator_health.get("active_isaac_command")
        if isinstance(active, dict):
            rows.append(self._isaac_command_row(active))
        seen_cmd_ids = {str(active.get("command_id"))} if isinstance(active, dict) else set()
        for command in self._isaac_commands:
            cid = str(command.get("command_id") or "")
            if cid in seen_cmd_ids:
                continue
            if command.get("status") in {"queued", "dispatched", "running", "failed", "succeeded"}:
                rows.append(self._isaac_command_row(command))
        for job in self._render_jobs:
            rows.append(
                {
                    "kind": "render",
                    "id": str(job.get("job_id") or ""),
                    "title": f"Render {str(job.get('job_id') or '')[:14]}",
                    "status": str(job.get("status") or ""),
                    "stage": str(job.get("progress_stage") or ""),
                    "scene_id": str(job.get("scene_id") or ""),
                }
            )
        status_rank = {"running": 0, "dispatched": 0, "queued": 1, "failed": 2, "succeeded": 3}
        rows.sort(key=lambda row: status_rank.get(str(row.get("status") or ""), 4))
        return rows

    def _isaac_command_row(self, command: dict[str, Any]) -> dict[str, Any]:
        command_type = str(command.get("command_type") or "command")
        status = str(command.get("status") or "")
        normalized = "running" if status == "dispatched" else status
        return {
            "kind": "isaac",
            "id": str(command.get("command_id") or ""),
            "title": f"Isaac {command_type.replace('_', ' ')}",
            "status": normalized,
            "stage": str(command.get("progress_stage") or command.get("progress_message") or ""),
            "scene_id": str(command.get("scene_id") or ""),
        }

    def _status_glyph(self, status: Any) -> str:
        value = str(status or "")
        if value in {"running", "dispatched"}:
            return "[run]"
        if value == "queued":
            return "[queue]"
        if value == "succeeded":
            return "[ok]"
        if value == "failed":
            return "[fail]"
        if value == "cancelled":
            return "[cancel]"
        return "[idle]"

    def _refresh_timeline(self) -> None:
        if self._timeline_label is None:
            return
        active = next((row for row in self._job_rows_for_console() if row.get("status") == "running"), None)
        stage = str(active.get("stage") or "") if active else ""
        steps = [
            ("Session", {"picked_up", "ensuring_session", "opening_session", "collecting_scene_refs"}),
            ("Capture", {"capturing_view", "capturing_stage_state", "syncing_viewport_camera"}),
            ("Submit", {"sending_capture_request", "polling_render", "queued"}),
            ("XML", {"staging_scene"}),
            ("GPU", {"loading_scene"}),
            ("Render", {"rendering", "ambient", "active", "polar"}),
            ("Save", {"saving_output"}),
            ("Manifest", {"writing_manifest", "complete", "ready"}),
        ]
        labels = []
        active_seen = False
        for label, aliases in steps:
            if stage in aliases:
                labels.append(f"[{label}]")
                active_seen = True
            elif active_seen:
                labels.append(label.lower())
            else:
                labels.append(label)
        self._timeline_label.text = "Timeline:\n" + " -> ".join(labels) + (f"\nCurrent: {stage}" if stage else "\nCurrent: idle")

    def _rebuild_capture_gallery(self) -> None:
        ui = self._ui
        self._rebuild_latest_capture_preview()
        if self._capture_gallery_container is None:
            return
        with self._capture_gallery_container:
            self._capture_gallery_container.clear()
            if not self._capture_records:
                ui.Label("No captures for the selected scene.", height=36, word_wrap=True)
                return
            for capture in self._capture_records[:5]:
                camera = str(capture.get("camera_id") or capture.get("camera_name") or "camera")
                status = str(capture.get("status") or "completed")
                timestamp = str(capture.get("timestamp") or "")[:19]
                mods = ", ".join(str(item) for item in (capture.get("modalities") or [])[:6])
                ui.Label(f"{self._status_glyph(status)} {camera} · {timestamp}\n{mods}", height=42, word_wrap=True)
                with ui.HStack(spacing=6, height=24):
                    open_btn = ui.Button("Open Bundle", width=116, height=22)
                    open_btn.set_clicked_fn(lambda c=dict(capture): self._open_capture_record(c))
                    manifest_btn = ui.Button("Manifest", width=88, height=22)
                    manifest_btn.set_clicked_fn(lambda c=dict(capture): self._open_capture_manifest(c))

    def _rebuild_latest_capture_preview(self) -> None:
        ui = self._ui
        if self._latest_capture_preview_container is None:
            return
        capture = self._capture_records[0] if self._capture_records else None
        with self._latest_capture_preview_container:
            self._latest_capture_preview_container.clear()
            if not capture:
                ui.Label("Latest capture preview: none", height=36, word_wrap=True)
                return
            local_path = self._capture_preview_local_path(capture)
            if self._is_isaac_image_path(local_path):
                try:
                    ui.Image(local_path, width=180, height=112)
                except Exception:
                    ui.Label(f"Latest preview:\n{local_path}", height=64, word_wrap=True)
            else:
                ui.Label("Latest capture has no local PNG preview yet.", height=44, word_wrap=True)

    def _capture_preview_local_path(self, capture: dict[str, Any]) -> str | None:
        try:
            try:
                from isaac_extension.daemon_client import material_preview_local_path
            except ImportError:  # pragma: no cover - Isaac runtime fallback
                from daemon_client import material_preview_local_path
            for item in capture.get("preview_items") or []:
                if not isinstance(item, dict):
                    continue
                raw_paths = item.get("raw_paths") if isinstance(item.get("raw_paths"), dict) else {}
                for key in ("png", "preview_png", "colorbar_png", "image"):
                    value = raw_paths.get(key)
                    if isinstance(value, str) and value:
                        local_path = material_preview_local_path(
                            {"artifact_path": value},
                            repo_root=os.environ.get("ROBOMITUBA_WINDOWS_REPO_ROOT") or os.environ.get("ROBOMITUBA_ROOT") or "",
                        )
                        if local_path:
                            return local_path
        except Exception:
            return None
        return None

    def _open_capture_record(self, capture: dict[str, Any]) -> None:
        job_id = str(capture.get("job_id") or "")
        frame_id = str(capture.get("frame_id") or "")
        scene_id = str(capture.get("scene_id") or self._current_scene_id() or "")
        if job_id and frame_id:
            threading.Thread(
                target=self._run_tracked_command,
                args=("open_latest_capture", scene_id, self._do_open_latest_capture),
                kwargs={"command": {"payload": {"job_id": job_id, "frame_id": frame_id}}},
                daemon=True,
            ).start()
            return
        self._on_open_latest_capture()

    def _open_capture_manifest(self, capture: dict[str, Any]) -> None:
        href = str(capture.get("manifest_href") or "")
        manifest_path = str(capture.get("manifest_path") or "")
        daemon_url = self._daemon_url()
        if href:
            webbrowser.open(f"{daemon_url}{href}")
        elif manifest_path:
            webbrowser.open(f"{daemon_url}/artifacts?path={manifest_path}")
        else:
            scene_id = self._current_scene_id()
            webbrowser.open(f"{daemon_url}/scenes/{scene_id}#captures" if scene_id else f"{daemon_url}/scenes")

    def _run_tracked_command(self, command_type: str, scene_id: str | None, worker: Any, *, command: dict[str, Any] | None = None) -> None:
        command_id = ""
        daemon_url = ""
        try:
            try:
                from isaac_extension.daemon_client import complete_isaac_command, start_isaac_command, update_isaac_command_progress
            except ImportError:  # pragma: no cover - Isaac runtime fallback
                from daemon_client import complete_isaac_command, start_isaac_command, update_isaac_command_progress

            daemon_url = self._daemon_url_field.model.get_value_as_string().strip()
            command_payload = command if isinstance(command, dict) else {}
            command_id = str(command_payload.get("command_id") or "")
            if not command_id:
                started = start_isaac_command(command_type, scene_id=scene_id, daemon_url=daemon_url, timeout_s=2.0)
                command_id = str(started.get("command_id") or "")
            payload = command_payload.get("payload") if isinstance(command_payload.get("payload"), dict) else {}

            def _report(status: str, stage: str, message: str, origin: str = "isaac_app", counts: dict[str, int] | None = None) -> None:
                self._set_result(message)
                self._log_progress(command_type, scene_id, status, stage, message, origin, counts)
                if command_id:
                    update_isaac_command_progress(
                        command_id,
                        daemon_url=daemon_url,
                        status=status,
                        progress_stage=stage,
                        progress_message=message,
                        progress_origin=origin,
                        progress_counts=counts,
                        timeout_s=2.0,
                    )

            _report("running", "picked_up", f"Starting {command_type.replace('_', ' ')}.", "isaac_app", None)
            result = worker(progress_callback=_report, command_id=command_id, command_payload=payload)
            if command_id:
                complete_isaac_command(command_id, daemon_url=daemon_url, status="succeeded", result=result, timeout_s=2.0)
        except Exception as exc:  # pragma: no cover
            self._set_result(f"{command_type} failed: {exc}")
            try:
                if command_id and daemon_url:
                    update_isaac_command_progress(
                        command_id,
                        daemon_url=daemon_url,
                        status="failed",
                        progress_stage="failed",
                        progress_message=str(exc),
                        progress_origin="isaac_app",
                        timeout_s=2.0,
                    )
                    complete_isaac_command(command_id, daemon_url=daemon_url, status="failed", error=str(exc), timeout_s=2.0)
            except Exception:
                pass

    def _rebuild_scene_picker(self) -> None:
        ui = self._ui
        labels = []
        for scene in self._scene_records:
            scene_id = str(scene.get("scene_id") or "scene")
            source = str(scene.get("source") or "catalog")
            labels.append(f"{scene_id} ({source})")
        if not labels:
            labels = ["(no daemon scenes)"]
        with self._scene_picker_container:
            self._scene_picker_container.clear()
            with ui.VStack(spacing=4):
                ui.Label("Daemon Scene Catalog", height=18)
                self._scene_combo = ui.ComboBox(0, *labels, height=24)
                self._scene_combo_model = self._scene_combo.model
                if self._scene_records:
                    self._populate_fields_from_scene(self._scene_records[0])

    def _collect_form_state(self) -> tuple[str, str, str | None, str | None, str, str, list[str], dict[str, Any]]:
        from robomituba_bridge import BsdfOverride

        daemon_url = self._daemon_url_field.model.get_value_as_string().strip()
        scene_ref = self._scene_ref_field.model.get_value_as_string().strip()
        scene_snapshot_ref = self._scene_snapshot_ref_field.model.get_value_as_string().strip() or None
        shape_map_ref = self._shape_map_ref_field.model.get_value_as_string().strip() or None
        scene_id = self._scene_id_field.model.get_value_as_string().strip() or DEFAULT_SCENE_ID
        submit_mode = SUBMIT_MODES[self._submit_mode_combo.model.get_item_value_model().get_value_as_int()]
        modalities = [name for name, model in self._modality_models.items() if model.get_value_as_bool()]
        if not modalities:
            modalities = ["rgb"]

        bsdf_overrides: dict[str, Any] = {}

        return daemon_url, scene_ref, scene_snapshot_ref, shape_map_ref, scene_id, submit_mode, modalities, bsdf_overrides

    def _do_refresh_scenes(self) -> None:
        try:
            try:
                from isaac_extension.daemon_client import get_scene_from_daemon, list_scenes_from_daemon
            except ImportError:  # pragma: no cover - Isaac runtime fallback
                from daemon_client import get_scene_from_daemon, list_scenes_from_daemon

            daemon_url = self._daemon_url_field.model.get_value_as_string().strip()
            self._log_progress("scene_catalog", None, "running", "refreshing", f"Refreshing daemon scene catalog from {daemon_url}.", "isaac_ui", None)
            scene_records = list_scenes_from_daemon(daemon_url=daemon_url)
            self._log_progress("scene_catalog", None, "running", "list_response", f"Daemon scene catalog returned {len(scene_records)} entries.", "isaac_ui", None)
            if not scene_records:
                fallback_scene_ids: list[str] = []
                current_scene_id = self._current_scene_id()
                if current_scene_id:
                    fallback_scene_ids.append(current_scene_id)
                typed_scene_id = self._scene_id_field.model.get_value_as_string().strip()
                if typed_scene_id and typed_scene_id not in fallback_scene_ids:
                    fallback_scene_ids.append(typed_scene_id)
                for fallback_scene_id in fallback_scene_ids:
                    try:
                        self._log_progress("scene_catalog", fallback_scene_id, "running", "fallback_lookup", f"Scene catalog empty. Trying direct fetch for {fallback_scene_id}.", "isaac_ui", None)
                        payload = get_scene_from_daemon(fallback_scene_id, daemon_url=daemon_url)
                    except Exception:
                        self._log_progress("scene_catalog", fallback_scene_id, "running", "fallback_miss", f"Direct fetch failed for {fallback_scene_id}.", "isaac_ui", None)
                        continue
                    scene = payload.get("scene") if isinstance(payload, dict) else None
                    if isinstance(scene, dict) and scene.get("scene_id"):
                        self._log_progress("scene_catalog", fallback_scene_id, "running", "fallback_hit", f"Direct fetch recovered scene {fallback_scene_id}.", "isaac_ui", None)
                        scene_records = [scene]
                        break
            self._scene_records = scene_records
            self._rebuild_scene_picker()
            if self._scene_records:
                self._set_result(f"Loaded {len(self._scene_records)} scene entries from daemon catalog.")
                self._log_progress("scene_catalog", None, "succeeded", "ready", f"Scene catalog ready with {len(self._scene_records)} entries.", "isaac_ui", None)
            else:
                self._set_result(
                    "Daemon scene catalog returned no entries. "
                    "If daemon has scenes, restart Isaac with launch_isaac_with_robomituba.bat and refresh again."
                )
                self._log_progress("scene_catalog", None, "failed", "empty", "Daemon scene catalog is empty after list and direct-fetch fallback.", "isaac_ui", None)
        except Exception as exc:  # pragma: no cover
            self._set_result(f"Scene refresh error: {exc}")
            self._log_progress("scene_catalog", None, "failed", "error", f"Scene refresh error: {exc}", "isaac_ui", None)

    def _do_load_scene(self, *, progress_callback: Any = None, command_id: str | None = None, command_payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            try:
                from isaac_extension.daemon_client import load_scene_from_daemon
            except ImportError:  # pragma: no cover - Isaac runtime fallback
                from daemon_client import load_scene_from_daemon

            daemon_url = self._daemon_url_field.model.get_value_as_string().strip()
            selected = self._selected_scene_record()
            if selected is None:
                raise RuntimeError("No daemon scene is selected.")
            self._populate_fields_from_scene(selected)
            result = load_scene_from_daemon(
                scene_id=str(selected.get("scene_id")),
                daemon_url=daemon_url,
                timeout_s=1800.0,
                progress_callback=progress_callback,
            )
            self._set_result(
                "\n".join(
                    [
                        "Scene loaded in Isaac.",
                        f"scene: {result.get('scene_id')}",
                        f"path: {result.get('usd_stage_path')}",
                    ]
                )
            )
            self._scene_state_dirty = True
            self._material_state_dirty = False
            self._setup_stage_dirty_tracking()
            self._attach_material_override_layer()
            return result
        except Exception as exc:  # pragma: no cover
            self._set_result(f"Load scene error: {exc}")
            raise

    def _do_open_latest_capture(self, *, progress_callback: Any = None, command_id: str | None = None, command_payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            try:
                from isaac_extension.daemon_client import open_capture_from_daemon
            except ImportError:  # pragma: no cover - Isaac runtime fallback
                from daemon_client import open_capture_from_daemon

            daemon_url = self._daemon_url_field.model.get_value_as_string().strip()
            selected = self._selected_scene_record()
            scene_id = str(selected.get("scene_id")) if selected is not None else None
            job_id = str(command_payload.get("job_id") or "") if isinstance(command_payload, dict) else ""
            frame_id = str(command_payload.get("frame_id") or "") if isinstance(command_payload, dict) else ""
            if progress_callback is not None:
                progress_callback("running", "opening_capture", "Opening latest capture preview.", "isaac_app", None)
            result = open_capture_from_daemon(
                scene_id=scene_id,
                job_id=job_id or None,
                frame_id=frame_id or None,
                daemon_url=daemon_url,
            )
            self._set_result(
                "\n".join(
                    [
                        "Opened capture preview.",
                        f"artifact: {result.get('artifact_path')}",
                    ]
                )
            )
            return result
        except Exception as exc:  # pragma: no cover
            self._set_result(f"Open capture error: {exc}")
            raise

    def _do_prepare_render_ready(self, *, progress_callback: Any = None, command_id: str | None = None, command_payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            try:
                from isaac_extension.daemon_client import prepare_render_ready_from_daemon
            except ImportError:  # pragma: no cover - Isaac runtime fallback
                from daemon_client import prepare_render_ready_from_daemon

            selected = self._selected_scene_record()
            if selected is None:
                raise RuntimeError("No daemon scene is selected.")
            self._populate_fields_from_scene(selected)
            daemon_url = self._daemon_url_field.model.get_value_as_string().strip()
            scene_id = str(selected.get("scene_id") or "")
            stage = self._get_stage()
            result = prepare_render_ready_from_daemon(
                scene_id,
                stage=stage,
                daemon_url=daemon_url,
                progress_callback=progress_callback,
            )
            generated = result.get("generated") or {}
            self._shape_map_ref_field.model.set_value(str(result.get("shape_map_ref") or ""))
            self._set_result(
                "\n".join(
                    [
                        "Render-ready files prepared.",
                        f"scene: {scene_id}",
                        f"shape_map: {result.get('shape_map_ref')}",
                        f"mapped prims: {generated.get('prim_count', 0)} · unmatched: {len(generated.get('unmatched_prim_paths') or [])}",
                    ]
                )
            )
            return result
        except Exception as exc:  # pragma: no cover
            self._set_result(f"Prepare render-ready error: {exc}")
            raise

    def _do_apply_selected_override(self, clear_only: bool = False) -> None:
        try:
            from robomituba_bridge import BsdfOverride
            try:
                from isaac_extension.stage_capture import capture_material_patch
            except ImportError:  # pragma: no cover - Isaac runtime fallback
                from stage_capture import capture_material_patch
            try:
                from isaac_extension.daemon_client import update_isaac_materials
            except ImportError:  # pragma: no cover - Isaac runtime fallback
                from daemon_client import update_isaac_materials

            daemon_url = self._daemon_url_field.model.get_value_as_string().strip()
            stage = self._get_stage()
            prim_paths = self._selected_prim_paths()
            if not prim_paths:
                raise RuntimeError("No selected prims are available in Isaac.")
            scoped_paths = self._expanded_material_scope_paths(stage, prim_paths)
            scene_id = self._current_scene_id() or DEFAULT_SCENE_ID
            if clear_only:
                self._clear_usd_material_overrides(stage, scoped_paths, daemon_url=daemon_url, scene_id=scene_id)
                return
            selected_index = 0
            if self._selected_bsdf_combo is not None:
                selected_index = int(self._selected_bsdf_combo.model.get_item_value_model().get_value_as_int())
            bsdf_type = BSDF_OPTIONS[selected_index]
            if bsdf_type == "none":
                self._clear_usd_material_overrides(stage, scoped_paths, daemon_url=daemon_url, scene_id=scene_id)
                return
            overrides = {prim_path: BsdfOverride(bsdf_type=bsdf_type) for prim_path in scoped_paths}
            try:
                from isaac_extension.material_override_layer import write_material_override
            except ImportError:  # pragma: no cover - Isaac runtime fallback
                from material_override_layer import write_material_override

            write_material_override(stage, scoped_paths, BsdfOverride(bsdf_type=bsdf_type), scene_id=scene_id, kind="bsdf", preset=bsdf_type)
            update_isaac_materials(capture_material_patch(overrides), daemon_url=daemon_url)
            self._material_state_dirty = True
            self._refresh_control_status()
            self._refresh_selection_label(prim_paths)
            self._set_result(f"Applied {bsdf_type} to {len(scoped_paths)} prim(s) via USD override layer.")
        except Exception as exc:  # pragma: no cover
            self._set_result(f"Selected override error: {exc}")

    def _do_apply_daemon_material(self) -> None:
        try:
            try:
                from isaac_extension.daemon_client import update_isaac_materials
            except ImportError:  # pragma: no cover - Isaac runtime fallback
                from daemon_client import update_isaac_materials
            try:
                from isaac_extension.stage_capture import capture_material_patch
            except ImportError:  # pragma: no cover - Isaac runtime fallback
                from stage_capture import capture_material_patch
            try:
                from isaac_extension.material_override_layer import material_record_to_override, write_material_override
            except ImportError:  # pragma: no cover - Isaac runtime fallback
                from material_override_layer import material_record_to_override, write_material_override

            scene_id = self._current_scene_id()
            if not scene_id:
                raise RuntimeError("No daemon scene is selected.")
            stage = self._get_stage()
            prim_paths = self._selected_prim_paths()
            if not prim_paths:
                raise RuntimeError("No selected prims are available in Isaac.")
            scoped_paths = self._expanded_material_scope_paths(stage, prim_paths)
            material = self._selected_daemon_material_record()
            if material is None:
                raise RuntimeError("No render daemon material is selected. Refresh materials first.")

            daemon_url = self._daemon_url_field.model.get_value_as_string().strip()
            override = material_record_to_override(material)
            kind = str(material.get("kind") or "measured")
            preset = str(material.get("key") or material.get("material_id") or "")
            write_material_override(stage, scoped_paths, override, scene_id=scene_id, kind=kind, preset=preset)
            update_isaac_materials(
                capture_material_patch({prim_path: override for prim_path in scoped_paths}),
                daemon_url=daemon_url,
                timeout_s=10.0,
            )
            self._refresh_selected_daemon_material_status(prim_paths)
            self._material_state_dirty = True
            self._refresh_control_status()
            self._refresh_selection_label(prim_paths)
            self._set_result(f"Applied {self._daemon_material_label(material)} to {len(scoped_paths)} prim(s) via USD override layer.")
        except Exception as exc:  # pragma: no cover
            self._set_result(f"Daemon material apply error: {exc}")

    def _do_reset_usd_material_override(self) -> None:
        try:
            stage = self._get_stage()
            prim_paths = self._selected_prim_paths()
            if not prim_paths:
                raise RuntimeError("No selected prims are available in Isaac.")
            scoped_paths = self._expanded_material_scope_paths(stage, prim_paths)
            self._clear_usd_material_overrides(
                stage,
                scoped_paths,
                daemon_url=self._daemon_url_field.model.get_value_as_string().strip(),
                scene_id=self._current_scene_id() or DEFAULT_SCENE_ID,
            )
            self._refresh_selection_label(prim_paths)
        except Exception as exc:  # pragma: no cover
            self._set_result(f"Reset override error: {exc}")

    def _clear_usd_material_overrides(self, stage: Any, prim_paths: list[str], *, daemon_url: str, scene_id: str) -> None:
        try:
            from isaac_extension.material_override_layer import clear_material_override
        except ImportError:  # pragma: no cover - Isaac runtime fallback
            from material_override_layer import clear_material_override
        try:
            from isaac_extension.stage_capture import capture_material_patch
        except ImportError:  # pragma: no cover - Isaac runtime fallback
            from stage_capture import capture_material_patch
        try:
            from isaac_extension.daemon_client import update_isaac_materials
        except ImportError:  # pragma: no cover - Isaac runtime fallback
            from daemon_client import update_isaac_materials

        cleared = clear_material_override(stage, prim_paths, scene_id=scene_id)
        update_isaac_materials(
            capture_material_patch({}, extras={"clear_paths": list(prim_paths)}),
            daemon_url=daemon_url,
            timeout_s=10.0,
        )
        self._material_state_dirty = True
        self._refresh_control_status()
        self._set_result(f"Reset RoboMitsuba override on {cleared} prim(s).")

    def _poll_remote_commands_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                try:
                    from isaac_extension.daemon_client import next_isaac_command
                except ImportError:  # pragma: no cover - Isaac runtime fallback
                    from daemon_client import next_isaac_command

                daemon_url = self._daemon_url_field.model.get_value_as_string().strip()
                if not daemon_url:
                    time.sleep(1.0)
                    continue
                command = next_isaac_command(daemon_url=daemon_url, timeout_s=1.0)
                if not command:
                    time.sleep(1.0)
                    continue
                command_id = str(command.get("command_id") or "")
                if not command_id:
                    time.sleep(0.25)
                    continue
                command_type = str(command.get("command_type") or "")
                scene_id = command.get("scene_id")
                worker = lambda **kwargs: self._execute_remote_command(command, **kwargs)
                self._run_tracked_command(command_type, str(scene_id) if scene_id else None, worker, command=command)
            except Exception:
                time.sleep(1.0)

    def _execute_remote_command(
        self,
        command: dict[str, Any],
        *,
        progress_callback: Any = None,
        command_id: str | None = None,
        command_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            from isaac_extension.daemon_client import (
                prepare_render_ready_from_daemon,
                request_apply_material_override,
                connect_scene_session_from_daemon,
                load_scene_from_daemon,
                open_capture_from_daemon,
                render_current_view_from_daemon,
                sync_scene_state_to_daemon,
                update_isaac_materials,
            )
        except ImportError:  # pragma: no cover - Isaac runtime fallback
            from daemon_client import (
                prepare_render_ready_from_daemon,
                request_apply_material_override,
                connect_scene_session_from_daemon,
                load_scene_from_daemon,
                open_capture_from_daemon,
                render_current_view_from_daemon,
                sync_scene_state_to_daemon,
                update_isaac_materials,
            )

        command_type = str(command.get("command_type") or "")
        scene_id = command.get("scene_id")
        payload = command.get("payload") if isinstance(command.get("payload"), dict) else {}
        daemon_url = self._daemon_url_field.model.get_value_as_string().strip()
        stage = None
        if command_type in {"sync_session", "render_current_view"}:
            stage = self._get_stage()

        if command_type == "load_scene":
            result = load_scene_from_daemon(
                scene_id=str(scene_id),
                daemon_url=daemon_url,
                progress_callback=progress_callback,
            )
            self._scene_state_dirty = True
            self._material_state_dirty = False
            self._setup_stage_dirty_tracking()
            self._set_result(f"Remote load complete.\nscene: {result.get('scene_id')}")
            # Auto-connect session if the scene has the necessary refs in the daemon catalog
            try:
                connect_result = connect_scene_session_from_daemon(
                    str(scene_id),
                    daemon_url=daemon_url,
                    progress_callback=progress_callback,
                )
                self._set_result(
                    f"Remote load + connect complete.\nscene: {result.get('scene_id')}\n"
                    f"session: {connect_result.get('session', {}).get('scene_id', scene_id)}"
                )
                return {**result, "session": connect_result}
            except Exception:
                # Scene may not be render-ready yet — load-only is still valid
                pass
            return result
        if command_type == "connect_session":
            result = connect_scene_session_from_daemon(
                str(scene_id),
                daemon_url=daemon_url,
                progress_callback=progress_callback,
            )
            self._set_result(f"Remote connect complete.\nscene: {scene_id}")
            return result
        if command_type == "prepare_render_ready":
            result = prepare_render_ready_from_daemon(
                str(scene_id),
                stage=self._get_stage(),
                daemon_url=daemon_url,
                progress_callback=progress_callback,
            )
            self._set_result(f"Remote prepare complete.\nscene: {scene_id}\nshape_map: {result.get('shape_map_ref')}")
            return result
        if command_type == "sync_session":
            result = sync_scene_state_to_daemon(
                stage,
                str(scene_id),
                daemon_url=daemon_url,
                progress_callback=progress_callback,
            )
            self._clear_sync_dirty_flags()
            self._set_result(f"Remote sync complete.\nscene: {scene_id}")
            return result
        if command_type == "render_current_view":
            result = render_current_view_from_daemon(
                str(scene_id),
                stage=stage,
                daemon_url=daemon_url,
                submit_mode=str(payload.get("submit_mode") or "async"),
                modalities=list(payload.get("modalities") or ["rgb"]),
                render_settings=dict(payload.get("render_settings") or {}),
                timeout_s=600.0,
                progress_callback=progress_callback,
                command_id=command_id,
                sync_policy=str(payload.get("sync_policy") or "auto"),
                force_resync=bool(payload.get("force_resync", False)),
                state_dirty=self._scene_state_dirty,
                material_dirty=self._material_state_dirty,
            )
            sync_mode = str(result.get("sync_mode") or "")
            if sync_mode == "full_resync":
                self._clear_sync_dirty_flags()
            elif sync_mode == "material_delta":
                self._clear_sync_dirty_flags(clear_state=False, clear_material=True)
            manifest_path = result.get("manifest_path") or result.get("status_url") or "-"
            self._set_result(f"Remote render complete.\nscene: {scene_id}\nresult: {manifest_path}")
            return result
        if command_type == "open_latest_capture":
            result = open_capture_from_daemon(scene_id=str(scene_id) if scene_id else None, daemon_url=daemon_url)
            self._set_result(f"Remote open capture complete.\nartifact: {result.get('artifact_path')}")
            return result
        if command_type == "apply_material_override":
            from robomituba_bridge import BsdfOverride
            try:
                from isaac_extension.stage_capture import capture_material_patch, capture_selected_prim_paths
            except ImportError:  # pragma: no cover - Isaac runtime fallback
                from stage_capture import capture_material_patch, capture_selected_prim_paths

            prim_paths = [str(path) for path in payload.get("prim_paths") or [] if str(path)]
            if not prim_paths:
                prim_paths = capture_selected_prim_paths()
            bsdf_type = str(payload.get("bsdf_type") or "none")
            if not prim_paths:
                raise RuntimeError("No selected prims are available for material override.")
            overrides = {}
            if bsdf_type != "none":
                overrides = {prim_path: BsdfOverride(bsdf_type=bsdf_type) for prim_path in prim_paths}
            _report = progress_callback or (lambda *_args, **_kwargs: None)
            _report("running", "serializing_patch", f"Applying {bsdf_type} to {len(prim_paths)} prim(s).", "isaac_app", None)
            result = update_isaac_materials(capture_material_patch(overrides), daemon_url=daemon_url)
            self._clear_sync_dirty_flags(clear_state=False, clear_material=True)
            self._set_result(f"Applied {bsdf_type} to {len(prim_paths)} prim(s).")
            return {"status": "applied", "bsdf_type": bsdf_type, "prim_paths": prim_paths, "session": result}
        raise RuntimeError(f"Unsupported remote command: {command_type}")

    def _do_connect(self, *, progress_callback: Any = None, command_id: str | None = None, command_payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            try:
                from isaac_extension.stage_capture import capture_session_open
            except ImportError:  # pragma: no cover - Isaac runtime fallback
                from stage_capture import capture_session_open
            try:
                from isaac_extension.daemon_client import connect_scene_session_from_daemon, open_isaac_session
            except ImportError:  # pragma: no cover - Isaac runtime fallback
                from daemon_client import connect_scene_session_from_daemon, open_isaac_session

            daemon_url, scene_ref, scene_snapshot_ref, shape_map_ref, scene_id, _submit_mode, _modalities, _bsdf_overrides = self._collect_form_state()
            selected = self._selected_scene_record()
            if selected is not None:
                self._populate_fields_from_scene(selected)
                scene_id = str(selected.get("scene_id") or scene_id)
                summary = connect_scene_session_from_daemon(
                    scene_id,
                    daemon_url=daemon_url,
                    progress_callback=progress_callback,
                )
            else:
                if not shape_map_ref:
                    raise RuntimeError("Shape Map Ref is required to open an Isaac session.")
                if progress_callback is not None:
                    progress_callback("running", "collecting_scene_refs", "Collecting scene session refs.", "isaac_app", None)
                summary = open_isaac_session(
                    capture_session_open(
                        scene_id=scene_id,
                        mitsuba_scene_ref=scene_ref,
                        scene_snapshot_ref=scene_snapshot_ref,
                        shape_map_ref=shape_map_ref,
                    ),
                    daemon_url,
                )
            self._set_result(
                "\n".join(
                    [
                        "Active session ready.",
                        f"scene: {summary.get('session', {}).get('scene_id')}",
                        f"shape_map: {summary.get('session', {}).get('shape_map_ref')}",
                    ]
                )
            )
            self._setup_stage_dirty_tracking()
            self._attach_material_override_layer()
            return summary
        except Exception as exc:  # pragma: no cover
            self._set_result(f"Connect error: {exc}")
            raise

    def _do_sync(self, *, progress_callback: Any = None, command_id: str | None = None, command_payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            try:
                from isaac_extension.stage_capture import capture_current_view_sensor_spec, capture_material_patch, capture_session_open, capture_state_patch
            except ImportError:  # pragma: no cover - Isaac runtime fallback
                from stage_capture import capture_current_view_sensor_spec, capture_material_patch, capture_session_open, capture_state_patch
            try:
                from isaac_extension.daemon_client import connect_scene_session_from_daemon, open_isaac_session, register_isaac_sensors, update_isaac_materials, update_isaac_selection, update_isaac_state
            except ImportError:  # pragma: no cover - Isaac runtime fallback
                from daemon_client import connect_scene_session_from_daemon, open_isaac_session, register_isaac_sensors, update_isaac_materials, update_isaac_selection, update_isaac_state

            stage = self._get_stage()
            sync_timeout_s = 60.0
            daemon_url, scene_ref, scene_snapshot_ref, shape_map_ref, scene_id, _submit_mode, modalities, bsdf_overrides = self._collect_form_state()
            selected = self._selected_scene_record()
            if selected is not None:
                self._populate_fields_from_scene(selected)
                scene_id = str(selected.get("scene_id") or scene_id)
                connect_scene_session_from_daemon(
                    scene_id,
                    daemon_url=daemon_url,
                    timeout_s=sync_timeout_s,
                    progress_callback=progress_callback,
                )
            else:
                if not shape_map_ref:
                    raise RuntimeError("Shape Map Ref is required to sync an Isaac session.")
                if progress_callback is not None:
                    progress_callback("running", "collecting_scene_refs", "Collecting scene session refs.", "isaac_app", None)
                open_isaac_session(
                    capture_session_open(
                        scene_id=scene_id,
                        mitsuba_scene_ref=scene_ref,
                        scene_snapshot_ref=scene_snapshot_ref,
                        shape_map_ref=shape_map_ref,
                    ),
                    daemon_url,
                    timeout_s=sync_timeout_s,
                )
            if progress_callback is not None:
                progress_callback("running", "capturing_stage_state", "Capturing current stage state from Isaac.", "isaac_app", None)
            state_summary = update_isaac_state(
                capture_state_patch(stage, scene_id=scene_id, bsdf_overrides_by_path=bsdf_overrides),
                daemon_url=daemon_url,
                timeout_s=sync_timeout_s,
            )
            if bsdf_overrides:
                if progress_callback is not None:
                    progress_callback("running", "serializing_patch", "Preparing BSDF override patch.", "isaac_app", None)
                update_isaac_materials(capture_material_patch(bsdf_overrides), daemon_url=daemon_url, timeout_s=sync_timeout_s)
            if progress_callback is not None:
                progress_callback("running", "uploading_patch", "Registering current view sensor and finalizing sync.", "isaac_app", None)
            sensor_summary = register_isaac_sensors(
                [capture_current_view_sensor_spec(modalities=modalities)],
                daemon_url=daemon_url,
                timeout_s=sync_timeout_s,
            )
            selection_summary = update_isaac_selection(
                self._selected_prim_paths(),
                daemon_url=daemon_url,
                timeout_s=min(sync_timeout_s, 15.0),
            )
            self._set_result(
                "\n".join(
                    [
                        "Session synced.",
                        f"objects: {state_summary.get('updated_objects', 0)}",
                        f"sensors: {sensor_summary.get('session', {}).get('sensor_count', 0)}",
                        f"selected: {selection_summary.get('selected_prim_count', 0)}",
                    ]
                )
            )
            self._clear_sync_dirty_flags()
            return {"state_summary": state_summary, "sensor_summary": sensor_summary, "selection_summary": selection_summary}
        except Exception as exc:  # pragma: no cover
            self._set_result(f"Sync error: {exc}")
            raise

    def _do_render(self, *, progress_callback: Any = None, command_id: str | None = None, command_payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            try:
                from isaac_extension.stage_capture import capture_current_view_sensor_spec, capture_material_patch, capture_session_open, capture_state_patch
            except ImportError:  # pragma: no cover - Isaac runtime fallback
                from stage_capture import capture_current_view_sensor_spec, capture_material_patch, capture_session_open, capture_state_patch
            try:
                from isaac_extension.daemon_client import capture_isaac_view, open_isaac_session, register_isaac_sensors, render_current_view_from_daemon, update_isaac_materials, update_isaac_state
            except ImportError:  # pragma: no cover - Isaac runtime fallback
                from daemon_client import capture_isaac_view, open_isaac_session, register_isaac_sensors, render_current_view_from_daemon, update_isaac_materials, update_isaac_state

            stage = self._get_stage()
            render_prep_timeout_s = 60.0
            daemon_url, scene_ref, scene_snapshot_ref, shape_map_ref, scene_id, submit_mode, modalities, bsdf_overrides = self._collect_form_state()
            command_payload = command_payload or {}
            requested_modalities = list(command_payload.get("modalities") or modalities or ["rgb"])
            render_settings = dict(command_payload.get("render_settings") or {})
            sync_policy = str(command_payload.get("sync_policy") or "auto")
            force_resync = bool(command_payload.get("force_resync", False))
            selected = self._selected_scene_record()
            if selected is not None or not shape_map_ref:
                if selected is not None:
                    self._populate_fields_from_scene(selected)
                if selected is not None:
                    scene_id = str(selected.get("scene_id") or scene_id)
                result = render_current_view_from_daemon(
                    scene_id,
                    stage=stage,
                    daemon_url=daemon_url,
                    submit_mode=submit_mode,
                    modalities=requested_modalities,
                    render_settings=render_settings,
                    bsdf_overrides_by_path=bsdf_overrides,
                    timeout_s=600.0,
                    progress_callback=progress_callback,
                    command_id=command_id,
                    sync_policy=sync_policy,
                    force_resync=force_resync,
                    state_dirty=self._scene_state_dirty,
                    material_dirty=self._material_state_dirty,
                )
            else:
                if not shape_map_ref:
                    raise RuntimeError("Shape Map Ref is required for Render Current View.")
                if progress_callback is not None:
                    progress_callback("running", "collecting_scene_refs", "Collecting scene session refs.", "isaac_app", None)
                open_isaac_session(
                    capture_session_open(
                        scene_id=scene_id,
                        mitsuba_scene_ref=scene_ref,
                        scene_snapshot_ref=scene_snapshot_ref,
                        shape_map_ref=shape_map_ref,
                    ),
                    daemon_url,
                    timeout_s=render_prep_timeout_s,
                )
                if progress_callback is not None:
                    progress_callback("running", "capturing_stage_state", "Capturing current stage state from Isaac.", "isaac_app", None)
                update_isaac_state(
                    capture_state_patch(stage, scene_id=scene_id, bsdf_overrides_by_path=bsdf_overrides),
                    daemon_url=daemon_url,
                    timeout_s=render_prep_timeout_s,
                )
                if bsdf_overrides:
                    if progress_callback is not None:
                        progress_callback("running", "serializing_patch", "Preparing BSDF override patch.", "isaac_app", None)
                    update_isaac_materials(capture_material_patch(bsdf_overrides), daemon_url=daemon_url, timeout_s=render_prep_timeout_s)
                if progress_callback is not None:
                    progress_callback("running", "capturing_view", "Capturing current viewport sensor definition.", "isaac_app", None)
                register_isaac_sensors(
                    [capture_current_view_sensor_spec(modalities=requested_modalities)],
                    daemon_url=daemon_url,
                    timeout_s=render_prep_timeout_s,
                )
                if progress_callback is not None:
                    progress_callback("running", "sending_capture_request", "Submitting current-view capture request to daemon.", "isaac_app", None)
                result = capture_isaac_view(
                    daemon_url=daemon_url,
                    modalities=requested_modalities,
                    submit_mode=submit_mode,
                    render_settings=render_settings,
                    timeout_s=600.0,
                    command_id=command_id,
                    extras={
                        "sync_policy": sync_policy,
                        "sync_mode": "full_resync",
                        "force_resync": force_resync or True,
                    },
                )
            sync_mode = str(result.get("sync_mode") or "")
            if sync_mode == "full_resync":
                self._clear_sync_dirty_flags()
            elif sync_mode == "material_delta":
                self._clear_sync_dirty_flags(clear_state=False, clear_material=True)
            if result.get("status") in ("queued", "accepted") and result.get("job_id"):
                job_id = result["job_id"]
                self._set_result(f"Render queued: {job_id}\nPolling for completion...")
                if progress_callback is not None:
                    progress_callback("running", "polling_render", f"Render queued: {job_id}. Waiting for completion...", "daemon_render", None)
                try:
                    from isaac_extension.daemon_client import wait_for_render_job
                except ImportError:  # pragma: no cover - Isaac runtime fallback
                    from daemon_client import wait_for_render_job

                def _on_poll_status(status_payload: dict) -> None:
                    progress = status_payload.get("progress") or 0
                    stage = str(status_payload.get("progress_stage") or "rendering")
                    msg = str(status_payload.get("progress_message") or f"Rendering: {progress:.0f}%")
                    self._set_result(f"Render {job_id}: {msg}")
                    if progress_callback is not None:
                        progress_callback("running", stage, msg, "daemon_render", None)

                result = wait_for_render_job(
                    job_id,
                    daemon_url=daemon_url,
                    poll_interval_s=2.0,
                    timeout_s=600.0,
                    on_status=_on_poll_status,
                )

            if result.get("status") == "succeeded" or result.get("status") == "completed":
                artifact_lines = [
                    f"✓ {modality}: {', '.join(paths.values())}"
                    for modality, paths in result.get("artifacts", {}).items()
                ]
                manifest_path = result.get("manifest_path")
                header = f"Completed render.\nmanifest: {manifest_path}" if manifest_path else "Completed render."
                self._set_result("\n".join([header, *artifact_lines]).strip())
            elif result.get("status") == "failed":
                error = result.get("error") or "unknown error"
                self._set_result(f"Render failed: {error}")
            else:
                self._set_result(
                    "\n".join(
                        [
                            f"Render job {result.get('job_id')}",
                            f"status: {result.get('status')}",
                            f"status_url: {result.get('status_url', '')}",
                        ]
                    )
                )
            return result
        except Exception as exc:  # pragma: no cover
            self._set_result(f"Error: {exc}")
            raise

    def _get_stage(self) -> Any:
        import omni.usd  # type: ignore

        stage = omni.usd.get_context().get_stage()
        if stage is None:
            raise RuntimeError("No USD stage open in Isaac Sim.")
        return stage

    def _collect_mesh_prim_paths(self, stage: Any) -> list[str]:
        from pxr import UsdGeom  # type: ignore

        return [str(prim.GetPath()) for prim in stage.Traverse() if prim.IsA(UsdGeom.Mesh)]

    def _set_result(self, text: str) -> None:
        if self._result_label is not None:
            self._result_label.text = text
        self._refresh_control_status()

    def _log_progress(
        self,
        command_type: str,
        scene_id: str | None,
        status: str,
        stage: str,
        message: str,
        origin: str,
        counts: dict[str, int] | None,
    ) -> None:
        signature = (status, stage, message)
        if signature == self._last_logged_progress:
            return
        self._last_logged_progress = signature
        scene_hint = f" ({scene_id})" if scene_id else ""
        counts_hint = ""
        if counts and counts.get("total", 0) > 0:
            counts_hint = f" [{counts.get('loaded', 0)}/{counts.get('total', 0)}]"
        line = f"[robomituba][{command_type}][{origin}] {stage}{scene_hint}{counts_hint} :: {message}"
        try:
            import carb  # type: ignore

            carb.log_info(line)
        except Exception:
            pass
        print(line)

    def destroy(self) -> None:
        self._stop_event.set()
        if self._stage_notice_registration is not None:
            try:
                self._stage_notice_registration.Revoke()
            except Exception:
                pass
            self._stage_notice_registration = None
        if self._keyboard_input is not None and self._keyboard_device is not None and self._keyboard_subscription is not None:
            try:
                self._keyboard_input.unsubscribe_to_keyboard_events(self._keyboard_device, self._keyboard_subscription)
            except Exception:
                pass
        self._ui_update_subscription = None
        for attr in ("_capture_window", "_jobs_window", "_optical_window", "_session_window"):
            window = getattr(self, attr, None)
            if window is None:
                continue
            try:
                window.destroy()
            except Exception:
                pass
            setattr(self, attr, None)
        self._window = None
