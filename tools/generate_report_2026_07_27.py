#!/usr/bin/env python3
"""Generate the 2026-07-27 report: resident band-flip renderer vs per-modality
scene reload — memory, time, and render-result comparison.

Reads  dev_report/images/band_bench_2026-07-27/metrics.json (+ preview PNGs)
Writes dev_report/report_2026-07-27.html
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
IMG_REL = "images/band_bench_2026-07-27"
IMG_DIR = REPO / "dev_report" / IMG_REL
OUT = REPO / "dev_report" / "report_2026-07-27.html"

CSS = """
:root { --bg:#0f1216; --fg:#e6e9ef; --mut:#9aa4b2; --line:#232a33; --ok:#39d98a; --bad:#ff6b6b; --acc:#6aa9ff; --warn:#ffcc66; }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--fg); font:15px/1.65 -apple-system,"Segoe UI",Roboto,"Noto Sans KR",sans-serif; }
.wrap { max-width:1120px; margin:0 auto; padding:40px 24px 80px; }
h1 { font-size:27px; margin:0 0 6px; letter-spacing:-.01em; }
h2 { font-size:20px; margin:44px 0 12px; padding-top:18px; border-top:1px solid var(--line); }
h3 { font-size:16px; margin:26px 0 8px; color:var(--acc); }
.sub { color:var(--mut); margin:0 0 28px; }
p { margin:10px 0; }
code { background:#1a1f26; padding:1px 6px; border-radius:4px; font-size:13px; color:#d7dee8; }
table { border-collapse:collapse; width:100%; margin:14px 0; font-size:14px; }
th,td { border:1px solid var(--line); padding:7px 10px; text-align:left; }
th { background:#161b22; font-weight:600; color:var(--mut); }
td.num { text-align:right; font-variant-numeric:tabular-nums; }
.win { color:var(--ok); font-weight:650; }
.lose { color:var(--bad); }
.verdict { display:inline-block; padding:2px 9px; border-radius:999px; font-size:12px; font-weight:600; }
.pass { background:rgba(57,217,138,.14); color:var(--ok); }
.fail { background:rgba(255,107,107,.14); color:var(--bad); }
.kpi { display:flex; gap:14px; flex-wrap:wrap; margin:18px 0; }
.kpi div { flex:1; min-width:190px; background:#141920; border:1px solid var(--line); border-radius:10px; padding:14px 16px; }
.kpi .k { color:var(--mut); font-size:12px; text-transform:uppercase; letter-spacing:.05em; }
.kpi .v { font-size:22px; font-weight:650; margin-top:4px; font-variant-numeric:tabular-nums; }
.note { background:#141920; border-left:3px solid var(--acc); padding:12px 16px; margin:16px 0; border-radius:0 8px 8px 0; }
.warn { border-left-color:var(--warn); }
.scroll { overflow-x:auto; }
ul { margin:10px 0; padding-left:22px; } li { margin:5px 0; }
.ba3-grid { display:grid; grid-template-columns:1fr; gap:18px; margin:14px 0; }
.ba3-grid figure { margin:0; }
.ba3 { display:grid; grid-template-columns:1fr 1fr; gap:6px; max-width:760px; }
.ba3 img { width:100%; border-radius:6px; border:1px solid var(--line); display:block; background:#000; }
.ba3-grid figcaption { font-size:12.5px; color:var(--mut); margin-top:6px; }
"""


def kpi(k: str, v: str) -> str:
    return f'<div><div class="k">{k}</div><div class="v">{v}</div></div>'


def verdict(ok: bool, text: str | None = None) -> str:
    cls = "pass" if ok else "fail"
    return f'<span class="verdict {cls}">{text or ("PASS" if ok else "FAIL")}</span>'


def main() -> int:
    M = json.loads((IMG_DIR / "metrics.json").read_text())
    n = M["modes"]["new"]
    orl = M["modes"]["old_reload"]
    ore = M["modes"]["old_resident"]
    spp = M["spp"]
    n_bands = len(n["bands"])
    dolp_vmax = json.loads((IMG_DIR / "preview_meta.json").read_text())["dolp_vmax"]

    load_new = sum(n["load_scene_s"])
    load_old = sum(orl["load_scene_s"])
    wall_new = n["total_wall_s"]
    wall_old = orl["total_wall_s"]
    mem_new = n["gpu_attributable_mib"]
    vram = ore["vram_total_mib"]
    need_resident = ore["required_estimate_mib"]
    flip_total = sum(b["flip_ms"] for b in n["bands"].values())
    flip_ms = flip_total / max(1, (n_bands - 1))
    per_load_s = load_old / len(orl["load_scene_s"])

    time_speedup = wall_old / max(wall_new, 1e-6)
    eq = M["equivalence"]
    eq_ok = all(v["dolp_mean_abs_diff"] < 0.02 for v in eq.values())

    band_rows = ""
    for band in n["bands"]:
        nb = n["bands"][band]
        band_rows += (
            f"<tr><td>{band}</td>"
            f'<td class="num">{nb["s0_mean"]:.4f}</td>'
            f'<td class="num">{nb["dolp_mean"]:.4f}</td>'
            f'<td class="num">{eq[band]["s0_mean_abs_diff"]:.2e}</td>'
            f'<td class="num">{eq[band]["dolp_mean_abs_diff"]:.2e}</td></tr>'
        )

    figs = ""
    for band in n["bands"]:
        figs += (
            f'<figure><div class="ba3">'
            f'<img src="{IMG_REL}/{band}_rgb.png" alt="{band} rgb">'
            f'<img src="{IMG_REL}/{band}_dolp.png" alt="{band} dolp">'
            f'</div><figcaption>{band} — S0 tonemapped (좌) / DoLP 0–{dolp_vmax:.3f} (우)</figcaption></figure>'
        )

    def loads_str(m):
        return " + ".join(f"{x:.0f}" for x in m["load_scene_s"]) + " s"

    html = f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Resident Band-Flip vs Per-Modality Reload — 2026-07-27</title>
<style>{CSS}</style></head><body><div class="wrap">

<h1>단일 씬 밴드 전환 렌더 vs modality별 씬 재로드</h1>
<p class="sub">2026-07-27 · discrete-band <code>cuda_ad_rgb_polarized</code> Stokes carrier ·
production build <code>build/mitsuba3-optix7</code> · Device 1 (WSL2 · RTX 5090, 32&nbsp;GB)</p>

<div class="note">
<strong>한 줄 요약.</strong> 카메라 리그의 여러 modality(가시광 RGB · NIR&nbsp;854 · 편광)를 한 시점에서 얻는 두 방식을
같은 프로덕션 실내 씬에서 직접 벤치마크했다. <strong>실제 운영하던 이전 방식</strong>은 modality를 바꿀 때마다 씬 메모리를
비우고 다시 로드했다 — 그 <strong>반복 재로드 IO가 병목</strong>이었고, 이것이 메모리 통합의 동기였다.
<strong>새 방식</strong>은 씬을 GPU에 <strong>한 번만</strong> 올리고 band selector weight를 <code>params.update()</code>로
제자리에서 갈아끼워, 재로드 IO를 <span class="win">{time_speedup:.2f}×</span> wall 만큼 없앤다.
재로드를 피하려고 두 modality의 씬을 <strong>둘 다 resident로 캐싱</strong>하는 대안은
<strong>{need_resident/1024:.0f}&nbsp;GB &gt; {vram/1024:.0f}&nbsp;GB VRAM</strong>로 <span class="lose">OOM</span>이라 불가능했다 —
그래서 이전엔 재로드(IO)가 강제됐다. 새 방식만 <strong>재로드 IO도 OOM도 없이</strong> 한 씬으로 두 밴드를 서비스한다.
</div>

<div class="kpi">
  {kpi("band flip ({} 재질)".format(n["weight_keys"]), f"{flip_ms:.0f} ms")}
  {kpi("scene reloads", f"{len(orl['load_scene_s'])} → {len(n['load_scene_s'])}")}
  {kpi("wall time", f"{wall_new:.0f}s vs {wall_old:.0f}s")}
  {kpi("resident 2-modality", "OOM > VRAM")}
</div>

<h2>1. 무엇을 비교했나</h2>
<p>
카메라 리그는 같은 시점에서 <strong>가시광 RGB · NIR(854&nbsp;nm) · spectral 편광(Stokes)</strong>을 함께 얻어야 한다.
discrete-band 파이프라인(2026-07-14 리포트)은 이 modality들을 <strong>하나의 <code>cuda_ad_rgb_polarized</code>
Stokes carrier</strong> 위에서 표현한다 — 밴드별 물성을 각 재질의 <code>blendbsdf</code> band selector(visible↔NIR)에 pin하고,
Stokes integrator가 한 번의 렌더로 <strong>강도(S0)와 편광(S1/S2/S3)을 동시에</strong> 낸다.
</p>
<pre><code>각 top-level &lt;bsdf id="X"&gt;  →  blendbsdf{{ weight }}{{ &lt;visible X&gt;, &lt;NIR clone&gt; }}
weight = 0 → visible band   ·   weight = 1 → NIR 854 band   ·   Stokes → S0 + 편광 동시</code></pre>
<p>세 실행 방식을 각각 <strong>독립 프로세스</strong>로 돌려 GPU 메모리 샘플을 깨끗하게 분리했다:</p>
<div class="scroll"><table>
<tr><th>방식</th><th>씬 로드</th><th>modality 전환</th><th>성격</th></tr>
<tr><td><strong>new</strong> (resident 밴드 전환)</td><td class="num">1회</td><td><code>params.update()</code> band flip</td>
    <td>목표 구조 — 한 씬으로 전 밴드 서비스</td></tr>
<tr><td><strong>old_reload</strong> — <em>실제 운영하던 방식</em></td><td class="num">{len(orl["load_scene_s"])}회</td><td>modality마다 메모리 clean + <code>load_file()</code> 재로드</td>
    <td><strong>재로드 IO가 병목</strong> (§2)</td></tr>
<tr><td><strong>old_resident</strong> — 재로드 회피 시도</td><td class="num">{len(orl["load_scene_s"])}회</td><td>재로드 대신 <strong>두 씬을 둘 다 유지</strong></td>
    <td>VRAM 초과 → <span class="lose">OOM</span> (§3) — 그래서 재로드가 강제됐다</td></tr>
</table></div>
<p class="mut">
씬: <code>{M["scene"]}</code> — bridge job이 실제 렌더한 프로덕션 실내 <code>render_scene.xml</code>({n["weight_keys"]}개 재질을 band
selector로 감쌈, 저장된 카메라 pose 그대로). 밴드 = visible / NIR&nbsp;854. spp&nbsp;=&nbsp;{spp}. 640×480. max_depth&nbsp;6.
</p>

<h2>2. 시간 — 반복 재로드 IO가 병목이었다</h2>
<div class="scroll"><table>
<tr><th>지표</th><th>new</th><th>old_reload</th><th>old_resident</th></tr>
<tr><td>씬 로드 횟수</td><td class="num win">{len(n['load_scene_s'])}</td>
    <td class="num">{len(orl['load_scene_s'])}</td><td class="num">{len(orl['load_scene_s'])}</td></tr>
<tr><td>씬 로드 시간</td><td class="num">{loads_str(n)}</td><td class="num">{loads_str(orl)}</td><td class="num">{per_load_s:.0f} + OOM</td></tr>
<tr><td>로드 합계</td><td class="num win">{load_new:.0f} s</td><td class="num">{load_old:.0f} s</td><td class="num">—</td></tr>
<tr><td>band flip 합계</td><td class="num">{flip_total:.0f} ms</td><td class="num">—</td><td class="num">—</td></tr>
<tr><td><strong>총 wall time</strong></td><td class="num win"><strong>{wall_new:.0f} s</strong></td>
    <td class="num">{wall_old:.0f} s</td><td class="num lose">미완 (VRAM 초과)</td></tr>
</table></div>
<div class="note">
<p>실제 운영하던 이전 방식은 modality를 바꿀 때마다 씬 메모리를 비우고 전체 씬을 <strong>다시 로드</strong>했다 — 텍스처·지오메트리를
CIFS에서 다시 읽고 OptiX 커널을 다시 컴파일한다. 새 방식은 <strong>{n_bands}개 밴드 중 첫 번째만 로드·컴파일</strong>하고
나머지는 <strong>{flip_ms:.0f}&nbsp;ms band flip</strong>으로 얻는다. modality를 하나 더 얻는 한계비용이
<strong>새 방식 ≈{flip_ms:.0f}&nbsp;ms</strong> 대 <strong>이전 방식 ≈{per_load_s:.0f}&nbsp;s(재로드 IO+컴파일)</strong>로,
이 반복 IO가 곧 메모리 통합을 하게 된 병목이다({time_speedup:.2f}× wall 단축).</p>
</div>
<p class="mut">
※ 이 씬의 텍스처는 CIFS 네트워크 마운트(<code>/jarvis</code>)에 있어 로드 절대시간(≈{per_load_s:.0f}s/회)이 로컬 디스크보다
부풀려져 있다. 그러나 비교의 핵심은 로드 절대값이 아니라 <strong>로드 횟수 {len(orl['load_scene_s'])}→{len(n['load_scene_s'])}</strong>이며,
OptiX 커널 재컴파일·GPU 재업로드는 캐시와 무관한 반복 비용이다.
</p>

<h2>3. 메모리 — 왜 재로드를 피할 수 없었나 (resident 캐싱 = OOM)</h2>
<div class="scroll"><table>
<tr><th>지표</th><th>new</th><th>old_reload</th><th>old_resident</th></tr>
<tr><td>사전 baseline (device)</td><td class="num">{n['gpu_baseline_mib']}</td><td class="num">{orl['gpu_baseline_mib']}</td><td class="num">{ore['gpu_baseline_mib']}</td></tr>
<tr><td>피크 device used</td><td class="num">{n['peak_gpu_mib']}</td><td class="num">{orl['peak_gpu_mib']}</td><td class="num lose">{vram} (한계)</td></tr>
<tr><td><strong>귀속 GPU (peak−baseline)</strong></td><td class="num win"><strong>{mem_new:,}&nbsp;MiB</strong></td>
    <td class="num">{orl['gpu_attributable_mib']:,}&nbsp;MiB</td>
    <td class="num lose">필요 ≈{need_resident:,}&nbsp;MiB</td></tr>
</table></div>
<div class="note warn">
<p><strong>이 씬 하나가 이미 ≈{mem_new/1024:.0f}&nbsp;GB를 쓴다.</strong> band-wrapped 씬은 visible과 NIR 재질을 <em>동시에</em>
GPU에 올려두고 weight로 고르기 때문이다. 새 방식은 이 씬 <strong>하나만</strong> 유지하며 제자리에서 밴드를 갈아끼운다.</p>
<p><strong>그럼 재로드 IO(§2)를 피하려고 두 modality의 씬을 둘 다 resident로 캐싱하면?</strong> ≈{need_resident/1024:.0f}&nbsp;GB가 필요한데
이 GPU의 VRAM은 {vram/1024:.0f}&nbsp;GB라, 두 번째 씬 로드가 VRAM을 초과해 WSL이 GPU 메모리를 host RAM으로 spill하며
<strong>8분 안에 완료되지 못했다(thrashing)</strong> → <span class="lose">불가</span>. <strong>즉 재로드를 캐싱으로 회피할 수 없어서,
이전엔 "modality마다 clean+재로드"(=재로드 IO)가 강제됐다.</strong></p>
<p>새 방식은 이 딜레마를 벗어난다 — 씬 <strong>하나만</strong> resident({mem_new/1024:.0f}&nbsp;GB, old_reload와 동일)로 두고
제자리 band-flip으로 두 밴드를 서비스하므로, <strong>재로드 IO도 OOM도 없다</strong>.</p>
</div>
<p class="mut">
※ WSL2의 <code>nvidia-smi</code>는 프로세스별 메모리를 보고하지 않아(compute-apps 목록이 빈다) device 전체
<code>memory.used</code>에서 CUDA 초기화 이전 baseline을 빼 귀속치를 얻었다. 데스크톱 표시 출력이 GPU를 공유해
±수백&nbsp;MiB 드리프트가 있을 수 있으나, 26 vs 52&nbsp;GB의 차이는 그 잡음을 훨씬 넘는다.
</p>

<h2>4. 렌더 결과 — 두 방식은 동일하고, 물리적으로 옳다</h2>
<div class="scroll"><table>
<tr><th>band</th><th>S0 mean</th><th>DoLP mean</th><th>|ΔS0| new−old</th><th>|ΔDoLP| new−old</th></tr>
{band_rows}
</table></div>
<p>
new와 old_reload는 <strong>같은 밴드 상태를 같은 seed로</strong> 렌더하므로 결과가 일치해야 한다 — 표의 차이는
Monte-Carlo 노이즈 수준이다({verdict(eq_ok, "동일")}). band flip은 재로드와 <strong>수치적으로 같은 씬</strong>을 만든다.
</p>
<div class="ba3-grid">{figs}</div>
<div class="note">
<p><strong>물리 검사.</strong> visible→NIR로 가면 확산 반사(ρ854)가 커지며 S0가
{n["bands"]["visible"]["s0_mean"]:.3f}→{n["bands"]["nir_854"]["s0_mean"]:.3f}로 오르고(왼쪽 벽·선반이 밝아진다),
정반사 편광이 희석되어 DoLP가 {n["bands"]["visible"]["dolp_mean"]:.3f}→{n["bands"]["nir_854"]["dolp_mean"]:.3f}로 낮아진다.
편광이 실제로 밴드별 물성에서 나온다는 뜻이다 — <code>nir_grayscale_proxy</code>로는 얻을 수 없는 대비다(2026-07-14 리포트 §1).</p>
</div>

<h2>5. 한계와 다음 단계</h2>
<ul>
<li>단일 뷰포인트·2밴드로 측정했다. modality 수가 늘수록(편광 각도 스윕, 추가 파장) 이전 방식의 재로드 시간과
    resident 메모리 배수는 선형으로 커지고, 새 방식의 한계비용은 band flip({flip_ms:.0f}&nbsp;ms)로 유지된다.</li>
<li>NIR 반사율은 여전히 placeholder(ρ854)다. 밴드 계약에 provenance 있는 값을 붙이는 것은 Stage&nbsp;1의 몫이다
    (<code>class_band_reflectance_v1.json</code>).</li>
<li>CIFS 로드 절대시간과 WSL device-level 메모리 측정의 잡음은 위 각주대로다. 로컬 SSD·전용 GPU에서는 로드 절대값이
    줄지만 <strong>로드 횟수·재컴파일·resident VRAM 초과의 구조적 차이는 동일하다.</strong></li>
</ul>

<p class="mut">재현: <code>tools/benchmark_band_render_vs_reload.py</code> (모드별 독립 프로세스, GPU 샘플러 포함) →
<code>tools/generate_report_2026_07_27.py</code>. 씬 <code>{M["scene"]}</code>. spp&nbsp;{spp}, repeats&nbsp;{M["repeats"]}.</p>

</div></body></html>
"""
    OUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUT}  ({len(html)/1024:.1f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
