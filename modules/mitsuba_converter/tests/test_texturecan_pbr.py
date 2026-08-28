from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

import cv2
import numpy as np
import pytest

from mitsuba_converter.ir_structural_pbr import bindings_for_scene, load_registry
from mitsuba_converter import texturecan_pbr
from mitsuba_converter.texturecan_pbr import (
    CATEGORY_SLUGS,
    SCALE_OVERRIDES_SCHEMA,
    approved_roles_from_review,
    create_extended_structural_review_profile,
    create_review_thumbnails,
    finalize_structural_registry,
    mirror_categories,
    parse_detail_page,
    provisional_roles,
    repair_wall_column_promotions,
    second_pass_structural_review,
    stage_one_asset,
    write_extended_scale_overrides,
    write_scale_overrides_template,
)


def _image_bytes(*, color: tuple[int, int, int] = (120, 120, 120), normal: bool = False, size: int = 2048) -> bytes:
    image = np.zeros((size, size, 3), dtype=np.uint8)
    image[:] = (255, 128, 128) if normal else color
    extension = ".png" if normal else ".jpg"
    ok, encoded = cv2.imencode(extension, image)
    assert ok
    return bytes(encoded)


def _zip(path: Path, *, metallic: bool = False, normal_name: str = "normal_opengl") -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("metal_0001_color_2k.jpg", _image_bytes())
        archive.writestr("metal_0001_roughness_2k.jpg", _image_bytes(color=(180, 180, 180)))
        archive.writestr(f"metal_0001_{normal_name}_2k.png", _image_bytes(normal=True))
        if metallic:
            archive.writestr("metal_0001_metallic_2k.jpg", _image_bytes(color=(255, 255, 255)))
    return path


def _spec(url: str = "https://example.invalid/metal_0001_2k_token.zip") -> dict:
    return {
        "id": "texturecan_metal_0001", "asset_id": "metal_0001", "provider": "TextureCan",
        "category": "metal", "source_url": "https://example.invalid/details/1/", "source_zip_url": url,
        "source_zip_name": "metal_0001_2k_token.zip", "title": "Scratched Aluminium Wall Sheet",
        "description": "scratched metal panel", "tags": ["Metal", "Wall", "Panel"], "license": "CC0-1.0",
        "license_provenance": {"license_url": "https://www.texturecan.com/terms/", "texturecan_terms_checked": True},
    }


def _copy_download(source: Path):
    def copied(_url: str, destination: Path, *, timeout: int = 300) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    return copied


def test_category_pagination_and_detail_parse_are_deterministic() -> None:
    pages = {
        "https://www.texturecan.com/category/Metal/": '<a href="/details/3/">a</a><a href="/category/Metal/2/">2</a>',
        "https://www.texturecan.com/category/Metal/2/": '<a href="/details/1/">b</a>',
    }
    urls = texturecan_pbr.discover_category_detail_urls("Metal", fetch=pages.__getitem__)
    assert urls == ["https://www.texturecan.com/details/1/", "https://www.texturecan.com/details/3/"]
    detail = parse_detail_page(
        urls[0],
        '<meta property="og:title" content="Steel Sheet"><meta name="tex1:tags" content="Metal, Wall">'
        '<a href="/downloads/metal_0001/metal_0001_2k_x.zip">2K Maps</a>',
        category="metal",
    )
    assert detail["id"] == "texturecan_metal_0001"
    assert detail["license"] == "CC0-1.0"
    assert set(provisional_roles(detail)) >= {"wall", "prop"}


def test_staging_validates_maps_and_thumbnail_deletion_is_role_local(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _zip(tmp_path / "source.zip", metallic=True)
    monkeypatch.setattr(texturecan_pbr, "download", _copy_download(source))
    root = tmp_path / "staging"
    record = stage_one_asset(_spec(), root)
    assert record["status"] == "accepted"
    assert record["metallic"] == {"mode": "texture", "map": "metallic"}
    manifest = {"schema": texturecan_pbr.STAGING_SCHEMA, "staging_version": texturecan_pbr.STAGING_VERSION,
                "materials": [record], "digest": "test"}
    (root / "staging_manifest.json").write_text(json.dumps(manifest))
    review = create_review_thumbnails(root)
    assert review["counts"]["wall"] == 1
    wall_token = root / "review" / "wall" / "texturecan_metal_0001.jpg"
    wall_token.unlink()
    assert (root / record["maps"]["base_color"]).is_file()  # deleting a token never deletes the raw asset
    approved = approved_roles_from_review(root)
    assert "wall" not in approved.get("texturecan_metal_0001", set())
    assert "prop" in approved["texturecan_metal_0001"]


def test_finalizer_requires_scale_and_makes_explicit_metal_panel_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _zip(tmp_path / "source.zip", metallic=True)
    monkeypatch.setattr(texturecan_pbr, "download", _copy_download(source))
    root = tmp_path / "staging"
    record = stage_one_asset(_spec(), root)
    manifest = {"schema": texturecan_pbr.STAGING_SCHEMA, "staging_version": texturecan_pbr.STAGING_VERSION,
                "materials": [record], "digest": "test"}
    (root / "staging_manifest.json").write_text(json.dumps(manifest))
    create_review_thumbnails(root)
    worksheet = write_scale_overrides_template(root, tmp_path / "scale_overrides.template.json")
    assert worksheet["assets"][record["id"]]["width"] is None
    assert set(worksheet["assets"][record["id"]]["approved_roles"]) >= {"wall", "panel"}
    scales = tmp_path / "scale_overrides.json"
    scales.write_text(json.dumps({"schema": SCALE_OVERRIDES_SCHEMA, "assets": {}}))
    with pytest.raises(ValueError, match="physical_size_m"):
        finalize_structural_registry(root, tmp_path / "final-missing", scales)
    scales.write_text(json.dumps({"schema": SCALE_OVERRIDES_SCHEMA, "assets": {
        record["id"]: {"width": 1.5, "height": 1.0, "source": "manual_review"},
    }}))
    output = tmp_path / "final"
    registry = finalize_structural_registry(root, output, scales)
    row = registry["materials"][0]
    assert registry["role_policy"] == "explicit_approved_roles_v1"
    assert {"wall", "panel"} <= set(row["approved_roles"])
    assert row["metallic"] == {"mode": "texture", "map": "metallic"}
    loaded = load_registry(output / "registry.lock.json")
    scene = {"units": [{"id": "panel", "kind": "structure", "semantic_type": "panel", "subtype": "panel",
                          "collections": ["room_panel"], "material_slots": [{}]}]}
    bindings, _ = bindings_for_scene(scene, loaded, seed=9)
    assert bindings[0]["metallic"] == {"mode": "texture", "map": "metallic"}
    assert bindings[0]["projection"] == "object_meter_repeat_v3"


def test_finalizer_ignores_prop_only_review_tokens_when_requiring_scales(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _zip(tmp_path / "source.zip", metallic=True)
    monkeypatch.setattr(texturecan_pbr, "download", _copy_download(source))
    root = tmp_path / "staging"
    record = stage_one_asset(_spec(), root)
    manifest = {"schema": texturecan_pbr.STAGING_SCHEMA, "staging_version": texturecan_pbr.STAGING_VERSION,
                "materials": [record], "digest": "test"}
    (root / "staging_manifest.json").write_text(json.dumps(manifest))
    create_review_thumbnails(root)
    # The staging review always has a prop token. Remove every structural
    # candidate, leaving a prop-only approval with deliberately empty scales.
    for role in ("wall", "ceiling"):
        (root / "review" / role / f"{record['id']}.jpg").unlink()
    scales = tmp_path / "scale_overrides.json"
    scales.write_text(json.dumps({"schema": SCALE_OVERRIDES_SCHEMA, "assets": {}}))
    with pytest.raises(ValueError, match="only approved prop tokens"):
        finalize_structural_registry(root, tmp_path / "final", scales)


def test_extended_profile_is_isolated_balanced_and_finalizable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _zip(tmp_path / "source.zip", metallic=True)
    monkeypatch.setattr(texturecan_pbr, "download", _copy_download(source))
    root = tmp_path / "staging"
    metal = stage_one_asset(_spec(), root)
    tile = {**metal, "id": "texturecan_tiles_0001", "asset_id": "tiles_0001", "category": "tile",
            "title": "White Bathroom Tile Texture", "description": "interior ceramic", "tags": ["Tile"]}
    exterior = {**metal, "id": "texturecan_ground_0001", "asset_id": "ground_0001", "category": "tile",
                "title": "Cobblestone Pavement with Puddles", "description": "outdoor", "tags": ["Tile"]}
    (root / "staging_manifest.json").write_text(json.dumps({
        "schema": texturecan_pbr.STAGING_SCHEMA, "staging_version": texturecan_pbr.STAGING_VERSION,
        "materials": [metal, tile, exterior], "digest": "test",
    }))
    profile = create_extended_structural_review_profile(root, review_subdir="review_extended", profile_name="test", max_assets=2)
    assert profile["candidate_asset_count"] == 2
    assert len(profile["selected"]) == 2
    assert not (root / "review").exists()
    assert (root / "review_extended" / "wall" / f"{metal['id']}.jpg").is_file()
    assert not (root / "review_extended" / "wall" / f"{exterior['id']}.jpg").exists()
    scales = tmp_path / "extended_scales.json"
    payload = write_extended_scale_overrides(root, scales, review_subdir="review_extended")
    assert set(payload["assets"]) == {metal["id"], tile["id"]}
    registry = finalize_structural_registry(root, tmp_path / "extended", scales, review_subdir="review_extended")
    assert len(registry["materials"]) == 2
    assert registry["review_subdir"] == "review_extended"
    by_id = {row["id"]: row for row in registry["materials"]}
    assert "column" in by_id[tile["id"]]["approved_roles"]
    assert "column" not in by_id[metal["id"]]["approved_roles"]

    # A registry built by the pre-column-promotion finalizer remains safely
    # repairable before any dataset job binds it.
    repaired_path = tmp_path / "extended" / "registry.lock.json"
    legacy = json.loads(repaired_path.read_text())
    legacy["materials"][1]["approved_roles"] = ["wall"]
    legacy["materials"][1]["semantic_compatibility"] = ["wall"]
    legacy["digest"] = texturecan_pbr.canonical_digest({key: value for key, value in legacy.items() if key != "digest"})
    repaired_path.write_text(json.dumps(legacy))
    repaired = repair_wall_column_promotions(tmp_path / "extended")
    assert "column" in repaired["materials"][1]["approved_roles"]


def test_staging_rejects_non_opengl_or_sub_2k_maps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _zip(tmp_path / "dx.zip", normal_name="normal_directx")
    monkeypatch.setattr(texturecan_pbr, "download", _copy_download(source))
    rejected = stage_one_asset(_spec(), tmp_path / "staging")
    assert rejected["status"] == "rejected"
    assert "normal_gl" in rejected["rejection"]
    small = tmp_path / "small.zip"
    with zipfile.ZipFile(small, "w") as archive:
        archive.writestr("concrete_color_2k.jpg", _image_bytes(size=512))
        archive.writestr("concrete_roughness_2k.jpg", _image_bytes(size=512))
        archive.writestr("concrete_normal_opengl_2k.png", _image_bytes(normal=True, size=512))
    monkeypatch.setattr(texturecan_pbr, "download", _copy_download(small))
    rejected = stage_one_asset({**_spec(), "id": "texturecan_metal_0002", "asset_id": "metal_0002"}, tmp_path / "small-staging")
    assert rejected["status"] == "rejected"
    assert "below 2K" in rejected["rejection"]


def test_mirror_category_keeps_discovery_rejection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pages = {
        "https://www.texturecan.com/category/Metal/": '<a href="/details/1/">a</a>',
        "https://www.texturecan.com/details/1/": "<html>no 2K download</html>",
    }
    payload = mirror_categories(tmp_path / "staging", categories=["metal"], fetch=pages.__getitem__)
    assert payload["categories"] == ["metal"]
    assert len(payload["materials"]) == 1
    assert payload["materials"][0]["status"] == "rejected"
    assert CATEGORY_SLUGS["metal"] == "Metal"


def test_category_resume_is_additive_not_a_destructive_filter(tmp_path: Path) -> None:
    pages = {
        "https://www.texturecan.com/category/Metal/": '<a href="/details/1/">a</a>',
        "https://www.texturecan.com/category/Tiles/": '<a href="/details/2/">b</a>',
        "https://www.texturecan.com/details/1/": "<html>no 2K download</html>",
        "https://www.texturecan.com/details/2/": "<html>no 2K download</html>",
    }
    root = tmp_path / "staging"
    mirror_categories(root, categories=["metal"], fetch=pages.__getitem__)
    resumed = mirror_categories(root, categories=["tile"], fetch=pages.__getitem__)
    assert resumed["categories"] == ["metal", "tile"]
    assert {row["category"] for row in resumed["materials"]} == {"metal", "tile"}


def test_second_pass_defers_only_unambiguously_nonstructural_review_tokens(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _zip(tmp_path / "source.zip")
    monkeypatch.setattr(texturecan_pbr, "download", _copy_download(source))
    root = tmp_path / "staging"
    base = stage_one_asset(_spec(), root)
    jacket = {**base, "id": "texturecan_fabric_0021", "asset_id": "fabric_0021", "category": "tile",
              "title": "Yellow Padded Jacket and Bubble Coat Texture", "description": "", "tags": []}
    concrete = {**base, "id": "texturecan_concrete_0001", "asset_id": "concrete_0001", "category": "concrete",
                "title": "Matte Interior Concrete Wall Texture", "description": "", "tags": []}
    (root / "staging_manifest.json").write_text(json.dumps({
        "schema": texturecan_pbr.STAGING_SCHEMA, "staging_version": texturecan_pbr.STAGING_VERSION,
        "materials": [jacket, concrete], "digest": "test",
    }))
    for asset_id in (jacket["id"], concrete["id"]):
        token = root / "review" / "wall" / f"{asset_id}.jpg"
        token.parent.mkdir(parents=True, exist_ok=True)
        token.write_bytes(b"review-token")
    preview = second_pass_structural_review(root, run_id="dry")
    by_id = {row["asset_id"]: row for row in preview["decisions"]}
    assert by_id[jacket["id"]]["status"] == "defer_hard"
    assert by_id[concrete["id"]]["status"] != "defer_hard"
    applied = second_pass_structural_review(root, apply_hard_deferrals=True, run_id="applied")
    assert len(applied["moved"]) == 1
    assert not (root / "review" / "wall" / f"{jacket['id']}.jpg").exists()
    assert (root / "review_deferred" / "applied" / "wall" / f"{jacket['id']}.jpg").is_file()
    assert (root / base["maps"]["base_color"]).is_file()
