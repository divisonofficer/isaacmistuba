#!/usr/bin/env python3
"""Report A — Polarization-render qualification (the mandatory gate).
Reads dev_report/images/polar_qualify/qualification.json,
writes dev_report/report_polar_qualify.html.
"""
from __future__ import annotations
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
QJSON = REPO / "dev_report/images/polar_qualify/qualification.json"
OUT = REPO / "dev_report/report_polar_qualify.html"

STAGE_TITLE = {
    0: "0 · 실행 환경 · 금지재질 게이트",
    1: "1 · 편광 광원 + 분석기 (Stokes · Malus · 카메라 회전)",
    2: "2 · 평면 경계면 해석적 Fresnel",
    3: "3 · 단일재질 구 (금속 · 확산 · 유리 · 금지재질 음성시험)",
}
IMG_REL = "images/polar_qualify"
CSS = """
:root{--bg:#0f1216;--fg:#e6e9ef;--mut:#9aa4b2;--line:#232a33;--ok:#39d98a;--bad:#ff6b6b;--acc:#6aa9ff;}
*{box-sizing:border-box;}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.6 -apple-system,"Segoe UI",Roboto,"Noto Sans KR",sans-serif;}
.wrap{max-width:1040px;margin:0 auto;padding:40px 24px 80px;}h1{font-size:25px;margin:0 0 6px;}
h2{font-size:18px;margin:34px 0 8px;padding-top:14px;border-top:1px solid var(--line);}
h3{font-size:14px;margin:16px 0 4px;color:var(--acc);}
.sub{color:var(--mut);margin:0 0 22px;}code{background:#1a1f26;padding:1px 6px;border-radius:4px;font-size:13px;}
table{border-collapse:collapse;width:100%;margin:10px 0;font-size:13.5px;}th,td{border:1px solid var(--line);padding:6px 9px;text-align:left;}
th{background:#161b22;color:var(--mut);}td.num{text-align:right;font-variant-numeric:tabular-nums;}
.badge{display:inline-block;padding:3px 12px;border-radius:999px;font-weight:700;font-size:14px;}
.pass{background:rgba(57,217,138,.16);color:var(--ok);}.fail{background:rgba(255,107,107,.16);color:var(--bad);}
.ok{color:var(--ok);}.xx{color:var(--bad);}
.note{background:#141920;border-left:3px solid var(--acc);padding:12px 16px;margin:14px 0;border-radius:0 8px 8px 0;}
.mut{color:var(--mut);font-size:12px;}
.grid{display:grid;grid-template-columns:120px repeat(5,1fr);gap:4px;margin:4px 0 12px;align-items:center;}
.grid img{width:100%;border:1px solid var(--line);border-radius:3px;display:block;background:#000;aspect-ratio:1;object-fit:cover;}
.grid .cap{font-size:11px;color:var(--mut);text-align:center;}
.grid .rl{font-size:12px;color:var(--fg);text-align:right;padding-right:6px;}
.legend{font-size:12px;color:var(--mut);margin:4px 0 8px;}
.sw{display:inline-block;width:44px;height:9px;border-radius:2px;vertical-align:middle;margin:0 4px;}
"""
MODS = [("rgb", "S0"), ("dolp", "DoLP"), ("aolp", "AoLP"), ("s1s0", "S1/S0"), ("s2s0", "S2/S0")]


def img_grid(images):
    if not images:
        return ""
    head = '<div class="grid"><div class="rl"></div>' + "".join(f'<div class="cap">{lab}</div>' for _, lab in MODS) + "</div>"
    rows = ""
    for im in images:
        cells = "".join(f'<div><img src="{IMG_REL}/{im["name"]}_{k}.png" alt="{im["name"]} {k}"></div>' for k, _ in MODS)
        rows += f'<div class="grid"><div class="rl">{im["label"]}</div>{cells}</div>'
    return f'<h3>렌더 이미지</h3>{head}{rows}'


def kv_table(measured):
    if not isinstance(measured, dict):
        return f'<code>{measured}</code>'
    rows = "".join(f"<tr><td>{k}</td><td class='num'>{v}</td></tr>" for k, v in measured.items())
    return f'<table>{rows}</table>'


def main() -> int:
    Q = json.loads(QJSON.read_text())
    gif = REPO / "dev_report" / IMG_REL / "malus_rotation.gif"
    malus_gif_html = ("" if not gif.is_file() else f"""
<h2>Malus 편광 애니메이션 (편광 광원 0→360° 회전 · 5모달리티)</h2>
<p class="mut">편광 배경 광원의 각도를 회전시키면, 고정된 4개 분석기(좌상 0° · 우상 45° · 좌하 90° · 우하 135°)의
<strong>S0</strong> 밝기가 <code>cos²(θ_source − θ_analyzer)</code>를 따라 변하며 소광 패치가 그리드를 순환한다.
동시에 분석기가 없는 <strong>배경</strong>에서는 <strong>AoLP·S1/S0·S2/S0</strong>가 광원 각도를 따라 회전하는 반면(=광원 편광),
분석기 뒤에서는 그 분석기 각도로 고정된다 — 두 현상을 한 프레임에서 함께 본다. <strong>DoLP</strong>는 분석기·배경 모두 ≈1(완전편광).</p>
<img src="{IMG_REL}/malus_rotation.gif" alt="Malus rotation (S0/DoLP/AoLP/S1S0/S2S0)" style="width:100%;max-width:960px;border:1px solid var(--line);border-radius:4px;">
""")

    s3v_path = REPO / "dev_report" / IMG_REL / "stage3v.json"
    stage3v_html = ""
    if s3v_path.is_file():
        S3V = json.loads(s3v_path.read_text())["stage3v"]
        NICE = {"metal_Al": "알루미늄 (roughconductor Al)", "gold_Au": "금 (roughconductor Au)",
                "glass": "유리 (dielectric n=1.5)", "coated_diffuse_red": "코팅 확산 (pplastic)"}
        rows = ""
        for im in S3V.get("studio_images", []):
            nm = im["name"]; base = f"{IMG_REL}/s3v_{nm}"
            polar = "".join(f'<div><img src="{base}_polar_{k}.png" alt=""></div>' for k, _ in MODS)
            rows += f"""
<h3>{NICE.get(nm, nm)}</h3>
<div style="display:grid;grid-template-columns:180px 1fr;gap:12px;align-items:start;margin-bottom:6px;">
  <div><img src="{base}_appear_rgb.png" alt="appearance" style="width:100%;border:1px solid var(--line);border-radius:4px;">
       <div class="cap">외형 패스 (envmap+3점, S0)</div></div>
  <div><div class="grid" style="grid-template-columns:repeat(5,1fr);">{polar}</div>
       <div class="cap">편광 패스 (polarized key) — S0 · DoLP · AoLP · S1/S0 · S2/S0</div></div>
</div>"""
        stage3v_html = f"""
<h2>Stage 3-V · 재질 미리보기 스튜디오 (INFO · 비게이트) <span class="mut">({S3V.get('seconds','?')}s, spp={S3V.get('spp') or ''})</span></h2>
<div class="note">
<strong>계측 장면과 시각 장면의 분리.</strong> 게이트 Stage 3의 구는 어두운 통제 배경이라 <em>수치 검증</em>엔 맞지만 금속·유리가
"색유리 덩어리"로 보였다. Stage 3-V는 <strong>비게이트 시각 미리보기</strong>로, 절차적 소프트박스 <strong>환경맵</strong>(외부 HDR·라이선스 없음) +
제품 3점 조명을 입혀 크롬/골드가 환경을 반사해 <strong>진짜 금속</strong>으로, 유리가 굴절·집광으로 <strong>진짜 유리</strong>로 읽히게 한다.
<strong>두 패스</strong>로 분리 — 외형(무편광, 자연스러운 S0)과 편광(polarized key로 DoLP/AoLP). 이 단계는 게이트 PASS/FAIL에 영향을 주지 않는다.
</div>
{rows}"""
    passed = Q["passed"]
    stages_html = ""
    for st in Q["stages"]:
        s = st["stage"]
        crows = ""
        for c in st["checks"]:
            mark = '<span class="ok">✓ PASS</span>' if c["passed"] else '<span class="xx">✗ FAIL</span>'
            crows += (f'<tr><td>{c["name"]}</td><td>{mark}</td>'
                      f'<td>{kv_table(c.get("measured"))}{("<div class=mut>"+c["note"]+"</div>") if c.get("note") else ""}</td></tr>')
        sp = '<span class="ok">PASS</span>' if st["passed"] else '<span class="xx">FAIL</span>'
        stages_html += f"""
<h2>Stage {STAGE_TITLE.get(s, s)} — {sp} <span class="mut">({st.get('seconds','?')}s)</span></h2>
<table><tr><th>검사</th><th>결과</th><th>측정값</th></tr>{crows}</table>
{img_grid(st.get('images'))}"""

    html = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Report A — 편광 렌더 적합성 시험</title><style>{CSS}</style></head><body><div class="wrap">
<h1>Report A — 편광 렌더 파이프라인 적합성 시험 (게이트)</h1>
<p class="sub">모든 오브젝트·장면 편광 실험 <strong>이전에</strong> 의무 통과해야 하는 gated qualification ·
variant <code>{Q.get('variant')}</code> · id <code>{Q.get('qualification_id')}</code></p>

<div class="note">
<strong>전체 판정: <span class="badge {'pass' if passed else 'fail'}">{'PASS' if passed else 'FAIL'}</span></strong><br>
plausible한 DoLP 영상이 광원·재질·주입·렌더 경로 중 어디서 틀렸는지 가리기 어렵던 문제(2026-07-06)를 없애기 위해,
파이프라인 자체를 먼저 인증한다. 앞 단계가 실패하면 뒤 단계·오브젝트 실험은 실행하지 않는다.
</div>

<div class="note">
<strong>핵심 통과 근거.</strong> 편광 광원(<code>polarized_area</code> emitter — 조명 자체가 편광이라 NEE가 살아 노이즈 없음)을
돌리면 AoLP가 1:1 추적, 평면 유전체는 Brewster 56°에서 DoLP 0.97, 확산 평면·순수 lambertian 구는 0,
그리고 금지재질 <code>roughdielectric/thindielectric/plastic/roughplastic</code>은 편광 트리오로 강제 소비된다.
</div>
<div class="note warn">
<strong>수치 판정 규약 (게이트 강화).</strong>
<strong>Malus</strong>는 반사 경로 없이 <em>편광 배경 + 4각도 분석기 그리드</em>를 한 번 렌더해 <strong>선형 S0</strong>(톤매핑 PNG 아님)의
패치 평균으로 판정한다 — I45≈I135≈0.484, I90/I0≈0.001로 대칭(이전 반사기반의 0.62/0.41 비대칭은 금속 Mueller 회전 때문이었다).
<strong>DoP</strong>는 수치 판정 전에 clip하지 않고 raw max·p99.9를 보고한다(물리 상한 S0≥√(S1²+S2²+S3²); 밝은 픽셀의 MC 잡음으로 1을 소폭 넘을 수 있어 ε=0.10 허용, 표시 영상만 clip).
<strong>DoLP 수치</strong>(금속 0.99·유리 0.49 등)는 <em>재질 고정 특성이 아니라 이 편광 광원·카메라 배치의 선택된 정반사 영역에서의 측정 중앙값</em>이다.
</div>
<p class="legend">이미지 범례 —
S0 tonemap(RGB) · DoLP <span class="sw" style="background:linear-gradient(90deg,#000,#f00)"></span> 0(검정)–1(빨강) ·
AoLP <span class="sw" style="background:linear-gradient(90deg,red,#ff0,#0f0,#0ff,#00f,#f0f,red)"></span> 방위각(색), 밝기=DoLP ·
S1/S0·S2/S0 <span class="sw" style="background:linear-gradient(90deg,#3b4cbf,#fff,#bf2626)"></span> −1…+1</p>
{malus_gif_html}
{stages_html}
{stage3v_html}

<h2>이 게이트의 사용법</h2>
<ul>
<li>코드/플러그인/재질정책 변경마다 <code>python validation/polarization/qualify.py</code> 실행 → <code>qualification.json</code>.</li>
<li>오브젝트(Report B)·장면(Report C) 실험은 <strong>PASS한 qualification_id를 인용</strong>해야 한다 —
결과가 "검증된 파이프라인에서 생성"임을 보장.</li>
<li>Stage 4(자산 주입·UV) / 5(오브젝트) / 6(장면)은 각자 하네스에 위임되며, 그 앞에 Stage 0–3 통과가 전제된다.</li>
</ul>
<p class="mut">재현: <code>validation/polarization/qualify.py</code> → <code>tools/generate_report_polar_qualify.py</code>.</p>
</div></body></html>"""
    OUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUT} ({len(html)/1024:.1f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
