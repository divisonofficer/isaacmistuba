#!/usr/bin/env python3
"""Run the standalone IR dataset viewer backend and static SPA."""
from __future__ import annotations

import argparse
import gzip
import json
import mimetypes
import os
import shutil
import sys
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
        self.controller: IRDatasetController | None = None


class Handler(BaseHTTPRequestHandler):
    server: ViewerServer

    def log_message(self, fmt: str, *args) -> None:
        print(f"[ir-viewer] {self.address_string()} {fmt % args}", file=sys.stderr, flush=True)

    def _json(self, status: HTTPStatus, payload, *, cache_control: str = "no-store") -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        compressed = len(data) >= 1024 and "gzip" in self.headers.get("Accept-Encoding", "")
        if compressed:
            data = gzip.compress(data, compresslevel=5)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", cache_control)
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

    def do_GET(self) -> None:  # noqa: N802
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
                self._json(HTTPStatus.OK, self.server.controller.status())
                return
            if path == "/api/controller/jobs":
                self._json(HTTPStatus.OK, self.server.controller.list_jobs())
                return
            if path == "/api/controller/infinigen-outputs":
                self._json(HTTPStatus.OK, self.server.controller.existing_outputs())
                return
            if len(parts) >= 4 and parts[:3] == ["api", "controller", "jobs"]:
                job_id = parts[3]
                if len(parts) == 4:
                    self._json(HTTPStatus.OK, self.server.controller.get(job_id))
                    return
                if len(parts) == 5 and parts[4] == "log":
                    self._json(HTTPStatus.OK, self.server.controller.log(job_id, int(query.get("tail", ["100"])[0])))
                    return
                if len(parts) == 5 and parts[4] == "recovery-plan":
                    self._json(HTTPStatus.OK, self.server.controller.recovery_plan(job_id))
                    return
            if len(parts) >= 3 and parts[:2] == ["api", "datasets"]:
                dataset_id = parts[2]
                if len(parts) == 3:
                    record = self.server.catalog.get(dataset_id)
                    self._json(HTTPStatus.OK, {**record.summary(), "config": record.config,
                                               "contract": record.contract, "qc": record.qc})
                    return
                # Dataset subroutes must be dispatched before the scene route below.
                # (They were accidentally left after a `return` while scenes support
                # was added, making every /viewpoints, /overview and /frames request
                # look like a 404.)
                if len(parts) == 4 and parts[3] == "viewpoints":
                    self._json(HTTPStatus.OK, self.server.catalog.viewpoints_payload(dataset_id))
                    return
                if len(parts) == 4 and parts[3] == "overview":
                    self._json(HTTPStatus.OK, self.server.catalog.overview_payload(dataset_id), cache_control="public, max-age=60")
                    return
                if len(parts) >= 5 and parts[3] == "frames":
                    frame_id = parts[4]
                    if len(parts) == 5:
                        self._json(HTTPStatus.OK, self.server.catalog.frame_payload(dataset_id, frame_id))
                        return
                    if len(parts) == 6 and parts[5] == "pixels":
                        x = int(query.get("x", ["-1"])[0]); y = int(query.get("y", ["-1"])[0])
                        modalities = [item for item in query.get("modalities", [""])[0].split(",") if item]
                        self._json(HTTPStatus.OK, self.server.previews.pixels(dataset_id, frame_id, x, y, modalities))
                        return
                    if len(parts) == 7 and parts[5] == "preview":
                        modality = parts[6]
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
                            self.send_response(HTTPStatus.NOT_MODIFIED); self.send_header("ETag", f'"{etag}"'); self.end_headers(); return
                        data, _ = self.server.previews.preview(dataset_id, frame_id, modality, **preview_kwargs, image_format=image_format)
                        self.send_response(HTTPStatus.OK); self.send_header("Content-Type", "image/webp" if format_name == "webp" else "image/png")
                        self.send_header("Content-Length", str(len(data))); self.send_header("ETag", f'"{etag}"')
                        self.send_header("Cache-Control", "public, max-age=31536000, immutable" if immutable else "public, max-age=60, must-revalidate")
                        self.end_headers(); self.wfile.write(data); return
            if len(parts) == 3 and parts[:2] == ["api", "scenes"]:
                self._json(HTTPStatus.OK, self.server.catalog.scene_payload(parts[2]))
                return
                if len(parts) == 4 and parts[3] == "viewpoints":
                    self._json(HTTPStatus.OK, self.server.catalog.viewpoints_payload(dataset_id))
                    return
                if len(parts) == 4 and parts[3] == "overview":
                    self._json(HTTPStatus.OK, self.server.catalog.overview_payload(dataset_id), cache_control="public, max-age=60")
                    return
                if len(parts) == 5 and parts[3] == "overview" and parts[4] == "traversability":
                    overview = self.server.catalog.overview_payload(dataset_id)
                    traversability = overview.get("traversability") or {}
                    relative = traversability.get("path")
                    if not relative:
                        raise KeyError("traversability")
                    record = self.server.catalog.get(dataset_id)
                    image_path = _safe_artifact_path(record.primary.path, str(relative))
                    data = image_path.read_bytes()
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Cache-Control", "public, max-age=31536000, immutable" if record.primary.kind == "bean" else "public, max-age=60, must-revalidate")
                    self.end_headers()
                    self.wfile.write(data)
                    return
                if len(parts) == 5 and parts[3] == "overview" and parts[4] == "mesh":
                    overview = self.server.catalog.overview_payload(dataset_id)
                    proxy = overview.get("proxy_mesh") or {}
                    relative = proxy.get("path")
                    if not relative:
                        raise KeyError("overview proxy is unavailable")
                    record = self.server.catalog.get(dataset_id)
                    mesh_path = _safe_artifact_path(record.primary.path, str(relative))
                    etag = str(proxy.get("sha256") or "")
                    cache_control = "public, max-age=31536000, immutable" if record.primary.kind == "bean" else "public, max-age=60, must-revalidate"
                    if self.headers.get("If-None-Match", "").strip('"') == etag:
                        self.send_response(HTTPStatus.NOT_MODIFIED); self.send_header("ETag", f'"{etag}"'); self.send_header("Cache-Control", cache_control); self.end_headers(); return
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "model/gltf-binary")
                    self.send_header("Content-Length", str(mesh_path.stat().st_size))
                    self.send_header("ETag", f'"{etag}"'); self.send_header("Cache-Control", cache_control)
                    self.end_headers()
                    with mesh_path.open("rb") as stream:
                        shutil.copyfileobj(stream, self.wfile)
                    return
                if len(parts) >= 5 and parts[3] == "frames":
                    frame_id = parts[4]
                    if len(parts) == 5:
                        self._json(HTTPStatus.OK, self.server.catalog.frame_payload(dataset_id, frame_id))
                        return
                    if len(parts) == 7 and parts[5] == "preview":
                        modality = parts[6]
                        record = self.server.catalog.get(dataset_id)
                        base_ev = default_exposure(record, modality)
                        preview_args = (dataset_id, frame_id, modality)
                        preview_kwargs = dict(
                            exposure_ev=base_ev + float(query.get("ev", ["0"])[0]),
                            minimum=float(query.get("min", ["0"])[0]),
                            maximum=float(query.get("max", ["10"])[0]),
                            overlay_modality=query.get("overlay", [None])[0],
                            overlay_opacity=float(query.get("opacity", ["0.45"])[0]),
                            max_width=int(query["max_width"][0]) if query.get("max_width") else None,
                        )
                        image_format = query.get("format", ["auto"])[0]
                        etag, format_name, immutable = self.server.previews.etag(*preview_args, **preview_kwargs, image_format=image_format)
                        if self.headers.get("If-None-Match", "").strip('"') == etag:
                            self.send_response(HTTPStatus.NOT_MODIFIED)
                            self.send_header("ETag", f'"{etag}"')
                            self.send_header("Vary", "Accept")
                            self.send_header("Cache-Control", "public, max-age=31536000, immutable" if immutable else "public, max-age=60, must-revalidate")
                            self.end_headers()
                            return
                        data, _ = self.server.previews.preview(*preview_args, **preview_kwargs, image_format=image_format)
                        self.send_response(HTTPStatus.OK)
                        self.send_header("Content-Type", "image/webp" if format_name == "webp" else "image/png")
                        self.send_header("Content-Length", str(len(data)))
                        self.send_header("Cache-Control", "public, max-age=31536000, immutable" if immutable else "public, max-age=60, must-revalidate")
                        self.send_header("ETag", f'"{etag}"')
                        self.send_header("Vary", "Accept")
                        self.end_headers()
                        self.wfile.write(data)
                        return
                    if len(parts) == 6 and parts[5] == "pixels":
                        x = int(query.get("x", ["-1"])[0]); y = int(query.get("y", ["-1"])[0])
                        modalities = [item for item in query.get("modalities", [""])[0].split(",") if item]
                        self._json(HTTPStatus.OK, self.server.previews.pixels(dataset_id, frame_id, x, y, modalities))
                        return
            if len(parts) == 3 and parts[:2] == ["api", "publish"]:
                self._json(HTTPStatus.OK, self.server.publisher.get(parts[2]))
                return
            if path.startswith("/api/"):
                self._json(HTTPStatus.NOT_FOUND, {"error": "unknown API route"})
                return
            self._static(path)
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
                self._json(HTTPStatus.ACCEPTED, self.server.controller.submit(self._body()))
                return
            if len(parts) == 5 and parts[:3] == ["api", "controller", "jobs"]:
                job_id, action = parts[3], parts[4]
                if action == "cancel":
                    self._json(HTTPStatus.OK, self.server.controller.cancel_job(job_id)); return
                if action == "retry":
                    self._json(HTTPStatus.ACCEPTED, self.server.controller.retry(job_id)); return
                if action == "resume":
                    body = self._body()
                    self._json(HTTPStatus.ACCEPTED, self.server.controller.resume(
                        job_id, mode=str(body.get("mode") or "recommended"),
                        insert_stages=list(body.get("insert_stages") or []),
                        rerun_from=(str(body["rerun_from"]) if body.get("rerun_from") else None),
                    )); return
                if action == "adopt":
                    self._json(HTTPStatus.OK, self.server.controller.adopt_external_import(job_id)); return
                if action == "priority":
                    self._json(HTTPStatus.OK, self.server.controller.priority(job_id, int(self._body().get("priority", 0)))); return
                if action == "remove":
                    self._json(HTTPStatus.OK, self.server.controller.remove_terminal_job(job_id)); return
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
                             statistics_root=args.work_root / ".catalog_statistics")
    previews = PreviewService(catalog, args.cache_dir, disk_max_bytes=int(args.cache_gib * 1024**3),
                              memory_max_bytes=int(args.memory_cache_mib * 1024**2))
    server = ViewerServer((args.host, args.port), Handler, catalog=catalog, previews=previews,
                          publisher=PublishManager(), bean_root=args.bean_root.resolve(), static_dir=args.static_dir)
    server.controller = IRDatasetController(repo_root=REPO_ROOT, work_root=args.work_root, bean_root=args.bean_root)
    print(f"[ir-viewer] frontend+API http://{args.host}:{server.server_address[1]}/", flush=True)
    print(f"[ir-viewer] roots bean={args.bean_root} work={args.work_root} out={args.out_root}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
