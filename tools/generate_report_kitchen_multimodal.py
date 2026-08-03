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
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
IMG_DIR = REPO / "dev_report/images/kitchen_multimodal_2026-07-31"
IMPORT_MANIFEST = REPO / "out/infinigen_imports/kr_20260730_single_room_kitchen/scene_manifest.json"
OUT = REPO / "dev_report/report_2026-07-31_kitchen_multimodal.html"

MODS = [
    ("rgb", "RGB — passive", "주변광만(무광). 실내 항법 뷰."),
    ("albedo", "Albedo (AOV)", "Mitsuba diffuse-reflectance AOV — visible bake 결과."),
    ("nir_pseudo_albedo", "NIR albedo (hybrid)", "NIR 밴드 반사율 맵(AOV): <b>hybrid</b> = class-prior μ_c + RGB 국소구조 전이 ρ=clip[μ_c(1+β_c·D)], D=상대 국소대비. visible albedo와 나란히 비교. 매끈한 벽은 μ_c 유지(과증폭 없음)."),
    ("nir_active_pseudo", "NIR — active point flash", "rig NIR <b>point(delta) flash</b>(하드웨어 충실) + hybrid NIR albedo. 오브젝트간 하드 섀도우, r² falloff. <b>flash pass spp=4096</b>(polar_spp 경유) + firefly clamp + max_depth 3 → MC 노이즈 소거."),
    ("dop", "DoP (red–black)", "편광 area flash. specular/유리에서 편광(빨강), diffuse는 검정."),
    ("aolp", "AoLP (hue=angle)", "편광각을 <b>색상(hue)</b>으로: 각도별 다른 색. 채도=DoLP라 무편광은 흰색, 편광 강한 곳(창유리·모서리)만 선명."),
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
path/AOV spp {manifest['spp']}/{manifest.get('aov_spp', manifest['spp'])} · NIR flash spp {manifest.get('nir_spp', manifest['spp'])} ·
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
<b>RGB는 passive</b>(주변광), <b>NIR은 active</b>(rig NIR point flash) — 목적에 맞게 분리.
NIR 밴드는 <b>hybrid NIR albedo</b>(class-prior μ_c × RGB 국소구조) 규약 적용 — pseudo/constant보다
오브젝트 텍스처 보존과 물리적 평균을 동시에 만족.
편광(DoP/AoLP)은 rig 편광 area flash. normal은 world sh_normal AOV, roughness/metallic은 baked 맵을 flat 시각화.
<br><span class="mut">주의: modality 그룹별 분리 렌더(active_nir와 dop/aolp 동시 호출 시 Dr.Jit AD 충돌),
polarized Stokes variant는 텍스처 256 캡으로 메모리 fit.</span></div>

{sections}

<h2>메모</h2>
<ul style="font-size:14px;line-height:1.7">
<li>이 실험은 <code>tools/render_kitchen_multimodal.py</code>로 재현. 뷰포인트는 그래프
노드×헤딩을 저해상도 프리뷰 렌더해 <b>content 점수(공간 std×조명 비율)</b>로 자동 선택 —
벽 모퉁이만 보는 노드는 점수 0으로 자동 제외.</li>
<li><b>AoLP 컬러맵.</b> 편광각을 hue로 인코딩(0°≡180° cyclic), 채도=DoLP(무편광→흰색).
grayscale 램프보다 각도 구분이 쉽다. S0≈0 픽셀의 DoLP=0/0(NaN)은 0으로 처리.</li>
<li><b>NIR speckle 근본원인 = spp 배선 버그(수정됨).</b> 앞선 렌더의 NIR flash 낱알은 실제로
<b>Monte-Carlo 노이즈</b>였다. multimodal은 <code>active_nir_intensity</code> 패스를 <code>config.polar_spp</code>로
렌더하는데 harness는 <code>path_spp</code>/<code>aov_spp</code>만 세팅하고 <code>polar_spp</code>는 기본값(256)으로
둬서 <code>--nir-spp 4096</code>이 조용히 무시됐다 → flash가 256 spp로 렌더. <code>cfg_nir.polar_spp=nir_spp</code>로
수정해 진짜 4096으로 렌더하니 벽·선반의 salt-pepper가 소거됐다(육안 확인). <code>cfg.spp</code>·AOV=polar_spp
계열과 동일한 "잘못된 spp 필드" 버그.</li>
<li><b>NIR albedo(hybrid) 노이즈.</b> hybrid 맵의 초기 표준화(log-luminance/σ) 방식이 매끈한 벽의
micro-variation을 grain으로 증폭했다. <b>상대 국소대비</b> D(x)=clip((L−LPF)/(LPF+ε),−1,1)로 바꿔
매끈면 D≈0(유지)·텍스처는 자연 대비로 표시. AOV 자체는 256에서 이미 수렴(256→512 grain 불변,
1024는 OOM fallback로 오히려 악화)이라 AOV spp 상향은 무효.</li>
<li><b>재질맵 렌더 방식.</b> roughness/metallic은 각 shape의 baked 맵을 <code>diffuse.reflectance</code>로
넣고 <b>albedo AOV</b>로 읽는다(조명/occlusion 무관, self-emitter의 OptiX SBT overflow 회피). map 없는 재질은
검정이 아니라 참값(roughness=scalar alpha, metallic=0/1)으로 표시. baked roughness는 실제 평균 ≈0.75(매트)로
정상 — 초기 렌더의 "roughness 0" 인상은 diffuse+occlusion viz의 오류였다.
<b>readout tex_cap=256(수정).</b> roughness/metallic만 full-res 텍스처라 baked 맵의 sparse outlier 텍셀이
minification에서 alias→벽에 salt-pepper speckle이 떴다(같은 AOV 경로인 base-color는 spike가 없어 클린).
텍스처를 256 캡으로 box-prefilter하니 speckle 소거(A/B 실렌더 확인). aov_spp 상향으론 안 잡힌다.
<b>meaningful fallback(수정).</b> roughness-map 없는 재질에 상수 0.5를 넣던 걸, 재질 semantics에서 실제
스칼라를 유도하도록 바꿨다: smooth dielectric(창유리)→<b>0.0</b>(delta-specular, 가짜 0.5 아님),
Lambertian→1.0, alpha 스칼라→그 값, 미상만 magenta 플래그. 이 규약은 provenance 계약
(<code>material_canonical.json</code>, <code>apps/material_pipeline.py</code>)으로 정식화됐다 —
각 파라미터가 baked/derived/prior/undefined 중 무엇인지 valid 플래그와 함께 기록.
<b>normal은 baked 텍스처가 아니라 <code>nn:sh_normal</code> world-space AOV</b>로 렌더 —
normal map 없는 폴리곤도 검정/neutral이 아니라 <b>실제 기하 법선</b>을 카메라 뷰 기준으로 보여준다
(map 있으면 perturbation 포함).</li>
<li>DoP는 창유리·카운터 모서리 등 Fresnel specular에서 편광 신호가 집중.</li>
<li><b>metallic provenance 수정.</b> Blender glTF export가 절차적 재질에 metallicFactor
기본값 1.0을 누출해 세라믹 바닥 등 41% 재질이 오금속화됐던 것을, .blend 소스 metallic
(source_metallic)을 권위로 판정하도록 수정(render_daemon). 바닥 metallic 0.88→≈0.</li>
<li><b>NIR = point flash.</b> area flash 대신 rig point(delta) emitter로 하드웨어 충실 +
오브젝트간 하드 섀도우. delta light는 direct가 NEE로 노이즈 0; GI firefly는 clamp+max_depth로 제거.
flash pass는 <b>polar_spp=4096</b>로 렌더(위 spp 배선 버그 수정).</li>
<li><b>남은 작업</b>: spatial-PBR η/k(공간가변 금속 IOR) 풀배선; metallic 4-mode(pure_metal/
pure_dielectric/mixed/unknown) + glTF factor×texture 정확 곱 (설계 확정, 미구현).</li>
</ul>
</body></html>"""
    OUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUT}  ({len(html)/1024:.1f} KB, {len(views)} viewpoints)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
