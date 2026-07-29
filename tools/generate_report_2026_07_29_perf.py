#!/usr/bin/env python3
"""Weekly dev report — performance improvements (unified spectral-polar scene).

Four sections:
  1. Modality unification: per-modality reload -> ONE spectral-polarization scene
     (band-flip), memory before/after  (band_bench_2026-07-27/metrics.json)
  2. Mesh decimation (semantic-topology LOD)  (lod_compare result_*.json + plan)
  3. Infinigen import module-connection graph (+ where decimation slots in)
  4. NIR albedo synthesis (class->rho854 priors, 1-channel)  (nir_reflectance + config)

Writes dev_report/report_2026-07-29_perf.html.
"""
from __future__ import annotations
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BAND = REPO / "dev_report/images/band_bench_2026-07-27/metrics.json"
LODc = REPO / "dev_report/images/lod_compare_2026-07-28"
PLAN = REPO / "out/infinigen_imports/kr_20260625/semantic_lod_plan.json"
NIRC = REPO / "configs/datasets/class_band_reflectance_v1.json"
OUT = REPO / "dev_report/report_2026-07-29_perf.html"
SCENE_POLYS = 27_136_473

CSS = """
:root{--bg:#0f1216;--fg:#e6e9ef;--mut:#9aa4b2;--line:#232a33;--ok:#39d98a;--bad:#ff6b6b;--acc:#6aa9ff;--warn:#ffcc66}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.65 -apple-system,"Segoe UI",Roboto,"Noto Sans KR",sans-serif}
.wrap{max-width:1080px;margin:0 auto;padding:40px 24px 90px}h1{font-size:25px;margin:0 0 6px}
h2{font-size:19px;margin:36px 0 8px;padding-top:16px;border-top:1px solid var(--line)}h3{font-size:14px;color:var(--acc);margin:16px 0 6px}
.sub{color:var(--mut);margin:0 0 22px}code{background:#1a1f26;padding:1px 6px;border-radius:4px;font-size:13px}
table{border-collapse:collapse;width:100%;margin:10px 0;font-size:13px}th,td{border:1px solid var(--line);padding:6px 9px;text-align:left}
th{background:#161b22;color:var(--mut)}td.num{text-align:right;font-variant-numeric:tabular-nums}
.big{font-size:30px;font-weight:800;color:var(--ok)}.note{background:#141920;border-left:3px solid var(--acc);padding:12px 16px;margin:14px 0;border-radius:0 8px 8px 0}
.warn{border-left-color:var(--warn)}.bad{border-left-color:var(--bad)}.mut{color:var(--mut);font-size:12px}
.ok{color:var(--ok)}.xx{color:var(--bad)}
/* module graph */
.graph{display:flex;flex-direction:column;gap:0;margin:14px 0;font-size:12.5px}
.row{display:flex;align-items:stretch;gap:10px;flex-wrap:wrap}
.box{background:#161b22;border:1px solid var(--line);border-radius:8px;padding:8px 12px;min-width:150px}
.box b{color:var(--fg)}.box .f{color:var(--mut);font-size:11px;display:block;margin-top:2px}
.box.mod{border-color:#2c3a4f}.box.hi{border-color:var(--warn);background:#20200f}
.arrow{color:var(--acc);align-self:center;font-size:18px;padding:0 2px}
.down{color:var(--acc);text-align:center;font-size:16px;margin:2px 0}
.mono{font-family:ui-monospace,Menlo,monospace}
"""


def _band():
    m = json.loads(BAND.read_text())["modes"]
    new, old_r, old_res = m["new"], m["old_reload"], m.get("old_resident", {})
    def wall(x): return round(x.get("total_wall_s", 0), 0)
    return {
        "new_wall": wall(new), "new_load": round(new["load_scene_s"][0], 0),
        "new_flip_ms": round(new["bands"]["nir_854"]["flip_ms"], 0),
        "new_mib": new.get("gpu_attributable_mib"),
        "reload_wall": wall(old_r), "reload_loads": len(old_r["load_scene_s"]),
        "reload_mib": old_r.get("gpu_attributable_mib"),
        "res_status": old_res.get("status"), "res_needed": old_res.get("required_estimate_mib"),
        "res_single": old_res.get("single_scene_attributable_mib"),
        "speedup": round(wall(old_r) / max(wall(new), 1), 2),
    }


def _lod():
    rf = json.loads((LODc / "result_full.json").read_text())
    rl = json.loads((LODc / "result_lod.json").read_text())
    plan = json.loads(PLAN.read_text())
    shapes = json.loads((REPO / "out/opticalnav/opticalnav-v0.2/scenes/infinigen_kr_20260625/semantic_lod_shapes.json").read_text())
    hp = plan["totals"]["highpoly_polys"]; dec = shapes["lod_faces"]
    scene_lod = dec + (SCENE_POLYS - hp)
    return {"full_mib": rf["peak_over_baseline_mib"], "lod_mib": rl["peak_over_baseline_mib"],
            "full_load": rf["load_scene_s"], "lod_load": rl["load_scene_s"],
            "mem_pct": round(100 * (1 - rl["peak_over_baseline_mib"] / rf["peak_over_baseline_mib"]), 0),
            "load_x": round(rf["load_scene_s"] / rl["load_scene_s"], 1),
            "scene_lod": scene_lod, "red": round(100 * (1 - scene_lod / SCENE_POLYS), 1)}


def _nir():
    d = json.loads(NIRC.read_text()); cl = d["classes"]
    ex = {k: cl[k].get("rho_854", {}).get("mean") for k in
          ["ceramic", "wood", "concrete", "rubber", "vegetation_leaf", "shell_calcite"] if k in cl}
    return {"n": len(cl), "ex": ex}


IMPORT_GRAPH = """
<div class="graph">
 <div class="row"><div class="box"><b>.blend</b><span class="f">Infinigen 씬</span></div>
   <span class="arrow">→</span>
   <div class="box mod"><b>bpy 추출</b><span class="f">apps/import_infinigen_scene.py · scene graph·object·material·light</span></div></div>
 <div class="down">↓</div>
 <div class="row">
   <div class="box mod"><b>per-object 메시 export</b><span class="f">OBJ + GLB + MTL (usemtl slot 분리)</span></div>
   <span class="arrow">→</span>
   <div class="box hi"><b>texture/PBR BAKE</b><span class="f">albedo·normal·roughness PNG (per object)<br>◆ mesh decimation 삽입 지점 (task 1)</span></div></div>
 <div class="down">↓</div>
 <div class="row">
   <div class="box mod"><b>optical-class 분류</b><span class="f">material_policy: metal/glass/diffuse → BSDF strategy</span></div>
   <span class="arrow">→</span>
   <div class="box mod"><b>scene_manifest.json</b><span class="f">units[]: polys·material_slots·optical_class·baked_normal</span></div></div>
 <div class="down">↓</div>
 <div class="row">
   <div class="box mod"><b>authoring_map / nav_graph</b><span class="f">navigation_dataset: camera_rig·viewpoint graph·episode</span></div>
   <span class="arrow">→</span>
   <div class="box mod"><b>render_scene.xml</b><span class="f">540 obj shape → mesh_cache 해시 dedup + shared_bsdf</span></div></div>
</div>
<p class="mut">◆ = 미래 mesh-decimation 단계는 <b>texture bake와 같은 per-object 루프</b>에 붙는다(같은 시점에 메시가 손에 있음).
정책 미정이므로 <code>decimate(mesh, budget)</code> 인터페이스로 추상화하여 이 모듈만 교체·발전시킨다(현재 semantic LOD 예산은
render_scene.xml 사후 단계에서 동작 — import 단계로 당기면 mesh_cache가 처음부터 경량화된다).</p>
"""


def main() -> int:
    b = _band(); l = _lod(); n = _nir()
    nir_rows = "".join(f"<tr><td>{k}</td><td class=num>{v}</td></tr>" for k, v in n["ex"].items())
    svg = (REPO / "dev_report/images/import_graph/import_flow.svg").read_text()
    svg = svg[svg.find("<svg"):]  # strip xml prolog so it inlines cleanly
    html = f"""<!doctype html><html lang=ko><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>성능 개선 종합 · 2026-07-29</title><style>{CSS}</style></head>
<body><div class=wrap>
<h1>성능 개선 종합 — 단일 스펙트럴-편광 씬 통합 · mesh decimation · NIR albedo</h1>
<p class=sub>2026-07-29 · OpticalNav 렌더 파이프라인의 메모리·시간·자산 개선을 하나로. 편광 파이프라인은
<a href="report_polar_qualify.html">적합성 게이트</a> PASS, 디버그는 <a href="report_debug_render.html">rig-faithful 디버그 렌더</a>로 검증.</p>

<h2>1 · 모달리티 통합 — 모달리티별 재로드 → 단일 스펙트럴-편광 씬</h2>
<p class=mut>원 동기: 예전에는 modality(RGB/NIR/편광)를 바꿀 때마다 <b>씬을 clean하고 재로드</b>해 IO 병목이었고, 두 모달리티 씬을
<b>동시 resident</b>로 두면 VRAM을 초과했다. 이제 하나의 <code>cuda_ad_rgb_polarized</code> 씬이 blendbsdf <b>band-flip</b>으로
가시광·NIR·편광을 모두 낸다 — 한 번 로드, 스펙트럼 전환은 params.update 한 번.</p>
<table><tr><th>방식</th><th>씬 로드</th><th>스펙트럼 전환</th><th>총 wall</th><th>VRAM</th><th>결과</th></tr>
<tr><td><b>통합 씬 (band-flip)</b></td><td class=num>1회 ({b['new_load']:.0f}s)</td><td class=num>{b['new_flip_ms']:.0f} ms</td>
  <td class=num>{b['new_wall']:.0f}s</td><td class=num>{b['new_mib']:,} MiB</td><td class=ok>✓ 최적</td></tr>
<tr><td>모달리티별 재로드 (old)</td><td class=num>{b['reload_loads']}회 재로드</td><td class=num>= 재로드</td>
  <td class=num>{b['reload_wall']:.0f}s</td><td class=num>{b['reload_mib']:,} MiB</td><td class=xx>IO 병목 ({b['speedup']}× 느림)</td></tr>
<tr><td>두 모달리티 씬 동시 resident (old)</td><td class=num>2회</td><td class=num>—</td>
  <td class=num>—</td><td class=num>~{b['res_needed']:,} MiB</td><td class=xx>VRAM 초과 → thrash 실패</td></tr></table>
<div class=note><b>이득.</b> 스펙트럼 전환이 <b>{b['new_load']:.0f}s 재로드 → {b['new_flip_ms']:.0f}ms band-flip</b>으로,
전체 sweep은 <b>{b['speedup']}× 빨라지고</b> IO 병목이 사라진다. 단일 footprint({b['new_mib']:,} MiB)라 이중-resident({b['res_needed']:,} MiB &gt; 32,607 VRAM) OOM도 회피.</div>

<h2>2 · Mesh decimation — semantic-topology LOD 예산</h2>
<p class=mut>고폴리 Infinigen 씬(infinigen_kr_20260625)을 appearance-contract·per-slot·topology veto로 압축.
<a href="report_2026-07-29_semantic_lod.html">상세 리포트</a>.</p>
<div class=note><span class=big>{SCENE_POLYS:,} → {l['scene_lod']:,} polys (−{l['red']}%)</span>
&nbsp; full vs LOD 실측: peak GPU <b>+{l['full_mib']:,} → +{l['lod_mib']:,} MiB (−{l['mem_pct']:.0f}%)</b>,
scene load <b>{l['full_load']:.0f}s → {l['lod_load']:.0f}s ({l['load_x']}×)</b>, mean render 동일(sampler-bound), S0·DoLP parity 확인.</div>

<h2>3 · Infinigen import 파이프라인 — 모듈 연결 그래프</h2>
<p class=mut>.blend → render_scene.xml의 실제 2-stage 흐름. <b>Stage 1</b>은 Blender 프로세스(bpy)에서 메시·bake·manifest를 만들고,
<code>scene_manifest.json</code> 파일로 넘겨 <b>Stage 2</b>(robomituba env)가 authoring map·render_scene.xml을 짓는다.
mesh decimation(task 1)은 <b>bpy 메시가 손에 있는 Stage 1의 per-object 루프</b>(bake 직전, <code>_ensure_uv</code> 前)에 붙어야
OBJ·bake·GLB가 모두 경량 메시를 반영한다.</p>
<div style="overflow-x:auto;text-align:center;margin:10px 0">{svg}</div>
<p class=mut><b>✓ task 1 구현됨</b> — <code>tools/infinigen/mesh_decimation.py</code>: <code>DecimationPolicy</code> 프로토콜 +
<code>decimate_object(bpy_obj, policy, ctx)</code>. <code>blender_export_scene.py</code>의 per-object 루프(UV/OBJ/bake 前)에
<code>--decimate-policy</code>로 배선(기본 <code>none</code>=무변화). 정책은 <b>이 모듈에서만</b> 발전 — 현재 <code>none</code>·<code>ratio_threshold</code>
(optical/구조 보호)·<code>semantic_contract</code>(미정 stub, §2 semantic 예산이 들어올 자리). manifest에 <code>decimation</code>·<code>polys</code>(감축 후) 기록.
기존 render-path 훅은 <b>에디터 프리뷰용</b>(<code>_write_decimated_preview_obj</code>)뿐이었다.</p>

<h2>4 · NIR albedo 합성 — class→ρ₈₅₄ prior + spatial transfer, 1채널</h2>

<div class=note bad><b>왜 RGB에서 NIR을 만들 수 없나.</b> Infinigen 자산의 <code>base_color</code>는 가시광 <b>RGB 3-point</b>(R·G·B 세 표본)뿐이다.
근적외선 반사율은 <b>물리적으로 독립인 4번째 채널</b>이라 RGB로부터 함수적으로 복원할 수 없다 — 예: 초록 <b>잎</b>과 초록 <b>페인트</b>는
RGB에서 동일해 보이지만, 잎은 red-edge 때문에 NIR에서 밝고(ρ₈₅₄≈0.5) 페인트는 어둡다. 따라서 <code>NIR = f(RGB)</code>는 원천적으로 틀린 접근이다.</div>

<h3>3-tier 우선순위 (측정 → 라이브러리 → class prior)</h3>
<div class=graph><div class=row>
  <div class=box><b>① measured</b><span class=f>자산에 실측 NIR이 있으면 사용 (현재 거의 없음)</span></div><span class=arrow>→</span>
  <div class=box><b>② library</b><span class=f>동일 재질군의 공개 분광 라이브러리</span></div><span class=arrow>→</span>
  <div class=box hi><b>③ class prior ★ 구현</b><span class=f>physical class → ρ₈₅₄ 평균+분산 prior</span></div>
</div></div>
<p class=mut>물리-재질 분류: <code>physical_material_for(shader, optical_class)</code> → {n['n']}개 클래스 중 하나 (+confidence).
반사율 조회: <code>nir_reflectance(pmat, band)</code> → μ_c, spread. <code>configs/datasets/class_band_reflectance_v1.json</code>.</p>

<h3>spatial transfer — 절대 레벨은 물리, 공간 구조만 RGB에서</h3>
<div class=note>
<div style="font-size:16px;text-align:center;margin:6px 0"><b>ρ<sub>NIR</sub>(x) = clip[ μ<sub>c</sub> · ( 1 + α<sub>c</sub> · ( L(x) / median(L) − 1 ) ), 0, 0.95 ]</b></div>
<b>μ<sub>c</sub></b> = class NIR 평균 반사율(위 표) — <u>절대 밝기를 결정</u>. &nbsp;
<b>L(x)</b> = 픽셀의 가시광 luminance(구조/디테일). &nbsp;
<b>α<sub>c</sub></b> = <code>rgb_structure_weight</code> — RGB의 <u>상대 밝기 패턴(구조)만</u> 얼마나 반영할지. 색(hue)은 쓰지 않는다.
즉 나뭇결·얼룩 같은 <u>공간 텍스처는 RGB에서 빌려오되</u>, 그 위의 <u>NIR 절대 반사율은 물리 클래스</u>가 못박는다.
<code>synthesize_nir_texture(rgb_albedo_linear, pmat, band)</code>.
</div>
<table><tr><th>physical class</th><th>ρ₈₅₄ (mean)</th><th></th><th>physical class</th><th>ρ₈₅₄ (mean)</th></tr>
<tr><td>vegetation_leaf</td><td class=num>{n['ex'].get('vegetation_leaf','—')}</td><td></td><td>ceramic</td><td class=num>{n['ex'].get('ceramic','—')}</td></tr>
<tr><td>shell_calcite</td><td class=num>{n['ex'].get('shell_calcite','—')}</td><td></td><td>wood</td><td class=num>{n['ex'].get('wood','—')}</td></tr>
<tr><td>concrete</td><td class=num>{n['ex'].get('concrete','—')}</td><td></td><td>rubber</td><td class=num>{n['ex'].get('rubber','—')}</td></tr></table>

<h3>metal·glass 예외 + 1채널 렌더</h3>
<div class=note><b>금속·유리는 diffuse 반사율을 부여하지 않는다.</b> <code>nir_scalar_reflectance()</code>가 metal/glass에 <b>None</b>을 반환 →
가짜 diffuse ρ를 씌우지 않고 <b>Fresnel(dielectric / roughconductor) 경로</b>로 처리(편광과 일관). NIR band는 discrete-band 씬에서
<b>단일밴드 스펙트럼</b>으로 blendbsdf weight-flip 렌더되며, S0는 <b>3채널 RGB가 아니라 1채널 반사율 맵</b>이다 —
<a href="report_2026-07-28_polar_lod.html">polar-LOD 리포트</a>에서 선인장 몸통(0.52)/흙(0.30)이 물성별로 다른 명도의 단일채널로 렌더됨을 검증.</div>

<h2>5 · webui 렌더 옵션 노출 (task 3 ✓)</h2>
<p class=mut>위 개선을 데이터셋 편집기 렌더 설정(<code>RailSensorsTab.svelte</code>)에서 <b>체크박스 2개</b>로 토글:</p>
<table><tr><th>옵션</th><th>동작</th><th>배선</th></tr>
<tr><td><b>Unified spectral-polar scene</b></td><td>rgb/nir 패스도 rgb_polarized Stokes carrier로 → 단일 resident 씬(§1)</td>
  <td><code>RenderConfig.unified_spectral</code> → <code>_render_pass</code> kind override</td></tr>
<tr><td><b>Mesh LOD (decimated scene)</b></td><td>full 대신 <code>render_scene_lod.xml</code>(§2) 렌더</td>
  <td>daemon이 render_settings에서 pop → scene-ref 교체 (별도 캐시키)</td></tr></table>
<p class=mut>기본 off(미전송)이라 기존 렌더는 byte-동일 · stale worker 안전. 편집 파일: <code>+page.svelte</code>(state·payload) ·
<code>RailSensorsTab.svelte</code>(체크박스) · <code>multimodal.py</code>(RenderConfig·_render_pass) · <code>render_daemon.py</code>(scene 선택).</p>

<p class=mut style="margin-top:26px">데이터: <code>band_bench_2026-07-27/metrics.json</code> · <code>lod_compare_2026-07-28/result_*.json</code> ·
<code>class_band_reflectance_v1.json</code>. <b>task 1(§3 import decimation 모듈) · task 3(§5 webui 옵션) 완료.</b></p>
</div></body></html>"""
    OUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUT} ({len(html)/1024:.1f} KB) · band {b['speedup']}x · lod -{l['red']}% · nir {n['n']} classes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
