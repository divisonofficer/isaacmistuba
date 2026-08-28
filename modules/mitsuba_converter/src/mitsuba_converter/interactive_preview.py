"""Low-latency Mitsuba RGB sessions used by the OpticalNav live viewer.

This deliberately does not use the durable render queue: an interactive
session owns one resident scene and only retains the newest camera pose.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import io
import math
import os
from pathlib import Path
import queue
import sys
import threading
import time
from typing import Any, Callable
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image

from .mitsuba_runtime import ensure_mitsuba_variant


LIVE_PREVIEW_RESOLUTIONS = (
    (256, 192), (384, 288), (512, 384), (640, 360),
    (640, 480), (768, 576), (1024, 768),
)


@dataclass(frozen=True)
class LivePreviewConfig:
    width: int = 640
    height: int = 360
    spp: int = 1
    max_depth: int = 4
    fov_deg: float = 70.0
    jpeg_quality: int = 82
    renderer_mode: str = "classic"


class DrJitFrozenRenderer:
    """Upstream Dr.Jit freeze adapter for a resident Mitsuba scene.

    This intentionally avoids a private Mitsuba C++ binding: Device 1's
    OptiX 8 build already exposes ``dr.freeze`` and its own rendering tests
    cover frozen ``mi.render(scene)`` calls.  The scene and sensor objects stay
    resident while their traversed parameters are updated before each call.
    """

    def __init__(self, scene: Any, sensor: Any, spp: int) -> None:
        import drjit as dr
        import mitsuba as mi

        if not dr.has_backend(dr.JitBackend.CUDA):
            raise RuntimeError("frozen live viewer requires an active Dr.Jit CUDA backend")
        self._dr = dr
        self._scene = scene
        self._sensor = sensor
        self._render = dr.freeze(
            lambda active_scene, active_sensor: mi.render(active_scene, sensor=active_sensor, spp=spp),
            backend=dr.JitBackend.CUDA,
            limit=1,
        )
        self.last_stage = "record"

    def render(self, _sequence: int) -> Any:
        previous = int(self._render.n_recordings)
        image = self._render(self._scene, self._sensor)
        self._dr.eval(image)
        self.last_stage = "record" if int(self._render.n_recordings) > previous else "replay"
        return image


def live_preview_config_from_env() -> LivePreviewConfig:
    """Read bounded live-only quality knobs without affecting dataset renders."""
    def integer(name: str, default: int, minimum: int, maximum: int) -> int:
        try:
            return max(minimum, min(maximum, int(os.environ.get(name, default))))
        except (TypeError, ValueError):
            return default

    renderer_mode = os.environ.get("ROBOMITUBA_LIVE_PREVIEW_RENDERER", "classic").strip().lower()
    if renderer_mode not in {"classic", "frozen"}:
        raise RuntimeError("ROBOMITUBA_LIVE_PREVIEW_RENDERER must be classic or frozen")
    return LivePreviewConfig(
        width=integer("ROBOMITUBA_LIVE_PREVIEW_WIDTH", 640, 160, 1280),
        height=integer("ROBOMITUBA_LIVE_PREVIEW_HEIGHT", 360, 90, 1080),
        spp=integer("ROBOMITUBA_LIVE_PREVIEW_SPP", 1, 1, 256),
        max_depth=integer("ROBOMITUBA_LIVE_PREVIEW_MAX_DEPTH", 4, 1, 8),
        jpeg_quality=integer("ROBOMITUBA_LIVE_PREVIEW_JPEG_QUALITY", 82, 30, 95),
        renderer_mode=renderer_mode,
    )


def live_preview_config_with_spp(spp: object | None) -> LivePreviewConfig:
    """Apply a per-WebSocket live-only SPP override to the environment profile."""
    config = live_preview_config_from_env()
    if spp is None or spp == "":
        return config
    try:
        requested = int(str(spp))
    except (TypeError, ValueError) as exc:
        raise ValueError("live preview spp must be one of 1, 2, 4, ..., 256") from exc
    if not 1 <= requested <= 256 or requested & (requested - 1):
        raise ValueError("live preview spp must be one of 1, 2, 4, ..., 256")
    return replace(config, spp=requested)


def live_preview_config_with_overrides(
    spp: object | None, width: object | None, height: object | None, renderer_mode: object | None = None,
) -> LivePreviewConfig:
    """Apply bounded per-WebSocket quality settings to the environment profile."""
    config = live_preview_config_with_spp(spp)
    if renderer_mode is not None and renderer_mode != "":
        requested_renderer = str(renderer_mode).strip().lower()
        if requested_renderer not in {"classic", "frozen"}:
            raise ValueError("live preview renderer must be classic or frozen")
        config = replace(config, renderer_mode=requested_renderer)
    if width is None and height is None:
        return config
    try:
        resolution = (int(str(width)), int(str(height)))
    except (TypeError, ValueError) as exc:
        raise ValueError("live preview width and height must select a supported resolution") from exc
    if resolution not in LIVE_PREVIEW_RESOLUTIONS:
        supported = ", ".join(f"{w}x{h}" for w, h in LIVE_PREVIEW_RESOLUTIONS)
        raise ValueError(f"live preview resolution must be one of: {supported}")
    return replace(config, width=resolution[0], height=resolution[1])


def live_preview_cold_start_estimate(scene_path: Path, config: LivePreviewConfig) -> dict[str, int]:
    """Give the UI a deliberately coarse first-frame expectation.

    Mitsuba does not expose incremental progress from ``load_file`` or texture
    uploads, so this is a cold-cache range rather than a false percentage. It
    is based only on cheap XML structure and the requested frozen recording
    work; it is never used for scheduling or timeout decisions.
    """
    try:
        root = ET.parse(scene_path).getroot()
        texture_count = sum(1 for _ in root.iter("texture"))
        shape_count = sum(1 for _ in root.iter("shape"))
    except (ET.ParseError, OSError):
        texture_count = 0
        shape_count = 0

    if texture_count <= 200:
        load_lower, load_upper = 12, 45
    elif texture_count <= 1_000:
        load_lower, load_upper = 35, 110
    elif texture_count <= 2_500:
        load_lower, load_upper = 90, 210
    else:
        load_lower, load_upper = 150, 360

    pixel_spp = (config.width * config.height / (640 * 360)) * config.spp
    scene_factor = 1.0 + texture_count / 500.0
    record_upper = max(3, math.ceil(pixel_spp * scene_factor * 0.7))
    record_lower = max(1, math.ceil(record_upper * 0.35))
    return {
        "texture_count": texture_count,
        "shape_count": shape_count,
        "load_lower_s": load_lower,
        "load_upper_s": load_upper,
        "record_lower_s": record_lower,
        "record_upper_s": record_upper,
        "first_frame_lower_s": load_lower + record_lower,
        "first_frame_upper_s": load_upper + record_upper,
    }


def scene_revision(path: Path) -> str:
    stat = path.stat()
    return f"{stat.st_mtime_ns:x}-{stat.st_size:x}"


def _jpeg(image: np.ndarray, quality: int) -> bytes:
    rgb = np.asarray(image, dtype=np.float32)[..., :3]
    # A viewer frame is display-referred only. Dataset EXR/PNG generation is
    # intentionally left to the regular multimodal pipeline.
    rgb = rgb / (1.0 + np.maximum(rgb, 0.0))
    rgb = np.power(np.clip(rgb, 0.0, 1.0), 1.0 / 2.2)
    out = io.BytesIO()
    Image.fromarray(np.rint(rgb * 255.0).astype(np.uint8), mode="RGB").save(
        out, format="JPEG", quality=quality, optimize=False
    )
    return out.getvalue()


def _cuda_rgb_scene_xml_compatibility(scene_path: Path) -> tuple[str | None, int]:
    """Return a compliant XML override for a known non-AD CUDA/OptiX crash.

    The Device 2 OptiX 7 build crashes while building a scene that contains a
    ``twosided`` wrapper around a perfect ``conductor``. This representation
    is outside OpticalNav's allowed preview BSDF set (pplastic,
    roughconductor, dielectric) and crashes with ``cuda_rgb`` only; scalar
    and ``cuda_ad_rgb`` both load it. The live session converts it to a direct
    GGX ``roughconductor`` with the configured minimum roughness. The source
    XML remains untouched and the conversion runs only at scene load/reload,
    never per camera update.
    """
    root = ET.parse(scene_path).getroot()
    converted = 0
    for bsdf in root.findall("bsdf"):
        nested = next((child for child in bsdf if child.tag == "bsdf"), None)
        if bsdf.get("type") != "twosided" or nested is None or nested.get("type") != "conductor":
            continue
        bsdf.attrib = {"type": "roughconductor", "id": bsdf.get("id", "")}
        bsdf[:] = list(nested)
        ET.SubElement(bsdf, "string", {"name": "distribution", "value": "ggx"})
        ET.SubElement(bsdf, "float", {"name": "alpha", "value": "0.1000"})
        converted += 1
    if not converted:
        return None, 0
    return ET.tostring(root, encoding="unicode"), converted


def normalize_live_frozen_bsdfs(scene_path: Path) -> tuple[str, dict[str, int]]:
    """Make the frozen bridge's XML contract explicit without editing the scene.

    ``twosided``, perfect ``conductor``, and ``roughplastic`` are intentionally
    not passed to the frozen renderer. OpticalNav's generated XML represents
    most opaque assets as ``twosided(normalmap(roughplastic))`` and combines
    them with ``blendbsdf``. This live-only conversion removes ``twosided``,
    retains normal-map textures and blend weights, and converts leaf BSDFs to
    the supported base set. Any other wrapper or base BSDF is a deterministic
    load error, rather than silently taking the old slow path or changing
    dataset output.
    """
    root = ET.parse(scene_path).getroot()
    conversions = {"pplastic": 0, "roughconductor": 0, "dielectric": 0, "normalmap": 0}
    allowed = {"pplastic", "roughconductor", "dielectric"}

    def child_bsdfs(container: ET.Element, label: str, expected: int) -> list[ET.Element]:
        children = [child for child in container if child.tag == "bsdf"]
        if len(children) != expected:
            raise RuntimeError(f"frozen live viewer requires {label} to contain exactly {expected} direct child BSDFs")
        return children

    def normalize_base(base: ET.Element) -> str:
        source_type = base.get("type", "")
        target_type = {"roughplastic": "pplastic", "conductor": "roughconductor"}.get(source_type, source_type)
        if target_type not in allowed:
            raise RuntimeError(
                f"frozen live viewer rejects BSDF '{source_type}' (allowed bases: pplastic, roughconductor, dielectric)"
            )
        if source_type != target_type:
            base.attrib = {**base.attrib, "type": target_type}
            conversions[target_type] += 1
        return target_type

    def normalize_bsdf(bsdf: ET.Element) -> None:
        source_type = bsdf.get("type", "")
        if source_type == "twosided":
            outer_id = bsdf.get("id")
            child = child_bsdfs(bsdf, "twosided", 1)[0]
            normalize_bsdf(child)
            if child.get("type") == "normalmap":
                conversions["normalmap"] += 1
            bsdf.attrib = {**child.attrib, **({"id": outer_id} if outer_id else {})}
            bsdf[:] = list(child)
            return
        if source_type == "normalmap":
            normalize_bsdf(child_bsdfs(bsdf, "normalmap", 1)[0])
            return
        if source_type == "blendbsdf":
            for child in child_bsdfs(bsdf, "blendbsdf", 2):
                normalize_bsdf(child)
            return
        normalize_base(bsdf)

    for bsdf in root.findall("bsdf"):
        normalize_bsdf(bsdf)
    return ET.tostring(root, encoding="unicode"), conversions


class InteractivePreviewSession:
    """One latest-pose-wins CUDA RGB rendering session.

    ``on_event`` receives JSON-serializable status dictionaries and
    ``on_frame`` receives (metadata, JPEG bytes). Both callbacks are called by
    the session worker, never by the WebSocket reader.
    """

    def __init__(
        self,
        scene_path: Path,
        *,
        on_event: Callable[[dict[str, Any]], None],
        on_frame: Callable[[dict[str, Any], bytes], None],
        variant: str = "cuda_rgb",
        config: LivePreviewConfig = LivePreviewConfig(),
    ) -> None:
        self.scene_path = scene_path
        self.on_event = on_event
        self.on_frame = on_frame
        self.variant = variant
        self.config = config
        self._lock = threading.Condition()
        self._latest_pose: dict[str, float] | None = None
        self._sequence = 0
        self._last_rendered_sequence = -1
        self._closed = False
        self._reload = True
        self._scene: Any | None = None
        self._sensor: Any | None = None
        self._sensor_params: Any | None = None
        self._revision: str | None = None
        self._frozen_renderer: Any | None = None
        self._thread = threading.Thread(target=self._run, name="interactive-preview", daemon=True)
        self._thread.start()

    def update_pose(self, payload: dict[str, Any]) -> None:
        def finite(name: str, default: float) -> float:
            try:
                value = float(payload.get(name, default))
                return value if math.isfinite(value) else default
            except (TypeError, ValueError):
                return default

        pose = {
            "x": finite("x", 0.0), "y": finite("y", 1.5), "z": finite("z", 0.0),
            "yaw_deg": finite("yaw_deg", 0.0), "pitch_deg": max(-89.0, min(89.0, finite("pitch_deg", 0.0))),
            "fov_deg": max(20.0, min(120.0, finite("fov_deg", self.config.fov_deg))),
        }
        with self._lock:
            self._latest_pose = pose
            self._sequence += 1
            self._lock.notify()

    def request_reload(self) -> None:
        with self._lock:
            self._reload = True
            self._lock.notify()

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._lock.notify_all()
        self._thread.join(timeout=2.0)

    def _emit(self, event_type: str, **payload: Any) -> None:
        print(
            f"[live-preview] {event_type} "
            + " ".join(f"{key}={value}" for key, value in payload.items()),
            file=sys.stderr,
            flush=True,
        )
        self.on_event({"type": event_type, **payload})

    def _load(self) -> None:
        import mitsuba as mi

        estimate = live_preview_cold_start_estimate(self.scene_path, self.config)
        self._emit(
            "status", state="warming", phase="estimate",
            detail="Estimating cold-start work from scene XML",
            estimate=estimate,
        )
        self._emit("status", state="warming", phase="variant", detail="Selecting CUDA renderer")
        active_variant = ensure_mitsuba_variant(self.variant)
        if active_variant != self.variant:
            raise RuntimeError(f"interactive preview requires {self.variant}, got {active_variant}")
        started = time.perf_counter()
        print(f"[live-preview] load begin scene={self.scene_path} variant={active_variant}", file=sys.stderr, flush=True)
        compat_count = 0
        if self.config.renderer_mode == "frozen":
            self._emit("status", state="warming", phase="materials", detail="Normalizing frozen-compatible BSDFs")
            scene_xml, conversions = normalize_live_frozen_bsdfs(self.scene_path)
            self._emit("status", state="warming", phase="scene", detail="Loading scene geometry and textures")
            thread = mi.Thread.thread()
            resolver = thread.file_resolver()
            if resolver is None:
                resolver = mi.FileResolver()
                resolver.append(str(Path(mi.__file__).resolve().parents[2]))
                thread.set_file_resolver(resolver)
            resolver.prepend(str(self.scene_path.parent))
            scene = mi.load_string(scene_xml)
            compat_count = sum(conversions.values())
        elif active_variant == "cuda_rgb":
            self._emit("status", state="warming", phase="scene", detail="Loading scene geometry and textures")
            scene_xml, compat_count = _cuda_rgb_scene_xml_compatibility(self.scene_path)
            if scene_xml is not None:
                # ``load_string`` needs the original XML directory to resolve
                # relative assets such as the environment map.
                thread = mi.Thread.thread()
                resolver = thread.file_resolver()
                # Python-created worker threads do not inherit Mitsuba's
                # resolver. Main-thread smoke tests therefore pass while the
                # interactive renderer sees ``None`` here.
                if resolver is None:
                    resolver = mi.FileResolver()
                    # ``load_string`` resolves built-in plugins (e.g. srgb)
                    # relative to the Mitsuba build root, not the scene XML.
                    # The default resolver normally contains this directory,
                    # but an external Python thread starts with no resolver.
                    resolver.append(str(Path(mi.__file__).resolve().parents[2]))
                    thread.set_file_resolver(resolver)
                resolver.prepend(str(self.scene_path.parent))
                scene = mi.load_string(scene_xml)
            else:
                scene = mi.load_file(str(self.scene_path))
        else:
            self._emit("status", state="warming", phase="scene", detail="Loading scene geometry and textures")
            scene = mi.load_file(str(self.scene_path))
        print(f"[live-preview] load complete scene={self.scene_path.name} compatibility_normalized={compat_count}", file=sys.stderr, flush=True)
        self._emit("status", state="warming", phase="sensor", detail="Configuring live camera and film")
        params = mi.traverse(scene)
        if "integrator.max_depth" in params:
            params["integrator.max_depth"] = self.config.max_depth
            params.update()
        sensor = mi.load_dict({
            "type": "perspective",
            "fov": self.config.fov_deg,
            "to_world": mi.ScalarTransform4f.look_at(origin=[0, 1.5, 0], target=[0, 1.5, -1], up=[0, 1, 0]),
            "film": {"type": "hdrfilm", "width": self.config.width, "height": self.config.height},
            "sampler": {"type": "independent", "sample_count": 1},
        })
        self._scene, self._sensor, self._sensor_params = scene, sensor, mi.traverse(sensor)
        if self.config.renderer_mode == "frozen":
            self._emit("status", state="warming", phase="freeze", detail="Preparing frozen CUDA render graph")
        self._frozen_renderer = (
            DrJitFrozenRenderer(scene, sensor, self.config.spp)
            if self.config.renderer_mode == "frozen" else None
        )
        self._revision = scene_revision(self.scene_path)
        self._emit(
            "ready", revision=self._revision, variant=active_variant,
            warmup_ms=round((time.perf_counter() - started) * 1000, 2),
            compatibility_conductor_normalized=compat_count,
            width=self.config.width, height=self.config.height,
            spp=self.config.spp, max_depth=self.config.max_depth,
            renderer_mode=self.config.renderer_mode,
        )

    def _set_camera(self, pose: dict[str, float]) -> None:
        import mitsuba as mi

        yaw, pitch = math.radians(pose["yaw_deg"]), math.radians(pose["pitch_deg"])
        forward = [math.sin(yaw) * math.cos(pitch), math.sin(pitch), -math.cos(yaw) * math.cos(pitch)]
        origin = [pose["x"], pose["y"], pose["z"]]
        target = [origin[index] + forward[index] for index in range(3)]
        self._sensor_params["to_world"] = mi.ScalarTransform4f.look_at(origin=origin, target=target, up=[0, 1, 0])
        self._sensor_params["x_fov"] = pose["fov_deg"]
        self._sensor_params.update()

    def _run(self) -> None:
        while True:
            with self._lock:
                while not self._closed and (
                    self._latest_pose is None
                    or (not self._reload and self._sequence == self._last_rendered_sequence)
                ):
                    self._lock.wait(timeout=0.25)
                if self._closed:
                    return
                pose = dict(self._latest_pose or {})
                sequence = self._sequence
                reload_needed = self._reload
                self._reload = False
            try:
                changed = self._revision is not None and scene_revision(self.scene_path) != self._revision
                if reload_needed or changed or self._scene is None:
                    self._load()
                self._set_camera(pose)
                started = time.perf_counter()
                import mitsuba as mi
                if self._frozen_renderer is not None and (
                    self._last_rendered_sequence < 0 or self._frozen_renderer.last_stage == "record"
                ):
                    self._emit("status", state="recording", phase="record", detail="Recording frozen CUDA graph for this scene")
                print(f"[live-preview] render begin sequence={sequence}", file=sys.stderr, flush=True)
                if self._frozen_renderer is not None:
                    rendered = self._frozen_renderer.render(sequence)
                    frozen_stage = str(self._frozen_renderer.last_stage)
                else:
                    rendered = mi.render(self._scene, sensor=self._sensor, spp=self.config.spp)
                    frozen_stage = "classic"
                dispatch_ms = (time.perf_counter() - started) * 1000.0
                image = np.asarray(rendered, dtype=np.float32)
                elapsed_ms = (time.perf_counter() - started) * 1000.0
                eval_ms = elapsed_ms - dispatch_ms
                print(
                    f"[live-preview] render complete sequence={sequence} total_ms={elapsed_ms:.2f} "
                    f"dispatch_ms={dispatch_ms:.2f} eval_ms={eval_ms:.2f} "
                    f"profile={self.config.width}x{self.config.height} spp={self.config.spp} depth={self.config.max_depth}",
                    file=sys.stderr, flush=True,
                )
                # Rendered images are snapshots of the newest pose available at
                # render start. Publishing that snapshot preserves a bounded
                # one-frame latency during continuous input. Discarding it when
                # a 30 Hz pose update arrives during a 32 ms render starves the
                # stream and reduces its observed FPS to nearly zero.
                with self._lock:
                    if self._closed:
                        return
                    self._last_rendered_sequence = sequence
                encode_started = time.perf_counter()
                jpeg = _jpeg(image, self.config.jpeg_quality)
                encode_ms = (time.perf_counter() - encode_started) * 1000.0
                self.on_frame({
                    "type": "frame", "sequence": sequence, "revision": self._revision,
                    "width": self.config.width, "height": self.config.height,
                    "render_ms": round(elapsed_ms, 2), "dispatch_ms": round(dispatch_ms, 2),
                    "eval_ms": round(eval_ms, 2), "encode_ms": round(encode_ms, 2), "pose": pose,
                    "renderer_mode": self.config.renderer_mode, "frozen_stage": frozen_stage,
                    "record_ms": round(elapsed_ms, 2) if frozen_stage == "record" else None,
                    "replay_ms": round(elapsed_ms, 2) if frozen_stage == "replay" else None,
                }, jpeg)
            except Exception as exc:
                self._emit("error", message=f"{type(exc).__name__}: {exc}")
                # Do not spin on an unavailable variant or a malformed scene.
                with self._lock:
                    self._latest_pose = None


def run_interactive_preview_worker(
    scene_path: str,
    commands: Any,
    results: Any,
    config: LivePreviewConfig | None = None,
) -> None:
    """Run an interactive session in a clean process owned by one client.

    Mitsuba's non-AD CUDA evaluator can segfault when it shares a process with
    the durable daemon's worker/persistence threads.  Keeping this entry point
    at module scope makes it usable with the ``spawn`` multiprocessing context.
    """
    def emit(event: dict[str, Any]) -> None:
        results.put(("event", event))

    def emit_frame(metadata: dict[str, Any], jpeg: bytes) -> None:
        try:
            metadata = dict(metadata)
            metadata["worker_enqueued_at"] = time.monotonic()
            results.put_nowait(("frame", metadata, jpeg))
        except queue.Full:
            # A slow client should lose an old preview frame, never block render.
            pass

    session = InteractivePreviewSession(
        Path(scene_path), on_event=emit, on_frame=emit_frame,
        config=config or live_preview_config_from_env(),
    )
    try:
        while True:
            try:
                message = commands.get(timeout=0.2)
            except queue.Empty:
                continue
            if not isinstance(message, dict):
                continue
            kind = str(message.get("type") or "")
            if kind == "close":
                return
            if kind == "camera":
                session.update_pose(message)
            elif kind == "reload":
                session.request_reload()
    finally:
        session.close()
