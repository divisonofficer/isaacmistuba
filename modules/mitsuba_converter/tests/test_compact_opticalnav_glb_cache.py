from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[3] / "apps/migrations/compact_opticalnav_glb_cache.py"
SPEC = importlib.util.spec_from_file_location("compact_opticalnav_glb_cache", SCRIPT)
assert SPEC and SPEC.loader
compact = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(compact)


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_compaction_promotes_staged_obj_and_is_idempotent(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    scene = repo / "out/opticalnav/test-project/scenes/test-scene"
    cache = scene / "mesh_cache"
    parts = cache / "glb_abc_parts"
    parts.mkdir(parents=True)
    source_glb = repo / "source.glb"
    source_glb.parent.mkdir(parents=True, exist_ok=True)
    source_glb.write_bytes(b"glb")
    part = parts / "000_mesh.obj"
    part.write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nvn 0 0 1\nf 1//1 2//1 3//1\n", encoding="utf-8")
    stat = part.stat()
    digest = hashlib.sha1(
        f"{part.resolve()}|{stat.st_mtime_ns}|{stat.st_size}|preserve_assembly_local|stage_obj_v5".encode()
    ).hexdigest()[:16]
    staged = cache / f"{digest}.obj"
    staged.write_text(part.read_text(encoding="utf-8"), encoding="utf-8")
    combined = cache / "glb_abc.obj"
    combined.write_text("duplicate", encoding="utf-8")
    (cache / "duplicate.png").write_bytes(b"png")

    source_ref = "source.glb"
    _write(scene / "authoring_map.json", {
        "objects": [{"id": "chair", "source_ref": source_ref}],
    })
    _write(scene / "scene_annotation.json", {
        "metadata": {"sync": {"render_scene": "pending", "render_scene_status": "syncing"}},
    })
    _write(scene / "render_scene_materialization.json", {
        "objects": [{"object_id": "chair", "source_ref": source_ref}],
        "mesh_stats": {"scene_mesh_cache": {
            "preserved_positions": 1,
            "preserved_bounds_max_abs_delta_m": 0.0,
            "preserved_bounds_tolerance_m": 1e-5,
        }},
    })
    _write(cache / "glb_abc.meta.json", {
        "adapter_version": 6,
        "status": "ok",
        "source_ref": source_ref,
        "source_path": str(source_glb),
        "combined_obj_path": str(combined),
        "combined_obj_ref": str(combined),
        "mesh_parts": [{
            "part_id": "part_000", "obj_path": str(part), "obj_ref": str(part),
            "triangle_count": 1,
        }],
    })
    (scene / "render_scene.xml").write_text(
        '<scene version="3.0.0"><shape type="obj" id="chair">'
        f'<string name="filename" value="{part}"/></shape></scene>', encoding="utf-8",
    )

    state = compact._collect(repo, "test-project", "test-scene")
    assert state["part_count"] == 1
    assert state["deletion_files"] == 3
    monkeypatch.setattr(compact, "_daemon_ports_alive", lambda: [])
    monkeypatch.setattr(compact, "_open_cache_fds", lambda _path: [])
    result = compact._apply(state)
    assert result["status"] == "complete"
    assert staged.is_file()
    assert not combined.exists()
    assert not parts.exists()
    assert not (cache / "duplicate.png").exists()
    source_stat = source_glb.stat()
    adapter_digest = hashlib.sha1(
        f"{source_glb.resolve()}|{source_stat.st_mtime_ns}|{source_stat.st_size}|glb_adapter_v7".encode()
    ).hexdigest()[:16]
    meta_path = cache / f"glb_{adapter_digest}.meta.json"
    assert not (cache / "glb_abc.meta.json").exists()
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["digest"] == adapter_digest
    assert meta["obj_contract"] == compact.SAFE_CONTRACT
    assert meta["mesh_parts"][0]["obj_ref"].endswith(f"/{digest}.obj")
    xml = (scene / "render_scene.xml").read_text(encoding="utf-8")
    assert str(staged.resolve()) in xml

    second = compact._collect(repo, "test-project", "test-scene")
    assert second["already_compacted"] is True
    assert compact._apply(second)["idempotent"] is True
