"""Tests for the multi-material OBJ splitter used to restore per-face-group render
fidelity for Infinigen meshes (orphan-material fix, dev_report investigation)."""

from __future__ import annotations

from pathlib import Path

from mitsuba_converter.obj_split import (
    iter_material_groups,
    sanitize_material_name,
    split_obj_by_material,
)

# A tiny two-material cube-ish OBJ: 6 verts, two usemtl groups.
_OBJ = """# test
mtllib x.mtl
o TestMesh
v 0 0 0
v 1 0 0
v 1 1 0
v 0 1 0
v 0 0 1
v 1 0 1
vt 0 0
vt 1 0
vt 1 1
vn 0 0 1
usemtl shader_wood.073
f 1/1/1 2/2/1 3/3/1
f 1/1/1 3/3/1 4/1/1
usemtl shader_rough_plastic.025
f 5/1/1 6/2/1 3/3/1
"""


def _write(tmp: Path) -> Path:
    p = tmp / "mesh.obj"
    p.write_text(_OBJ)
    return p


def test_sanitize_matches_importer():
    # mirrors apps/import_infinigen_scene._san
    assert sanitize_material_name("shader_wood.073") == "shader_wood.073"
    assert sanitize_material_name("Bed Frame #2") == "Bed_Frame_2"
    assert sanitize_material_name("") == "x"


def test_iter_material_groups(tmp_path):
    obj = _write(tmp_path)
    groups = iter_material_groups(obj)
    assert [g["material_name"] for g in groups] == ["shader_wood.073", "shader_rough_plastic.025"]
    assert [g["material_id"] for g in groups] == ["shader_wood.073", "shader_rough_plastic.025"]
    assert groups[0]["face_count"] == 2 and groups[0]["triangle_count"] == 2
    assert groups[1]["face_count"] == 1 and groups[1]["triangle_count"] == 1


def test_split_writes_remapped_subobjs(tmp_path):
    obj = _write(tmp_path)
    parts = split_obj_by_material(obj)
    assert len(parts) == 2
    wood = next(p for p in parts if p["material_id"] == "shader_wood.073")
    plastic = next(p for p in parts if p["material_id"] == "shader_rough_plastic.025")

    wood_txt = Path(wood["path"]).read_text()
    # wood group references verts 1,2,3,4 -> 4 remapped verts, 2 faces
    assert wood_txt.count("\nv ") == 4
    assert wood_txt.count("\nf ") == 2
    assert "usemtl shader_wood.073" in wood_txt

    plastic_txt = Path(plastic["path"]).read_text()
    # plastic group references verts 5,6,3 -> 3 remapped verts, 1 face
    assert plastic_txt.count("\nv ") == 3
    assert plastic_txt.count("\nf ") == 1
    # face indices must be remapped to the local 1..N range (no original idx 5/6)
    face_line = [l for l in plastic_txt.splitlines() if l.startswith("f ")][0]
    vidx = [int(tok.split("/")[0]) for tok in face_line.split()[1:]]
    assert max(vidx) <= 3 and min(vidx) >= 1


def test_single_material_no_split(tmp_path):
    single = tmp_path / "single.obj"
    single.write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nusemtl only\nf 1 2 3\n")
    assert split_obj_by_material(single) == []
