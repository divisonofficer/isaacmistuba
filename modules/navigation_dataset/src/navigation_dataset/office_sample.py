from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import Any

from .authoring_compile import compile_authoring_map
from .authoring_map import validate_authoring_map
from .office_assets import build_office_asset_coverage
from .scene_annotations import write_scene_annotation
from .scene_sync import write_render_scene_sync


JsonDict = dict[str, Any]
DEFAULT_PROJECT_ID = "opticalnav-v0.2"
DEFAULT_SHARED_OFFICE_SCENE_ID = "shared_office_floor_001"
DEFAULT_SHARED_OFFICE_FIXTURE = Path("tests/fixtures/opticalnav/shared_office_authoring_map.json")


@dataclass(frozen=True)
class SharedOfficeSampleInstallResult:
    project_id: str
    scene_id: str
    scene_dir: Path
    written_files: list[Path]
    compile_summary: JsonDict
    asset_gap_categories: list[str]
    external_needed_categories: list[str]
    render_scene_status: str = "pending"

    def to_payload(self, *, repo_root: str | Path | None = None) -> JsonDict:
        root = Path(repo_root) if repo_root is not None else None

        def ref(path: Path) -> str:
            if root is not None:
                try:
                    return path.relative_to(root).as_posix()
                except ValueError:
                    pass
            return path.as_posix()

        return {
            "project_id": self.project_id,
            "scene_id": self.scene_id,
            "scene_dir": ref(self.scene_dir),
            "written_files": [ref(path) for path in self.written_files],
            "compile_summary": self.compile_summary,
            "asset_gap_categories": list(self.asset_gap_categories),
            "external_needed_categories": list(self.external_needed_categories),
            "render_scene_status": self.render_scene_status,
        }


def _load_shared_office_fixture(repo_root: Path, fixture_path: str | Path | None = None) -> JsonDict:
    fixture = Path(fixture_path) if fixture_path is not None else repo_root / DEFAULT_SHARED_OFFICE_FIXTURE
    if not fixture.is_absolute():
        fixture = repo_root / fixture
    return json.loads(fixture.read_text(encoding="utf-8"))


def build_shared_office_authoring_map(
    repo_root: str | Path,
    *,
    scene_id: str = DEFAULT_SHARED_OFFICE_SCENE_ID,
    fixture_path: str | Path | None = None,
) -> JsonDict:
    root = Path(repo_root)
    payload = _load_shared_office_fixture(root, fixture_path)
    payload["scene_id"] = scene_id
    payload["floorplan_ref"] = f"/api/scenes/{scene_id}/floorplan"
    payload.setdefault("metadata", {})
    payload["metadata"] = {
        **dict(payload.get("metadata") or {}),
        "sample_scene": True,
        "sample_scene_kind": "shared_office_v1",
        "installed_scene_id": scene_id,
    }
    validate_authoring_map(payload, require_compile_ready=True)
    return payload


def _pending_render_readiness(scene_id: str, summary: JsonDict, asset_gaps: list[str]) -> JsonDict:
    warnings = []
    if asset_gaps:
        warnings.append(
            {
                "key": "sample_asset_gaps",
                "label": "Sample placeholders present",
                "message": f"External or download asset gaps remain: {', '.join(asset_gaps)}.",
            }
        )
    return {
        "ok": False,
        "status": "pending",
        "render_sync_mode": "editor_generated_xml",
        "scene_id": scene_id,
        "message": "Shared office sample map is installed. Run Save Map / Sync Render Scene to materialize render_scene.xml.",
        "checks": [
            {
                "key": "authoring_map",
                "ok": True,
                "label": "Authoring map installed",
                "level": "error",
                "message": None,
            },
            {
                "key": "scene_annotation",
                "ok": True,
                "label": "Scene annotation compiled",
                "level": "error",
                "message": None,
            },
            {
                "key": "render_scene_xml",
                "ok": False,
                "label": "Render XML pending",
                "level": "error",
                "message": "render_scene.xml has not been generated yet.",
            },
        ],
        "summary": dict(summary),
        "errors": [],
        "warnings": warnings,
    }


def _try_materialize_render_scene(
    repo_root: Path,
    project_dir: Path,
    scene_dir: Path,
    scene_id: str,
    authoring_map: JsonDict,
    overlay: JsonDict,
    summary: JsonDict,
    asset_gaps: list[str],
) -> tuple[str, JsonDict]:
    """Generate render_scene.xml and editor sidecars when mitsuba_converter is available.

    The normal web UI path creates these files from Save Map / Sync Render Scene.
    Sample installation writes files directly, so it must perform the same
    materialization step to avoid initial 404s in the dataset editor.
    """
    for module_src in (
        repo_root / "modules" / "robomituba_bridge" / "src",
        repo_root / "modules" / "mitsuba_converter" / "src",
    ):
        if module_src.exists() and str(module_src) not in sys.path:
            sys.path.insert(0, str(module_src))
    try:
        from mitsuba_converter.render_daemon import (  # type: ignore
            _build_materialization_audit,
            _build_opticalnav_render_readiness,
            _build_xml_scene_index,
            _generate_opticalnav_render_scene_xml,
            _stage_xml_obj_filenames_to_scene_mesh_cache,
        )
    except Exception as exc:
        readiness = _pending_render_readiness(scene_id, summary, asset_gaps)
        readiness.setdefault("warnings", []).append(
            {
                "key": "mitsuba_converter_unavailable",
                "label": "Render materialization skipped",
                "message": f"Could not import mitsuba_converter render materializer: {exc}",
            }
        )
        return "pending", readiness

    render_scene_path = scene_dir / "render_scene.xml"
    mesh_stats: dict[str, int] = {}
    materialization_records: list[dict[str, Any]] = []
    try:
        shape_count = _generate_opticalnav_render_scene_xml(
            authoring_map,
            overlay,
            render_scene_path,
            editor_geometry=None,
            repo_root=repo_root,
            mesh_resolver=None,
            mesh_stats=mesh_stats,
            materialization_records=materialization_records,
        )
        render_scene_ref = render_scene_path.relative_to(repo_root).as_posix()
        mesh_stats["scene_mesh_cache"] = _stage_xml_obj_filenames_to_scene_mesh_cache(
            render_scene_path,
            scene_mesh_cache_dir=scene_dir / "mesh_cache",
            repo_root=repo_root,
        )
        audit = _build_materialization_audit(
            scene_id=scene_id,
            overlay_objects=list(overlay.get("objects") or []),
            materialization_records=materialization_records,
            mesh_stats=mesh_stats,
        )
        (scene_dir / "render_scene_materialization.json").write_text(
            json.dumps(audit, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        xml_index = _build_xml_scene_index(
            render_scene_path,
            scene_id=scene_id,
            materialization_records=materialization_records,
        )
        if xml_index is not None:
            (scene_dir / "xml_scene_index.json").write_text(
                json.dumps(xml_index, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        readiness = _build_opticalnav_render_readiness(
            authoring_map,
            repo_root=repo_root,
            render_scene_path=render_scene_path,
            render_scene_ref=render_scene_ref,
            overlay_shape_count=shape_count,
            materialization_records=materialization_records,
        )
        sv_path = scene_dir / "scene_variant.json"
        if sv_path.exists():
            sv = json.loads(sv_path.read_text(encoding="utf-8"))
            sv["render_sync_mode"] = "editor_generated_xml"
            sv["overlay_scene_xml_ref"] = render_scene_ref
            sv["base_scene_xml_ref"] = None
            sv["render_readiness_ref"] = (scene_dir / "render_readiness.json").relative_to(project_dir).as_posix()
            sv_path.write_text(json.dumps(sv, ensure_ascii=False, indent=2), encoding="utf-8")

        annotation_path = scene_dir / "scene_annotation.json"
        if annotation_path.exists():
            raw = json.loads(annotation_path.read_text(encoding="utf-8"))
            raw.setdefault("metadata", {})["sync"] = {
                **dict(raw.get("metadata", {}).get("sync", {})),
                "render_scene": "synced" if readiness.get("ok") else "blocked",
                "render_scene_mode": "editor_generated_xml",
                "render_scene_xml_ref": render_scene_ref,
                "scene_variant_ref": (scene_dir / "scene_variant.json").relative_to(project_dir).as_posix(),
                "render_scene_overlay_ref": "scenes/{scene_id}/render_scene_overlays.json".format(scene_id=scene_id),
                "render_readiness_ref": (scene_dir / "render_readiness.json").relative_to(project_dir).as_posix(),
                "render_readiness_status": readiness.get("status"),
            }
            annotation_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
        return "synced" if readiness.get("ok") else "blocked", readiness
    except Exception as exc:
        readiness = _pending_render_readiness(scene_id, summary, asset_gaps)
        readiness["status"] = "blocked"
        readiness["errors"] = [{"key": "render_scene_materialization", "message": str(exc)}]
        return "blocked", readiness


def install_shared_office_sample(
    repo_root: str | Path,
    *,
    project_id: str = DEFAULT_PROJECT_ID,
    scene_id: str = DEFAULT_SHARED_OFFICE_SCENE_ID,
    fixture_path: str | Path | None = None,
    force: bool = False,
    materialize_render_scene: bool = True,
) -> SharedOfficeSampleInstallResult:
    root = Path(repo_root)
    project_dir = root / "out" / "opticalnav" / project_id
    scene_dir = project_dir / "scenes" / scene_id
    authoring_path = scene_dir / "authoring_map.json"
    if authoring_path.exists() and not force:
        raise FileExistsError(f"{authoring_path} already exists. Pass force=True to overwrite sample artifacts.")

    authoring_map = build_shared_office_authoring_map(root, scene_id=scene_id, fixture_path=fixture_path)
    compile_result = compile_authoring_map(authoring_map, usd_ref=f"scenes/{scene_id}/scene.usd")
    sync_result = write_render_scene_sync(scene_dir, authoring_map, compile_result.annotation, project_dir=project_dir)

    scene_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    authoring_path.write_text(json.dumps(authoring_map, ensure_ascii=False, indent=2), encoding="utf-8")
    written.append(authoring_path)

    annotation_path = write_scene_annotation(scene_dir / "scene_annotation.json", compile_result.annotation)
    written.append(annotation_path)
    written.extend([scene_dir / "scene_variant.json", scene_dir / "render_scene_overlays.json"])

    asset_gaps = sorted(str(item) for item in (authoring_map.get("metadata") or {}).get("known_asset_gaps", []))
    coverage = build_office_asset_coverage(root)
    external_needed = sorted(
        category
        for category, info in (coverage.get("summary") or {}).items()
        if info.get("status") == "external_needed"
    )
    if materialize_render_scene:
        render_scene_status, readiness = _try_materialize_render_scene(
            root,
            project_dir,
            scene_dir,
            scene_id,
            authoring_map,
            sync_result.overlay,
            compile_result.summary,
            asset_gaps,
        )
    else:
        render_scene_status = "pending"
        readiness = _pending_render_readiness(scene_id, compile_result.summary, asset_gaps)
    sample_summary = {
        "scene_id": scene_id,
        "project_id": project_id,
        "compile_summary": compile_result.summary,
        "sync": {
            "scene_variant_ref": sync_result.scene_variant_ref,
            "render_scene_overlay_ref": sync_result.overlay_ref,
            "dataset": "synced",
            "render_scene_overlay": "synced",
            "render_scene": render_scene_status,
            "render_scene_mode": sync_result.sync.get("render_scene_mode", "editor_generated_xml"),
            "isaac_stage": "pending",
            "message": (
                "Authoring map and render XML are installed."
                if render_scene_status == "synced"
                else "Authoring map is installed, but render XML materialization is not ready."
            ),
        },
        "asset_gaps": asset_gaps,
        "external_needed_categories": external_needed,
        "office_coverage_status": {
            category: info.get("status")
            for category, info in (coverage.get("summary") or {}).items()
        },
    }
    summary_path = scene_dir / "sample_map_summary.json"
    summary_path.write_text(json.dumps(sample_summary, ensure_ascii=False, indent=2), encoding="utf-8")
    written.append(summary_path)

    readiness_path = scene_dir / "render_readiness.json"
    readiness_path.write_text(json.dumps(readiness, ensure_ascii=False, indent=2), encoding="utf-8")
    written.append(readiness_path)
    for sidecar in ("render_scene.xml", "render_scene_materialization.json", "xml_scene_index.json"):
        path = scene_dir / sidecar
        if path.exists():
            written.append(path)

    return SharedOfficeSampleInstallResult(
        project_id=project_id,
        scene_id=scene_id,
        scene_dir=scene_dir,
        written_files=written,
        compile_summary=compile_result.summary,
        asset_gap_categories=asset_gaps,
        external_needed_categories=external_needed,
        render_scene_status=render_scene_status,
    )
