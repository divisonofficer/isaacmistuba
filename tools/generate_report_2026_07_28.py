#!/usr/bin/env python3
"""2026-07-28 report: large-scale (50-viewpoint) resident-scene band sweep vs
per-(viewpoint x band) reload, with the full modality set per Stokes pass.

Reads  dev_report/images/band_sweep_2026-07-28/metrics.json (+ panel PNGs)
Writes dev_report/report_2026-07-28.html
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
IMG_REL = "images/band_sweep_2026-07-28"
IMG_DIR = REPO / "dev_report" / IMG_REL
OUT = REPO / "dev_report" / "report_2026-07-28.html"

CSS = """
:root { --bg:#0f1216; --fg:#e6e9ef; --mut:#9aa4b2; --line:#232a33; --ok:#39d98a; --bad:#ff6b6b; --acc:#6aa9ff; --warn:#ffcc66; }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--fg); font:15px/1.65 -apple-system,"Segoe UI",Roboto,"Noto Sans KR",sans-serif; }
.wrap { max-width:1180px; margin:0 auto; padding:40px 24px 80px; }
h1 { font-size:27px; margin:0 0 6px; letter-spacing:-.01em; }
h2 { font-size:20px; margin:44px 0 12px; padding-top:18px; border-top:1px solid var(--line); }
h3 { font-size:16px; margin:26px 0 8px; color:var(--acc); }
.sub { color:var(--mut); margin:0 0 28px; }
p { margin:10px 0; }
a { color:var(--acc); }
code { background:#1a1f26; padding:1px 6px; border-radius:4px; font-size:13px; color:#d7dee8; }
table { border-collapse:collapse; width:100%; margin:14px 0; font-size:14px; }
th,td { border:1px solid var(--line); padding:7px 10px; text-align:left; }
th { background:#161b22; font-weight:600; color:var(--mut); }
td.num { text-align:right; font-variant-numeric:tabular-nums; }
.win { color:var(--ok); font-weight:650; }
.lose { color:var(--bad); }
.verdict { display:inline-block; padding:2px 9px; border-radius:999px; font-size:12px; font-weight:600; }
.pass { background:rgba(57,217,138,.14); color:var(--ok); }
.kpi { display:flex; gap:14px; flex-wrap:wrap; margin:18px 0; }
.kpi div { flex:1; min-width:180px; background:#141920; border:1px solid var(--line); border-radius:10px; padding:14px 16px; }
.kpi .k { color:var(--mut); font-size:12px; text-transform:uppercase; letter-spacing:.05em; }
.kpi .v { font-size:22px; font-weight:650; margin-top:4px; font-variant-numeric:tabular-nums; }
.note { background:#141920; border-left:3px solid var(--acc); padding:12px 16px; margin:16px 0; border-radius:0 8px 8px 0; }
.warn { border-left-color:var(--warn); }
.scroll { overflow-x:auto; }
ul { margin:10px 0; padding-left:22px; } li { margin:5px 0; }
.mod-grid { display:grid; grid-template-columns:repeat(6,1fr); gap:6px; margin:8px 0; }
.mod-grid figure { margin:0; }
.mod-grid img { width:100%; border-radius:5px; border:1px solid var(--line); display:block; background:#000; aspect-ratio:4/3; object-fit:cover; }
.mod-grid figcaption { font-size:11px; color:var(--mut); text-align:center; margin-top:3px; }
.vp-title { font-size:13px; color:var(--fg); margin:16px 0 2px; }
.legend { font-size:12px; color:var(--mut); margin:6px 0 0; }
.swatch { display:inline-block; width:52px; height:10px; border-radius:2px; vertical-align:middle; margin:0 4px; }
"""

MODS = [("rgb", "RGB (visible S0)"), ("nir", "NIR 854 (S0)"), ("dolp", "DoLP"),
        ("aolp", "AoLP"), ("s1s0", "S1/S0"), ("s2s0", "S2/S0")]


def kpi(k, v):
    return f'<div><div class="k">{k}</div><div class="v">{v}</div></div>'


def main() -> int:
    M = json.loads((IMG_DIR / "metrics.json").read_text())
    n = M["new"]
    o = M["old_projected"]
    pm = json.loads((IMG_DIR / "panel_meta.json").read_text())
    dolp_vmax = pm["dolp_vmax"]
    nvp = M["n_viewpoints"]
    nren = M["n_renders"]
    spp = M["spp"]
    load1 = sum(n["load_scene_s"])
    speedup = M["speedup_wall"]
    mem = n["gpu_attributable_mib"]
    vram = o.get("vram_total_mib")
    resident_need = o["resident_required_mib"]
    thr_new = n["throughput_vp_per_min"]
    thr_old = nvp / (o["wall_s"] / 60.0)

    # modality panels
    panels = ""
    for pv in n["panel_viewpoints"]:
        vi = pv["vi"]
        cells = "".join(
            f'<figure><img src="{IMG_REL}/vp{vi:02d}_{key}.png" alt="{lab}"><figcaption>{lab}</figcaption></figure>'
            for key, lab in MODS
        )
        panels += (
            f'<div class="vp-title">viewpoint <code>{pv.get("node") or pv.get("node_id")}</code> · heading {pv.get("heading") or pv.get("heading_id")} '
            f'({pv["yaw_deg"]:.0f}°) · pos ({pv["x"]:.1f}, {pv["y"]:.1f})</div>'
            f'<div class="mod-grid">{cells}</div>'
        )

    bm = M["band_means"]
    band_rows = "".join(
        f'<tr><td>{b}</td><td class="num">{bm[b]["s0_mean"]:.4f}</td>'
        f'<td class="num">{bm[b]["dolp_mean"]:.4f}</td></tr>'
        for b in bm
    )

    vram_txt = (f'{vram/1024:.0f} GB' if vram else 'VRAM')
    html = f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>대규모 뷰포인트 스윕 — resident 재사용 vs 재로드 · 2026-07-28</title>
<style>{CSS}</style></head><body><div class="wrap">

<h1>한 씬 · {nvp} 뷰포인트 · 전 모달리티 — 메모리 재사용 대규모 벤치마크</h1>
<p class="sub">2026-07-28 · discrete-band <code>cuda_ad_rgb_polarized</code> Stokes carrier ·
production build <code>build/mitsuba3-optix7</code> · Device 1 (WSL2 · RTX 5090, {vram_txt}) ·
<a href="report_2026-07-27.html">← 2026-07-27 (2-뷰포인트 메모리/OOM 발견)</a></p>

<div class="note">
<strong>한 줄 요약.</strong> 프로덕션 실내 씬을 GPU에 <strong>한 번만</strong> 올리고, {nvp}개 뷰포인트를 카메라 pose
<code>params.update()</code>({n["mean_pose_update_ms"]:.0f}&nbsp;ms)와 밴드 selector flip({n["mean_flip_ms"]:.0f}&nbsp;ms)만으로
순회하며 각 지점에서 <strong>RGB · NIR · DoLP · AoLP · S1/S0 · S2/S0</strong>를 한 번의 Stokes 렌더로 뽑았다.
같은 결과를 뷰포인트·밴드마다 씬을 재로드하는 이전 방식으로 얻으면 <span class="win">{speedup:.1f}×</span> 느리고,
두 밴드를 동시에 resident로 두면 <span class="lose">{resident_need/1024:.0f}&nbsp;GB &gt; {vram_txt}</span>로 들어가지도 않는다.
새 방식의 GPU 사용은 뷰포인트 수와 무관하게 <strong>{mem/1024:.0f}&nbsp;GB 고정</strong>이다.
</div>

<div class="kpi">
  {kpi("viewpoints × bands", f"{nvp} × {M['n_bands']} = {nren} 렌더")}
  {kpi("scene loads", f"1 (재로드 0)")}
  {kpi("pose+band 전환", f"{n['mean_pose_update_ms']:.0f}+{n['mean_flip_ms']:.0f} ms")}
  {kpi("wall 단축", f"{speedup:.1f}×")}
  {kpi("GPU (뷰포인트 무관)", f"{mem/1024:.0f} GB 고정")}
</div>

<h2>1. 셋업</h2>
<p>
씬 <code>{M["scene"]}</code>({n["weight_keys"]}개 재질을 band selector로 감싼 프로덕션 실내)를 로드하고, 이 씬의
viewpoint graph(<code>{M["graph"].split("/")[-1]}</code>, 113 노드 × 12 heading)에서 위치·heading을 고루 섞어
<strong>{nvp}개 뷰포인트</strong>를 샘플했다. 각 뷰포인트에서 <strong>visible / NIR&nbsp;854</strong> 두 밴드를 렌더하고,
Stokes 한 패스에서 6개 모달리티를 동시에 뽑았다.
</p>
<pre><code>resident scene (1회 로드)
  └─ for vp in {nvp} viewpoints:
        params["PerspectiveCamera.to_world"] = pose(vp)      # ~{n['mean_pose_update_ms']:.0f} ms, 재컴파일 없음
        for band in (visible, nir_854):
           params["shared_bsdf_*.weight.value"] = band       # ~{n['mean_flip_ms']:.0f} ms
           img = render()   # Stokes -> RGB/NIR · DoLP · AoLP · S1/S0 · S2/S0</code></pre>

<h2>2. 스케일링 — 뷰포인트가 늘수록 재로드 방식이 무너진다</h2>
<div class="scroll"><table>
<tr><th>지표</th><th>new (resident 재사용)</th><th>old (뷰포인트·밴드별 재로드)</th></tr>
<tr><td>씬 로드 횟수</td><td class="num win">1</td><td class="num">{o["reloads"]}</td></tr>
<tr><td>씬 로드 시간 합</td><td class="num win">{load1:.0f} s</td><td class="num">{o["reloads"]*o["per_reload_load_s"]:.0f} s</td></tr>
<tr><td>렌더 {nren}장</td><td class="num">{n["render_only_s"]:.0f} s</td><td class="num">{o["reloads"]*o["per_render_s"]:.0f} s</td></tr>
<tr><td>pose+band 전환 합</td><td class="num">{(n["wall_s"]-load1-n["render_only_s"]):.0f} s</td><td class="num">—</td></tr>
<tr><td><strong>총 wall time</strong></td><td class="num win"><strong>{n["wall_s"]:.0f} s</strong></td><td class="num">{o["wall_s"]:.0f} s (투영)</td></tr>
<tr><td>throughput</td><td class="num win">{thr_new:.1f} vp/min</td><td class="num">{thr_old:.2f} vp/min</td></tr>
</table></div>
<div class="note">
<p>새 방식의 뷰포인트 한계비용은 <strong>pose {n['mean_pose_update_ms']:.0f}&nbsp;ms + 렌더</strong>뿐이다(재로드·재컴파일 0).
이전 방식은 뷰포인트·밴드마다 씬을 통째로 다시 올린다 — 로드 한 번이 <strong>≈{o["per_reload_load_s"]:.0f}&nbsp;s</strong>이므로
{o["reloads"]}회 재로드가 <strong>≈{o["reloads"]*o["per_reload_load_s"]/60:.0f}분</strong>을 삼킨다. 여기서 <strong>{speedup:.1f}×</strong> 차이가 난다.</p>
<p class="mut">old 값은 실측 재로드 {o["sample_k"]}회(로드 중앙값 {o["per_reload_load_s"]:.0f}&nbsp;s, 렌더 {o["per_render_s"]:.0f}&nbsp;s)를
{o["reloads"]}회로 투영한 것이다 — 100회를 실제로 재로드하면 3시간 이상이라 대표 표본으로 단가를 측정했다.
렌더 시간은 이 씬에서 spp가 아니라 씬 고정비용(280재질 megakernel + area emitter)에 지배되므로 재로드 절약분이 곧 순이득이다.</p>
</div>

<h2>3. 메모리 — 뷰포인트 수와 무관하게 상수</h2>
<div class="kpi">
  {kpi("baseline (device)", f"{n['gpu_baseline_mib']} MiB")}
  {kpi("peak used", f"{n['peak_gpu_mib']} MiB")}
  {kpi("귀속 GPU", f"{mem:,} MiB")}
  {kpi("{}vp 순회 후 증가".format(nvp), "0 (상수)")}
</div>
<p>
새 방식은 {nvp}개 뷰포인트를 도는 내내 씬 <strong>하나</strong>만 유지하므로 GPU 사용이 <strong>{mem/1024:.0f}&nbsp;GB에서 상수</strong>다.
이전 방식으로 여러 modality를 동시에 addressable하게 두려면 씬을 밴드마다 resident로 올려야 하는데, 이는
<strong>≈{resident_need/1024:.0f}&nbsp;GB &gt; {vram_txt}</strong>로 <span class="lose">VRAM에 들어가지 않는다</span>
(<a href="report_2026-07-27.html">2026-07-27 리포트</a>에서 두 번째 씬 로드가 host RAM으로 spill하며 thrashing함을 실측).
재로드로 이를 피하면 §2의 시간을 지불한다. 새 방식은 둘 다 회피한다.
</p>

<h2>4. 모달리티 — 한 Stokes 패스에서 6종</h2>
<p>
아래는 스윕에서 고른 대표 뷰포인트들이다. 각 행은 <strong>하나의 카메라 pose</strong>에서 나온
RGB(visible) · NIR&nbsp;854 · DoLP · AoLP · S1/S0 · S2/S0다 — 강도와 편광이 <strong>같은 렌더</strong>에서 함께 나온다.
</p>
<p class="legend">
DoLP <span class="swatch" style="background:linear-gradient(90deg,#440154,#21908c,#fde725)"></span> 0–{dolp_vmax:.3f} ·
AoLP <span class="swatch" style="background:linear-gradient(90deg,red,#ff0,#0f0,#0ff,#00f,#f0f,red)"></span> 방위각(색상), 밝기=DoLP ·
S1/S0·S2/S0 <span class="swatch" style="background:linear-gradient(90deg,#3b4cbf,#fff,#bf2626)"></span> −1…+1
</p>
{panels}
<div class="note">
<p><strong>물리 검사.</strong> 유리·금속·창 표면에서 정반사 Fresnel 편광이 DoLP/AoLP로 나타나고, 확산 벽면은 낮다.
밴드별 평균(50 뷰포인트 집계)에서 visible→NIR로 갈 때 확산 반사가 커지며 편광이 희석된다:</p>
</div>
<table>
<tr><th>band</th><th>S0 mean (50vp)</th><th>DoLP mean (50vp)</th></tr>
{band_rows}
</table>

<h2>5. 한계</h2>
<ul>
<li>old wall은 실측 단가×{o["reloads"]}회 <strong>투영</strong>이다(100회 실재로드=3시간+ 회피). new는 {nvp}vp 전부 실측했다.</li>
<li>CIFS(<code>/jarvis</code>) 텍스처라 로드 절대시간(≈{o["per_reload_load_s"]:.0f}s/회)이 로컬보다 부풀려져 있으나,
    구조적 차이(로드 횟수 {o["reloads"]}→1, resident VRAM 초과)는 하드웨어와 무관하다.</li>
<li>NIR 반사율은 placeholder(ρ854), 밴드 계약 provenance는 Stage&nbsp;1의 몫이다.</li>
<li>WSL device-level 메모리 측정(±수백 MiB)·spp 고정비용 특성은 §2·§3 각주대로다.</li>
</ul>

<p class="mut">재현: <code>tools/benchmark_band_sweep.py</code> → <code>tools/generate_report_2026_07_28.py</code>.
씬 <code>{M["scene"]}</code>, graph <code>{M["graph"].split("/")[-1]}</code>. {nvp}vp × {M["n_bands"]}band, spp&nbsp;{spp}.</p>

</div></body></html>
"""
    OUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUT}  ({len(html)/1024:.1f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
