#!/usr/bin/env python3
"""Report for the Semantic-Topology-Aware LOD budget plan.
Reads out/infinigen_imports/<scene>/semantic_lod_plan.json -> dev_report/report_semantic_lod.html
"""
from __future__ import annotations
import argparse
import json
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CSS = """
:root{--bg:#0f1216;--fg:#e6e9ef;--mut:#9aa4b2;--line:#232a33;--ok:#39d98a;--bad:#ff6b6b;--warn:#ffcc66;--acc:#6aa9ff;}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.6 -apple-system,"Segoe UI",Roboto,"Noto Sans KR",sans-serif}
.wrap{max-width:1100px;margin:0 auto;padding:40px 24px 80px}h1{font-size:25px;margin:0 0 6px}
h2{font-size:18px;margin:32px 0 8px;padding-top:14px;border-top:1px solid var(--line)}
.sub{color:var(--mut);margin:0 0 20px}code{background:#1a1f26;padding:1px 6px;border-radius:4px;font-size:13px}
table{border-collapse:collapse;width:100%;margin:10px 0;font-size:13px}th,td{border:1px solid var(--line);padding:5px 8px;text-align:left}
th{background:#161b22;color:var(--mut)}td.num{text-align:right;font-variant-numeric:tabular-nums}
.big{font-size:34px;font-weight:800;color:var(--ok)}.note{background:#141920;border-left:3px solid var(--acc);padding:12px 16px;margin:14px 0;border-radius:0 8px 8px 0}
.pill{display:inline-block;padding:1px 8px;border-radius:999px;font-size:11px;font-weight:700}
.c-optical_interface{background:rgba(106,169,255,.18);color:#9cc4ff}.c-rigid_planar{background:rgba(255,204,102,.18);color:var(--warn)}
.c-branched_identity{background:rgba(57,217,138,.18);color:var(--ok)}.c-compact_solid{background:rgba(200,200,210,.14);color:#cfd6e0}
.c-organic_mass{background:rgba(160,120,220,.20);color:#c8a8f0}.c-task_critical{background:rgba(255,107,107,.18);color:var(--bad)}
.rev{color:var(--warn);font-weight:700}.mut{color:var(--mut);font-size:12px}
.bar{height:8px;border-radius:4px;background:linear-gradient(90deg,var(--ok),var(--warn));display:inline-block;vertical-align:middle}
"""


def pill(c): return f'<span class="pill c-{c}">{c}</span>'


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--scene", default="kr_20260625"); a = ap.parse_args()
    P = json.loads((REPO / "out/infinigen_imports" / a.scene / "semantic_lod_plan.json").read_text())
    t = P["totals"]
    phase = P.get("phase", "")
    # factory rollup
    agg = defaultdict(lambda: [0, 0, 0.0, 0])
    for u in P["units"]:
        r = agg[u["factory"]]; r[0] += 1; r[1] += u["polys"]; r[2] += u["target_fraction"] * u["polys"]; r[3] += int(u["review"])
    frows = ""
    for f, (n, pol, kept, rev) in sorted(agg.items(), key=lambda kv: -kv[1][1]):
        frows += (f"<tr><td>{f}</td><td class=num>{n}</td><td class=num>{pol:,}</td>"
                  f"<td class=num>{kept/pol*100:.1f}%</td><td class=num>{round(kept):,}</td>"
                  f"<td class=num>{rev or ''}</td></tr>")
    # per-unit detail (heaviest first)
    urows = ""
    for u in sorted(P["units"], key=lambda x: -x["polys"]):
        slots = "".join(
            f'<div style="margin:1px 0">{pill(s["contract"])} '
            f'<span class="mut">{s["optical_class"]}</span> '
            f'<b>r*={s["retained_ratio"]:.2f}</b> '
            f'<span class="mut">{s.get("confidence","")}</span></div>'
            for s in u["slots"])
        rev = '<span class="rev">● review</span>' if u["review"] else ''
        urows += (f'<tr><td>{u["object_id"].split("_.")[0]}<div class=mut>{u["semantic_type"]} · '
                  f'{"baked" if u["baked_normal"] else "pure-geo"}</div></td>'
                  f'<td class=num>{u["polys"]:,}</td><td>{u["task_role"]}</td>'
                  f'<td>{slots}</td><td class=num>{u["target_fraction"]:.3f}</td><td>{rev}</td></tr>')

    html = f"""<!doctype html><html lang=ko><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Semantic–Topology LOD Budget · {P.get('scene_id')}</title><style>{CSS}</style></head><body><div class=wrap>
<h1>Semantic–Topology-Aware LOD Budget — {P.get('scene_id')}</h1>
<p class=sub>Phase: <code>{phase}</code> · 압축 예산은 <b>오브젝트 삼각형 수가 아니라 시멘틱이 요구하는 외관 보존 조건(appearance contract)</b>과
정규화된 토폴로지·역할·투영크기로 <b>material slot 단위</b>로 결정한다.</p>

<div class=note>
<div class=big>{t['scene_polys']:,} → {t['provisional_scene_polys_after']:,} polys &nbsp;(−{t['provisional_reduction_pct']}%)</div>
고폴리 {t['highpoly_units']}개 유닛이 scene polygon의 {100*t['highpoly_polys']/t['scene_polys']:.0f}%를 차지.
tri-fraction은 아직 <b>slot 균등 가정(잠정)</b> — Phase B가 실제 per-slot 비율·토폴로지 veto로 대체하면
식물 컨테이너는 잎이 tri의 대부분이라 더 공격적, 얇은 유리·금속 용기 slot은 보호된다.
<b>{t['review_units']}개 유닛</b>(주로 NatureShelfTrinkets: 조개 vs 산호)이 Phase-B geometry veto 대기.
</div>

<h2>Appearance contract 별 정책</h2>
<table><tr><th>contract</th><th>보존 대상</th><th>prior</th><th>floor</th></tr>
<tr><td>{pill('compact_solid')}</td><td>전체 실루엣·큰 곡률 (조개·돌·둥근 소품)</td><td class=num>10%</td><td class=num>3%</td></tr>
<tr><td>{pill('branched_identity')}</td><td>주요 가지 수·분기 구조 (산호·가지)</td><td class=num>30%</td><td class=num>10%</td></tr>
<tr><td>{pill('organic_mass')}</td><td>전체 덩어리·인식성 (선인장·퍼지 식생)</td><td class=num>3%</td><td class=num>1%</td></tr>
<tr><td>{pill('rigid_planar')}</td><td>직선·평면·모서리·구멍 (캐비닛·문·선반)</td><td class=num>50%</td><td class=num>30%</td></tr>
<tr><td>{pill('optical_interface')}</td><td>곡면 법선·외곽·재질 경계·Fresnel (유리·금속 용기)</td><td class=num>30%</td><td class=num>10%</td></tr>
<tr><td>{pill('task_critical')}</td><td>충돌 형상·정확한 실루엣 (유리문·장애물·landmark)</td><td class=num>50%</td><td class=num>30%</td></tr></table>
<p class=mut>보정: background_decoration +1 공격 · landmark −1 보수 · collision/target −2 보수 ·
projected&lt;32px +1 공격 · &gt;96px −1 보수 · optical_eval_target은 optical slot ≥30% floor · low-confidence는 한 단계 보존 + review.</p>

<h2>Factory 별 집계</h2>
<table><tr><th>factory</th><th>유닛</th><th>polys</th><th>평균 r*</th><th>→ kept</th><th>review</th></tr>{frows}</table>

<h2>유닛별 상세 (무거운 순)</h2>
<table><tr><th>object / role</th><th>polys</th><th>task_role</th><th>slots (contract · optical · r*)</th><th>F_target</th><th></th></tr>{urows}</table>

<p class=mut style="margin-top:24px">재현: <code>tools/build_semantic_lod_plan.py --scene {a.scene}</code> →
<code>tools/generate_report_semantic_lod.py</code>. rule engine: <code>tools/semantic_lod_budget.py</code>.</p>
</div></body></html>"""
    out = REPO / "dev_report/report_semantic_lod.html"
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out} ({len(html)/1024:.1f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
