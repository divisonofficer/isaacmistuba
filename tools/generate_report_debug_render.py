#!/usr/bin/env python3
"""Report for the rig-faithful debug render (skill: debug-render).
Reads dev_report/images/debug_render_rig/debug_render.json -> dev_report/report_debug_render.html
"""
from __future__ import annotations
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
IMG = "images/debug_render_rig"
D = REPO / "dev_report/images/debug_render_rig/debug_render.json"
OUT = REPO / "dev_report/report_debug_render.html"
MODS = [("s0", "S0"), ("dop", "DoP (red-black)"), ("aolp", "AoLP"),
        ("s1s0", "S1/S0"), ("s2s0", "S2/S0"), ("s3s0", "S3/S0")]
CSS = """
:root{--bg:#0f1216;--fg:#e6e9ef;--mut:#9aa4b2;--line:#232a33;--ok:#39d98a;--acc:#6aa9ff;--warn:#ffcc66}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.6 -apple-system,"Segoe UI",Roboto,"Noto Sans KR",sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:40px 24px 80px}h1{font-size:24px;margin:0 0 6px}
h2{font-size:18px;margin:30px 0 8px;padding-top:14px;border-top:1px solid var(--line)}h3{font-size:14px;color:var(--acc);margin:14px 0 4px}
.sub{color:var(--mut);margin:0 0 20px}code{background:#1a1f26;padding:1px 6px;border-radius:4px;font-size:13px}
table{border-collapse:collapse;width:100%;margin:8px 0;font-size:13px}th,td{border:1px solid var(--line);padding:5px 8px;text-align:left}
th{background:#161b22;color:var(--mut)}.note{background:#141920;border-left:3px solid var(--acc);padding:12px 16px;margin:14px 0;border-radius:0 8px 8px 0}
.warn{border-left-color:var(--warn)}.mut{color:var(--mut);font-size:12px}
.grid{display:grid;grid-template-columns:110px repeat(6,1fr);gap:4px;margin:4px 0 14px;align-items:center}
.grid img{width:100%;border:1px solid var(--line);border-radius:3px;display:block;background:#000;aspect-ratio:1.25;object-fit:cover}
.grid .cap{font-size:11px;color:var(--mut);text-align:center}.grid .rl{font-size:12px;text-align:right;padding-right:6px}
.legend{font-size:12px;color:var(--mut);margin:6px 0}.sw{display:inline-block;width:40px;height:9px;border-radius:2px;vertical-align:middle;margin:0 4px}
"""


def main() -> int:
    d = json.loads(D.read_text())
    head = '<div class="grid"><div class="rl"></div>' + "".join(f'<div class="cap">{l}</div>' for _, l in MODS) + "</div>"
    blocks = ""
    for vp in d.get("viewpoints", []):
        blocks += (f'<h2>viewpoint {vp["vi"]} <span class=mut>· base (x={vp["x"]}, y={vp["y"]}, yaw={vp["yaw_deg"]}°)</span></h2>')
        for s in vp["sensors"]:
            rows = ""
            for band in s["spectra"]:
                cells = "".join(f'<div><img src="{IMG}/vp{vp["vi"]}_{s["sensor_id"]}_{band}_{k}.png"></div>' for k, _ in MODS)
                bm = s["bands"].get(band, {})
                rl = f'{band}<div class=mut>S0 {bm.get("s0_mean",0):.3f}<br>DoP {bm.get("dop_mean",0):.3f}</div>'
                rows += f'<div class="grid"><div class="rl">{rl}</div>{cells}</div>'
            dep = ""
            if s.get("depth"):
                dd = s["depth"]
                dep = (f'<div style="display:flex;gap:8px;align-items:flex-start;margin:2px 0 6px">'
                       f'<div><img src="{IMG}/vp{vp["vi"]}_{s["sensor_id"]}_depth.png" '
                       f'style="width:150px;border:1px solid var(--line);border-radius:3px;aspect-ratio:1.25;object-fit:cover;background:#000">'
                       f'<div class=cap>Depth (AOV) · {dd.get("min_m")}–{dd.get("max_m")} m · valid {dd.get("valid_frac",0)*100:.0f}%</div></div></div>')
            blocks += (f'<h3>{s["sensor_id"]} <span class=mut>· {s["sensor_type"]} · fov {s["fov_h_deg"]:.0f}° · '
                       f'mount {s["mount"]} · modalities {s["modalities"]}</span></h3>{head}{rows}{dep}')
        if vp.get("lidar"):
            ld = vp["lidar"]
            blocks += (f'<h3>LiDAR (geometric spinning range cast) <span class=mut>· {ld["rings"]}×{ld["az"]} '
                       f'· hit {ld.get("hit_frac",0)*100:.0f}% · {ld.get("min_m")}–{ld.get("max_m")} m</span></h3>'
                       f'<img src="{IMG}/vp{vp["vi"]}_lidar.png" style="width:100%;max-width:960px;border:1px solid var(--line);'
                       f'border-radius:3px;image-rendering:pixelated"><div class=cap>세로=elevation ring, 가로=azimuth 0–360° · '
                       f'색=range (viridis, 검정=미반사)</div>')
        # NIR albedo 정책 비교 (메인 씬, 동일 조건 lit NIR 렌더, albedo만 교체)
        if (REPO/"dev_report"/f"{IMG}/vp{vp['vi']}_nir_physical.png").is_file():
            vi = vp["vi"]
            blocks += (f'<h3>NIR albedo 정책 비교 (메인 씬, grayscale · 동일 카메라·조명·spp4096, NIR band) — polar_cam</h3>'
                       f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;max-width:720px">'
                       f'<div><img src="{IMG}/vp{vi}_nir_physical.png" style="width:100%;border:1px solid var(--line);border-radius:3px;background:#000">'
                       f'<div class=cap>① 물리 NIR (원본 씬 재질 reflectance)</div></div>'
                       f'<div><img src="{IMG}/vp{vi}_nir_pseudo.png" style="width:100%;border:1px solid var(--line);border-radius:3px;background:#000">'
                       f'<div class=cap>② pseudo-NIR (모든 albedo→max(rgb,1−rgb)·[.229,.587,.114] 텍스처 치환)</div></div></div>')

    html = f"""<!doctype html><html lang=ko><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>Debug Render — camera rig</title><style>{CSS}</style></head>
<body><div class=wrap>
<h1>Rig-faithful 디버그 렌더 — {d['rig']}</h1>
<p class=sub>skill <code>debug-render</code>의 예시 출력 · camera rig 정의를 따라 <b>{len(d.get('viewpoints',[]))} viewpoint × 모든 센서 × 스펙트럼</b>을
<b>단일 resident scene load</b>({d['load_scene_s']}s)에서 렌더 · {d['n_render']} renders · spp {d['spp']} ·
mount={d.get('mount_convention','zup')} · variant <code>cuda_ad_rgb_polarized</code></p>

<div class=note><b>규칙.</b> 디버그 렌더는 임의 카메라가 아니라 <b>camera rig 정의</b>(<code>out/control_plane_cache/camera_rigs/{d['rig']}.json</code>)를
따라야 실제 의도한 광학 시스템과 매칭되는지 알 수 있다. 각 센서를 자기 mount pose·fov·modality의 스펙트럼으로 렌더하고,
하나의 스펙트럴-편광 씬을 band-flip으로 재사용해 rgb·nir·polarization을 <b>한 번의 로드</b>로 모두 얻는다(모달리티별 재로드=옛 IO 병목).</p></div>

<p class=legend>범례 — S0: 가시광 tonemap(RGB) / NIR grayscale ·
DoP <span class=sw style="background:linear-gradient(90deg,#000,#f00)"></span> 0–1 (√(S1²+S2²+S3²)/S0, 원편광 포함) ·
AoLP <span class=sw style="background:linear-gradient(90deg,red,#ff0,#0f0,#0ff,#00f,#f0f,red)"></span> 방위각 ·
S1/S0·S2/S0·S3/S0 <span class=sw style="background:linear-gradient(90deg,#3b4cbf,#fff,#bf2626)"></span> −1…+1 ·
Depth·LiDAR range <span class=sw style="background:linear-gradient(90deg,#450a5a,#218f8d,#fde725)"></span> 근–원(m, 검정=미반사)</p>

<div class=note warn><b>Depth · LiDAR.</b> 각 카메라 센서는 <b>AOV depth</b>(pinhole 거리)를 함께 렌더한다.
뷰포인트마다 <b>기하 스피닝 LiDAR</b>(Ouster OS1-128류, elevation×azimuth ray-cast)로 range 이미지를 낸다.
⚠️ <b>진짜 transient ToF LiDAR</b>(time-resolved, <code>depth_transient</code>)는 <code>mitransient</code> 패키지 +
transient-capable Mitsuba variant가 필요한데 현 OptiX7 빌드엔 없어 이 환경에선 불가 — 여기서는 <b>기하 range cast</b>로 대체했다.
(transient 지원 빌드가 준비되면 <code>mitransient_adapter</code>로 교체 가능.)</div>

{blocks}

<h2>이 렌더가 잡아낸 것 (rig 규약 검증)</h2>
<div class=note warn><b>mount 높이 규약 불일치 — 이 렌더는 z-up(저자 의도)으로 보정했다.</b>
현재 프로덕션(<code>sensor_sweep._sensor_pose_from_xy_yaw</code>)은 <code>mount.xyz_m</code>를 <b>[lateral, height, forward]</b>(y-up)로 읽어
이 rig <code>[-0.2, 0.1, 1.5]</code>를 <b>높이 0.1m·전방 1.5m</b>로 해석 → 카메라가 바닥에 박힌다. 반면 rig는 ROS <code>base_link</code>
<b>[lateral, forward, height]</b>(z-up)로 <b>높이 1.5m</b>를 의도한 것으로 보인다. 위 패널은 <code>--mount-convention zup</code>로
<b>의도한 1.5m 눈높이</b>를 렌더한 것이다. <b>디버그 렌더가 rig을 그대로 따랐기에 이 y-up↔z-up 불일치가 드러났다</b> —
스킬의 존재 이유. 정상화하려면 프로덕션이 base_link z-up을 y-up으로 변환하도록 고쳐야 한다.</div>

<h2>LiDAR specular 동작 검증 — 거울에서 반사 지오메트리 range (거울 4개 씬)</h2>
<div class=note><b>실제 하드웨어처럼.</b> 기하 ray-cast가 거울/유리에서 첫 표면에 멈추면 거울을 "불투명"하게 인식한다(비물리적).
실제 LiDAR 빔은 거울에서 <b>반사·투과되어 그 너머 지오메트리를 접힌 경로로 range</b>한다. 그래서 <b>delta</b>(완전반사 거울 /
매끈 유리) hit 시 sampled specular 방향으로 광선을 이어가 diffuse return까지 경로를 누적한다(<code>--lidar-specular N</code> 바운스).
아래 씬은 specular 표면이 <b>13.8%</b>: naive(멈춤)에선 range 0.43–7.90 m, specular-follow에선 거울 픽셀이 반사 지오메트리를 잡아
0.43–<b>10.06 m</b>로 늘어난다.</div>
<div style="display:flex;flex-direction:column;gap:6px;margin:8px 0">
  <div><div class=cap>sb=0 naive — 거울/유리(빨강)가 평면으로 뭉개짐(표면 거리)</div>
    <img src="{IMG}/analysis_lidar_spec0.png" style="width:100%;border:1px solid var(--line);border-radius:3px;image-rendering:pixelated"></div>
  <div><div class=cap>sb=6 specular-follow — 거울 픽셀에 반사/투과된 방 지오메트리 깊이가 나타남</div>
    <img src="{IMG}/analysis_lidar_spec6.png" style="width:100%;border:1px solid var(--line);border-radius:3px;image-rendering:pixelated"></div>
</div>

<h2>NIR albedo 정책 통제 실험 — reflectance만 교체, 나머지 렌더 조건 동일</h2>
<div class=note><b>통제 조건.</b> 텍스처 있는 diffuse quad를 <b>동일 카메라·조명·spp(256)·integrator</b>로 세 번 렌더하고
<b>재질 reflectance만</b> 바꾼다. 셋 다 lit 렌더라 깨끗하고, 조명이 같아 정확히 비교된다.
(scene_band의 금속 재질은 albedo AOV가 정의되지 않아 앞선 AOV 방식이 깨졌던 것 — 이 실험은 diffuse만 써서 회피.)</div>
<div class="grid" style="grid-template-columns:repeat(3,1fr)">
  <div><img src="{IMG}/ctrl_rgb.png"><div class=cap>① RGB albedo 텍스처로 렌더 (원본)</div></div>
  <div><img src="{IMG}/ctrl_nir_physical.png"><div class=cap>② 물리 NIR albedo(class-prior 상수 0.5)로 렌더 — <b>grayscale</b></div></div>
  <div><img src="{IMG}/ctrl_nir_pseudo.png"><div class=cap>③ pseudo-NIR albedo(RGB텍스처→max(rgb,1−rgb)·[.229,.587,.114])로 렌더 — <b>grayscale</b></div></div>
</div>
<div class=note warn><b>통제 실험 결론.</b> 순수 diffuse에서는 ② 물리 NIR(상수)이 <b>완전 평탄</b>(텍스처 소실), ③ pseudo-NIR은 RGB에서 와서
<b>나무결·구조 보존</b>. 즉 pseudo-NIR은 <b>디테일을 살리지만 물리적 NIR 반사율이 아니다</b>(RGB 대비를 그림).</div>
<div class=note><b>메인 씬(scene_band) 실측 — 각 viewpoint의 "NIR albedo 정책 비교" 참조.</b> 모든 <code>_albedo.png</code>(164개)를
pseudo-NIR로 교체해 동일 조건(카메라·조명·spp4096·NIR band)으로 렌더하니 <b>물리 vs pseudo가 거의 동일</b>(corr <b>0.997~0.999</b>,
diff 4.9% 픽셀만 &gt;3/255). 이유: 이 씬은 순수 diffuse가 없고 <b>pplastic(코팅 확산 432) + 금속(316)</b> 지배라, 저조도 NIR 외관이
<b>Fresnel/specular 코팅 + 조명·기하</b>에 지배되고 <b>diffuse albedo(→pseudo) 기여가 작다</b>. 결론: <b>이 재질 구성에선 NIR albedo
정책(물리 vs pseudo)이 렌더에 거의 영향 없음</b> — 통제 실험처럼 순수 diffuse일 때만 정책 차이가 크게 드러난다. class-prior 합성 본 경로는
Infinigen import(<code>nir_reflectance.py</code>).</div>

<p class=mut>재현: <code>tools/debug_render_rig.py --rig {d['rig']}</code> (depth·lidar·specular 포함) → <code>tools/generate_report_debug_render.py</code> ·
skill: <code>.claude/skills/debug-render/SKILL.md</code></p>
</div></body></html>"""
    OUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUT} ({len(html)/1024:.1f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
