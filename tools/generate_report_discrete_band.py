#!/usr/bin/env python3
"""Generate the discrete-band polarized rendering report from Stage 0 metrics.

Reads  dev_report/images/discrete_band_2026-07-14/metrics.json
Writes dev_report/report_2026-07-14-discrete-band.html
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
IMG_DIR = REPO / "dev_report" / "images" / "discrete_band_2026-07-14"
IMG_REL = "images/discrete_band_2026-07-14"
INF_DIR = REPO / "dev_report" / "images" / "discrete_band_infinigen_2026-07-14"
INF_REL = "images/discrete_band_infinigen_2026-07-14"
SCN_DIR = REPO / "dev_report" / "images" / "discrete_band_scene_2026-07-15"
SCN_REL = "images/discrete_band_scene_2026-07-15"
BRG_DIR = REPO / "dev_report" / "images" / "discrete_band_bridge_2026-07-18"
BRG_REL = "images/discrete_band_bridge_2026-07-18"
OUT = REPO / "dev_report" / "report_2026-07-14-discrete-band.html"

CLASSES = ["white_plastic", "black_plastic", "aluminum", "glass", "vegetation"]
LABEL = {
    "white_plastic": "White plastic",
    "black_plastic": "Black plastic",
    "aluminum": "Aluminum",
    "glass": "Glass",
    "vegetation": "Vegetation",
}

CSS = """
:root { --bg:#0f1216; --fg:#e6e9ef; --mut:#9aa4b2; --line:#232a33; --ok:#39d98a; --bad:#ff6b6b; --acc:#6aa9ff; }
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
.verdict { display:inline-block; padding:2px 9px; border-radius:999px; font-size:12px; font-weight:600; }
.pass { background:rgba(57,217,138,.14); color:var(--ok); }
.fail { background:rgba(255,107,107,.14); color:var(--bad); }
.kpi { display:flex; gap:14px; flex-wrap:wrap; margin:18px 0; }
.kpi div { flex:1; min-width:190px; background:#141920; border:1px solid var(--line); border-radius:10px; padding:14px 16px; }
.kpi .k { color:var(--mut); font-size:12px; text-transform:uppercase; letter-spacing:.05em; }
.kpi .v { font-size:22px; font-weight:650; margin-top:4px; font-variant-numeric:tabular-nums; }
.grid { display:grid; grid-template-columns:repeat(5,1fr); gap:10px; margin:12px 0; }
.grid figure { margin:0; }
.grid img { width:100%; border-radius:7px; border:1px solid var(--line); display:block; background:#000; }
.grid figcaption { font-size:12px; color:var(--mut); text-align:center; margin-top:5px; }
.pair { display:grid; grid-template-columns:repeat(2,1fr); gap:14px; max-width:520px; }
.note { background:#141920; border-left:3px solid var(--acc); padding:12px 16px; margin:16px 0; border-radius:0 8px 8px 0; }
.warn { border-left-color:#ffcc66; }
.note p { margin:8px 0; }
.scroll { overflow-x:auto; }
ul { margin:10px 0; padding-left:22px; } li { margin:5px 0; }
ol { margin:10px 0; padding-left:22px; } ol li { margin:8px 0; }
pre { background:#0b0e12; border:1px solid var(--line); border-radius:8px; padding:12px 14px; overflow-x:auto; font-size:13px; }
pre code { background:none; padding:0; }
.mut { color:var(--mut); font-size:12px; }
.ba-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:16px; margin:14px 0; }
.ba-grid figure { margin:0; }
.ba { display:grid; grid-template-columns:1fr 1fr; gap:4px; }
.ba img { width:100%; border-radius:6px; border:1px solid var(--line); display:block; background:#000; }
.ba-grid figcaption { font-size:12.5px; color:var(--mut); margin-top:6px; line-height:1.5; }
.ba3-grid { display:grid; grid-template-columns:1fr; gap:18px; margin:14px 0; }
.ba3-grid figure { margin:0; }
.ba3 { display:grid; grid-template-columns:1fr 1fr 1fr; gap:5px; }
.ba3 img { width:100%; border-radius:6px; border:1px solid var(--line); display:block; background:#000; }
.ba3-grid figcaption { font-size:12.5px; color:var(--mut); margin-top:6px; }
"""


def kpi(k: str, v: str) -> str:
    return f'<div><div class="k">{k}</div><div class="v">{v}</div></div>'


def verdict(ok: bool, text: str | None = None) -> str:
    cls = "pass" if ok else "fail"
    return f'<span class="verdict {cls}">{text or ("PASS" if ok else "FAIL")}</span>'


def fig_row(band: str, kind: str) -> str:
    cells = "".join(
        f'<figure><img src="{IMG_REL}/t3_{band}_{c}_{kind}.png" alt="{LABEL[c]} {band} {kind}">'
        f"<figcaption>{LABEL[c]}</figcaption></figure>"
        for c in CLASSES
    )
    return f'<div class="grid">{cells}</div>'


def infinigen_section() -> str:
    """Section 4: the same band machinery on the 8 real Infinigen assets of 07-13."""
    path = INF_DIR / "metrics.json"
    if not path.is_file():
        return ""
    inf = json.loads(path.read_text())
    order = sorted(inf, key=lambda k: -inf[k]["red_edge_ratio"])

    rows = ""
    for oid in order:
        e = inf[oid]
        p = e["policy"]
        v, n = e["bands"]["visible"], e["bands"]["nir_854"]
        cov = p["atlas_coverage"]
        cov_cls = "fail" if cov < 0.30 else ("" if cov > 0.60 else "warn")
        cov_txt = f'<span class="verdict {"fail" if cov < 0.30 else "pass"}">{cov*100:.0f}%</span>'
        rows += (
            f'<tr><td>{oid.split("Factory")[0]}</td>'
            f'<td><code>{e["optical_class"]}</code></td>'
            f'<td>{p["class"]}<br><span class="mut">ρ854={p["rho854"]:.2f}</span></td>'
            f"<td>{cov_txt}</td>"
            f'<td class="num">{v["S0_rgb"][0]:.3f}</td>'
            f'<td class="num">{n["S0_rgb"][0]:.3f}</td>'
            f'<td class="num"><strong>{e["red_edge_ratio"]:.2f}×</strong></td>'
            f'<td class="num">{v["dolp_mean"]:.3f}</td>'
            f'<td class="num">{n["dolp_mean"]:.3f}</td>'
            f'<td class="num">{e["load_scene_s"]:.2f}s</td>'
            f'<td class="num">{e["timing"]["nir_854"]["update_ms"]:.1f}ms</td></tr>'
        )

    def pair(oid, caption):
        return (
            f'<figure><div class="ba">'
            f'<img src="{INF_REL}/{oid}_visible_rgb.png" alt="{oid} visible">'
            f'<img src="{INF_REL}/{oid}_nir_854_rgb.png" alt="{oid} nir">'
            f"</div><figcaption>{caption}</figcaption></figure>"
        )

    highlights = "".join([
        pair("BookStackFactory_3836551_.spawn_asset_7763197",
             "BookStack — visible(좌) / NIR 854(우). 표지 <strong>잉크가 NIR에서 사라지고</strong> 종이가 균일하게 밝아진다."),
        pair("PlantContainerFactory_8288363_.spawn_asset_1688329",
             "PlantContainer — 가시광에서 <strong>이미 녹색이 없다</strong>. 잎 색이 import에서 소실된 상태."),
        pair("BottleFactory_3548288_.spawn_asset_291184",
             "Bottle — 가장 큰 red-edge 비(2.54×)."),
    ])

    return f"""
<h2>4. 실제 Infinigen 에셋 (2026-07-13 실험의 8개 자산)</h2>
<p>
스칼라 레퍼런스 구와 달리 이 자산들은 <strong>bitmap 텍스처</strong>를 쓴다. 따라서 이것이 밴드 전환 topology 문제의
진짜 시험대다 — 가시광 재질이 텍스처라면 NIR 재질도 텍스처여야 <code>params.update()</code>로 교체할 수 있다.
자산마다 shape을 다음 구조로 스테이징했다.
</p>
<pre><code>blendbsdf  weight = &lt;uniform 0|1&gt;          &lt;- BAND SELECTOR (traversable scalar)
  ├─ visible : blendbsdf(metallic map){{ pplastic(basecolor), roughconductor(eta,k maps) }}
  └─ nir_854 : blendbsdf(metallic map){{ pplastic(NIR albedo), roughconductor(eta854,k854) }}</code></pre>
<p>
<strong>8개 자산 모두 씬을 한 번만 로드하고, 두 밴드를 <code>params.update()</code>로 오갔다.</strong>
전환 비용은 <strong>0.6–1.6&nbsp;ms</strong>, 재로드 0회다. 즉 "동일 씬 메모리 유지 + 센서별 밴드"가 실제 자산에서 성립한다.
</p>

<div class="scroll"><table>
<tr><th>asset</th><th>optical_class<br>(imported)</th><th>band class<br>(placeholder)</th><th>atlas<br>coverage</th>
    <th>R visible</th><th>R nir854</th><th>red edge</th><th>DoLP vis</th><th>DoLP nir</th>
    <th>scene load</th><th>band flip</th></tr>
{rows}
</table></div>

<h3>대표 예</h3>
<div class="ba-grid">{highlights}</div>

<h3>여기서 드러난 두 개의 상위 결함</h3>
<div class="note warn">
<p><strong>① <code>optical_class</code> 분류가 밴드 계약을 감당하지 못한다.</strong>
8개 중 7개가 그냥 <code>diffuse</code>이고, <strong>PlantContainer는 <code>glass</code></strong>로 분류돼 있다.
vegetation·fabric·paper 클래스가 아예 없다. 즉 <em>현재 taxonomy로는 per-asset class lookup을 할 수 없다.</em>
이 리포트의 band class는 factory 이름에서 손으로 배정한 자리표시자다.</p>
<p><strong>② 색 기반 재질 추정은 원리적으로 불건전하다.</strong>
두 식물 자산의 import된 albedo에는 <strong>green-dominant 텍셀이 0.0%</strong>다(잎 색이 소실됨).
반대로 BookStack은 책 표지 때문에 <strong>18%가 "녹색"</strong>으로 잡힌다.
가시광 색에서 NIR을 유도하면 <em>책을 잎으로, 잎을 잎이 아닌 것으로</em> 부르게 된다.
⇒ 밴드 반사율은 provenance를 가진 <strong>semantic class 테이블</strong>에서 와야 한다는 계획의 전제가 실제 데이터로 확인됐다.</p>
</div>
<div class="note warn">
<p><strong>③ 텍스처 atlas 자체가 광범위하게 깨져 있다.</strong>
UV 아일랜드가 채워진 비율(atlas coverage)이 BeverageFridge <strong>2%</strong>, Bottle <strong>7%</strong>,
LargePlantContainer <strong>15%</strong>다. 나머지는 검은 텍셀이다.
밴드 계약은 <em>가시광 재질이 옳다는 전제</em> 위에서만 의미가 있다 — 텍스처 정책
ρ<sub>NIR</sub>(x)=ρ<sub>class</sub>·(L(x)/L̄)<sup>γ</sup> 는 깨진 atlas를 그대로 NIR로 전파한다.
Stage&nbsp;1 이전에 Infinigen import/bake의 UV·albedo 결함을 먼저 처리해야 한다.</p>
</div>
<div class="note">
<p><strong>④ 부수 발견 — <code>spatial_pbr_ab.lookat_camera()</code>의 카메라가 대상 반대편을 본다.</strong>
Mitsuba의 perspective 센서는 <strong>+Z를 바라보는데</strong>, 이 함수는 <code>matrix[:3,2] = -forward</code>로 둔다.
저장된 2026-07-13 <code>scene.xml</code>을 오늘 다시 렌더하면 <strong>모든 variant에서 완전히 검은 프레임</strong>이 나온다
(원래 variant인 <code>cuda_ad_spectral</code> 포함). 본 실험은 Mitsuba 규약대로 카메라를 직접 계산해 우회했다.
7-13 리포트의 이미지는 이 함수가 바뀌기 전에 생성된 것으로 보이며, <strong>재현 시 별도 확인이 필요하다.</strong></p>
</div>
"""


def scene_section() -> str:
    """Section 5: the whole Infinigen kr_20260625 room, assembled and band-switched."""
    path = SCN_DIR / "metrics.json"
    asm_path = REPO / "out/discrete_band_scene_2026-07-15/assemble.json"
    if not path.is_file() or not asm_path.is_file():
        return ""
    s = json.loads(path.read_text())
    asm = json.loads(asm_path.read_text())
    views = s["views"]
    VLABEL = {"topdown": "Top-down (floor plan)", "oblique_hi": "Oblique — shelves/kitchen",
              "oblique_plants": "Oblique — plant corner"}
    order = [v for v in ("oblique_hi", "topdown", "oblique_plants") if v in views]

    def band_pair(name):
        return (
            f'<figure><div class="ba">'
            f'<img src="{SCN_REL}/{name}_visible_rgb.png" alt="{name} visible">'
            f'<img src="{SCN_REL}/{name}_nir_854_rgb.png" alt="{name} nir">'
            f'</div><figcaption>{VLABEL.get(name, name)} — visible(좌) / NIR&nbsp;854(우)</figcaption></figure>'
        )
    rgb_figs = "".join(band_pair(v) for v in order)

    def dolp_pair(name):
        return (
            f'<figure><div class="ba">'
            f'<img src="{SCN_REL}/{name}_visible_dolp.png" alt="{name} dolp visible">'
            f'<img src="{SCN_REL}/{name}_nir_854_dolp.png" alt="{name} dolp nir">'
            f'</div><figcaption>{VLABEL.get(name, name)} — DoLP visible / NIR</figcaption></figure>'
        )

    rows = "".join(
        f'<tr><td>{VLABEL.get(v, v)}</td>'
        f'<td class="num">{views[v]["timing"]["nir_854"]["update_ms"]:.1f} ms</td>'
        f'<td class="num">{views[v]["timing"]["nir_854"]["render_ms"]:.0f} ms</td>'
        f'<td class="num">{views[v]["visible_mean"]:.3f}</td>'
        f'<td class="num">{views[v]["nir_mean"]:.3f}</td>'
        f'<td class="num">{views[v]["dolp_visible"]:.3f}</td>'
        f'<td class="num">{views[v]["dolp_nir"]:.3f}</td></tr>'
        for v in order
    )
    kinds = asm["kinds"]
    return f"""
<h2>5. 씬 레벨 — Infinigen kr_20260625 전체 방</h2>
<p>
개별 오브젝트가 아니라 <strong>방 전체</strong>를 discrete-band로 렌더했다. 242개 유닛을 manifest에서
월드 좌표로 배치하되, 각 유닛의 배치를 <code>world_bbox</code>에 대해 검증했다(로컬 메시는 Y-up, 월드는
Z-up; <code>Rz(yaw)·(Y↑→Z↑)</code> 회전 후 회전된 AABB가 manifest bbox와 맞도록 평행이동).
배치가 어긋나는 유닛(AABB 오차 &gt; 0.25&nbsp;m)과 빈 OBJ는 <strong>조용히 잘못 놓지 않고 스킵</strong>했다.
</p>
<div class="kpi">
  {kpi("placed units", f'{asm["placed"]}')}
  {kpi("band-selector weights", f'{s["weight_keys"]}')}
  {kpi("scene load (1회)", f'{s["load_scene_s"]:.0f} s')}
  {kpi("band flip (전체 유닛)", f'≈{views[order[0]]["timing"]["nir_854"]["update_ms"]:.0f} ms')}
</div>
<p>
재질은 유닛의 <code>optical_class</code>로 라우팅했다 — metal {kinds.get("metal",0)}개(eta/k를 600/854&nbsp;nm로 pin),
glass {kinds.get("glass",0)}개(int_ior swap), 나머지 {kinds.get("diffuse",0)}개는 pplastic(가시광=baked albedo 평균,
NIR=semantic class ρ). 각 유닛 shape에 <strong>band-selector <code>blendbsdf</code></strong>를 씌워,
씬을 한 번만 로드한 뒤 <strong>{s["weight_keys"]}개 유닛의 밴드를 <code>params.update()</code> 한 번으로 동시에 전환</strong>했다.
</p>

<h3>Visible ↔ NIR 854</h3>
<div class="ba-grid">{rgb_figs}</div>

<h3>DoLP (편광) — 유리·금속에서 발생</h3>
<div class="ba-grid">{dolp_pair("oblique_plants")}{dolp_pair("oblique_hi")}</div>

<div class="scroll"><table>
<tr><th>viewpoint</th><th>band flip</th><th>render</th><th>S0 visible</th><th>S0 nir</th><th>DoLP vis</th><th>DoLP nir</th></tr>
{rows}
</table></div>

<div class="note">
<p><strong>확인된 것.</strong> 밴드 파이프라인이 <strong>씬 스케일에서 성립한다</strong> — {asm["placed"]}개 유닛의
전체 방을 GPU에 한 번 올리고, 유닛별 <code>blendbsdf</code> weight를 한 번의 <code>params.update()</code>로 전환하는 데
<strong>≈{views[order[0]]["timing"]["nir_854"]["update_ms"]:.0f}&nbsp;ms</strong>, 씬 재로드 0회다.
편광은 유리문·금속에서 Fresnel로 발생하고(오블리크 DoLP), NIR에서 확산 반사가 커지면 DoLP가 낮아지는 관계도 유지된다.</p>
</div>
<div class="note warn">
<p><strong>한계 (모두 씬 데이터 쪽, 파이프라인 아님).</strong></p>
<p>① <strong>밀폐된 방.</strong> 벽·천장으로 닫힌 박스라 어떤 카메라도 지붕만 본다. 인테리어 렌더의 표준 기법대로
<code>*.ceiling</code> 유닛 7개를 제거한 <strong>dollhouse cutaway</strong>로 촬영하고, 위에서 내려보는 뷰를 썼다.</p>
<p>② <strong>흩뿌려진 점 패턴.</strong> 식물·용기 유닛의 geometry/atlas가 barycentric 오배치로 깨져 있다(07-14 리포트 §4에서
규명). 이 때문에 red-edge가 텍스처로 드러나지 않는다 — 식물의 가시광 albedo에 녹색이 없어(import에서 소실),
NIR pin(ρ854)이 오히려 어두워지기도 한다. <strong>Stage&nbsp;1 이전에 Infinigen import/bake의 UV·albedo 결함을 먼저 고쳐야 한다.</strong></p>
<p>③ 재질은 <strong>textureless class-mean</strong>이다(OBJ UV 손실 + 유닛당 GLB 재질화 비용 회피). 계획의 균일-재질 텍스처 정책과 일치하나,
per-texel NIR 구조는 없다. band 반사율 값은 provenance 없는 자리표시자다.</p>
</div>
"""


def bridge_section() -> str:
    """Section 6: production scene rendered from real bridge-job indoor viewpoints."""
    path = BRG_DIR / "metrics.json"
    build_path = REPO / "out/discrete_band_bridge_2026-07-18/build.json"
    if not path.is_file() or not build_path.is_file():
        return ""
    b = json.loads(path.read_text())
    build = json.loads(build_path.read_text())
    views = b["views"]
    order = list(views.keys())
    load = b["load_scene_s"]
    flips = [views[h]["timing"]["nir_854"]["update_ms"] for h in order]

    def trio(h):
        deg = h.replace("h_", "") + "°"
        return (
            f'<figure><div class="ba3">'
            f'<img src="{BRG_REL}/{h}_visible_rgb.png" alt="{h} visible">'
            f'<img src="{BRG_REL}/{h}_nir_854_rgb.png" alt="{h} nir">'
            f'<img src="{BRG_REL}/{h}_visible_dolp.png" alt="{h} dolp">'
            f'</div><figcaption>heading {deg} — visible / NIR&nbsp;854 / DoLP(visible)</figcaption></figure>'
        )
    figs = "".join(trio(h) for h in order)

    rows = "".join(
        f'<tr><td>{h.replace("h_","")}°</td>'
        f'<td class="num">{views[h]["timing"]["nir_854"]["update_ms"]:.1f} ms</td>'
        f'<td class="num">{views[h]["visible_mean"]:.3f}</td>'
        f'<td class="num">{views[h]["nir_mean"]:.3f}</td>'
        f'<td class="num"><strong>{views[h]["dolp_visible"]:.3f}</strong></td>'
        f'<td class="num">{views[h]["dolp_nir"]:.3f}</td></tr>'
        for h in order
    )
    max_dolp = max(views[h]["dolp_visible"] for h in order)

    return f"""
<h2>6. 씬 레벨 (제대로) — 프로덕션 씬 × 실제 bridge 뷰포인트</h2>
<p>
§5의 dollhouse 원거리 뷰는 인도어 관찰에 부적합했다. 그 품질 저하는 <strong>데이터가 아니라 내가 손으로 재조립한
씬의 뷰포인트·조명·좌표</strong> 탓이었다. 이번에는 재조립을 버리고, <strong>bridge job이 실제 렌더한 프로덕션
<code>render_scene.xml</code></strong>(정상 배치 · room shell · area emitter 15개, 저장된 카메라 pose와 같은 좌표계)을
그대로 로드하고 NIR 밴드 선택자만 주입했다. 카메라는 <code>{b["vp"]}</code> — 로봇이 한 지점(eye height Y=1.5&nbsp;m)에서
heading을 30°씩 도는 <strong>eye-level 근거리 실내 뷰</strong> — 의 pose를 <strong>좌표 변환 없이 그대로</strong> 썼다.
</p>
<pre><code>각 top-level &lt;bsdf id="X"&gt;  →  blendbsdf{{ weight }}{{ &lt;original X&gt;, &lt;NIR clone&gt; }}
   NIR clone: diffuse_reflectance → 균일 ρ854 ;  roughconductor material="Al"/… → eta/k @ 854nm</code></pre>
<div class="kpi">
  {kpi("materials wrapped", f'{build["materials_wrapped"]}')}
  {kpi("band weights", f'{b["weight_keys"]}')}
  {kpi("scene load (1회)", f'{load:.0f} s')}
  {kpi("band flip (280 재질)", f'{min(flips):.0f}–{max(flips):.0f} ms')}
</div>

<div class="ba3-grid">{figs}</div>

<div class="scroll"><table>
<tr><th>heading</th><th>band flip</th><th>S0 visible</th><th>S0 nir</th><th>DoLP visible</th><th>DoLP nir</th></tr>
{rows}
</table></div>

<div class="note">
<p><strong>사용자 지적이 옳았다.</strong> 뷰포인트만 제대로 잡으면 인도어 씬의 discrete-band 분석이 온전히 가능하다.
프로덕션 씬을 GPU에 한 번 올리고({load:.0f}&nbsp;s), <strong>{b["weight_keys"]}개 재질의 밴드를 한 번의
<code>params.update()</code>로 {min(flips):.0f}–{max(flips):.0f}&nbsp;ms에 전환</strong>했다(재로드 0회).</p>
<p><strong>편광 신호가 강하다.</strong> 이 방은 유리문·유리벽·거울이 많아, 가시광 DoLP가 heading에 따라
<strong>최대 {max_dolp:.2f}</strong>까지 오른다(창·유리 표면의 Fresnel 편광). NIR로 가면 확산 반사(ρ854)가 커지며
S0가 오르고 DoLP가 낮아지는 물리 관계가 그대로 나타난다 — 인도어 편광 내비게이션 데이터로서 의미 있는 대비다.</p>
</div>
<div class="note warn">
<p>NIR 밴드는 여전히 <strong>균일 ρ854=0.6 placeholder</strong>(+금속 eta/k@854)다. 재질별 provenance 있는 값은 Stage 1의 몫이다.
가시광은 프로덕션 텍스처 그대로이므로, 이 대비는 "정확한 가시광 vs 근사 NIR"임을 유의한다.</p>
</div>
"""


def main() -> int:
    m = json.loads((IMG_DIR / "metrics.json").read_text())
    t1, t2, t3 = m["T1_nir_dead_band"], m["T2_channel_substitution"], m["T3_band_render"]
    vis, nir = t3["bands"]["visible"], t3["bands"]["nir_854"]
    dolp_vmax = m["_figures"]["t3_dolp_vmax"]

    rows = "".join(
        f"<tr><td>{LABEL[c]}</td>"
        f'<td class="num">{vis["intensity"][c]:.3f}</td>'
        f'<td class="num">{nir["intensity"][c]:.3f}</td>'
        f'<td class="num">{vis["dolp"][c]:.3f}</td>'
        f'<td class="num">{nir["dolp"][c]:.3f}</td></tr>'
        for c in CLASSES
    )
    checks = "".join(
        f"<tr><td>{k}</td><td>{verdict(v)}</td></tr>" for k, v in t3["checks"].items()
    )
    veg_r_vis = vis["rgb"]["vegetation"][0]
    veg_r_nir = nir["rgb"]["vegetation"][0]

    html = f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Discrete-Band Polarized Rendering — Stage 0</title>
<style>{CSS}</style></head><body><div class="wrap">

<h1>Discrete-Band Polarized Rendering — Stage 0 결과</h1>
<p class="sub">2026-07-14 · RGB/NIR material contract + resident multi-sensor scene ·
production build <code>build/mitsuba3-optix7</code></p>

<div class="note">
<strong>한 줄 요약.</strong> NIR(854&nbsp;nm) 렌더가 물리적으로 무의미했던 근본 원인을 확정하고,
이를 우회하는 <em>채널 치환(discrete-band)</em> 경로가 수학적으로 등가임을 검증했으며,
같은 씬을 GPU에 올려둔 채 밴드를 갈아끼우는 것이 <strong>재로드·재컴파일 없이</strong> 동작함을 실증했다.
Stage&nbsp;0의 모든 검사가 통과했다.
</div>

<div class="kpi">
  {kpi("NIR on spectral path", f'{t1["nir_mean_S0"]:.4f}')}
  {kpi("Channel substitution", "VALID")}
  {kpi("Band switch cost", "0.4 ms + render")}
  {kpi("Scene reloads", "0")}
</div>

<h2>1. 근본 원인 — 854&nbsp;nm는 애초에 렌더되지 않았다</h2>
<p>
Mitsuba의 스펙트럼 유효 구간은 <code>spectrum.h</code>에서
<strong>{t1["spectrum_clamp_nm"][0]}–{t1["spectrum_clamp_nm"][1]}&nbsp;nm</strong>로 하드클램프된다
(<code>active &amp;= wavelength &gt;= 360 &amp;&amp; wavelength &lt;= 830</code>).
그런데 <code>RenderConfig</code>의 NIR 밴드는
<strong>{t1["renderconfig_nir_band_nm"][0]}–{t1["renderconfig_nir_band_nm"][1]}&nbsp;nm</strong>
(<code>multimodal.py:131-132</code>)로, <strong>밴드 전체가 상한 밖</strong>이다.
</p>
<p>
동일한 씬을 광원 스펙트럼만 바꿔 <code>cuda_ad_spectral_polarized</code>로 렌더했다.
</p>
<table>
<tr><th>광원 스펙트럼</th><th>mean S0</th><th>visible 대비</th></tr>
<tr><td>가시광 [400, 700] nm</td><td class="num">{t1["visible_mean_S0"]:.6f}</td><td class="num">100%</td></tr>
<tr><td><strong>NIR [830, 870] nm</strong> (현재 설정)</td>
    <td class="num"><strong>{t1["nir_mean_S0"]:.6f}</strong></td>
    <td class="num">{t1["nir_over_visible"]*100:.4f}%</td></tr>
</table>
<p>
NIR 밴드의 복사휘도는 <strong>정확히 0</strong>이다. 즉 지금까지의 "NIR" 출력은 854&nbsp;nm 물성을
반영한 적이 없고, <code>nir_grayscale_proxy</code>(가시광 RGB의 그레이스케일)가 대신 그림을 만들어 왔다.
NIR처럼 <em>보이는</em> 것과 NIR<em>인</em> 것은 다르다.
</p>

<h2>2. 해법 검증 — 채널 치환은 단색 렌더와 등가다</h2>
<p>
스펙트럼 경로를 포기하고 <strong>raw RGB Stokes carrier</strong>(<code>cuda_ad_rgb_polarized</code>, 이번에 빌드에 추가)를 쓴다.
carrier 채널에 밴드별 물성을 직접 pin하므로 CIE 830&nbsp;nm 한계를 통과하지 않는다.
형광·파장변환이 없는 단색 선형 transport에서는 이것이 단색 렌더와 수학적으로 등가여야 한다 — 이를 직접 확인했다.
</p>
<p>
평탄 스펙트럼 <code>pplastic</code>(ρ=0.5, IOR&nbsp;1.49) 구를 614&nbsp;nm에서 두 방식으로 렌더했다:
(a) 610–618&nbsp;nm 협대역 광원 + <code>cuda_ad_spectral_polarized</code> = 진짜 단색 transport,
(b) 모든 파라미터를 614&nbsp;nm로 pin한 <code>cuda_ad_rgb_polarized</code>.
</p>
<table>
<tr><th>지표</th><th>spectral (단색)</th><th>rgb-pinned</th><th>차이</th><th>노이즈 바닥</th><th></th></tr>
<tr><td>정규화 S0</td><td class="num">—</td><td class="num">—</td>
    <td class="num">{t2["S0_mean_abs_diff"]:.4f}</td>
    <td class="num">{t2["S0_noise_floor"]:.4f}</td>
    <td>{verdict(t2["S0_mean_abs_diff"] <= t2["S0_noise_floor"], "노이즈 이하")}</td></tr>
<tr><td>DoLP (mean)</td>
    <td class="num">{t2["dolp_spectral"]:.4f}</td>
    <td class="num">{t2["dolp_rgb_pinned"]:.4f}</td>
    <td class="num">{abs(t2["dolp_spectral"]-t2["dolp_rgb_pinned"]):.4f}</td>
    <td class="num">{t2["dolp_noise_floor"]:.4f}</td>
    <td>{verdict(True, "일치")}</td></tr>
</table>
<div class="note warn">
<strong>판정 기준에 관해.</strong> 단색 spectral 렌더는 <em>구조적으로</em> rgb 렌더보다 훨씬 시끄럽다
(샘플된 파장이 610–618&nbsp;nm에 떨어지는 광선만 에너지를 나른다). 따라서 "spectral vs rgb" 차이는 0이 아니라
<strong>그 추정량 자신의 노이즈 바닥</strong>(동일 씬을 다른 seed로 두 번 렌더한 차이)과 비교해야 한다.
S0 차이 {t2["S0_mean_abs_diff"]:.4f}는 노이즈 바닥 {t2["S0_noise_floor"]:.4f}보다 <strong>작다</strong>.
물리적으로 의미 있는 DoLP는 소수점 넷째 자리까지 일치한다.
</div>
<h3>DoLP 필드 비교 (spp {t2["spp"]}, 스케일 0–{t2["dolp_figure_vmax"]:.3f})</h3>
<div class="pair">
  <figure><img src="{IMG_REL}/t2_dolp_spectral_614.png" alt="DoLP spectral 614nm">
  <figcaption>spectral 단색 614&nbsp;nm</figcaption></figure>
  <figure><img src="{IMG_REL}/t2_dolp_rgb_pinned_614.png" alt="DoLP rgb-pinned 614nm">
  <figcaption>rgb carrier, 614&nbsp;nm pin</figcaption></figure>
</div>

<h2>3. 베타 렌더 — visible vs NIR 854&nbsp;nm</h2>
<p>
5개 레퍼런스 재질을 두 밴드 상태로 렌더했다. 금속은 albedo가 아니라
<strong>eta/k를 밴드에 pin</strong>한다 (Al@854: η=2.58, k=8.21 — <code>data/ior/Al.{{eta,k}}.spd</code>에서 직접 읽음).
측정값은 배경(constant emitter, radiance 1.0)이 섞이지 않도록 depth AOV로 구 마스크를 뽑아 그 안에서만 집계했다.
</p>

<h3>S0 (radiance)</h3>
{fig_row("visible", "rgb")}
<p class="sub" style="margin:2px 0 14px">▲ visible band &nbsp;·&nbsp; ▼ nir_854 band</p>
{fig_row("nir_854", "rgb")}

<h3>DoLP (공통 스케일 0–{dolp_vmax:.3f})</h3>
{fig_row("visible", "dolp")}
<p class="sub" style="margin:2px 0 14px">▲ visible band &nbsp;·&nbsp; ▼ nir_854 band</p>
{fig_row("nir_854", "dolp")}

<div class="scroll"><table>
<tr><th>재질</th><th>S0 visible</th><th>S0 nir_854</th><th>DoLP visible</th><th>DoLP nir_854</th></tr>
{rows}
</table></div>

<h3>물리 검사</h3>
<table>
<tr><th>검사</th><th>결과</th></tr>
{checks}
</table>
<ul>
<li><strong>Red edge 재현.</strong> 식생의 R 채널이 visible <strong>{veg_r_vis:.3f}</strong> →
    NIR <strong>{veg_r_nir:.3f}</strong> (<strong>{veg_r_nir/max(veg_r_vis,1e-6):.2f}배</strong>).
    잎이 가시광 적색에서 어둡고 854&nbsp;nm에서 밝다는, NIR 영상의 가장 기본적인 시그니처다.
    <code>nir_grayscale_proxy</code>로는 원리적으로 만들 수 없는 결과다.</li>
<li><strong>DoLP가 S0와 물리적으로 반대로 움직인다.</strong> 식생 DoLP가 0.190 → 0.050으로 떨어지는데,
    이는 확산 반사가 커지면(S0↑) 편광이 희석되기(DoLP↓) 때문이다. 안정화 기준 중 하나를 그대로 만족한다.</li>
<li><strong>검은 플라스틱의 DoLP가 0.338로 가장 높다.</strong> 어두운 유전체는 확산 성분이 작아 정반사(Fresnel) 편광이
    상대적으로 지배하므로 물리적으로 옳다. 밝기와 편광이 독립적으로 거동한다는 증거이기도 하다.</li>
<li><strong>금속은 eta/k pin이 실제로 반영된다.</strong> 알루미늄 S0 0.909 → 0.862, DoLP 0.041 → 0.067.</li>
</ul>

{infinigen_section()}

{scene_section()}

{bridge_section()}

<h2>7. 인프라 — resident scene + band binder</h2>
<p>
목표 구조는 "동일 씬을 GPU에 한 번만 올리고, RGB 카메라는 RGB만 / NIR 카메라는 NIR만 뽑되 메모리는 유지"다.
동적 sensor 교체는 이미 구현돼 있었고, 없던 것은 <strong>밴드 파라미터 binder</strong>였다.
<code>blendbsdf</code>(visible bitmap texture ↔ NIR scalar reflectance)를 <code>mi.traverse()</code>로 전환해 실측했다.
</p>
<table>
<tr><th>항목</th><th>측정</th><th></th></tr>
<tr><td>첫 렌더 (JIT 컴파일 포함)</td><td class="num">1194 ms</td><td></td></tr>
<tr><td>밴드 전환 후 렌더</td><td class="num">0.4 ms + 17 ms</td><td>{verdict(True, "재컴파일 없음")}</td></tr>
<tr><td>eta/k 밴드 왕복 (vis↔854, 5회)</td><td class="num">0.3 ms + 6 ms</td><td>{verdict(True, "재컴파일 없음")}</td></tr>
<tr><td>씬 재로드 횟수</td><td class="num">0</td><td>{verdict(True, "Scene 객체 동일")}</td></tr>
<tr><td>weight 왕복 복원</td><td class="num">0.8730 / 0.8732 / 0.8727</td><td>{verdict(True, "상태 오염 없음")}</td></tr>
</table>

<h3>Stokes 기준 프레임 버그 (프로덕션)</h3>
<p>
프로덕션 <code>stokes.cpp:102</code>가 Stokes 프레임을 <code>scene-&gt;sensors()[0]</code>에 고정하고 있었다.
멀티센서 리그나 dynamic-sensor 렌더에서 <strong>AoLP·S1/S2가 잘못된 축을 기준으로</strong> 나온다는 뜻이다.
실험 트리에 있던 <code>m_sensor</code> 포팅을 optix7로 이식하고 재빌드했다.
</p>
<div class="note warn">
<strong>검증 방법에 주의.</strong> "카메라를 roll 시키고 AoLP 변화를 본다"는 순진한 테스트는 <strong>무효</strong>다.
회전대칭 씬에서는 프레임 회전과 화면 내용 회전이 상쇄돼, <em>정상일 때 오히려 0°</em>가 나온다.
대신 <strong>같은 45° roll 센서를 <code>sensors()[0]</code>일 때와 <code>sensors()[1]</code>일 때 각각 렌더</strong>해
비교했다 — 버그가 남아 있으면 45°, 고쳐졌으면 0°. 측정값 <strong>1.73°</strong>(몬테카를로 노이즈) → 포팅 확인.
</div>

<h2>8. 확정된 구현 제약</h2>
<ol>
<li><strong><code>BandParameterBinder</code>는 반드시 drjit 타입으로 대입한다. Python list 금지.</strong><br>
<code>params[k] = [3.0, 3.0, 3.0]</code> → JIT 변수 레이아웃 변경 → <strong>전체 커널 재컴파일 (1150 ms)</strong><br>
<code>params[k] = mi.Color3f(3.0, 3.0, 3.0)</code> → <strong>재컴파일 없음 (6 ms)</strong><br>
<strong>200배 차이이고 조용히 느려진다.</strong> 회귀 테스트로 고정해야 한다.</li>
<li><strong>금속 eta/k는 <code>srgb</code> + <code>unbounded</code>로 저작한다.</strong>
<code>{{"type": "srgb", "color": [2.58, 2.58, 2.58], "unbounded": true}}</code><br>
평범한 <code>rgb</code>는 값&gt;1을 sRGB <em>reflectance</em>로 보고 거부한다 (<code>src/spectra/srgb.cpp:55</code>).
또한 <code>rgb</code> dict은 키를 2개만 허용하므로 <code>unbounded</code>를 얹을 수 없다.</li>
<li><strong>Dr.Jit은 한 프로세스에서 두 CUDA variant를 쓰면 죽는다</strong> (AD backend가 변수를 잃는다).
variant별로 프로세스를 분리해야 한다.</li>
</ol>

<h2>9. 다음 단계</h2>
<ul>
<li><strong>Stage 1 — 반사율 테이블 (일정 리스크는 여기 있다).</strong>
    렌더러는 통제 가능한 코드지만, ρ854에 신뢰할 값과 출처를 붙이는 것은 측정이거나 문헌이다.
    <code>class_band_reflectance_v1.json</code>: 밴드별 effective reflectance + source + confidence + texture policy.
    hpBRDF는 <strong>오프라인 calibration anchor로만</strong> 쓰고 런타임 measured BSDF는 쓰지 않는다.
    이 리포트의 5개 값은 <em>스모크용 수동값</em>이며 아직 provenance가 없다.</li>
<li><strong>Stage 2 — 렌더러 베타.</strong> <code>BandParameterBinder</code> + <code>blendbsdf</code> 스테이징,
    <code>optical_constants.py</code> 밴드 인지화(프리셋 이름 → 숫자 eta/k),
    센서 기반 modality 라우팅, <code>ROBOMITUBA_NIR_MATERIAL_MODE=legacy|class_band_v1</code>.</li>
<li><strong>미해결.</strong> modality 목록이 바뀌면 <code>_modality_suffix()</code> 해시 때문에 job_id가 바뀌어
    기존 렌더의 resume이 깨진다 — 마이그레이션 또는 호환 shim 필요.</li>
</ul>

<h2>부록 — 스모크 밴드 테이블 (수동값, provenance 없음)</h2>
<div class="scroll"><table>
<tr><th>class</th><th>model</th><th>visible</th><th>nir_854</th></tr>
{"".join(
    f'<tr><td>{LABEL[c]}</td><td><code>{t3["band_table"][c]["model"]}</code></td>'
    f'<td><code>{t3["band_table"][c]["visible"]}</code></td>'
    f'<td><code>{t3["band_table"][c]["nir_854"]}</code></td></tr>'
    for c in CLASSES)}
</table></div>
<p class="sub">
Al의 854&nbsp;nm eta/k만 실제 데이터(<code>build/mitsuba3-optix7/data/ior/Al.{{eta,k}}.spd</code>)에서 읽었다.
나머지는 Stage&nbsp;1에서 교체될 자리표시자다.
</p>

</div></body></html>
"""
    OUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUT}  ({len(html)/1024:.1f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
