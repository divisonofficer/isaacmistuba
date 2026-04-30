"""Robomituba Isaac Extension — omni.ui panel."""
from __future__ import annotations

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
        self._runtime_sync_status = _runtime_extension_sync_status()
        self._runtime_sync_label: Any = None
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
                    runtime_sync_message = str(self._runtime_sync_status.get("message") or "").strip()
                    if runtime_sync_message:
                        self._runtime_sync_label = ui.Label(runtime_sync_message, height=42, word_wrap=True)

                    ui.Spacer(height=4)
                    ui.Label("Quick Actions", height=20)
                    self._scene_picker_container = ui.VStack(height=60)
                    with self._scene_picker_container:
                        pass
                    with ui.HStack(spacing=6, height=30):
                        refresh_scenes_btn = ui.Button("Refresh Scenes", width=140, height=30)
                        refresh_scenes_btn.set_clicked_fn(self._on_refresh_scenes)
                        load_scene_btn = ui.Button("Load Scene", width=120, height=30)
                        load_scene_btn.set_clicked_fn(self._on_load_scene)
                        prepare_btn = ui.Button("Prepare Render-Ready", width=170, height=30)
                        prepare_btn.set_clicked_fn(self._on_prepare_render_ready)
                        open_capture_btn = ui.Button("Open Latest Capture", width=170, height=30)
                        open_capture_btn.set_clicked_fn(self._on_open_latest_capture)

                    ui.Spacer(height=4)
                    ui.Label("Advanced Session Settings", height=20)
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
                    with ui.HStack(spacing=6, height=32):
                        connect_btn = ui.Button("Connect Scene", width=160, height=32)
                        connect_btn.set_clicked_fn(self._on_connect)
                        sync_btn = ui.Button("Sync Session", width=160, height=32)
                        sync_btn.set_clicked_fn(self._on_sync)

                    ui.Spacer(height=8)
                    ui.Label("Ranger Mini Robots", height=20)
                    with ui.HStack(spacing=6, height=30):
                        spawn_robot_btn = ui.Button("Spawn RangerMini", width=180, height=30)
                        spawn_robot_btn.set_clicked_fn(self._on_spawn_robot)
                        refresh_robot_btn = ui.Button("Refresh Robot List", width=180, height=30)
                        refresh_robot_btn.set_clicked_fn(self._on_refresh_robots)
                        focus_robot_btn = ui.Button("Find Selected", width=150, height=30)
                        focus_robot_btn.set_clicked_fn(self._on_focus_robot)
                    self._robot_picker_container = ui.VStack(height=30)
                    with self._robot_picker_container:
                        pass
                    self._robot_list_label = ui.Label("No RangerMini robots in the stage.", height=90, word_wrap=True)
                    ui.Label("Keyboard: Up/Down move, Left/Right turn, Q/E spin, Space stop, P park", height=20)
                    with ui.HStack(spacing=6, height=30):
                        for label, action in RANGER_ACTIONS[:5]:
                            btn = ui.Button(label, width=100, height=30)
                            btn.set_clicked_fn(lambda a=action: self._on_robot_action(a))
                    with ui.HStack(spacing=6, height=30):
                        for label, action in RANGER_ACTIONS[5:]:
                            btn = ui.Button(label, width=100, height=30)
                            btn.set_clicked_fn(lambda a=action: self._on_robot_action(a))

                    ui.Spacer(height=6)
                    ui.Label("Selection + Material Browser", height=20)
                    self._selection_label = ui.Label("No selected prims synced yet.", height=40, word_wrap=True)
                    with ui.HStack(spacing=6, height=30):
                        open_material_browser_btn = ui.Button("Open Material Browser", width=180, height=30)
                        open_material_browser_btn.set_clicked_fn(self._on_open_material_browser)
                        push_selection_btn = ui.Button("Sync Selection", width=140, height=30)
                        push_selection_btn.set_clicked_fn(self._on_sync_selection)
                    with ui.HStack(spacing=6, height=30):
                        self._selected_bsdf_combo = ui.ComboBox(0, *BSDF_OPTIONS, width=180, height=24)
                        apply_selected_btn = ui.Button("Apply to Selected", width=150, height=30)
                        apply_selected_btn.set_clicked_fn(self._on_apply_selected_override)
                        clear_selected_btn = ui.Button("Clear Selected", width=130, height=30)
                        clear_selected_btn.set_clicked_fn(self._on_clear_selected_override)
                    ui.Label("Render Daemon Materials", height=20)
                    self._selected_daemon_material_label = ui.Label("Selected material override: unknown", height=38, word_wrap=True)
                    self._daemon_material_picker_container = ui.VStack(height=30)
                    with self._daemon_material_picker_container:
                        pass
                    with ui.HStack(spacing=6, height=30):
                        refresh_materials_btn = ui.Button("Refresh Materials", width=150, height=30)
                        refresh_materials_btn.set_clicked_fn(self._on_refresh_daemon_materials)
                        apply_daemon_material_btn = ui.Button("Apply Daemon Material", width=190, height=30)
                        apply_daemon_material_btn.set_clicked_fn(self._on_apply_daemon_material)

                    ui.Spacer(height=8)
                    render_btn = ui.Button("Render Current View", height=36)
                    render_btn.set_clicked_fn(self._on_render)

                    ui.Spacer(height=6)
                    ui.Label("Result", height=20)
                    self._result_label = ui.Label("—", height=80, word_wrap=True)
        self._rebuild_scene_picker()
        self._do_refresh_scenes()
        self._setup_stage_dirty_tracking()
        threading.Thread(target=self._poll_remote_commands_loop, daemon=True).start()
        threading.Thread(target=self._poll_selection_loop, daemon=True).start()
        threading.Thread(target=self._poll_viewport_camera_loop, daemon=True).start()
        self._setup_keyboard_shortcuts()
        self._rebuild_robot_picker()
        self._refresh_robot_records()
        self._rebuild_daemon_material_picker()
        threading.Thread(target=self._do_refresh_daemon_materials, daemon=True).start()

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
        try:
            import omni.kit.commands  # type: ignore

            prim_paths = self._selected_prim_paths()
            if prim_paths:
                omni.kit.commands.execute("FramePrimsCommand", prim_to_move=False, prims_to_frame=prim_paths, time_code=0.0)
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
        if reason:
            self._log_progress("sync_state", self._current_scene_id(), "running", "state_dirty", reason, "isaac_stage", None)

    def _mark_material_state_dirty(self, *, reason: str | None = None) -> None:
        self._material_state_dirty = True
        if reason:
            self._log_progress("sync_state", self._current_scene_id(), "running", "material_dirty", reason, "isaac_stage", None)

    def _clear_sync_dirty_flags(self, *, clear_state: bool = True, clear_material: bool = True) -> None:
        if clear_state:
            self._scene_state_dirty = False
        if clear_material:
            self._material_state_dirty = False

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
        if self._selection_label is None:
            return
        if not prim_paths:
            self._selection_label.text = "No selected prims synced yet."
            self._refresh_selected_daemon_material_status(prim_paths)
            return
        preview = ", ".join(path.split("/")[-1] or path for path in prim_paths[:3])
        if len(prim_paths) > 3:
            preview = f"{preview} +{len(prim_paths) - 3}"
        self._selection_label.text = f"Selected prims: {preview}"

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
                    }
                    records.append(record)
            selected = self._selected_daemon_material_record()
            selected_key = str(selected.get("key")) if selected else None
            self._daemon_material_records = records
            self._rebuild_daemon_material_picker(selected_key=selected_key)
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
        self._refresh_selection_label(prim_paths)
        if signature == self._last_selection_signature:
            return
        self._last_selection_signature = signature
        if daemon_url:
            update_isaac_selection(prim_paths, daemon_url=daemon_url, timeout_s=2.0)
            self._refresh_selected_daemon_material_status(prim_paths)

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
            if progress_callback is not None:
                progress_callback("running", "opening_capture", "Opening latest capture preview.", "isaac_app", None)
            result = open_capture_from_daemon(
                scene_id=scene_id,
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
            prim_paths = self._selected_prim_paths()
            if not prim_paths:
                raise RuntimeError("No selected prims are available in Isaac.")
            selected_index = 0
            if self._selected_bsdf_combo is not None:
                selected_index = int(self._selected_bsdf_combo.model.get_item_value_model().get_value_as_int())
            bsdf_type = "none" if clear_only else BSDF_OPTIONS[selected_index]
            overrides = {}
            if bsdf_type != "none":
                overrides = {prim_path: BsdfOverride(bsdf_type=bsdf_type) for prim_path in prim_paths}
            update_isaac_materials(capture_material_patch(overrides), daemon_url=daemon_url)
            self._clear_sync_dirty_flags(clear_state=False, clear_material=True)
            self._set_result(f"Applied {bsdf_type} to {len(prim_paths)} selected prim(s).")
        except Exception as exc:  # pragma: no cover
            self._set_result(f"Selected override error: {exc}")

    def _do_apply_daemon_material(self) -> None:
        try:
            try:
                from isaac_extension.daemon_client import apply_curated_material, apply_measured_material
            except ImportError:  # pragma: no cover - Isaac runtime fallback
                from daemon_client import apply_curated_material, apply_measured_material

            scene_id = self._current_scene_id()
            if not scene_id:
                raise RuntimeError("No daemon scene is selected.")
            prim_paths = self._selected_prim_paths()
            if not prim_paths:
                raise RuntimeError("No selected prims are available in Isaac.")
            material = self._selected_daemon_material_record()
            if material is None:
                raise RuntimeError("No render daemon material is selected. Refresh materials first.")

            daemon_url = self._daemon_url_field.model.get_value_as_string().strip()
            applied = 0
            for prim_path in prim_paths:
                if material.get("kind") == "curated":
                    apply_curated_material(
                        scene_id,
                        prim_path=prim_path,
                        material_id=str(material.get("material_id") or ""),
                        daemon_url=daemon_url,
                        timeout_s=10.0,
                    )
                else:
                    apply_measured_material(
                        scene_id,
                        prim_path=prim_path,
                        dataset_id=str(material.get("dataset_id") or ""),
                        material_id=str(material.get("material_id") or ""),
                        measured_file_path=str(material.get("native_file") or ""),
                        bsdf_type=str(material.get("bsdf_type") or "measured_polarized"),
                        daemon_url=daemon_url,
                        timeout_s=10.0,
                    )
                applied += 1
            self._refresh_selected_daemon_material_status(prim_paths)
            self._set_result(f"Applied {self._daemon_material_label(material)} to {applied} selected prim(s).")
        except Exception as exc:  # pragma: no cover
            self._set_result(f"Daemon material apply error: {exc}")

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
        if self._window is not None:
            self._window.destroy()
            self._window = None
