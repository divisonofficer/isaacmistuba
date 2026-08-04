#!/usr/bin/env python3
"""Report: end-to-end Infinigen→OpticalNav kitchen import + multimodal render.

Reads dev_report/images/kitchen_multimodal_2026-07-31/manifest.json (written by
tools/render_kitchen_multimodal.py) and the import manifest, and lays out per
viewpoint the modality grid: RGB(passive) · albedo · NIR(active, hybrid-albedo) ·
DoP · AoLP · normal/roughness/metallic map renders. Documents the pipeline
(semantic decimation → bake → nav graph → passive/active/polar render conventions).

    python tools/generate_report_kitchen_multimodal.py
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
IMG_DIR = REPO / "dev_report/images/kitchen_multimodal_2026-07-31"


def _versioned(img: str) -> str:
    """Return a per-content filename (hardlinked copy `<stem>__v<mtime>.png`) so the
    browser re-fetches when an image changes — same-filename caching (a real problem for
    a file:// report) is defeated WITHOUT a `?v=` query (which breaks file:// loading).
    Old versions of the same stem are pruned."""
    p = IMG_DIR / img
    ver = int(p.stat().st_mtime)
    stem, ext = os.path.splitext(img)
    vname = f"{stem}__v{ver}{ext}"
    vpath = IMG_DIR / vname
    if not vpath.exists():
        for old in IMG_DIR.glob(f"{stem}__v*{ext}"):
            old.unlink()
        try:
            os.link(p, vpath)          # hardlink: no extra disk
        except OSError:
            shutil.copy2(p, vpath)
    return vname
IMPORT_MANIFEST = REPO / "out/infinigen_imports/kr_20260730_single_room_kitchen/scene_manifest.json"
OUT = REPO / "dev_report/report_2026-07-31_kitchen_multimodal.html"

MODS = [
    ("rgb", "RGB — visible band", "band carrier의 <b>visible 밴드</b>(weight 0) Stokes S0. 동일 씬·동일 passive 조명."),
    ("nir_active_pseudo", "NIR — 854 band", "같은 band carrier의 <b>NIR 밴드</b>(weight 1) S0. __vis와 <b>BSDF·물리파라미터 동일, diffuse albedo만</b> hybrid NIR 반사율로 교체. 컬러 박스가 NIR에서 회색으로(밴드차이), 유리는 양밴드 투명(Fresnel·max_depth 8), 금속 일관."),
    ("dop", "DoP (red–black)", "NIR 밴드 Stokes 편광도. specular/유리에서 편광(빨강), diffuse는 검정."),
    ("aolp", "AoLP (hue=angle)", "편광각을 <b>색상(hue)</b>으로: 각도별 다른 색. 채도=DoLP라 무편광은 흰색, 편광 강한 곳(창유리·모서리)만 선명."),
    ("albedo", "Albedo (ray_intersect)", "primary-ray 직접 추출한 visible base color(조명 무관). AOV 아님 — 아래 property map 참고."),
    ("map_normal", "Normal (world sh_normal)", "primary-ray shading normal(월드): normal map 있으면 perturbed, 없으면 폴리곤 기하 법선. 벽 방향별 색·바닥=위."),
    ("map_roughness", "Roughness map", "canonical roughness(유리=0·매트=high). ray_intersect로 UV 직접 lookup — AOV backend stripe 버그 우회."),
    ("map_metallic", "Metallic map", "canonical metallic(전도체=1, 나머지 0). .blend authoring 권위 — 누출 glTF factor/texture 배제."),
]

CSS = """
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
 max-width:1200px;margin:0 auto;padding:24px;color:#1a1a1a;background:#fafafa}
h1{font-size:24px} h2{font-size:19px;margin-top:32px;border-bottom:2px solid #eee;padding-bottom:6px}
.sub{color:#666;font-size:14px} code{background:#f0f0f0;padding:1px 5px;border-radius:3px;font-size:13px}
.note{background:#f4f7fb;border-left:3px solid #4a7fc0;padding:10px 14px;margin:12px 0;font-size:14px;line-height:1.55}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:14px 0}
.cell{background:#fff;border:1px solid #e3e3e3;border-radius:6px;overflow:hidden}
.cell img{width:100%;display:block;background:#222}
.cap{padding:6px 8px;font-size:12px} .cap b{font-size:13px}
.mut{color:#777;font-size:12px} table{border-collapse:collapse;font-size:13px;margin:8px 0}
td,th{border:1px solid #ddd;padding:4px 10px;text-align:right} th{background:#f5f5f5}
.pipe{background:#fff;border:1px solid #e3e3e3;border-radius:6px;padding:12px 16px;font-size:14px;line-height:1.7}
"""


def _decim_stats() -> dict:
    if not IMPORT_MANIFEST.is_file():
        return {}
    man = json.loads(IMPORT_MANIFEST.read_text())
    units = man.get("units", [])
    dec = [u for u in units if u.get("decimation", {}).get("decimated")]
    before = sum((u.get("decimation", {}).get("faces_before") or u.get("polys", 0)) for u in units)
    after = sum((u.get("decimation", {}).get("faces_after")
                 if u.get("decimation") else u.get("polys", 0)) or u.get("polys", 0) for u in units)
    return {"units": len(units), "decimated": len(dec), "before": before, "after": after,
            "pct": (100 * (1 - after / before)) if before else 0.0}


def main() -> int:
    manifest = json.loads((IMG_DIR / "manifest.json").read_text())
    ds = _decim_stats()
    views = manifest["views"]

    sections = ""
    for v in views:
        cells = ""
        for key, title, desc in MODS:
            img = v["images"].get(key)
            if not img or not (IMG_DIR / img).is_file():
                continue
            cells += (f'<div class="cell"><img src="images/kitchen_multimodal_2026-07-31/{_versioned(img)}" '
                      f'alt="{title}"><div class="cap"><b>{title}</b><br><span class="mut">{desc}</span></div></div>')
        sections += (f'<h2>Viewpoint {v["index"]} — <code>{v["node_id"]}</code></h2>'
                     f'<p class="mut">position (world XZ) = {[round(x,2) for x in v["position"][:2]]}</p>'
                     f'<div class="grid">{cells}</div>')

    decim_html = (f'<table><tr><th>유닛</th><th>decimated</th><th>faces before</th>'
                  f'<th>faces after</th><th>감소</th></tr><tr>'
                  f'<td>{ds["units"]}</td><td>{ds["decimated"]}</td><td>{ds["before"]:,}</td>'
                  f'<td>{ds["after"]:,}</td><td>−{ds["pct"]:.1f}%</td></tr></table>') if ds else ""

    html = f"""<!doctype html><html><head><meta charset="utf-8">
<title>Kitchen import + multimodal render (2026-07-31)</title><style>{CSS}</style></head><body>
<h1>Infinigen → OpticalNav: kitchen import + 멀티모달 렌더</h1>
<p class="sub">2026-07-31 · scene <code>{manifest['scene_id']}</code> ·
{len(views)} viewpoints · {manifest['size'][0]}×{manifest['size'][1]} ·
unified discrete-band Stokes carrier · 순수 analytic(pplastic·roughconductor·dielectric) · spp 8000 ·
Device 1 / RTX 5090 / <code>cuda_ad_rgb_polarized</code></p>

<div class="pipe"><b>파이프라인.</b>
① Infinigen <code>.blend</code> → import (texture bake · semantic-contract decimation) →
② nav grid + viewpoint graph →
③ <b>provenance 계약</b>(<code>material_canonical.json</code>) →
④ <b>band carrier</b>(재질마다 <code>blendbsdf(weight,__vis,__nir)</code>) 1회 로드 →
⑤ RGB/NIR는 weight flip Stokes, property map은 ray_intersect (아래).</div>

<div class="note"><b>Mesh decimation (② 규약).</b> import 중 bpy export 루프에서
<code>semantic_contract</code> 정책으로 객체별 retained-ratio를 계산해 decimate.
배경 장식(선반 소품)은 3%까지, 구조물/유리/금속은 보호.
{decim_html}</div>

<div class="note"><b>렌더 규약 — unified band carrier.</b>
3-별도패스(RGB passive · pseudo-NIR-swap flash · polar)를 폐기하고, <b>모든 재질을
<code>blendbsdf(weight, __vis, __nir)</code>로 감싼 band carrier 씬</b>(<code>spectral_band.build_band_scene</code>)을
<code>cuda_ad_rgb_polarized</code>로 <b>1회 로드</b> → 재질 weight를 0(visible)/1(NIR)로 flip(재로드 없음) → Stokes로
RGB·NIR·DoP·AoLP를 한 번에 뽑는다. <code>__nir</code>은 <code>__vis</code>의 deep copy라 <b>BSDF 플러그인·물리
파라미터(alpha·normal·IOR·η/k)가 동일하고 diffuse albedo만</b> hybrid NIR 반사율(<code>synthesize_nir_texture</code>)로
바뀐다 — 금속/유리는 diffuse albedo가 없어 Fresnel 그대로(밴드 불변). 양 밴드가 <b>동일 passive 조명 +
max_depth 8</b>이라 유리가 투과하고 금속 반사가 일관 — 옛 flash·depth-3 아티팩트(금속거울·유리검정)가 사라진다.
<br><span class="mut">property map(albedo/normal/roughness/metallic)은 integrator를 안 거치고 primary-ray
<code>scene.ray_intersect</code>로 직접 추출한다(아래).</span></div>

{sections}

<h2>메모</h2>
<ul style="font-size:14px;line-height:1.7">
<li><b>RGB/NIR = 같은 band carrier, weight flip.</b> <code>tools/render_kitchen_unified.py</code>가
band 씬을 1회 로드하고 재질 weight를 0/1로 바꿔 두 밴드를 뽑는다. RGB와 NIR은 <b>동일 BSDF·물리
파라미터</b>이고 diffuse albedo만 밴드별로 다르다. 밴드 차이는 diffuse 재질에서 드러난다 — 컬러 박스가 NIR에서
회색(NIR 반사율)으로. 금속·유리는 visible↔NIR 광학이 비슷해(Al ~92%, IOR~1.5) 두 밴드가 유사한 게 정상.</li>
<li><b>유리/금속 아티팩트 해소.</b> 옛 pseudo-NIR는 point flash를 썼는데, 그때 금속이 거울(flash 반사)·
유리가 검정(<code>max_depth 3</code>이 다중 굴절면 투과를 잘라 불투명)으로 렌더됐다. band carrier는 <b>양 밴드가
동일 passive 조명 + max_depth 8</b>이라 유리가 투과하고 금속 반사가 일관 — 둘 다 렌더 설정 아티팩트였음이 확인됐다.</li>
<li><b>property map = primary-ray ray_intersect(핵심).</b> depth/normal/roughness/metallic/albedo는 광수송이
아니므로 integrator를 안 거치고 <code>scene.ray_intersect</code>로 직접 추출한다. 이 빌드의 <code>aov</code>
integrator·film 누적 backend가 <b>spp에 비례해 AOV에 규칙적 세로 stripe를 주입</b>하는 버그가 있어(평면 하나
depth가 spp=1 매끈→spp=4096 빗살, RGB path는 클린) 옛 mapviz(albedo AOV) roughness가 노이지했다. ray_intersect는
integrator·film·spp를 통째로 우회해 clean.</li>
<li><b>meaningful roughness + provenance 계약.</b> roughness는 canonical semantics에서 실제값을 유도한다:
smooth dielectric(창유리)→<b>0.0</b>, Lambertian→1.0, alpha 스칼라→그 값, 미상만 magenta(가짜 0.5 안 씀).
metallic은 <b>.blend authoring 권위</b> — Blender glTF export가 절차적 재질에 누출한 metallicFactor=1.0·
fabricated metallic 텍스처를 배제(전도체만 1). 각 파라미터의 baked/derived/prior/undefined + valid를
<code>material_canonical.json</code>(<code>apps/material_pipeline.py</code>)에 기록.</li>
<li><b>AoLP 컬러맵.</b> 편광각을 hue로 인코딩(0°≡180° cyclic), 채도=DoLP(무편광→흰색). S0≈0 픽셀의
DoLP=0/0(NaN)은 0으로 처리. DoP는 창유리·모서리 등 Fresnel specular에서 집중.</li>
<li><b>순수 analytic 재질 계약.</b> 씬을 pplastic·roughconductor·dielectric <b>3종</b>으로 정규화
(measured pBRDF는 편광 정확도용 옵션 anchor일 뿐 기본 아님 → build_band_scene <code>force_analytic</code>이
measured→pplastic, smooth conductor→roughconductor로 접음). 렌더 계약(material_contract §4):
<b>roughconductor source-faithful</b>(base_color를 F0로 1회만; Al×base_color 이중곱 제거) +
<b>microfacet alpha=r²</b>(Blender Principled). 계약은 band carrier(렌더)에만, render_scene.xml은
원본 r/base_color GT로 유지.</li>
<li><b>금속 albedo.</b> rough conductor는 diffuse+specular 혼합이므로 albedo=0(거울)이 아니라
그 <b>base_color(specular_reflectance)가 금속색</b>. property albedo가 이를 반영(어두운 gunmetal 컵은
회색으로). 단 RGB 실렌더에선 금속이 환경을 반사하므로 어두운 환경에선 어둡게(NIR flash로 highlight 관측).</li>
<li><b>NIR = band-gated active flash.</b> band carrier에 rig NIR point 광원을 얹고 밴드별로 radiance를
flip: visible=0(passive), NIR=on. 한 씬·한 weight flip으로 <b>RGB엔 안 보이고 NIR엔 보이는 액티브 조명</b>
(주변광의 ~50×, 금속 highlight 관측 목적).</li>
<li><b>--no-polar 고속 모드.</b> 편광이 불필요하면 <code>path</code> integrator(cuda_ad_rgb)로 RGB/NIR만
(DoP/AoLP 생략) → 실측 <b>~5× 빠름</b>(1024spp vp_000012: Stokes 76/65s vs path 12/15s). max_depth 8 +
복잡 재질이라 Mueller 행렬 연산이 지배적. 이 리포트는 DoP/AoLP 위해 polar로 렌더.</li>
<li><b>남은 작업</b>: band 렌더 노출/조명 튜닝, stage2 spectral η/k 정밀화, property map float EXR +
valid mask, render_daemon 본체에 계약 채택.</li>
</ul>
</body></html>"""
    OUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUT}  ({len(html)/1024:.1f} KB, {len(views)} viewpoints)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
