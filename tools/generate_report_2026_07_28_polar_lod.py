#!/usr/bin/env python3
"""2026-07-28 results report: single-object polarization vs mesh LOD.

Renders each representative Infinigen prop across mesh LOD levels under active
polarized lighting and shows the full modality set (RGB · NIR · DoLP · AoLP ·
S1/S0 · S2/S0) side-by-side so the polarization degradation can be judged by eye,
alongside the numeric fidelity vs the Monte-Carlo noise floor.

Reads  dev_report/images/polar_lod_2026-07-28/metrics.json (+ panel PNGs)
Writes dev_report/report_2026-07-28_polar_lod.html
"""
from __future__ import annotations
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
IMG_REL = "images/polar_lod_2026-07-28"
IMG_DIR = REPO / "dev_report" / IMG_REL
OUT = REPO / "dev_report" / "report_2026-07-28_polar_lod.html"
PANEL_LIGHT = "az65_p0"
MODS = [("rgb", "S0 (RGB)"), ("dolp", "DoLP"), ("aolp", "AoLP"),
        ("s1s0", "S1/S0"), ("s2s0", "S2/S0")]
# User's by-eye polarization-quality budgets (visual judgment; can differ from the
# auto IoU/ΔDoLP budget). {key: (safe_lod, note)}.
EYEBALL_BUDGET = {
    "trinket_0p5M_a": ("10%", "1%에서 표면이 깨짐"),
    "plant_metal": ("1%", "1%까지 형태 유지"),
    "plant_glass": ("10%", "10%까지 유리 반사 유지"),
}
ASSET_LABEL = {
    "trinket_4M": "산호 trinket 4.08M (diffuse · 가지형)",
    "trinket_0p5M_a": "조개 trinket 0.53M · A (diffuse · blob)",
    "trinket_0p5M_b": "조개 trinket 0.53M · B (diffuse · blob)",
    "plant_metal": "선인장 in 금속화분 (multi-material · slot별 렌더: 화분=metal, 선인장·가시·흙=diffuse)",
    "plant_glass": "버섯 in 유리병 (multi-material · slot별 렌더: 병=glass, 버섯·모래=diffuse)",
    "cabinet_ctrl": "캐비닛 대조군 (diffuse · 얇은 판)",
}

CSS = """
:root { --bg:#0f1216; --fg:#e6e9ef; --mut:#9aa4b2; --line:#232a33; --ok:#39d98a; --bad:#ff6b6b; --acc:#6aa9ff; --warn:#ffcc66; }
*{box-sizing:border-box;} body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.6 -apple-system,"Segoe UI",Roboto,"Noto Sans KR",sans-serif;}
.wrap{max-width:1180px;margin:0 auto;padding:40px 24px 80px;}
h1{font-size:25px;margin:0 0 6px;} h2{font-size:20px;margin:40px 0 10px;padding-top:16px;border-top:1px solid var(--line);}
h3{font-size:15px;margin:18px 0 6px;color:var(--acc);}
.sub{color:var(--mut);margin:0 0 24px;} p{margin:9px 0;} a{color:var(--acc);}
code{background:#1a1f26;padding:1px 6px;border-radius:4px;font-size:13px;}
table{border-collapse:collapse;width:100%;margin:12px 0;font-size:13.5px;}
th,td{border:1px solid var(--line);padding:6px 9px;text-align:left;} th{background:#161b22;color:var(--mut);}
td.num{text-align:right;font-variant-numeric:tabular-nums;}
.note{background:#141920;border-left:3px solid var(--acc);padding:12px 16px;margin:14px 0;border-radius:0 8px 8px 0;}
.warn{border-left-color:var(--warn);} .good{border-left-color:var(--ok);}
.grid{display:grid;gap:4px;margin:6px 0;overflow-x:auto;}
.grid img{width:100%;border:1px solid var(--line);border-radius:3px;display:block;background:#000;image-rendering:auto;}
.cap{font-size:11px;color:var(--mut);text-align:center;padding:2px;}
.rowlab{font-size:12px;color:var(--fg);display:flex;align-items:center;justify-content:flex-end;padding-right:8px;}
.ok{color:var(--ok);} .bad{color:var(--bad);} .acc{color:var(--acc);}
.legend{font-size:12px;color:var(--mut);margin:6px 0;}
.sw{display:inline-block;width:46px;height:9px;border-radius:2px;vertical-align:middle;margin:0 4px;}
.mut{color:var(--mut);font-size:12px;}
"""


def img_grid(key, band_short, lods_imaged, faces_by_lod):
    # transposed layout: rows = LOD levels, columns = the 5 modalities.
    def _mod_name(mod_key, mod_name):
        # NIR band: S0 is a single-channel class-prior NIR reflectance map, not RGB
        return "NIR S0 (1채널)" if (mod_key == "rgb" and band_short == "nir") else mod_name
    cells = f'<div class="grid" style="grid-template-columns:110px repeat({len(MODS)},1fr)">'
    # header row: modality labels
    cells += '<div class="rowlab"></div>'
    for mod_key, mod_name in MODS:
        cells += f'<div class="cap">{_mod_name(mod_key, mod_name)}</div>'
    for lab in lods_imaged:
        f = faces_by_lod.get(lab, "")
        lodlab = f'{lab}<br><span class="mut">{f:,} tri</span>' if isinstance(f, int) else lab
        cells += f'<div class="rowlab">{lodlab}</div>'
        for mod_key, mod_name in MODS:
            src = f"{IMG_REL}/{key}_{band_short}_{lab}_{mod_key}.png"
            cells += f'<div><img src="{src}" alt="{_mod_name(mod_key, mod_name)} {lab}"></div>'
    cells += "</div>"
    return cells


def _asset_id(key, e):
    aid = e.get("asset_id")
    if aid:
        return aid
    try:
        import sys
        sys.path.insert(0, str(REPO / "tools"))
        from single_object_polar_lod import ASSETS
        return Path(ASSETS[key]["mesh"]).stem
    except Exception:
        return key


def main() -> int:
    M = json.loads((IMG_DIR / "metrics.json").read_text())
    spp = M.get("spp")
    assets = M["assets"]
    order = [k for k in ASSET_LABEL if k in assets]

    sections = ""
    summary_rows = ""
    for key in order:
        e = assets[key]
        pl = e.get("panel_lods") or {}
        imaged = pl.get("lods_imaged", [])
        faces_by_lod = {}
        for r in e["lods"]:
            faces_by_lod[r["lod"]] = r["faces"]
        # per-object safe compression budget: most-compressed LOD (coarsening) that
        # still meets IoU>=0.7 AND dDoLP<=max(2*noise,0.01), monotone. visible/az65.
        floor_v = e.get("noise_floor", {}).get(f"visible_{PANEL_LIGHT}", {}).get("dDoLP", 0.0)
        thr = max(2 * floor_v, 0.01)
        vrecs = [r for r in e["lods"] if r["band"] == "visible" and r["light"] == PANEL_LIGHT and r["lod"] != "orig"]
        safe = None
        for r in vrecs:  # 30% -> 1% coarsening
            if r["silhouette_iou"] >= 0.7 and r["dDoLP"] <= thr:
                safe = r
            else:
                break
        if safe is None:
            budget_pct, budget_faces, vcls, vlabel = 100, e["orig_tris"], "bad", "압축 불가 (thin/foliage)"
        else:
            budget_pct = int(str(safe["lod"]).replace("pct", ""))
            budget_faces = safe["faces"]
            vcls = "ok" if budget_pct <= 3 else "warn"
            vlabel = f"~{budget_pct}%까지 안전"
        e["_verdict"] = (vlabel, vcls)
        e["_ref_iou"] = safe["silhouette_iou"] if safe else (vrecs[0]["silhouette_iou"] if vrecs else 0)
        eye = EYEBALL_BUDGET.get(key)
        if eye:
            eye_pct = int(str(eye[0]).replace("%", ""))
            agree = "≈" if abs(eye_pct - budget_pct) <= 1 else ("↑아그레시브" if eye_pct < budget_pct else "↓보수적")
            eye_cell = f'<td class="acc">{eye[0]} <span class="mut">({eye[1]}; 계산대비 {agree})</span></td>'
        else:
            eye_cell = '<td class="mut">—</td>'
        summary_rows += (
            f'<tr><td>{ASSET_LABEL[key]}<br><span class="mut" style="font-size:11px">{_asset_id(key, e)}</span></td>'
            f'<td class="num">{e["orig_tris"]:,}</td>'
            f'<td class="num {vcls}">{budget_pct}% ({budget_faces:,} tri)</td>'
            f'<td class="num">≤{thr:.3f}</td>'
            f'<td class="{vcls}">{vlabel}</td>'
            f'{eye_cell}</tr>')
        # fidelity table (panel light, both bands)
        rows = ""
        nf = e.get("noise_floor", {})
        for band in ("visible", "nir_854"):
            floor = nf.get(f"{band}_{PANEL_LIGHT}", {}).get("dDoLP", 0.0)
            recs = [r for r in e["lods"] if r["band"] == band and r["light"] == PANEL_LIGHT]
            for r in recs:
                if r["lod"] == "orig":
                    continue
                ok = r["dDoLP"] <= max(floor * 1.5, 1e-4)
                rows += (
                    f'<tr><td>{band.replace("_854","")}</td><td>{r["lod"]}</td>'
                    f'<td class="num">{r["faces"]:,}</td>'
                    f'<td class="num">{r["dDoLP"]:.4f}</td>'
                    f'<td class="num">{r["dAoLP_deg"]:.1f}°</td>'
                    f'<td class="num">{r["dS1S0"]:.4f}</td>'
                    f'<td class="num">{r["rel_dS0"]*100:.1f}%</td>'
                    f'<td class="num">{r["silhouette_iou"]:.3f}</td>'
                    f'<td class="{"ok" if ok else "bad"}">{"≤noise" if ok else "＞noise"}</td></tr>')
            rows += (f'<tr><td colspan="3" class="mut">{band.replace("_854","")} 노이즈 바닥 (원본 2-seed)</td>'
                     f'<td class="num mut">{floor:.4f}</td><td colspan="5" class="mut"></td></tr>')

        grids = ""
        for band, bs in (("visible", "vis"), ("nir_854", "nir")):
            grids += f'<h3>{band.replace("_854"," 854")} band</h3>' + img_grid(key, bs, imaged, faces_by_lod)

        _vl, _vc = e["_verdict"]
        slot_html = ""
        if e.get("slots"):
            def _slot_nir(s):
                r = s.get("nir854")
                return f", ρ854={r:.2f}" if isinstance(r, (int, float)) else ", NIR=Fresnel"
            parts = " · ".join(
                f'<code>{s["matname"]}</code> ({s["cls"]}, {s["faces"]:,} tri{_slot_nir(s)})'
                for s in e["slots"])
            metal_tri = sum(s["faces"] for s in e["slots"] if s["cls"] in ("glass", "metal_aluminum", "metal", "mirror"))
            tot_tri = sum(s["faces"] for s in e["slots"]) or 1
            container_pct = 100.0 * metal_tri / tot_tri
            slot_html = (
                f'<p class="mut">material_slots (slot별 렌더 · NIR ρ854): {parts}</p>'
                f'<div class="note good" style="margin:8px 0"><strong>무엇을 고쳤나.</strong> 유닛 optical_class는 '
                f'<em>용기</em>({e["cls"]}) 재질이라, 이전엔 메시 전체를 그 BSDF 하나로 렌더했다 — 용기는 전체 삼각형의 '
                f'<strong>{container_pct:.1f}%</strong>뿐이고 나머지 <strong>{100-container_pct:.1f}%</strong>(식생·흙·모래)가 '
                f'잘못 {e["cls"]}로 칠해졌다. 수정: OBJ의 <code>usemtl</code> 그룹을 manifest <code>material_slots</code>의 '
                f'per-slot optical_class로 분리해 slot마다 올바른 BSDF(glass→dielectric, metal→roughconductor Al, '
                f'diffuse→pplastic)로 렌더한다.</div>')
        elif e.get("shader"):
            _r = e.get("nir854")
            _rtxt = f"{_r:.2f}" if isinstance(_r, (int, float)) else "—"
            slot_html = (f'<p class="mut">shader <code>{e["shader"]}</code> · NIR ρ854 = '
                         f'<strong>{_rtxt}</strong> (class-prior, single-channel)</p>')
        sections += f"""
<h2>{ASSET_LABEL[key]} &nbsp;<span class="{_vc}" style="font-size:14px">[{_vl}]</span></h2>
<p class="mut">asset id <code>{_asset_id(key, e)}</code></p>
<p class="mut">원본 {e['orig_tris']:,} 삼각형 · optical_class <code>{e['cls']}</code> · 이미지 LOD {', '.join(imaged)} · 조명 {PANEL_LIGHT}</p>
{slot_html}
{grids}
<h3>수치 — LOD별 편광 오차 (원본 대비, 조명 {PANEL_LIGHT})</h3>
<div style="overflow-x:auto"><table>
<tr><th>band</th><th>LOD</th><th>faces</th><th>ΔDoLP</th><th>ΔAoLP</th><th>ΔS1/S0</th><th>rel ΔS0</th><th>silhouette IoU</th><th>판정</th></tr>
{rows}
</table></div>
"""

    failed = M.get("failed", {})
    failed_html = ""
    if failed:
        failed_html = '<div class="note warn"><strong>실패한 자산:</strong> ' + \
            ", ".join(f"{k} ({v[:60]})" for k, v in failed.items()) + "</div>"

    # Tier-1 (geometry, GPU-free) vs Tier-2 (render) calibration
    calib_html = ""
    bp = IMG_DIR / "lod_budget.json"
    if bp.is_file():
        gres = json.loads(bp.read_text()).get("results", {})
        crows = ""
        for key in order:
            g = gres.get(key)
            e = assets.get(key)
            if not g or not e:
                continue
            t2 = [r for r in e["lods"] if r["band"] == "visible" and r["light"] == PANEL_LIGHT and r["lod"] == "10pct"]
            iou = t2[0]["silhouette_iou"] if t2 else None
            crows += (f'<tr><td>{ASSET_LABEL[key]}</td>'
                      f'<td class="num">{g["safe_frac"]*100:.1f}%</td>'
                      f'<td>{g["verdict"]}</td>'
                      f'<td class="num">{("%.2f"%iou) if iou is not None else "-"}</td>'
                      f'<td class="num">{e["_verdict"][0]}</td></tr>')
        calib_html = f"""
<h2>Tier-1 (지오메트리, 렌더 불필요) vs Tier-2 (렌더) 보정</h2>
<p>안전 예산 분석 체계의 핵심은 <strong>렌더 없이 지오메트리만으로 예산을 예측</strong>(Tier-1)해 60개+ 전체에
확장하고, 대표 소수를 렌더(Tier-2)로 보정하는 것이다. Tier-1은 면적가중 Fresnel-DoLP proxy + chamfer + 표면적
보존으로 압축률별 품질을 추정한다.</p>
<div class="scroll"><table>
<tr><th>자산</th><th>Tier-1 안전예산 (지오메트리)</th><th>Tier-1 판정</th><th>Tier-2 IoU@10%</th><th>Tier-2 예산</th></tr>
{crows}
</table></div>
<div class="note">
<p><strong>방향은 전부 일치</strong>(조개=공격적, 산호=~30%, 화분=취약). <strong>산호는 정량까지 일치</strong>(둘 다 ~30%).
두 tier가 갈리는 곳이 오히려 유용하다 — <strong>캐비닛</strong>은 Tier-1이 압축 가능(평면), Tier-2 렌더 IoU는 0.56으로
불가라는데, 얇고 어두운 물체라 S0 마스크가 노이즈다 → <strong>Tier-1이 더 신뢰</strong>. 화분은 Tier-1이 낙관적 →
얇은구조 페널티(표면적/두께) 보강 여지. 즉 Tier-1 지오메트리 예측이 유효하며, 렌더는 보정·검증용이다.</p>
</div>"""

    html = f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>단일 오브젝트 편광 vs 메시 LOD — 결과 · 2026-07-28</title>
<style>{CSS}</style></head><body><div class="wrap">

<h1>단일 오브젝트 편광 렌더 vs 메시 LOD — 육안 판단용 결과</h1>
<p class="sub">2026-07-28 · discrete-band <code>cuda_ad_rgb_polarized</code> · spp&nbsp;{spp} · 능동 편광조명(area+polarizer) ·
계획: <a href="report_2026-07-28_mesh_opt_plan.html">mesh_opt_plan</a></p>

<div class="note">
<strong>보는 법.</strong> 각 자산을 원본 고밀도 → 중간 → 최저폴리로 decimate하며 <strong>RGB · DoLP · AoLP · S1/S0 · S2/S0</strong>를
visible/NIR 두 밴드로 렌더했다. <strong>visible S0 열은 실제 3채널 컬러</strong>(Stokes S0의 R/G/B, 톤맵)이며 — 단일재질 자산은
gray placeholder(pplastic ρ0.5)라 무채색으로 보이는 게 정상이고, 다중재질 화분은 slot별 diffuse albedo로 컬러가 보인다.
<strong>NIR S0 열은 실제 1채널 반사율 맵</strong>이다 — 각 재질 slot이 class-prior NIR 반사율(ρ854; 식생≈0.52·흙≈0.30·
모래≈0.30·조개/산호≈0.66·나무≈0.50)로 칠해져 <strong>slot마다 다른 회색</strong>으로 나온다(metal/glass은 Fresnel). NIR은 RGB에서
유도하지 않는 독립 채널이다. 열을 가로질러 각 모달리티가 <strong>얼마나 무너지는지 눈으로</strong> 보고,
아래 표에서 <strong>원본 2-seed 노이즈 바닥</strong> 대비 오차가 그 이하(≤noise)면 주행 데이터로는 사실상 구분 불가로 판정한다.
</div>

<div class="note good">
<strong>결론 (한 눈에).</strong> 최적화 가능성은 소품 종류가 아니라 <strong>토폴로지</strong>가 가른다 —
<strong>안전 압축 예산이 오브젝트마다 60배 넘게 다르다.</strong>
<span class="ok">solid blob</span>(조개)은 원본의 <strong>~1%</strong>까지 줄여도 편광 보존,
<span class="warn">가지형</span>(산호)은 <strong>~10–30%</strong>가 한계(408K에서 IoU 0.65),
<span class="bad">thin foliage</span>(다육 가시·잎 화분)는 <strong>30%도 불가</strong>(형상=외관).
그래서 절대 삼각형 수(예: 일괄 12K)가 아니라 <strong>오브젝트별 비율 예산</strong>이 필요하다 —
같은 12K도 조개엔 과하고(2.3%) 산호엔 파괴적(0.3%)이다.
<strong>같은 NatureShelfTrinkets 안에서도 조개(blob)는 안전, 산호(가지형)는 파괴</strong> — 팩토리 일괄 LOD는 위험하다.
</div>
<div style="overflow-x:auto"><table>
<tr><th>자산</th><th>원본 tris</th><th>안전 압축 예산 (IoU≥0.7 &amp; ΔDoLP≤임계)</th><th>ΔDoLP 임계</th><th>계산 판정</th><th>육안 판정 (사용자)</th></tr>
{summary_rows}
</table></div>
<div class="note">
<strong>육안 판정 vs 계산 예산.</strong> 사용자가 렌더 패널을 직접 보고 매긴 안전 압축률을 계산값(IoU/ΔDoLP) 옆에 병기했다 —
둘은 종종 갈린다. <strong>조개(trinket_0p5M_a)</strong>: 계산은 ~1%까지 안전이라지만 육안은 <strong>10%</strong>가 한계(1%에서 표면이 깨져 보임) →
사용자가 더 보수적. <strong>선인장 금속화분(plant_metal)</strong>: 계산은 silhouette IoU가 30%에서 이미 무너져 "압축 불가"인데,
육안은 <strong>1%까지 OK</strong> — 퍼지한 가시덩어리는 실루엣 IoU가 낮아도 "선인장처럼" 보여서, thin-foliage에는 IoU 마스크가
지나치게 가혹함을 시사. <strong>버섯 유리병(plant_glass)</strong>: 계산은 ~30%(10%에서 ΔDoLP가 임계 초과), 육안은 <strong>10%</strong> →
사용자가 더 공격적. 즉 IoU/ΔDoLP 자동예산은 <em>보수적 하한</em>으로, 최종 예산은 육안 검수와 병행해야 한다.
</div>
<div class="note good">
<strong>다중재질 — slot별 렌더로 수정됨 (2026-07-28).</strong> "선인장/버섯 화분"은 <strong>다중재질 유닛</strong>이다 — 유닛
optical_class(metal/glass)는 <em>용기</em> 재질일 뿐, 삼각형의 대부분은 <code>diffuse</code> 식생이다(선인장 984K·가시 1.0M·흙
381K vs 금속화분 66K; 버섯 1.2M·모래 586K vs 유리병 90K). 이전 버전은 유닛 전체를 <strong>단일 재질(용기 클래스)</strong>로
렌더해 "선인장 전체가 금속, 버섯 전체가 유리"로 물리적으로 틀렸다. 이번 판은 OBJ의 <code>usemtl</code> 그룹을
<code>material_slots</code>의 per-slot optical_class로 분리해 <strong>slot마다 올바른 BSDF</strong>(glass→dielectric, metal→roughconductor
Al, diffuse→pplastic)로 렌더한다 — 그래서 <strong>선인장·가시·버섯·모래는 diffuse, 용기만 metal/glass</strong>다. S0(RGB) 열에서 이제
선인장이 녹색 diffuse, 화분만 금속으로 보인다. LOD는 slot별로 동일 비율 decimate한다.
<span class="mut">주의: diffuse slot의 albedo 색상(선인장=녹색 등)은 S0 가독성을 위한 <em>예시값</em>이며 편광신호(pplastic 코트 Fresnel)의
정성적 결론에는 영향이 없다. 얇은구조(가시·잎)는 재질과 무관하게 decimation에 붕괴하므로 압축-예산 결론은 그대로 유지된다.</span>
</div>
{calib_html}
<p class="legend">
DoLP <span class="sw" style="background:linear-gradient(90deg,#000,#990000,#ff4d38)"></span> 0–자산별vmax (검정=무편광, 빨강=고편광) ·
AoLP <span class="sw" style="background:linear-gradient(90deg,red,#ff0,#0f0,#0ff,#00f,#f0f,red)"></span> 방위각(색), 밝기=DoLP ·
S1/S0·S2/S0 <span class="sw" style="background:linear-gradient(90deg,#3b4cbf,#fff,#bf2626)"></span> −1…+1
</p>
{failed_html}
{sections}

<h2>메모</h2>
<ul>
<li>재질은 optical_class로 편광 트리오 주입(glass→smooth <code>dielectric</code>, metal→<code>roughconductor</code> Al, diffuse→<code>pplastic</code>).</li>
<li><strong>NIR ρ854 = class-prior 합성값</strong>(<code>modules/mitsuba_converter/nir_reflectance.py</code> +
<code>configs/datasets/class_band_reflectance_v1.json</code>). diffuse slot은 shader/optical_class → physical_material
클래스 평균 NIR 반사율을 <em>uniform scalar</em>로 주입(그래서 NIR S0가 1채널)하고, metal/glass은 diffuse가 아니라 Fresnel(eta·k@854 /
dielectric) 경로를 쓴다 — NIR을 RGB에서 유도하지 않는다. <strong>주의: ρ854 값은 물리적으로 추론한 class prior이며 측정
provenance(Stage-1)는 미완이다</strong> — 절대 NIR 밝기의 정량 결론에는 쓰지 말 것.</li>
<li>단일 오브젝트를 0.3&nbsp;m로 정규화해 근접 프레이밍 — 주행 거리(투영 수십 px)에서는 sub-pixel 평균으로 편광 차이가 더 줄어든다(별도 scene A/B에서 검증 예정).</li>
<li>노멀맵 베이크 변형(C)은 미포함 — 여기서는 <strong>단순 decimation(B)</strong>만으로 편광이 얼마나 보존되는지를 본다.</li>
<li><strong>메시 LOD 알고리즘</strong>: quadric error metric decimation (QEM, Garland–Heckbert 1997). 구현은
<code>trimesh 4.4.1</code>의 <code>simplify_quadric_decimation()</code> → 백엔드 <code>Open3D 0.18.0</code>
(<code>open3d.geometry.TriangleMesh.simplify_quadric_decimation</code>). 다중재질 자산은 slot(usemtl)별로 각각 같은 비율로 decimate.
(<code>fast_simplification 0.1.13</code>도 설치돼 있으나 trimesh 4.4.1은 Open3D 경로를 사용.)</li>
</ul>
<p class="mut">재현: <code>tools/single_object_polar_lod.py</code> → <code>tools/generate_report_2026_07_28_polar_lod.py</code>.</p>
</div></body></html>
"""
    OUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUT}  ({len(html)/1024:.1f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
