#!/usr/bin/env python3
"""Weekly dev report — Semantic-Topology-Aware LOD budgeting + full-vs-LOD render.

Reads:
  out/infinigen_imports/kr_20260625/semantic_lod_plan.json        (Phase A policy)
  <scene>/semantic_lod_shapes.json                                (decimation result)
  dev_report/images/lod_compare_2026-07-28/{result_full,result_lod,comparison}.json
  dev_report/images/lod_compare_2026-07-28/{full,lod}_vp*.npz     (panels)
Writes dev_report/report_2026-07-29_semantic_lod.html + renders RGB/DoLP panel PNGs.
"""
from __future__ import annotations
import json
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
SDIR = REPO / "out/opticalnav/opticalnav-v0.2/scenes/infinigen_kr_20260625"
IMG = REPO / "dev_report/images/lod_compare_2026-07-28"
OUT = REPO / "dev_report/report_2026-07-29_semantic_lod.html"
SCENE_POLYS = 27_136_473
_LUM = np.array([0.2126, 0.7152, 0.0722], np.float32)


def _tonemap(rgb):
    x = np.clip(rgb, 0, None); x = x / (1 + x)
    return (np.clip(x ** (1 / 2.2), 0, 1) * 255).astype(np.uint8)


def _redblack(dolp):
    d = np.clip(dolp, 0, 1)
    return np.stack([(d * 255).astype(np.uint8), np.zeros_like(d, np.uint8), np.zeros_like(d, np.uint8)], -1)


def _panels():
    """Render RGB (S0) + DoLP PNGs for each matched full/lod panel viewpoint."""
    from PIL import Image
    pairs = []
    for npz in sorted(IMG.glob("lod_vp*.npz")):
        vi = npz.stem.split("vp")[1]
        d = np.load(npz)
        Image.fromarray(_tonemap(np.nan_to_num(d["s0_rgb"]))).save(IMG / f"lod_vp{vi}_rgb.png")
        Image.fromarray(_redblack(np.nan_to_num(d["dolp"]))).save(IMG / f"lod_vp{vi}_dolp.png")
        full = IMG / f"full_vp{vi}.npz"
        if full.is_file():
            df = np.load(full)
            Image.fromarray(_tonemap(np.nan_to_num(df["s0_rgb"]))).save(IMG / f"full_vp{vi}_rgb.png")
            Image.fromarray(_redblack(np.nan_to_num(df["dolp"]))).save(IMG / f"full_vp{vi}_dolp.png")
        pairs.append((vi, full.is_file()))
    return pairs


def main() -> int:
    plan = json.loads((REPO / "out/infinigen_imports/kr_20260625/semantic_lod_plan.json").read_text())
    shapes = json.loads((SDIR / "semantic_lod_shapes.json").read_text())
    # correct scene-level accounting (per-shape orig is unreliable after cache-skip)
    hp_orig = plan["totals"]["highpoly_polys"]
    decimated_lod = shapes["lod_faces"]              # sum of decimated shape targets
    kept_lowpoly = SCENE_POLYS - hp_orig
    scene_lod = decimated_lod + kept_lowpoly
    reduction = round(100 * (1 - scene_lod / SCENE_POLYS), 1)

    comp = (IMG / "comparison.json")
    C = json.loads(comp.read_text()) if comp.is_file() else {}
    rl = (IMG / "result_lod.json"); rf = (IMG / "result_full.json")
    R_lod = json.loads(rl.read_text()) if rl.is_file() else {}
    R_full = json.loads(rf.read_text()) if rf.is_file() else {}
    pairs = _panels() if any(IMG.glob("*.npz")) else []

    # veto rollup from shape records
    from collections import Counter
    vcls = Counter(s["veto"]["contract"] for s in shapes["shape_records"] if s.get("veto"))

    def render_block():
        if not R_lod:
            return "<p class=mut>렌더 비교 대기 중.</p>"
        rows = ""
        def row(k, f, l, unit=""):
            return f"<tr><td>{k}</td><td class=num>{f}{unit}</td><td class=num>{l}{unit}</td></tr>"
        fmem = R_full.get("peak_over_baseline_mib", "—"); lmem = R_lod.get("peak_over_baseline_mib", "—")
        rows += row("scene load (s)", R_full.get("load_scene_s", "—"), R_lod.get("load_scene_s", "—"))
        rows += row("peak GPU mem (+MiB)", fmem, lmem)
        rows += row("mean render (s/vp)", R_full.get("mean_render_s", "—"), R_lod.get("mean_render_s", "—"))
        fd = R_full.get("error");
        note = ""
        if R_full.get("error"):
            note = f'<div class=note><b>full 씬 baseline:</b> <code>{R_full["error"]}</code> — 27M polys·1.5GB 단일 OBJ의 CIFS 로드/26GB VRAM가 실사용 한계를 넘는다(=LOD의 동기 자체). 알려진 값: ~26 GB VRAM.</div>'
        panels = ""
        for vi, has_full in pairs:
            fcol = (f'<td><img src="images/lod_compare_2026-07-28/full_vp{vi}_rgb.png"><div class=cap>full S0</div></td>'
                    f'<td><img src="images/lod_compare_2026-07-28/full_vp{vi}_dolp.png"><div class=cap>full DoLP</div></td>') if has_full else '<td colspan=2 class=mut>full 미실행</td>'
            panels += (f'<tr><td class=rl>vp{vi}</td>{fcol}'
                       f'<td><img src="images/lod_compare_2026-07-28/lod_vp{vi}_rgb.png"><div class=cap>LOD S0</div></td>'
                       f'<td><img src="images/lod_compare_2026-07-28/lod_vp{vi}_dolp.png"><div class=cap>LOD DoLP</div></td></tr>')
        return f"""{note}
<table><tr><th>지표</th><th>full (원본)</th><th>LOD</th></tr>{rows}</table>
<h3>매칭 뷰포인트 패널 (S0 · DoLP red-black)</h3>
<table class=pan>{panels}</table>"""

    urows = ""
    for u in sorted(plan["units"], key=lambda x: -x["polys"])[:14]:
        sl = "  ".join(f'{s["contract"].split("_")[0]}:{s["retained_ratio"]:.2f}' for s in u["slots"])
        urows += (f'<tr><td>{u["factory"].replace("Factory","")}</td><td class=num>{u["polys"]:,}</td>'
                  f'<td>{u["semantic_type"]}</td><td>{u["task_role"]}</td><td>{sl}</td>'
                  f'<td class=num>{u["target_fraction"]:.2f}</td></tr>')

    html = f"""<!doctype html><html lang=ko><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>Semantic LOD · 2026-07-29</title>
<style>
:root{{--bg:#0f1216;--fg:#e6e9ef;--mut:#9aa4b2;--line:#232a33;--ok:#39d98a;--acc:#6aa9ff;--warn:#ffcc66}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.65 -apple-system,"Segoe UI",Roboto,"Noto Sans KR",sans-serif}}
.wrap{{max-width:1080px;margin:0 auto;padding:40px 24px 80px}}h1{{font-size:25px;margin:0 0 6px}}
h2{{font-size:18px;margin:34px 0 8px;padding-top:14px;border-top:1px solid var(--line)}}h3{{font-size:14px;color:var(--acc);margin:16px 0 6px}}
.sub{{color:var(--mut);margin:0 0 20px}}code{{background:#1a1f26;padding:1px 6px;border-radius:4px;font-size:13px}}
table{{border-collapse:collapse;width:100%;margin:10px 0;font-size:13px}}th,td{{border:1px solid var(--line);padding:5px 8px;text-align:left}}
th{{background:#161b22;color:var(--mut)}}td.num{{text-align:right;font-variant-numeric:tabular-nums}}
.big{{font-size:34px;font-weight:800;color:var(--ok)}}.note{{background:#141920;border-left:3px solid var(--acc);padding:12px 16px;margin:14px 0;border-radius:0 8px 8px 0}}
.warn{{border-left-color:var(--warn)}}.mut{{color:var(--mut);font-size:12px}}.cap{{font-size:11px;color:var(--mut);text-align:center}}
.rl{{font-size:12px;text-align:right;color:var(--fg)}}table.pan img{{width:150px;border:1px solid var(--line);border-radius:3px;display:block;background:#000}}
</style></head><body><div class=wrap>
<h1>Semantic–Topology-Aware LOD Budgeting — infinigen_kr_20260625</h1>
<p class=sub>2026-07-29 · 압축 예산 = <b>오브젝트 삼각형 수가 아니라 시멘틱이 요구하는 외관 보존 조건(appearance contract) + 정규화 토폴로지 + task-role/projected-size</b>를
<b>material slot 단위</b>로. 편광 렌더 파이프라인은 사전 <a href="report_polar_qualify.html">적합성 게이트</a> PASS.</p>

<div class=note><div class=big>{SCENE_POLYS:,} → {scene_lod:,} polys &nbsp;(−{reduction}%)</div>
고폴리 60유닛(scene의 95%) {hp_orig:,} → {decimated_lod:,} · 저폴리 {kept_lowpoly:,} 유지.
render_scene.xml의 540 shape 중 <b>{shapes['shapes_swapped']}개</b>가 decimated 메시로 교체(<code>render_scene_lod.xml</code>).
transform·BSDF ref·material_policy는 불변 → <b>per-slot 재질 배치 자동 보존</b>.</div>

<h2>1 · 방법론 (contract 우선, per-slot)</h2>
<table><tr><th>appearance contract</th><th>보존 대상</th><th>prior</th><th>floor</th></tr>
<tr><td>compact_solid</td><td>전체 실루엣·큰 곡률 (조개·돌)</td><td class=num>10%</td><td class=num>3%</td></tr>
<tr><td>branched_identity</td><td>가지 수·분기 (산호)</td><td class=num>30%</td><td class=num>10%</td></tr>
<tr><td>organic_mass</td><td>전체 덩어리 (선인장·잎)</td><td class=num>3%</td><td class=num>1%</td></tr>
<tr><td>rigid_planar</td><td>직선·평면·모서리 (캐비닛)</td><td class=num>50%</td><td class=num>30%</td></tr>
<tr><td>optical_interface</td><td>곡면 법선·재질 경계·Fresnel (유리·금속 용기)</td><td class=num>30%</td><td class=num>10%</td></tr></table>
<p class=mut>보정: background_decoration +1 공격 · landmark −1 보수 · collision/target −2 · projected&lt;32px +1 · &gt;96px −1 ·
optical_eval_target(유리문·벽)은 optical slot ≥30% floor · low-confidence 한 단계 보존+review.</p>

<h2>2 · Phase A 정책 (manifest 메타데이터, 메시 I/O 0)</h2>
<p class=mut>semantic_type→task_role, optical_class+factory→contract, dimensions→projected proxy. 무거운 14유닛:</p>
<table><tr><th>factory</th><th>polys</th><th>semantic</th><th>task_role</th><th>slots (contract:r*)</th><th>F</th></tr>{urows}</table>

<h2>3 · Decimation (per-slot QEM, mesh_cache 한 번 로드)</h2>
<div class=note warn><b>trinket veto caveat.</b> NatureShelfTrinkets는 한 메시에 여러 소품이 뭉쳐 있어 connected-component 수가 커
대부분 <code>branched_identity</code>로 분류됨(veto: {dict(vcls)}). 결과적으로 floor <b>10%</b>로 보수적·안전하게 유지(−90%)했다.
component-수 휴리스틱이 "여러 개의 compact 조개 클러스터"를 "가지형 산호"와 혼동하는 한계가 있어, 다음 라운드에서
per-instance 분리 후 재분류하면 조개는 3%까지 더 줄일 여지가 있다.</div>
<p class=mut>예: 4M-face NatureShelfTrinkets → veto branched → 408,333 (10%). 대형 메시는 CIFS 스톨 회피 위해 로컬 복사 후 decimate.</p>

<h2>4 · full vs LOD 렌더 (cuda_ad_rgb_polarized · stokes)</h2>
{render_block()}

<p class=mut style="margin-top:24px">재현: <code>build_semantic_lod_plan.py</code> → <code>build_lod_scene.py</code> → <code>benchmark_lod_scene.py --mode compare</code> → 이 리포트.</p>
</div></body></html>"""
    OUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUT} ({len(html)/1024:.1f} KB) · scene {SCENE_POLYS:,}->{scene_lod:,} (-{reduction}%) · panels {len(pairs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
