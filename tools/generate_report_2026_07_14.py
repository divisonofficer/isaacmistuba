#!/usr/bin/env python3
"""Generate the 2026-07-14 Infinigen PBR-map report."""
from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import BoundaryNorm, ListedColormap
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = ROOT / "out/spatial_pbr_ab/2026-07-13-rgb-polar-256-glb"
IMAGE_DIR = ROOT / "dev_report/images/0714_pbr_maps"
REPORT_PATH = ROOT / "dev_report/report_2026-07-14.html"
MANIFEST_PATH = ROOT / "out/infinigen_audits/spatial_pbr_visualization_2026-07-14.json"

NAMES = ["dielectric", "Ag", "Al", "Au", "Cr", "Cu", "Ni_palik", "W"]
COLORS = ["#d9d9d9", "#4c78a8", "#72b7b2", "#f58518", "#e45756", "#54a24b", "#b279a2", "#111111"]
INDEX_CMAP = ListedColormap(COLORS, name="roughconductor_index")
INDEX_NORM = BoundaryNorm(np.arange(-0.5, 8.5, 1), INDEX_CMAP.N)

# The checked-in 07-13 HTML contains G1-G5/ARMN provenance, not the user's
# original P0-P5 table.  The asterisk marks these as display bins only.
REPRESENTATIVES = [
    ("P0*", "NatureShelfTrinketsFactory_7695705_.spawn_asset_742423", "basecolor + constant roughness; metallic absent"),
    ("P1*", "BedFactory_7812946_.spawn_asset_5878389", "basecolor/roughness texture; dielectric control"),
    ("P2*", "LargePlantContainerFactory_2686399_.spawn_asset_5396567", "low-roughness dielectric control"),
    ("P3*", "BookStackFactory_3836551_.spawn_asset_7763197", "spatial metallic, sparse conductor occupancy"),
    ("P4*", "BeverageFridgeFactory_4647172_.spawn_asset_4618900", "spatial metallic, partial occupancy"),
    ("P5*", "BottleFactory_3548288_.spawn_asset_291184", "spatial metallic, conductor-dominant"),
]
CONTROLS = [
    ("semantic control", "BookColumnFactory_8291484_.spawn_asset_7622244"),
    ("glass analytic control", "PlantContainerFactory_8288363_.spawn_asset_1688329"),
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_asset(object_id: str) -> tuple[Path, dict[str, Any], dict[str, np.ndarray]]:
    d = EXPERIMENT / "asset_maps" / object_id
    record_path = d / f"{object_id}_spatial_pbr.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    arrays = dict(np.load(d / f"{object_id}_optical_maps.npz"))
    return d, record, arrays


def rgb(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGB"), dtype=np.float32) / 255.0


def make_figure(profile: str, object_id: str, role: str) -> dict[str, Any]:
    d, record, arrays = load_asset(object_id)
    base = rgb(d / f"{object_id}_basecolor.png")
    metallic = arrays["metallic"].astype(np.float32)
    alpha = arrays["alpha"].astype(np.float32)
    rough = np.sqrt(np.clip(alpha, 0, 1))
    index = arrays["conductor_index"].astype(np.uint8)
    eta = arrays["eta"].astype(np.float32)[..., 1]
    kval = arrays["k"].astype(np.float32)[..., 1]
    normal_path = d / f"{object_id}_normal.png"
    normal = rgb(normal_path) if normal_path.is_file() else np.full_like(base, 0.5)
    stats = record.get("stats", {})
    eta_vmax = max(2.0, float(np.nanpercentile(eta[index > 0], 99)) if np.any(index > 0) else 2.0)
    k_vmax = max(1.0, float(np.nanpercentile(kval[index > 0], 99)) if np.any(index > 0) else 1.0)
    eta = np.ma.masked_where(index == 0, eta)
    kval = np.ma.masked_where(index == 0, kval)
    idx = np.ma.masked_where(~np.isfinite(index), index)
    fig, ax = plt.subplots(2, 5, figsize=(22, 11.5), constrained_layout=True)
    fig.suptitle(f"{profile}  ·  {object_id}\n{role}  ·  GLB-authoritative UV  ·  spatial PBR/F0", fontsize=16, fontweight="bold")

    def panel(a: Any, image: Any, title: str, cmap: Any = "viridis", vmin: float | None = None,
              vmax: float | None = None, norm: Any = None, cb: bool = True,
              ticks: list[float] | None = None, ticklabels: list[str] | None = None) -> Any:
        a.set_title(title, fontsize=11)
        a.set_xticks([]); a.set_yticks([])
        im = a.imshow(image, cmap=cmap, vmin=vmin, vmax=vmax, norm=norm, interpolation="nearest")
        if cb:
            bar = fig.colorbar(im, ax=a, fraction=0.046, pad=0.03)
            if ticks is not None:
                bar.set_ticks(ticks)
                if ticklabels is not None:
                    bar.set_ticklabels(ticklabels)
            bar.ax.tick_params(labelsize=8)
        return im

    panel(ax[0, 0], base, "basecolor (sRGB)", cmap=None, cb=False)
    panel(ax[0, 1], rough, "roughness r", "magma", 0, 1)
    panel(ax[0, 2], metallic, "effective metallic", "viridis", 0, 1)
    panel(ax[0, 3], alpha, "Mitsuba alpha = r²", "magma", 0, 1)
    panel(ax[0, 4], normal, "normal map (RGB)", cmap=None, cb=False)
    panel(ax[1, 0], eta, "η / n @ 550 nm", "cividis", 0, eta_vmax)
    panel(ax[1, 1], kval, "k @ 550 nm", "inferno", 0, k_vmax)
    panel(ax[1, 2], idx, "conductor-index segmentation", INDEX_CMAP, norm=INDEX_NORM,
          ticks=list(range(8)), ticklabels=NAMES)
    ax[1, 3].axis("off")
    matches = stats.get("matches", [])
    match_text = "\n".join(f"{m['index']}: {m['material']}  {m['fraction'] * 100:.1f}%" for m in matches) or "no conductor texels"
    ax[1, 3].text(0.02, 0.98, "GLOBAL INDEX LEGEND\n\n" + "\n".join(f"{i}  {n}" for i, n in enumerate(NAMES)) +
                   "\n\nOBSERVED\n" + match_text + f"\n\nF0 L2 mean: {stats.get('f0_match_l2_mean')}",
                   va="top", family="monospace", fontsize=10,
                   bbox={"boxstyle": "round,pad=0.6", "facecolor": "#f5f5f5", "edgecolor": "#cccccc"})
    ax[1, 4].axis("off")
    ax[1, 4].text(0.02, 0.98, "INTERPRETATION\n\nindex = selected roughconductor\npreset, not source material ID.\n\n0 is dielectric; 1–7 are fixed\nglobal conductor presets.\n\nη/k are F0-nearest, three-band\nRGB-anchor estimates; raw NPZ/EXR\nare authoritative.",
                  va="top", fontsize=10, linespacing=1.4,
                  bbox={"boxstyle": "round,pad=0.6", "facecolor": "#fff8e1", "edgecolor": "#d6a700"})
    out = IMAGE_DIR / f"0714_{profile.replace('*', 'provisional')}_{object_id}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=220, facecolor="white")
    plt.close(fig)
    return {"profile": profile, "object_id": object_id, "role": role,
            "figure": str(out.relative_to(ROOT)),
            "record": str((d / f"{object_id}_spatial_pbr.json").relative_to(ROOT)),
            "arrays": str((d / f"{object_id}_optical_maps.npz").relative_to(ROOT)),
            "stats": stats, "matches": matches,
            "record_sha256": sha256(d / f"{object_id}_spatial_pbr.json"),
            "provenance": record.get("provenance", {})}


def make_legend() -> str:
    out = IMAGE_DIR / "0714_conductor_index_legend.png"
    fig, a = plt.subplots(figsize=(10, 1.5)); fig.subplots_adjust(bottom=0.43, left=0.04, right=0.98, top=0.82)
    sm = plt.cm.ScalarMappable(norm=INDEX_NORM, cmap=INDEX_CMAP)
    bar = fig.colorbar(sm, cax=a, orientation="horizontal", ticks=np.arange(8))
    bar.ax.set_xticklabels([f"{i}: {n}" for i, n in enumerate(NAMES)], fontsize=10)
    bar.set_label("Global roughconductor selection index (categorical; nearest interpolation)", fontsize=11)
    fig.savefig(out, dpi=220, facecolor="white"); plt.close(fig)
    return str(out.relative_to(ROOT))


def esc(value: Any) -> str:
    return html.escape(str(value))


def pct(stats: dict[str, Any]) -> str:
    v = stats.get("conductor_fraction")
    return "—" if v is None else f"{float(v) * 100:.1f}%"


def render_html(entries: list[dict[str, Any]], controls: list[dict[str, Any]], legend: str) -> None:
    def img_rel(path: str) -> str:
        p = Path(path)
        if p.parts and p.parts[0] == "dev_report":
            return str(p.relative_to("dev_report"))
        return "../" + str(p)
    rows = []
    for e in entries:
        s = e["stats"]
        rows.append(f"<tr><td><code>{esc(e['profile'])}</code></td><td>{esc(e['object_id'])}</td><td>{esc(e['role'])}</td><td>{esc(s.get('metallic_min'))}–{esc(s.get('metallic_max'))}</td><td>{pct(s)}</td><td>{esc(s.get('f0_match_l2_mean'))}</td></tr>")
    figures = []
    for e in entries + controls:
        figures.append(f"<section class='asset'><h3>{esc(e['profile'])} · {esc(e['object_id'])}</h3><p class='small'>{esc(e['role'])}</p><a href='{img_rel(e['figure'])}'><img loading='lazy' src='{img_rel(e['figure'])}' alt='{esc(e['object_id'])} PBR maps'></a><p class='small'>sidecar: <code>{esc(e['record'])}</code> · arrays: <code>{esc(e['arrays'])}</code></p></section>")
    controls_rows = []
    for e in controls:
        controls_rows.append(f"<tr><td>{esc(e['object_id'])}</td><td>{esc(e['role'])}</td><td>{pct(e['stats'])}</td><td>{esc(e['provenance'].get('optical_class', '—'))}</td></tr>")
    context_blocks = []
    for e in entries + controls:
        asset_root = "../" + str(EXPERIMENT.relative_to(ROOT) / e["object_id"])
        context_blocks.append(
            f"<div class='context'><h3>{esc(e['profile'])} · {esc(e['object_id'])}</h3>"
            f"<div class='context-grid'><a href='{asset_root}/rgb_contact_sheet.png'><img loading='lazy' src='{asset_root}/rgb_contact_sheet.png' alt='{esc(e['object_id'])} RGB A/B native contact sheet'></a>"
            f"<a href='{asset_root}/polar_contact_sheet.png'><img loading='lazy' src='{asset_root}/polar_contact_sheet.png' alt='{esc(e['object_id'])} polarized A/B native contact sheet'></a></div>"
            f"<a href='{asset_root}/polar_diagnostics_contact_sheet.png'><img loading='lazy' src='{asset_root}/polar_diagnostics_contact_sheet.png' alt='{esc(e['object_id'])} polarization diagnostics with colorbars'></a></div>"
        )
    text = f"""<!doctype html><html lang='ko'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>2026-07-14 Infinigen PBR visualisation</title><style>
body{{margin:0;background:#f5f7fb;color:#172033;font:16px/1.6 system-ui,sans-serif}}main{{max-width:1500px;margin:auto;padding:34px 30px 80px;background:white}}h1{{font-size:2rem}}h2{{margin-top:42px;border-bottom:2px solid #e5e7eb;padding-bottom:7px}}table{{width:100%;border-collapse:collapse;margin:16px 0 24px}}th,td{{border:1px solid #d9dee8;padding:8px 10px;text-align:left;vertical-align:top}}th{{background:#eef2f7}}.note{{padding:15px 18px;border-left:5px solid #3973ac;background:#eef6ff;margin:18px 0}}.asset,.context{{margin:34px 0 52px;border-top:1px solid #d9dee8;padding-top:12px}}.asset img,.context img{{display:block;width:100%;height:auto;border:1px solid #d9dee8}}.context-grid{{display:grid;grid-template-columns:1fr 1fr;gap:18px;align-items:start}}.context-grid img{{width:100%}}.small{{color:#596579;font-size:.88rem}}code{{background:#f1f3f6;padding:1px 4px;border-radius:3px}}ul{{padding-left:22px}}
</style></head><body><main><h1>2026-07-14 · Infinigen PBR component / spatial conductor visualisation</h1>
<p>GLB-authoritative UV에서 추출한 PBR atlas를 <code>sv-polartexture</code> 입력 컴포넌트 관점으로 정리하고, spatial PBR adapter가 생성한 η(n), k, alpha, blend weight, conductor-index를 시각적으로 검증한다.</p>
<div class='note'><strong>핵심 결론.</strong> conductor index는 연속 물리량이 아니라 categorical segmentation이다. source material ID가 아니라 F0 nearest-match가 선택한 roughconductor preset이므로 두 의미를 같은 label로 부르지 않는다.</div>
<h2>1. 입력·출력 계약</h2><ul><li>OBJ가 아니라 sibling GLB를 materialize한 UV를 authoritative로 사용했다.</li><li>basecolor, roughness r, effective metallic, alpha=r², normal 및 η/k를 lossless 고해상도 figure로 표시한다.</li><li>η/k는 550 nm RGB anchor를 표시하고 3채널 원본은 NPZ/EXR로 보존한다.</li></ul>
<h2>2. RGB / polarized A/B context</h2><p>아래는 동일 geometry·UV·카메라·조명·seed에서 생성한 7/13 A/B 결과다. 이전 top-level contact sheet는 자산별 sheet를 다시 축소한 overview였으므로, 여기서는 자산별 native contact sheet와 diagnostics 원본을 직접 연결한다. 각 polar diagnostic에는 DoLP/DoP, AoLP, raw S1/S2, S1/S0, S2/S0와 native colorbar가 들어 있다.</p>{''.join(context_blocks)}
<h2>3. Global conductor-index segmentation</h2><img src='{img_rel(legend)}' alt='conductor index legend'><table><thead><tr><th>index</th><th>preset</th><th>의미</th></tr></thead><tbody>{''.join(f"<tr><td>{i}</td><td>{esc(n)}</td><td>{'dielectric 영역' if i == 0 else 'F0 nearest roughconductor 선택'}</td></tr>" for i,n in enumerate(NAMES))}</tbody></table><p>global index와 nearest interpolation을 고정했다. index 0은 dielectric이며 padding/background와 합치지 않는다. screen-space object mask는 7/13 A/B 산출물의 <code>screen_space_maps.npz</code>에서 별도로 확인한다.</p>
<h2>4. Representative profiles (P0–P5)</h2><p>현재 체크인된 7/13 HTML에는 P0–P5 표가 없고 G1–G5/ARMN provenance만 있다. 아래 <code>*</code>는 시각화용 provisional bin임을 뜻한다. 원래 P0–P5 정의표가 복구되면 profile label만 교체한다.</p><table><thead><tr><th>profile</th><th>object</th><th>role</th><th>metallic range</th><th>conductor texel</th><th>F0 L2 mean</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
<h2>5. Map panels</h2><p>index 색상은 물리량 크기를 뜻하지 않는다. η/k는 연속 colorbar, metallic/alpha는 [0,1], index는 categorical legend다. η/k는 basecolor F0로부터 유도한 실험값이며 금속 종류 ground truth가 아니다.</p>{''.join(figures)}
<h2>6. Semantic controls</h2><p>BookColumn은 diffuse optical class인데 conductor texel이 높게 나오는 semantic mismatch control이고, PlantContainer는 glass analytic control이다.</p><table><thead><tr><th>object</th><th>role</th><th>conductor texel</th><th>optical class</th></tr></thead><tbody>{''.join(controls_rows)}</tbody></table>
<h2>7. 제한사항</h2><ul><li>Fridge, BookColumn, Bottle, BookStack에서 spatial metallic과 continuous blend weight의 map transport를 확인했지만, W 집중과 높은 F0 error 때문에 η/k identity는 신뢰 가능한 ground truth가 아니다.</li><li>normal texture는 source normal과 geometry-derived normal을 구분해야 한다.</li><li>polar diagnostic은 각 자산의 <code>polar_diagnostics_contact_sheet.png</code>에서 DoLP/AoLP/S1/S2 colorbar와 함께 확인한다.</li></ul><p class='small'>manifest: <code>out/infinigen_audits/spatial_pbr_visualization_2026-07-14.json</code> · sidecar schema: <code>robomituba.spatial_pbr.v1</code></p></main></body></html>"""
    REPORT_PATH.write_text(text, encoding="utf-8")


def main() -> int:
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    entries = [make_figure(*item) for item in REPRESENTATIVES]
    controls = [make_figure("control", object_id, role) for role, object_id in CONTROLS]
    legend = make_legend()
    manifest = {"schema": "robomituba.spatial_pbr_visualization.v1", "date": "2026-07-14", "experiment_root": str(EXPERIMENT.relative_to(ROOT)), "glb_uv_authoritative": True, "index_mapping": {str(i): n for i,n in enumerate(NAMES)}, "index_interpolation": "nearest", "p0_p5_label_status": "provisional_display_bins; authoritative 07-13 P0-P5 table absent from checked-in HTML", "representatives": entries, "controls": controls, "legend": legend}
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    render_html(entries, controls, legend)
    print(json.dumps({"report": str(REPORT_PATH), "manifest": str(MANIFEST_PATH), "figures": len(entries)+len(controls)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
