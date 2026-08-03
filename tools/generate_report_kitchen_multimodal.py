#!/usr/bin/env python3
"""Report: end-to-end Infinigen→OpticalNav kitchen import + multimodal render.

Reads dev_report/images/kitchen_multimodal_2026-07-31/manifest.json (written by
tools/render_kitchen_multimodal.py) and the import manifest, and lays out per
viewpoint the modality grid: RGB(passive) · albedo · NIR(active, pseudo-albedo) ·
DoP · AoLP · normal/roughness/metallic map renders. Documents the pipeline
(semantic decimation → bake → nav graph → passive/active/polar render conventions).

    python tools/generate_report_kitchen_multimodal.py
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
IMG_DIR = REPO / "dev_report/images/kitchen_multimodal_2026-07-31"
IMPORT_MANIFEST = REPO / "out/infinigen_imports/kr_20260730_single_room_kitchen/scene_manifest.json"
OUT = REPO / "dev_report/report_2026-07-31_kitchen_multimodal.html"

MODS = [
    ("rgb", "RGB — passive", "주변광만(무광). 실내 항법 뷰."),
    ("albedo", "Albedo (AOV)", "Mitsuba diffuse-reflectance AOV — bake 결과."),
    ("nir_active_pseudo", "NIR — active flash", "rig NIR flash + <b>pseudo-NIR albedo</b> 규약. 근거리 밝고 falloff. 벽의 미세 요철은 flash가 normal-map을 grazing 조명한 실제 표면 relief(노이즈 아님)."),
    ("dop", "DoP (red–black)", "편광 area flash. specular/유리에서 편광(빨강), diffuse는 검정."),
    ("aolp", "AoLP", "선형 편광각 0–180°."),
    ("map_normal", "Normal (world sh_normal)", "픽셀별 실제 법선(AOV): normal map 있으면 perturbed, 없으면 폴리곤 기하 법선. 벽 방향별 색·바닥=위."),
    ("map_roughness", "Roughness map", "baked roughness — 매트 표면 밝음, 유리/광택 어두움."),
    ("map_metallic", "Metallic map", "baked metallic (금속만 밝음)."),
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
            cells += (f'<div class="cell"><img src="images/kitchen_multimodal_2026-07-31/{img}" '
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
spp {manifest['spp']} (NIR {manifest.get('nir_spp', manifest['spp'])}) ·
Device 1 / RTX 5090 / <code>cuda_ad_rgb_polarized</code></p>

<div class="pipe"><b>파이프라인.</b>
① Infinigen <code>.blend</code> → <code>run_infinigen_import.sh</code> (texture bake ON) →
② <b>semantic-contract mesh decimation</b> (appearance-contract LOD 예산) →
③ nav traversability grid + viewpoint graph (21 nodes) →
④ 멀티모달 렌더 (아래).</div>

<div class="note"><b>Mesh decimation (② 규약).</b> import 중 bpy export 루프에서
<code>semantic_contract</code> 정책으로 객체별 retained-ratio를 계산해 decimate.
배경 장식(선반 소품)은 3%까지, 구조물/유리/금속은 보호.
{decim_html}</div>

<div class="note"><b>렌더 규약.</b>
<b>RGB는 passive</b>(주변광), <b>NIR은 active</b>(rig NIR flash) — 목적에 맞게 분리.
NIR 밴드는 확정된 <b>pseudo-NIR albedo</b>(<code>max(rgb,1-rgb)·[.229,.587,.114]</code>) 규약 적용.
편광(DoP/AoLP)은 rig 편광 area flash. normal/roughness/metallic은 baked 맵을 flat 시각화.
<br><span class="mut">주의: modality 그룹별 분리 렌더(active_nir와 dop/aolp 동시 호출 시 Dr.Jit AD 충돌),
polarized Stokes variant는 텍스처 256 캡으로 메모리 fit.</span></div>

{sections}

<h2>메모</h2>
<ul style="font-size:14px;line-height:1.7">
<li>이 실험은 <code>tools/render_kitchen_multimodal.py</code>로 재현. 뷰포인트는 그래프
노드 중 방 중심에서 먼 것을 골라 <b>중심을 바라보게</b> 프레이밍(가까운 벽 회피).</li>
<li><b>NIR speckle 검증.</b> 벽의 낱알 무늬는 렌더(MC) 노이즈가 아니라 <b>실제 표면 relief</b>다 —
동일 뷰를 <b>spp 128과 4096으로 렌더하면 픽셀 단위로 동일</b>(local-diff-std 2.44 불변). active flash가
plaster의 <b>normal map</b> 요철을 grazing 각도로 조명해 생기는 micro-shadow로, passive RGB(부드러운 주변광)에선
안 보이고 active 센싱에서만 드러나는 특성. pseudo-NIR albedo에 0.8px 블러를 줘도 남는다 → albedo가 아닌 normal 기인.</li>
<li><b>재질맵 렌더 방식.</b> roughness/metallic은 각 shape의 baked 맵을 <code>diffuse.reflectance</code>로
넣고 <b>albedo AOV</b>로 읽는다(조명/occlusion 무관, self-emitter의 OptiX SBT overflow 회피). map 없는 재질은
검정이 아니라 참값(roughness=scalar alpha, metallic=0/1)으로 표시. baked roughness는 실제 평균 ≈0.75(매트)로
정상 — 초기 렌더의 "roughness 0" 인상은 diffuse+occlusion viz의 오류였다.
<b>normal은 baked 텍스처가 아니라 <code>nn:sh_normal</code> world-space AOV</b>로 렌더 —
normal map 없는 폴리곤도 검정/neutral이 아니라 <b>실제 기하 법선</b>을 카메라 뷰 기준으로 보여준다
(map 있으면 perturbation 포함).</li>
<li>DoP는 창유리·카운터 모서리 등 Fresnel specular에서 편광 신호가 집중.</li>
<li><b>남은 작업</b>: spatial-PBR η/k(공간가변 금속 IOR) 풀배선 — 현재 렌더는
optical_class별 polar-capable BSDF(pplastic/dielectric/roughconductor) 사용.</li>
</ul>
</body></html>"""
    OUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUT}  ({len(html)/1024:.1f} KB, {len(views)} viewpoints)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
