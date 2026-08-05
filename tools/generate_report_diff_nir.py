#!/usr/bin/env python3
"""Report: active-NIR flash/no-flash DIFFERENTIAL imaging protocol (kitchen QA).

Scans dev_report/images/kitchen_diff_nir_2026-08-04/ (written by
tools/render_kitchen_unified.py --nir-flash) and lays out, per viewpoint, the 5-pass
protocol + active polarization:

  RGB passive · NIR I_off · NIR I_on(observation) · ΔI=I_on−I_off · flash-only DIRECT GT
  · DoP(I_on) · AoLP(I_on)

The point of the report is the firefly resolution: fireflies are LEGITIMATE sensor
content in the path-traced observation (I_on) and are kept unclamped; the clean
specular-recovery GT comes from a separate flash-only `direct` integrator pass that has
no indirect paths, so it is firefly-free BY CONSTRUCTION — no clamp/despeckle on any raw
float EXR (despeckle is preview-PNG-only, off by default).

    python tools/generate_report_diff_nir.py
"""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
IMG_REL = "images/kitchen_diff_nir_2026-08-04"
IMG_DIR = REPO / "dev_report" / IMG_REL
OUT = REPO / "dev_report/report_2026-08-05_diff_nir.html"

# (file suffix, column title, caption)
COLS = [
    ("rgb", "RGB passive", "visible 밴드(weight 0) Stokes S0 · ambient only · path d8. 표준 passive 관측."),
    ("nir_passive", "NIR I_off", "NIR 밴드(weight 1) · ambient only, flash OFF · path d8. 수동 NIR."),
    ("nir_active", "NIR I_on (관측)", "ambient + flash · path d8. <b>네트워크가 보는 전체 관측</b>: highlight+shadow+"
                   "wall bounce+glass+indirect+caustic. <b>firefly는 정당한 센서 신호</b> → raw EXR unclamped, despeckle 안 함."),
    ("nir_dflash", "ΔI = I_on − I_off", "선형 이미지 공간 차분 = <b>active-light response</b>(실센서 flash/no-flash "
                   "differential과 동일). signed EXR. 두 독립 MC 렌더 차분이라 노이즈 증폭됨."),
    ("nir_flash_direct", "flash DIRECT GT", "flash ON, <b>ambient OFF</b>, <code>direct</code> integrator. indirect 경로 0 "
                         "→ caustic firefly가 <b>구조적으로 없음</b>. specular-recovery <b>GT(clean)</b>."),
    ("dop", "DoP (I_on)", "관측(I_on) 밴드 Stokes 편광도. glass/specular에서 편광(빨강), diffuse 검정."),
    ("aolp", "AoLP (I_on)", "편광각을 hue로 · 채도=DoLP(무편광 흰색). 창유리·모서리에서 선명."),
]

CSS = """
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
 max-width:1400px;margin:0 auto;padding:24px;color:#1a1a1a;background:#fafafa}
h1{font-size:24px} h2{font-size:19px;margin-top:32px;border-bottom:2px solid #eee;padding-bottom:6px}
.sub{color:#666;font-size:14px} code{background:#f0f0f0;padding:1px 5px;border-radius:3px;font-size:13px}
.note{background:#f4f7fb;border-left:3px solid #4a7fc0;padding:10px 14px;margin:12px 0;font-size:14px;line-height:1.55}
.good{background:#f2faf3;border-left:3px solid #3fa34d}
.grid{display:grid;grid-template-columns:repeat(7,1fr);gap:8px;margin:14px 0}
.cell{background:#fff;border:1px solid #e3e3e3;border-radius:6px;overflow:hidden}
.cell img{width:100%;display:block;background:#222}
.cap{padding:6px 8px;font-size:11px} .cap b{font-size:12px}
.mut{color:#777;font-size:11px} table{border-collapse:collapse;font-size:13px;margin:8px 0}
td,th{border:1px solid #ddd;padding:4px 10px;text-align:right} th{background:#f5f5f5}
td.l,th.l{text-align:left}
.pipe{background:#fff;border:1px solid #e3e3e3;border-radius:6px;padding:12px 16px;font-size:14px;line-height:1.7}
"""


def _versioned(name: str) -> str:
    """Per-content hardlink `<stem>__v<mtime>.png` to defeat file:// same-name caching."""
    p = IMG_DIR / name
    ver = int(p.stat().st_mtime)
    stem, ext = os.path.splitext(name)
    vname = f"{stem}__v{ver}{ext}"
    vpath = IMG_DIR / vname
    if not vpath.exists():
        for old in IMG_DIR.glob(f"{stem}__v*{ext}"):
            old.unlink()
        try:
            os.link(p, vpath)
        except OSError:
            shutil.copy2(p, vpath)
    return vname


def _viewpoints() -> list[str]:
    """Discover viewpoint stems `vp<idx>_<node>` from the rgb previews, ordered by idx."""
    stems = set()
    for f in IMG_DIR.glob("vp*_rgb.png"):
        stems.add(f.name[:-len("_rgb.png")])
    def key(s):
        m = re.match(r"vp(\d+)_", s)
        return int(m.group(1)) if m else 0
    return sorted(stems, key=key)


def main() -> int:
    vps = _viewpoints()
    sections = ""
    for stem in vps:
        cells = ""
        for suf, title, desc in COLS:
            name = f"{stem}_{suf}.png"
            if not (IMG_DIR / name).is_file():
                cells += f'<div class="cell"><div class="cap mut">({title}: 없음)</div></div>'
                continue
            cells += (f'<div class="cell"><img src="{IMG_REL}/{_versioned(name)}" alt="{title}">'
                      f'<div class="cap"><b>{title}</b><br><span class="mut">{desc}</span></div></div>')
        nid = stem.split("_", 1)[1]
        sections += (f'<h2>Viewpoint <code>{nid}</code></h2>'
                     f'<div class="grid">{cells}</div>')

    html = f"""<!doctype html><html><head><meta charset="utf-8">
<title>Active-NIR differential imaging protocol (2026-08-05)</title><style>{CSS}</style></head><body>
<h1>Active-NIR flash/no-flash 차분 이미징 프로토콜 — firefly 근본해결</h1>
<p class="sub">2026-08-05 · scene <code>infinigen_single_room_kitchen_20260730</code> ·
{len(vps)} viewpoints · 640×480 · unified discrete-band Stokes carrier ·
순수 analytic(pplastic·roughconductor·dielectric) · spp 256 ·
Device 1 / RTX 5090 / <code>cuda_ad_rgb_polarized</code> · 산출물 <code>dev_report/{IMG_REL}</code></p>

<div class="pipe"><b>문제.</b> NIR active-flash 관측에 흰 "밀가루" 반점(firefly)이 낀다. 이는 밝고 작은 광원이
near-mirror(source-faithful roughconductor η≈0.0001/k≈1) · 유리에서 diffuse로 만드는 <b>caustic(SDS 간접경로)</b>이며
spp를 올려도 잘 안 사라진다. <b>clamp/despeckle로 지우면 안 된다</b> — inverse-rendering GT의 bright-path 에너지를
잘라 관측·타깃을 왜곡한다. point→area emitter 교체(I/(4·half²)≈444k radiance)로도 안 줄었다(작은 LED는 본질적으로 near-delta).
근본해결은 <b>integrator/pass 구조</b>다.</div>

<div class="note good"><b>해결 — flash/no-flash 차분 프로토콜(뷰포인트당 5패스).</b> 모든 패스의 raw는 <b>unclamped float EXR</b>.
<table>
<tr><th class="l">패스</th><th>ambient</th><th>flash</th><th class="l">integrator</th><th class="l">역할</th></tr>
<tr><td class="l">RGB passive</td><td>ON</td><td>OFF</td><td class="l">path d8</td><td class="l">visible 관측</td></tr>
<tr><td class="l">NIR I_off</td><td>ON</td><td>OFF</td><td class="l">path d8</td><td class="l">수동 NIR</td></tr>
<tr><td class="l">NIR I_on</td><td>ON</td><td>ON</td><td class="l">path d8</td><td class="l"><b>관측</b>(네트워크 입력) — firefly 정당·보존</td></tr>
<tr><td class="l">ΔI=I_on−I_off</td><td>—</td><td>—</td><td class="l">파생(선형)</td><td class="l">active-light response(센서 differential)</td></tr>
<tr><td class="l">flash DIRECT GT</td><td><b>OFF</b></td><td>ON</td><td class="l"><b>direct</b></td><td class="l"><b>clean specular GT</b> — firefly 구조적 부재</td></tr>
</table>
관측(I_on)의 firefly는 로봇 센서가 실제로 기록하는 정당한 신호라 그대로 두고, specular 복원용 <b>깨끗한 타깃</b>은
indirect 경로가 아예 없는 <b>flash-only <code>direct</code></b> 패스에서 얻는다. clamp 불필요.</div>

<div class="note"><b>검증(spp64 smoke, vp_000005@180).</b> NIR I_on의 3×3 firefly <b>120개</b>(raw max 23419) →
flash DIRECT GT <b>26개(−78%)</b>. direct의 raw max는 여전히 높지만(30420) 그건 <b>진짜 direct specular lobe</b>
(near-mirror에 flash 정반사)이지 dirt가 아니다. 프리뷰상 I_on의 어두운 창에 흩뿌려진 반점이 DIRECT GT에선
<b>깨끗한 검정</b>으로 사라지고 정반사점 1개만 남는다.</div>

{sections}

<h2>메모</h2>
<ul style="font-size:14px;line-height:1.7">
<li><b>firefly = caustic이지 MC dirt 아님.</b> Mitsuba3엔 BDPT/PPM/MLT가 없고 ptracer만 caustic 지향이나,
이 프로토콜에선 <b>ptracer 불필요</b> — 관측은 path 그대로(firefly OK), GT는 direct로 clean.</li>
<li><b>raw는 절대 clamp 안 함.</b> <code>_declutter_fireflies</code>는 preview PNG 전용·기본 off(<code>--preview-despeckle</code>).
raw float EXR(GT·관측·ΔI)은 항상 unclamped.</li>
<li><b>scene-sequential 필수.</b> path·direct 두 밴드씬(각 424 material×2 blendbsdf)을 동시 resident 하면 GPU 메모리
고갈→Dr.Jit malloc-cache thrash(무한 느려짐). path씬으로 전 뷰포인트 관측 → <code>del</code>+<code>gc</code>+
<code>dr.flush_malloc_cache()</code> → direct씬 로드해 GT.</li>
<li><b>integrator는 traverse로 못 바꿈</b> → <code>build_band_scene(integrator="path"|"direct")</code>로 XML 2개
(<code>scene_band.xml</code>·<code>scene_band_direct.xml</code>) 생성. ambient 토글은 <code>.radiance.value</code> 중
flash 아닌 4개(constant sky + area ceiling 3개)를 0으로.</li>
<li><b>ΔI 노이즈.</b> 두 독립 MC 렌더 차분이라 노이즈가 증폭된다(spp 올리면 개선). 관측 자체의 spp256 Stokes 그레인은
firefly와 별개(필요시 denoise/고spp).</li>
<li><b>vp_000016 관측.</b> 이 뷰포인트는 passive S0≈0.001(RGB·NIR passive가 거의 검정 — 어두운 코너를 봄). flash가
씬을 드러내는 유일한 광원이라 <b>active 조명이 가장 중요한 케이스</b>이고 DIRECT GT가 가장 깨끗하다.</li>
<li><b>실행.</b> <code>LD_LIBRARY_PATH=/usr/lib/wsl/lib PYTHONPATH=build/mitsuba3-optix7/python /usr/bin/python3
tools/render_kitchen_unified.py --nir-flash --spp 256 --viewpoints ...</code>
(이 호스트의 <code>cuda_ad_rgb_polarized</code>는 repo-local optix7 빌드에만 있고 <b>/usr/bin/python3(3.10)</b> 필요).</li>
</ul>
</body></html>"""
    OUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUT}  ({len(html)/1024:.1f} KB, {len(vps)} viewpoints)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
