#!/usr/bin/env python3
"""Run the standalone IR dataset viewer backend and static SPA."""
from __future__ import annotations

import argparse
import gzip
import json
import mimetypes
import os
import shutil
import socket
import sys
import threading
import time
import select
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

APP_DIR = Path(__file__).resolve().parent
REPO_ROOT = APP_DIR.parents[1]
sys.path.insert(0, str(REPO_ROOT))
for module in ("robomituba_bridge", "mitsuba_converter"):
    sys.path.insert(0, str(REPO_ROOT / "modules" / module / "src"))

from mitsuba_converter.ir_dataset_publish import PublishManager  # noqa: E402
from mitsuba_converter.ir_dataset_contract import _safe_artifact_path  # noqa: E402
from apps.ir_dataset_viewer.backend.catalog import DatasetCatalog, PreviewService, default_exposure  # noqa: E402
from apps.ir_dataset_viewer.backend.preview_queue import PreviewWorkScheduler  # noqa: E402
from apps.ir_dataset_viewer.backend.controller import IRDatasetController  # noqa: E402


class ViewerServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, handler, *, catalog: DatasetCatalog, previews: PreviewService,
                 publisher: PublishManager, bean_root: Path, static_dir: Path):
        super().__init__(address, handler)
        self.catalog = catalog
        self.previews = previews
        self.publisher = publisher
        self.bean_root = bean_root
        self.static_dir = static_dir
        self.preview_queue = PreviewWorkScheduler(interactive_slots=2, background_slots=1)
        self.controller: IRDatasetController | None = None


class Handler(BaseHTTPRequestHandler):
    server: ViewerServer
    protocol_version = "HTTP/1.1"

    def _controller(self) -> IRDatasetController:
        controller = self.server.controller
        if controller is None:
            raise RuntimeError("control center is still loading; browse APIs are ready")
        return controller

    def log_message(self, fmt: str, *args) -> None:
        print(f"[ir-viewer] {self.address_string()} {fmt % args}", file=sys.stderr, flush=True)

    def _timing_header(self, *parts: str) -> str:
        started = getattr(self, "_request_started", None)
        duration_ms = 0.0 if started is None else (time.perf_counter() - started) * 1000.0
        return ", ".join([*parts, f"ir_viewer;dur={duration_ms:.1f}"])

    def _json(self, status: HTTPStatus, payload, *, cache_control: str = "no-store",
              headers: dict[str, str] | None = None, timing: tuple[str, ...] = ()) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        compressed = len(data) >= 1024 and "gzip" in self.headers.get("Accept-Encoding", "")
        if compressed:
            data = gzip.compress(data, compresslevel=5)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", cache_control)
        self.send_header("Server-Timing", self._timing_header(*timing))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        if compressed:
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Vary", "Accept-Encoding")
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > 1024 * 1024:
            return {}
        value = json.loads(self.rfile.read(length))
        if not isinstance(value, dict):
            raise ValueError("JSON body must be an object")
        return value

    def _api_error(self, exc: Exception) -> None:
        if isinstance(exc, KeyError):
            status = HTTPStatus.NOT_FOUND
        elif isinstance(exc, (ValueError, FileNotFoundError, FileExistsError)):
            status = HTTPStatus.BAD_REQUEST
        elif isinstance(exc, RuntimeError):
            status = HTTPStatus.CONFLICT
        else:
            status = HTTPStatus.INTERNAL_SERVER_ERROR
        self._json(status, {"error": str(exc)})

    def _client_disconnected(self) -> bool:
        """Best-effort disconnect check while a preview is waiting for a slot."""
        try:
            readable, _, _ = select.select([self.connection], [], [], 0)
            if not readable:
                return False
            data = self.connection.recv(1, socket.MSG_PEEK | socket.MSG_DONTWAIT)
            return data == b""
        except (BlockingIOError, ValueError, OSError):
            return False

    def do_GET(self) -> None:  # noqa: N802
        self._request_started = time.perf_counter()
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        try:
            if path == "/api/health":
                self._json(HTTPStatus.OK, {"ok": True, "service": "ir-dataset-viewer"})
                return
            if path == "/api/datasets":
                force = query.get("refresh", ["0"])[0] in {"1", "true"}
                self._json(HTTPStatus.OK, self.server.catalog.list_payload(force=force))
                return
            if path == "/api/scenes":
                self._json(HTTPStatus.OK, self.server.catalog.scenes_payload({key: values[-1] for key, values in query.items()}))
                return
            parts = [unquote(part) for part in path.split("/") if part]
            if path == "/api/controller/status":
                include_hidden = query.get("include_hidden", ["0"])[0] in {"1", "true"}
                self._json(HTTPStatus.OK, self._controller().status(include_hidden=include_hidden))
                return
            if path == "/api/controller/jobs":
                include_hidden = query.get("include_hidden", ["0"])[0] in {"1", "true"}
                self._json(HTTPStatus.OK, self._controller().list_jobs(include_hidden=include_hidden))
                return
            if path == "/api/controller/infinigen-outputs":
                self._json(HTTPStatus.OK, self._controller().existing_outputs())
                return
            if len(parts) >= 4 and parts[:3] == ["api", "controller", "jobs"]:
                job_id = parts[3]
                if len(parts) == 4:
                    self._json(HTTPStatus.OK, self._controller().get(job_id))
                    return
                if len(parts) == 5 and parts[4] == "log":
                    self._json(HTTPStatus.OK, self._controller().log(job_id, int(query.get("tail", ["100"])[0])))
                    return
                if len(parts) == 5 and parts[4] == "recovery-plan":
                    self._json(HTTPStatus.OK, self._controller().recovery_plan(job_id))
                    return
            if len(parts) >= 3 and parts[:2] == ["api", "datasets"]:
                dataset_id = parts[2]
                if len(parts) == 3:
                    record = self.server.catalog.get(dataset_id)
                    # The catalog list is metadata-only for responsiveness;
                    # hydrate the selected dataset once for modalities, frame
                    # rows, and the authoritative contract.
                    record = self.server.catalog._with_rows(record)
                    self._json(HTTPStatus.OK, {**record.summary(include_full_qc=True), "config": record.config,
                                               "contract": record.contract, "qc": record.qc,
                                               "readiness": record.readiness_label},
                               headers={"X-IR-Index-Cache": self.server.catalog.index_cache_status()})
                    return
                # Dataset subroutes must be dispatched before the scene route below.
                # (They were accidentally left after a `return` while scenes support
                # was added, making every /viewpoints, /overview and /frames request
                # look like a 404.)
                if len(parts) == 4 and parts[3] == "viewpoints":
                    self._json(HTTPStatus.OK, self.server.catalog.viewpoints_payload(dataset_id),
                               headers={"X-IR-Index-Cache": self.server.catalog.index_cache_status()})
                    return
                if len(parts) == 4 and parts[3] == "browse":
                    payload = self.server.catalog.browse_payload(
                        dataset_id,
                        viewpoint_id=query.get("viewpoint", [""])[0],
                        frame_id=query.get("frame", [""])[0],
                    )
                    self._json(HTTPStatus.OK, payload,
                               headers={"X-IR-Index-Cache": self.server.catalog.index_cache_status()},
                               timing=self.server.catalog.request_timing_headers())
                    return
                if len(parts) == 4 and parts[3] == "overview":
                    self._json(HTTPStatus.OK, self.server.catalog.overview_payload(dataset_id), cache_control="public, max-age=60",
                               headers={"X-IR-Index-Cache": self.server.catalog.index_cache_status()})
                    return
                if len(parts) == 5 and parts[3] == "overview" and parts[4] in {"traversability", "mesh"}:
                    overview = self.server.catalog.overview_payload(dataset_id)
                    key = "traversability" if parts[4] == "traversability" else "proxy_mesh"
                    entry = overview.get(key) or {}
                    relative = entry.get("path")
                    if not relative:
                        raise KeyError("overview proxy is unavailable" if parts[4] == "mesh" else "traversability")
                    record = self.server.catalog.get(dataset_id)
                    artifact_path = _safe_artifact_path(record.primary.path, str(relative))
                    etag = str(entry.get("sha256") or "")
                    cache_control = "public, max-age=31536000, immutable" if record.primary.kind == "bean" else "public, max-age=60, must-revalidate"
                    if etag and self.headers.get("If-None-Match", "").strip('"') == etag:
                        self.send_response(HTTPStatus.NOT_MODIFIED)
                        self.send_header("ETag", f'"{etag}"')
                        self.send_header("Cache-Control", cache_control)
                        self.send_header("Server-Timing", self._timing_header())
                        self.end_headers()
                        return
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "model/gltf-binary" if parts[4] == "mesh" else "image/png")
                    self.send_header("Content-Length", str(artifact_path.stat().st_size))
                    if etag:
                        self.send_header("ETag", f'"{etag}"')
                    self.send_header("Cache-Control", cache_control)
                    self.send_header("Server-Timing", self._timing_header())
                    self.end_headers()
                    with artifact_path.open("rb") as stream:
                        shutil.copyfileobj(stream, self.wfile)
                    return
                if len(parts) >= 5 and parts[3] == "frames":
                    frame_id = parts[4]
                    if len(parts) == 5:
                        self._json(HTTPStatus.OK, self.server.catalog.frame_payload(dataset_id, frame_id),
                                   headers={"X-IR-Index-Cache": self.server.catalog.index_cache_status()})
                        return
                    if len(parts) == 6 and parts[5] == "pixels":
                        x = int(query.get("x", ["-1"])[0]); y = int(query.get("y", ["-1"])[0])
                        modalities = [item for item in query.get("modalities", [""])[0].split(",") if item]
                        self._json(HTTPStatus.OK, self.server.previews.pixels(dataset_id, frame_id, x, y, modalities),
                                   headers={"X-IR-Index-Cache": self.server.catalog.index_cache_status()})
                        return
                    if len(parts) == 7 and parts[5] == "preview":
                        modality = parts[6]
                        priority = query.get("priority", ["interactive"])[0]
                        if priority not in PreviewWorkScheduler.PRIORITIES:
                            raise ValueError("priority must be interactive, comparison, or prefetch")
                        record = self.server.catalog.get(dataset_id)
                        base_ev = default_exposure(record, modality)
                        preview_kwargs = dict(
                            exposure_ev=base_ev + float(query.get("ev", ["0"])[0]),
                            minimum=float(query.get("min", ["0"])[0]), maximum=float(query.get("max", ["10"])[0]),
                            overlay_modality=query.get("overlay", [None])[0], overlay_opacity=float(query.get("opacity", ["0.45"])[0]),
                            max_width=int(query["max_width"][0]) if query.get("max_width") else None,
                        )
                        image_format = query.get("format", ["auto"])[0]
                        etag, format_name, immutable = self.server.previews.etag(dataset_id, frame_id, modality, **preview_kwargs, image_format=image_format)
                        if self.headers.get("If-None-Match", "").strip('"') == etag:
                            self.send_response(HTTPStatus.NOT_MODIFIED)
                            self.send_header("ETag", f'"{etag}"')
                            self.send_header("Server-Timing", self._timing_header())
                            self.send_header("X-IR-Index-Cache", self.server.catalog.index_cache_status())
                            self.send_header("X-IR-Preview-Cache", "http-304")
                            self.send_header("X-IR-Preview-Queue", "bypass")
                            self.end_headers(); return
                        cache_started = time.perf_counter()
                        cached = self.server.previews.cached_preview(dataset_id, frame_id, modality, **preview_kwargs, image_format=image_format)
                        cache_ms = (time.perf_counter() - cache_started) * 1000.0
                        queue_state = "bypass"
                        queue_ms = decode_ms = 0.0
                        if cached is not None:
                            data, _ = cached
                        else:
                            lease = self.server.preview_queue.acquire(priority, cancelled=self._client_disconnected)
                            if lease is None:
                                # The browser has aborted an idle request while it was queued.
                                return
                            queue_ms = lease.waited_ms
                            queue_state = f"{priority};wait={queue_ms:.1f}"
                            try:
                                if self._client_disconnected():
                                    return
                                work_started = time.perf_counter()
                                data, _ = self.server.previews.preview(dataset_id, frame_id, modality, **preview_kwargs, image_format=image_format)
                                decode_ms = (time.perf_counter() - work_started) * 1000.0
                            finally:
                                self.server.preview_queue.release(lease)
                        self.send_response(HTTPStatus.OK); self.send_header("Content-Type", "image/webp" if format_name == "webp" else "image/png")
                        self.send_header("Content-Length", str(len(data))); self.send_header("ETag", f'"{etag}"')
                        self.send_header("Cache-Control", "public, max-age=31536000, immutable" if immutable else "public, max-age=60, must-revalidate")
                        self.send_header("Server-Timing", self._timing_header(
                            f"preview_cache;dur={cache_ms:.1f}", f"preview_queue;dur={queue_ms:.1f}",
                            f"preview_decode_encode;dur={decode_ms:.1f}"))
                        self.send_header("X-IR-Index-Cache", self.server.catalog.index_cache_status())
                        self.send_header("X-IR-Preview-Cache", self.server.previews.preview_cache_status())
                        self.send_header("X-IR-Preview-Queue", queue_state)
                        self.end_headers(); self.wfile.write(data); return
            if len(parts) == 3 and parts[:2] == ["api", "scenes"]:
                self._json(HTTPStatus.OK, self.server.catalog.scene_payload(parts[2]))
                return
            if len(parts) == 3 and parts[:2] == ["api", "publish"]:
                self._json(HTTPStatus.OK, self.server.publisher.get(parts[2]))
                return
            if path.startswith("/api/"):
                self._json(HTTPStatus.NOT_FOUND, {"error": "unknown API route"})
                return
            self._static(path)
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as exc:
            self._api_error(exc)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        parts = [unquote(part) for part in parsed.path.split("/") if part]
        try:
            if parsed.path == "/api/publish":
                body = self._body()
                dataset_id = str(body.get("dataset_id") or "")
                origin = self.server.catalog.publish_origin(dataset_id)
                result = self.server.publisher.submit(origin.path, self.server.bean_root,
                                                      str(body.get("name") or origin.path.name))
                self._json(HTTPStatus.ACCEPTED, result)
                return
            if parsed.path == "/api/controller/jobs":
                self._json(HTTPStatus.ACCEPTED, self._controller().submit(self._body()))
                return
            if len(parts) == 5 and parts[:3] == ["api", "controller", "jobs"]:
                job_id, action = parts[3], parts[4]
                if action == "cancel":
                    self._json(HTTPStatus.OK, self._controller().cancel_job(job_id)); return
                if action == "replan":
                    body = self._body()
                    self._json(HTTPStatus.ACCEPTED, self._controller().replan(
                        job_id, legacy_plan=(str(body["legacy_plan"]) if body.get("legacy_plan") else None),
                    )); return
                if action == "retry":
                    self._json(HTTPStatus.ACCEPTED, self._controller().retry(job_id)); return
                if action == "retry-showcase":
                    self._json(HTTPStatus.ACCEPTED, self._controller().retry_with_showcase(job_id)); return
                if action == "resume":
                    body = self._body()
                    self._json(HTTPStatus.ACCEPTED, self._controller().resume(
                        job_id, mode=str(body.get("mode") or "recommended"),
                        insert_stages=list(body.get("insert_stages") or []),
                        rerun_from=(str(body["rerun_from"]) if body.get("rerun_from") else None),
                    )); return
                if action == "adopt":
                    self._json(HTTPStatus.OK, self._controller().adopt_external_import(job_id)); return
                if action == "priority":
                    self._json(HTTPStatus.OK, self._controller().priority(job_id, int(self._body().get("priority", 0)))); return
                if action == "remove":
                    self._json(HTTPStatus.OK, self._controller().remove_terminal_job(job_id)); return
                if action in {"hide", "unhide"}:
                    self._json(HTTPStatus.OK, self._controller().set_job_visibility(job_id, hidden=action == "hide")); return
                if action == "replace":
                    body = self._body()
                    self._json(HTTPStatus.ACCEPTED, self._controller().replace_failed_generated_scene(
                        job_id, logical_seed=str(body.get("logical_seed") or ""),
                    )); return
            if len(parts) == 4 and parts[:2] == ["api", "publish"] and parts[3] == "cancel":
                self._json(HTTPStatus.OK, self.server.publisher.cancel(parts[2]))
                return
            self._json(HTTPStatus.NOT_FOUND, {"error": "unknown API route"})
        except Exception as exc:
            self._api_error(exc)

    def _static(self, url_path: str) -> None:
        relative = "index.html" if url_path in {"", "/"} else url_path.lstrip("/")
        if ".." in Path(relative).parts:
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        target = (self.server.static_dir / relative).resolve()
        static_root = self.server.static_dir.resolve()
        if static_root != target and static_root not in target.parents:
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if not target.is_file():
            target = static_root / "index.html"
        if not target.is_file():
            self._json(HTTPStatus.NOT_FOUND, {"error": "viewer frontend is not built"})
            return
        data = target.read_bytes()
        mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache" if target.name == "index.html" else "public, max-age=86400")
        self.end_headers()
        self.wfile.write(data)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8780)
    parser.add_argument("--bean-root", type=Path, default=Path("/bean/ir_dataset"))
    parser.add_argument("--out-root", type=Path, default=REPO_ROOT / "out" / "ir_dataset")
    parser.add_argument("--work-root", type=Path, default=Path("/bean/ir_dataset_work"))
    parser.add_argument("--cache-dir", type=Path, default=Path("/tmp/robomituba-ir-viewer-cache"))
    parser.add_argument("--cache-gib", type=float, default=5.0)
    parser.add_argument("--memory-cache-mib", type=float, default=512.0)
    parser.add_argument("--static-dir", type=Path, default=APP_DIR / "dist")
    args = parser.parse_args()
    if not args.static_dir.is_dir() or not (args.static_dir / "index.html").is_file():
        parser.error(
            f"viewer frontend is not built: {args.static_dir}. "
            "Run `cd apps/ir_dataset_viewer && npm run build` first."
        )
    catalog = DatasetCatalog([("bean", args.bean_root), ("work", args.work_root), ("out", args.out_root)],
                             statistics_root=args.work_root / ".catalog_statistics",
                             readiness_root=args.work_root / ".catalog_quality_labels",
                             review_root=args.work_root / ".catalog_scene_reviews")
    previews = PreviewService(catalog, args.cache_dir, disk_max_bytes=int(args.cache_gib * 1024**3),
                              memory_max_bytes=int(args.memory_cache_mib * 1024**2))
    server = ViewerServer((args.host, args.port), Handler, catalog=catalog, previews=previews,
                          publisher=PublishManager(), bean_root=args.bean_root.resolve(), static_dir=args.static_dir)
    print(f"[ir-viewer] frontend+API http://{args.host}:{server.server_address[1]}/", flush=True)
    print(f"[ir-viewer] roots bean={args.bean_root} work={args.work_root} out={args.out_root}", flush=True)
    # Controller recovery scans durable job logs and can be expensive.  Do
    # not block the dataset browser (especially the first showcase lookup) on
    # that scan; controller endpoints return a short loading error meanwhile.
    def load_controller() -> None:
        server.controller = IRDatasetController(repo_root=REPO_ROOT, work_root=args.work_root, bean_root=args.bean_root)
        print("[ir-viewer] controller ready", flush=True)
    threading.Thread(target=load_controller, name="ir-controller-bootstrap", daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
