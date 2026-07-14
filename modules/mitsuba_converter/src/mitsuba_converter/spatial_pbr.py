"""Texture-only spatial PBR preprocessing for Mitsuba analytic BSDFs.

This module deliberately does not touch geometry.  Robomituba already owns the
GLB/OBJ materialization, transforms, and UV contract; the responsibility here is
limited to converting PBR texture values into render-ready scalar/optical maps.

The important glTF rules are applied before any BSDF classification::

    roughness = metallicRoughnessTexture.G * roughnessFactor
    metallic  = metallicRoughnessTexture.B * metallicFactor
    alpha     = roughness ** 2

Standalone baked Infinigen atlases already contain the evaluated shader value,
so their factor should remain 1.0.  The continuous metallic map is preserved as
the ``blendbsdf`` weight; a threshold is used only to decide where conductor n/k
and an index are meaningful.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
from PIL import Image


RGB_WAVELENGTHS_NM = np.asarray([650.0, 550.0, 450.0], dtype=np.float32)
DEFAULT_DIELECTRIC_IOR = 1.5

# Keep the matching set intentionally conservative.  Mitsuba's IOR directory
# also contains semiconductors/dielectrics (e.g. ThF4, MgO, TiO2); treating all
# of them as roughconductors caused the July-13 ThF4 false-match failure.
DEFAULT_CONDUCTOR_PRESETS = ("Ag", "Al", "Au", "Cr", "Cu", "Ni_palik", "W")


def _read_spd(path: Path) -> tuple[np.ndarray, np.ndarray]:
    wavelengths: list[float] = []
    values: list[float] = []
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) < 2:
            continue
        try:
            wavelengths.append(float(fields[0]))
            values.append(float(fields[1]))
        except ValueError:
            continue
    if not wavelengths:
        raise ValueError(f"empty SPD: {path}")
    return np.asarray(wavelengths, dtype=np.float32), np.asarray(values, dtype=np.float32)


def build_conductor_table(
    ior_dir: Path,
    presets: Sequence[str] = DEFAULT_CONDUCTOR_PRESETS,
    wavelengths_nm: np.ndarray = RGB_WAVELENGTHS_NM,
) -> dict[str, Any]:
    """Sample Mitsuba eta/k spectra at the RGB anchor wavelengths."""
    names: list[str] = []
    eta_rows: list[np.ndarray] = []
    k_rows: list[np.ndarray] = []
    for name in presets:
        eta_path = ior_dir / f"{name}.eta.spd"
        k_path = ior_dir / f"{name}.k.spd"
        if not eta_path.is_file() or not k_path.is_file():
            raise FileNotFoundError(f"missing conductor IOR files for {name}: {ior_dir}")
        eta_wl, eta_values = _read_spd(eta_path)
        k_wl, k_values = _read_spd(k_path)
        names.append(str(name))
        eta_rows.append(np.interp(wavelengths_nm, eta_wl, eta_values).astype(np.float32))
        k_rows.append(np.interp(wavelengths_nm, k_wl, k_values).astype(np.float32))
    eta = np.stack(eta_rows)
    k = np.stack(k_rows)
    f0 = ((eta - 1.0) ** 2 + k**2) / ((eta + 1.0) ** 2 + k**2)
    return {
        "names": names,
        "wavelengths_nm": np.asarray(wavelengths_nm, dtype=np.float32),
        "eta": eta,
        "k": k,
        "f0": f0.astype(np.float32),
    }

def srgb_to_linear(values: np.ndarray) -> np.ndarray:
    x = np.asarray(values, dtype=np.float32)
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def _load_rgb(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGB"), dtype=np.uint8)


def _load_scalar(
    path: Path | None,
    *,
    size: tuple[int, int],
    channel: int,
    factor: float,
    constant: float,
) -> np.ndarray:
    width, height = size
    if path is None:
        return np.full((height, width), np.clip(constant, 0.0, 1.0), dtype=np.float32)
    image = Image.open(path).convert("RGB")
    if image.size != size:
        image = image.resize(size, Image.Resampling.BILINEAR)
    values = np.asarray(image, dtype=np.float32)[..., int(channel)] / 255.0
    return np.clip(values * float(factor), 0.0, 1.0)


def _save_scalar_png(path: Path, values: np.ndarray) -> None:
    encoded = np.rint(np.clip(values, 0.0, 1.0) * 255.0).astype(np.uint8)
    Image.fromarray(encoded, mode="L").save(path)


def _nearest_conductors(
    pixel_f0: np.ndarray,
    preset_f0: np.ndarray,
    *,
    chunk_size: int = 262_144,
) -> np.ndarray:
    result = np.empty(len(pixel_f0), dtype=np.int32)
    for start in range(0, len(pixel_f0), chunk_size):
        stop = min(len(pixel_f0), start + chunk_size)
        distances = np.linalg.norm(
            pixel_f0[start:stop, None, :] - preset_f0[None, :, :], axis=2
        )
        result[start:stop] = np.argmin(distances, axis=1)
    return result


def _write_exr(path: Path, rgb: np.ndarray) -> None:
    # OpenCV is optional at package import time.  It is present in the production
    # render environment and writes EXR in BGR order.
    os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
    try:
        import cv2  # type: ignore
    except Exception as exc:  # pragma: no cover - environment-specific fallback
        raise RuntimeError("OpenCV with OpenEXR support is required for --write-exr") from exc
    data = np.asarray(rgb, dtype=np.float32)
    if data.ndim == 3 and data.shape[2] == 3:
        data = data[..., ::-1]
    if not cv2.imwrite(str(path), data):
        raise RuntimeError(f"failed to write EXR: {path}")


def convert_spatial_pbr_textures(
    *,
    object_id: str,
    output_dir: Path,
    base_color_path: Path,
    roughness_path: Path | None = None,
    metallic_path: Path | None = None,
    normal_path: Path | None = None,
    roughness_channel: int = 0,
    metallic_channel: int = 0,
    roughness_factor: float = 1.0,
    metallic_factor: float = 1.0,
    roughness_constant: float = 0.5,
    metallic_constant: float = 0.0,
    dielectric_ior: float = DEFAULT_DIELECTRIC_IOR,
    conductor_threshold: float = 0.5,
    conductor_table: dict[str, Any] | None = None,
    ior_dir: Path | None = None,
    conductor_presets: Sequence[str] = DEFAULT_CONDUCTOR_PRESETS,
    write_exr: bool = True,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create Mitsuba-ready spatial PBR and optical maps for one UV atlas."""
    output_dir.mkdir(parents=True, exist_ok=True)
    base_color_path = Path(base_color_path)
    base = _load_rgb(base_color_path)
    height, width = base.shape[:2]
    size = (width, height)
    roughness = _load_scalar(
        Path(roughness_path) if roughness_path else None,
        size=size,
        channel=roughness_channel,
        factor=roughness_factor,
        constant=roughness_constant,
    )
    metallic = _load_scalar(
        Path(metallic_path) if metallic_path else None,
        size=size,
        channel=metallic_channel,
        factor=metallic_factor,
        constant=metallic_constant,
    )
    alpha = np.square(roughness, dtype=np.float32)
    conductor = metallic >= float(conductor_threshold)

    table = conductor_table
    if table is None:
        if ior_dir is None:
            raise ValueError("ior_dir or conductor_table is required")
        table = build_conductor_table(Path(ior_dir), conductor_presets)
    names = [str(v) for v in table["names"]]
    eta_table = np.asarray(table["eta"], dtype=np.float32)
    k_table = np.asarray(table["k"], dtype=np.float32)
    f0_table = np.asarray(table["f0"], dtype=np.float32)

    eta_map = np.full((height, width, 3), float(dielectric_ior), dtype=np.float32)
    k_map = np.zeros((height, width, 3), dtype=np.float32)
    index_map = np.zeros((height, width), dtype=np.uint8)
    match_error = np.empty(0, dtype=np.float32)
    if np.any(conductor):
        base_linear = srgb_to_linear(base.astype(np.float32) / 255.0)
        pixel_f0 = base_linear[conductor]
        best = _nearest_conductors(pixel_f0, f0_table)
        eta_map[conductor] = eta_table[best]
        k_map[conductor] = k_table[best]
        index_map[conductor] = (best + 1).astype(np.uint8)
        match_error = np.linalg.norm(pixel_f0 - f0_table[best], axis=1)

    prefix = output_dir / object_id
    base_out = prefix.with_name(f"{object_id}_basecolor.png")
    Image.fromarray(base, mode="RGB").save(base_out)
    alpha_out = prefix.with_name(f"{object_id}_alpha.png")
    metallic_out = prefix.with_name(f"{object_id}_metallic.png")
    weight_out = prefix.with_name(f"{object_id}_bsdf_weight.png")
    index_out = prefix.with_name(f"{object_id}_conductor_index.png")
    _save_scalar_png(alpha_out, alpha)
    _save_scalar_png(metallic_out, metallic)
    _save_scalar_png(weight_out, metallic)
    Image.fromarray(index_map, mode="L").save(index_out)
    normal_out: Path | None = None
    if normal_path is not None:
        normal_out = prefix.with_name(f"{object_id}_normal.png")
        shutil.copyfile(normal_path, normal_out)

    npz_out = prefix.with_name(f"{object_id}_optical_maps.npz")
    np.savez_compressed(
        npz_out,
        eta=eta_map,
        k=k_map,
        conductor_index=index_map,
        metallic=metallic,
        alpha=alpha,
    )
    eta_exr = k_exr = None
    if write_exr:
        eta_exr = prefix.with_name(f"{object_id}_n_map.exr")
        k_exr = prefix.with_name(f"{object_id}_k_map.exr")
        _write_exr(eta_exr, eta_map)
        _write_exr(k_exr, k_map)

    counts = np.bincount(index_map.ravel(), minlength=len(names) + 1)
    matches = [
        {
            "index": idx,
            "material": "dielectric" if idx == 0 else names[idx - 1],
            "pixels": int(count),
            "fraction": float(count / index_map.size),
        }
        for idx, count in enumerate(counts)
        if count
    ]
    matches.sort(key=lambda row: row["pixels"], reverse=True)
    record: dict[str, Any] = {
        "schema": "robomituba.spatial_pbr.v1",
        "object_id": object_id,
        "size": [width, height],
        "inputs": {
            "base_color": str(base_color_path),
            "roughness": str(roughness_path) if roughness_path else None,
            "metallic": str(metallic_path) if metallic_path else None,
            "normal": str(normal_path) if normal_path else None,
            "roughness_channel": int(roughness_channel),
            "metallic_channel": int(metallic_channel),
            "roughness_factor": float(roughness_factor),
            "metallic_factor": float(metallic_factor),
            "roughness_constant": float(roughness_constant),
            "metallic_constant": float(metallic_constant),
        },
        "outputs": {
            "base_color": str(base_out),
            "alpha": str(alpha_out),
            "metallic": str(metallic_out),
            "bsdf_weight": str(weight_out),
            "normal": str(normal_out) if normal_out else None,
            "optical_maps_npz": str(npz_out),
            "eta_exr": str(eta_exr) if eta_exr else None,
            "k_exr": str(k_exr) if k_exr else None,
            "conductor_index": str(index_out),
        },
        "stats": {
            "roughness_min": float(roughness.min()),
            "roughness_max": float(roughness.max()),
            "roughness_mean": float(roughness.mean()),
            "alpha_mean": float(alpha.mean()),
            "metallic_min": float(metallic.min()),
            "metallic_max": float(metallic.max()),
            "metallic_mean": float(metallic.mean()),
            "conductor_fraction": float(conductor.mean()),
            "f0_match_l2_mean": float(match_error.mean()) if len(match_error) else None,
            "matches": matches,
        },
        "conductor_presets": names,
        "wavelengths_nm": np.asarray(table["wavelengths_nm"]).tolist(),
        "provenance": dict(provenance or {}),
    }
    record_out = prefix.with_name(f"{object_id}_spatial_pbr.json")
    record_out.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    record["record_path"] = str(record_out)
    return record


def summarize_records(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(records)
    return {
        "object_count": len(rows),
        "spatial_metallic_count": sum(
            1
            for row in rows
            if row["stats"]["metallic_min"] != row["stats"]["metallic_max"]
        ),
        "mean_conductor_fraction": float(
            np.mean([row["stats"]["conductor_fraction"] for row in rows])
        )
        if rows
        else 0.0,
    }
