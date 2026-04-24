"""curated_library.py — Hand-picked catalog of common realistic materials.

Each entry carries a Mitsuba ``bsdf_spec`` dict that drives both roles:

* **Bake**: ``bake_curated_previews`` builds a scene with this BSDF and writes
  ``assets/material_previews/curated/{material_id}.png`` — those PNGs are
  committed to the repo so the frontend can show a realistic thumbnail even
  when the user's machine has no working Mitsuba binary.
* **Apply**: when the user clicks "적용" on a curated tile, the daemon hands
  the same spec off to the scene-override path, so the preview and the
  actually-applied BSDF are consistent.

The catalog is intentionally small (~28 entries) and broad-coverage: metals,
plastics, dielectrics, principled (wood / paint / leather), fluids, fabrics,
and one neutral reference (spectralon).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal


Category = Literal[
    "metal", "plastic", "dielectric", "principled", "fluid", "fabric", "other"
]


@dataclass(frozen=True)
class CuratedMaterial:
    material_id: str
    display_name: str
    category: Category
    bsdf_spec: dict[str, Any]
    description: str


CATEGORY_DISPLAY: list[tuple[str, str]] = [
    ("all", "전체"),
    ("metal", "금속"),
    ("plastic", "플라스틱"),
    ("dielectric", "유전체"),
    ("principled", "프린시폴드"),
    ("fluid", "유체"),
    ("fabric", "패브릭"),
    ("other", "기타"),
]


def _rgb(values: tuple[float, float, float]) -> dict[str, Any]:
    return {"type": "rgb", "value": list(values)}


def _roughconductor(material: str, alpha: float, *, anisotropic: bool = False,
                    alpha_u: float | None = None, alpha_v: float | None = None,
                    specular_reflectance: tuple[float, float, float] | None = None) -> dict[str, Any]:
    spec: dict[str, Any] = {"type": "roughconductor", "material": material, "distribution": "ggx"}
    if anisotropic and alpha_u is not None and alpha_v is not None:
        spec["alpha_u"] = alpha_u
        spec["alpha_v"] = alpha_v
    else:
        spec["alpha"] = alpha
    if specular_reflectance is not None:
        spec["specular_reflectance"] = _rgb(specular_reflectance)
    return spec


def _roughplastic(diffuse: tuple[float, float, float], alpha: float,
                  *, int_ior: float = 1.49) -> dict[str, Any]:
    return {
        "type": "roughplastic",
        "diffuse_reflectance": _rgb(diffuse),
        "alpha": alpha,
        "int_ior": int_ior,
        "distribution": "ggx",
    }


def _dielectric(int_ior: float) -> dict[str, Any]:
    return {"type": "dielectric", "int_ior": int_ior, "ext_ior": 1.0}


def _roughdielectric(int_ior: float, alpha: float) -> dict[str, Any]:
    return {
        "type": "roughdielectric",
        "int_ior": int_ior,
        "ext_ior": 1.0,
        "alpha": alpha,
        "distribution": "ggx",
    }


def _principled(base_color: tuple[float, float, float], *, roughness: float,
                metallic: float = 0.0, specular: float = 0.5,
                clearcoat: float = 0.0, sheen: float = 0.0,
                sheen_tint: float = 0.0, anisotropic: float = 0.0) -> dict[str, Any]:
    return {
        "type": "principled",
        "base_color": _rgb(base_color),
        "roughness": roughness,
        "metallic": metallic,
        "specular": specular,
        "clearcoat": clearcoat,
        "sheen": sheen,
        "sheen_tint": sheen_tint,
        "anisotropic": anisotropic,
    }


def _diffuse(color: tuple[float, float, float]) -> dict[str, Any]:
    return {"type": "diffuse", "reflectance": _rgb(color)}


# ── Catalog ─────────────────────────────────────────────────────────────────

_CURATED_MATERIALS: list[CuratedMaterial] = [
    # ── Metals ──────────────────────────────────────────────────────────────
    CuratedMaterial(
        "aluminum", "Aluminum", "metal",
        _roughconductor("Al", 0.08),
        "일반 알루미늄. 약간 거친 반사.",
    ),
    CuratedMaterial(
        "brushed_steel", "Brushed Steel", "metal",
        _roughconductor("Fe", 0.0, anisotropic=True, alpha_u=0.05, alpha_v=0.30),
        "결이 수평으로 난 브러시드 스틸.",
    ),
    CuratedMaterial(
        "chrome", "Chrome", "metal",
        _roughconductor("Cr", 0.02),
        "크롬 도금. 강한 거울 반사.",
    ),
    CuratedMaterial(
        "copper", "Copper", "metal",
        _roughconductor("Cu", 0.05),
        "연마된 구리. 따뜻한 반사.",
    ),
    CuratedMaterial(
        "brass", "Brass", "metal",
        _roughconductor("Cu", 0.10, specular_reflectance=(1.00, 0.85, 0.55)),
        "황동. 약간 무광의 금색 금속.",
    ),
    CuratedMaterial(
        "gold_polished", "Gold (Polished)", "metal",
        _roughconductor("Au", 0.02),
        "연마된 순금.",
    ),
    CuratedMaterial(
        "black_anodized", "Black Anodized", "metal",
        _roughconductor("Al", 0.20, specular_reflectance=(0.08, 0.08, 0.08)),
        "검정 아노다이징 알루미늄.",
    ),

    # ── Plastics ────────────────────────────────────────────────────────────
    CuratedMaterial(
        "plastic_abs", "Plastic (ABS)", "plastic",
        _roughplastic((0.55, 0.50, 0.45), 0.12),
        "일반적인 ABS 플라스틱 하우징.",
    ),
    CuratedMaterial(
        "plastic_pvc", "Plastic (PVC)", "plastic",
        _roughplastic((0.78, 0.80, 0.82), 0.08),
        "쿨톤 흰색 PVC.",
    ),
    CuratedMaterial(
        "plastic_satin", "Plastic (Satin)", "plastic",
        _roughplastic((0.35, 0.38, 0.45), 0.25),
        "새틴 피니시의 블루그레이 플라스틱.",
    ),
    CuratedMaterial(
        "rubber", "Rubber", "plastic",
        _roughplastic((0.05, 0.05, 0.05), 0.45, int_ior=1.4),
        "검은 고무. 거의 무반사에 가까운 거친 표면.",
    ),
    CuratedMaterial(
        "carbon_fiber", "Carbon Fiber", "plastic",
        _roughconductor("Cr", 0.0, anisotropic=True, alpha_u=0.02, alpha_v=0.30,
                        specular_reflectance=(0.15, 0.15, 0.15)),
        "카본 파이버 직조. 방향성 하이라이트.",
    ),

    # ── Dielectrics ─────────────────────────────────────────────────────────
    CuratedMaterial(
        "glass_clear", "Glass (Clear)", "dielectric",
        _dielectric(1.5046),
        "투명 유리.",
    ),
    CuratedMaterial(
        "glass_frosted", "Glass (Frosted)", "dielectric",
        _roughdielectric(1.5046, 0.20),
        "프로스티드(젖빛) 유리.",
    ),
    CuratedMaterial(
        "water", "Water", "dielectric",
        _dielectric(1.333),
        "물 (얇은 표면).",
    ),
    CuratedMaterial(
        "oil", "Oil", "dielectric",
        _dielectric(1.47),
        "식용유 / 미네랄 오일.",
    ),
    CuratedMaterial(
        "ceramic_white", "Ceramic (White)", "dielectric",
        _roughplastic((0.82, 0.82, 0.80), 0.04),
        "흰색 세라믹. 약간의 글로스.",
    ),
    CuratedMaterial(
        "concrete", "Concrete", "dielectric",
        _diffuse((0.45, 0.44, 0.43)),
        "중성 회색 콘크리트 (확산).",
    ),

    # ── Principled ──────────────────────────────────────────────────────────
    CuratedMaterial(
        "paint_red", "Paint (Red)", "principled",
        _principled((0.72, 0.08, 0.08), roughness=0.35, specular=0.5),
        "차체 도장 느낌의 빨간 페인트.",
    ),
    CuratedMaterial(
        "paint_matte_gray", "Paint (Matte Gray)", "principled",
        _principled((0.35, 0.35, 0.35), roughness=0.70, specular=0.3),
        "무광 회색 페인트.",
    ),
    CuratedMaterial(
        "wood_oak", "Wood (Oak)", "principled",
        _principled((0.62, 0.45, 0.28), roughness=0.55, specular=0.4, clearcoat=0.1),
        "마감된 오크. 클리어코트 약간.",
    ),
    CuratedMaterial(
        "wood_walnut", "Wood (Walnut)", "principled",
        _principled((0.28, 0.18, 0.10), roughness=0.50, specular=0.4, clearcoat=0.1),
        "마감된 월넛. 어두운 톤.",
    ),
    CuratedMaterial(
        "leather_brown", "Leather (Brown)", "principled",
        _principled((0.28, 0.15, 0.08), roughness=0.70, specular=0.3),
        "무광 브라운 가죽.",
    ),

    # ── Fluid / wax ─────────────────────────────────────────────────────────
    CuratedMaterial(
        "water_pool", "Water (Pool)", "fluid",
        _dielectric(1.333),
        "수조용 물 (볼륨 근사 없음).",
    ),
    CuratedMaterial(
        "wax_cream", "Wax (Cream)", "fluid",
        _principled((0.95, 0.90, 0.78), roughness=0.55, specular=0.4, sheen=0.4, sheen_tint=0.2),
        "크림색 왁스. Sheen 근사로 서브서피스 느낌.",
    ),

    # ── Fabric ──────────────────────────────────────────────────────────────
    CuratedMaterial(
        "fabric_cotton", "Fabric (Cotton)", "fabric",
        _diffuse((0.85, 0.82, 0.75)),
        "크림색 면 직물.",
    ),
    CuratedMaterial(
        "velvet_navy", "Velvet (Navy)", "fabric",
        _principled((0.10, 0.15, 0.35), roughness=0.85, sheen=1.0, sheen_tint=0.5),
        "네이비 벨벳. 강한 sheen.",
    ),
    CuratedMaterial(
        "denim", "Denim", "fabric",
        _principled((0.20, 0.30, 0.50), roughness=0.85, sheen=0.3),
        "데님. 약한 sheen.",
    ),

    # ── Other ───────────────────────────────────────────────────────────────
    CuratedMaterial(
        "spectralon", "Spectralon", "other",
        _diffuse((0.98, 0.98, 0.98)),
        "거의 완전 확산 반사 표준 재질.",
    ),
]


_BY_ID: dict[str, CuratedMaterial] = {m.material_id: m for m in _CURATED_MATERIALS}


# ── Public API ──────────────────────────────────────────────────────────────

def list_curated_materials() -> list[CuratedMaterial]:
    return list(_CURATED_MATERIALS)


def get_curated_material(material_id: str) -> CuratedMaterial | None:
    return _BY_ID.get(material_id)


def curated_preview_path(repo_root: Path, material_id: str) -> Path:
    return repo_root / "assets" / "material_previews" / "curated" / f"{material_id}.png"
