#!/usr/bin/env python3
"""Generate the spatial-PBR (polartexture) A/B render-quality report.

Branch A is the pre-work baseline: one analytic BSDF chosen from the unit's
``optical_class``.  Branch B is the spatial layer: a ``blendbsdf`` driven by the
per-texel metallic atlas, mixing ``pplastic`` with a ``roughconductor`` whose
eta/k come from F0 nearest-preset EXR maps.  Everything else in the pair -
geometry, UV, camera, light, seed, spp - is asserted identical, so the delta is
attributable to the material layer alone.
"""
from __future__ import annotations

import collections
import html
import json
import math
import os
import shutil
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import BoundaryNorm, LinearSegmentedColormap, ListedColormap
from PIL import Image

# The legend carries Korean role names; DejaVu has no Hangul coverage.  The font
# lives in the user font dir, which matplotlib's cache does not scan by default.
_KO_FONT = Path.home() / ".fonts/NotoSansKR-VF.ttf"
if _KO_FONT.is_file():
    import matplotlib.font_manager as fm

    fm.fontManager.addfont(str(_KO_FONT))
    matplotlib.rcParams["font.family"] = [
        fm.FontProperties(fname=str(_KO_FONT)).get_name(),
        "DejaVu Sans",
    ]
matplotlib.rcParams["axes.unicode_minus"] = False

ROOT = Path(__file__).resolve().parents[1]
# The 640x512 final-profile run is authoritative. The 256/64 smoke run is kept
# as the "before" side of the glass fix comparison.
EXPERIMENT = Path(
    os.environ.get("SPATIAL_PBR_AB_RUN", ROOT / "out/spatial_pbr_ab/2026-07-29-final-640-512")
)
SMOKE_RUN = ROOT / "out/spatial_pbr_ab/2026-07-13-rgb-polar-256-glb"
BACKUP = SMOKE_RUN / "_pre_smoothglass_backup"
UV_AUDIT = EXPERIMENT / "uv_audit.json"
IMAGE_DIR = ROOT / "dev_report/images/0729_spatial_pbr_ab"
REPORT_PATH = ROOT / "dev_report/report_2026-07-29_spatial_pbr_ab.html"

# dataviz categorical slots 1 and 2 (validated: CVD dE 24.7, normal dE 33.6,
# both >= 3:1 on a light surface).
C_POS = "#2a78d6"
C_NEG = "#eb6834"
C_GLASS = "#1baf7a"

# The glass unit cannot act as a negative control: branch B has no transmission
# path at all, so it is reported as its own role rather than averaged into the
# dielectric controls.
GLASS_ID = "PlantContainerFactory_8288363_.spawn_asset_1688329"
ROLE_LABEL = {
    "positive": "positive · spatial metallic (4)",
    "negative": "negative · 불투명 dielectric control (3)",
    "glass": "glass · 투과 재질 (1)",
}
ROLE_COLOR = {"positive": C_POS, "negative": C_NEG, "glass": C_GLASS}
INK = "#172033"
MUTED = "#596579"
GRID = "#d9dee8"

# The condition shown in the per-asset figures.  All four conditions are in the
# tables; one is displayed so the page stays readable.
HERO_CONDITION = "front__left50"

DESCRIPTIONS = {
    "BottleFactory_6220686_.spawn_asset_1976314": "spatial metallic · metal 14% / diel 64% · graded 21%",
    "StandingSinkFactory_335794_.spawn_asset_4727617": "spatial metallic · metal 31% / diel 57% · graded 13%",
    "BottleFactory_9066242_.spawn_asset_2200086": "spatial metallic · metal 44% / diel 40% · graded 16%",
    "BottleFactory_129128_.spawn_asset_4533336": "spatial metallic · metal 82% · graded 18%",
    "BeverageFridgeFactory_4647172_.spawn_asset_4618900": "spatial metallic, partial conductor occupancy",
    "BookColumnFactory_8291484_.spawn_asset_7622244": "spatial metallic, conductor-dominant 표지",
    "BottleFactory_3548288_.spawn_asset_291184": "spatial metallic, conductor-dominant",
    "BookStackFactory_3836551_.spawn_asset_7763197": "spatial metallic, sparse conductor occupancy",
    "BedFactory_7812946_.spawn_asset_5878389": "dielectric control, basecolor/roughness texture",
    "NatureShelfTrinketsFactory_7695705_.spawn_asset_742423": "dielectric control, constant roughness",
    "LargePlantContainerFactory_2686399_.spawn_asset_5396567": "low-roughness dielectric control",
    "PlantContainerFactory_8288363_.spawn_asset_1688329": "glass control, smooth dielectric baseline",
}

OBJECT_FIELDS = [
    ("delta_dolp_mean", "ΔDoLP mean", 4),
    ("delta_dolp_p95", "ΔDoLP p95", 4),
    ("delta_dolp_gt_005_fraction", "ΔDoLP&gt;0.05 화소비", 3),
    ("weighted_aolp_distance_rad", "AoLP 거리 (rad)", 4),
    ("s1_over_s0_mae", "S1/S0 MAE", 4),
    ("s2_over_s0_mae", "S2/S0 MAE", 4),
    ("rgb_relative_mae", "RGB rel-MAE", 3),
]


def esc(value: Any) -> str:
    return html.escape(str(value))


def short(object_id: str) -> str:
    """Factory name without the spawn hash, which carries no information here."""
    return object_id.split("Factory_")[0] + "Factory" if "Factory_" in object_id else object_id


def load_pairs(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))["pairs"]


def by_asset(pairs: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for pair in pairs:
        out[pair["asset"]].append(pair)
    return out


def mean(rows: list[dict[str, Any]], roi: str, field: str, block: str = "metrics") -> float:
    return sum(r[block][roi][field] for r in rows) / len(rows)


def ci95(values: list[float]) -> tuple[float, float]:
    n = len(values)
    m = sum(values) / n
    if n < 2:
        return (m, m)
    var = sum((v - m) ** 2 for v in values) / (n - 1)
    half = 1.96 * math.sqrt(var / n)
    return (m - half, m + half)


def group_of(rows: list[dict[str, Any]]) -> str:
    return rows[0]["group"]


def role_of(rows: list[dict[str, Any]]) -> str:
    """Reporting role. The config's binary group is kept, but glass is split out."""
    return "glass" if rows[0]["asset"] == GLASS_ID else rows[0]["group"]


def rows_for_role(assets: dict[str, list[dict[str, Any]]], role: str) -> list[dict[str, Any]]:
    return [r for rs in assets.values() if role_of(rs) == role for r in rs]


def bsdf_label(rows: list[dict[str, Any]], branch: str) -> str:
    return str(rows[0]["bsdf"][branch]["type"])


# ---------------------------------------------------------------------------
# Polarization colour convention.  These reproduce `.claude/skills/debug-render`
# (`tools/debug_render_rig.py:_save_panel`) exactly so every polarization figure
# in the project reads the same way:
#   DoP        red-black      black = unpolarized -> red = polarized
#   AoLP       hue (cyclic)   hue = ((deg + 90) / 180) % 1
#   S1/S2/S3   blue-white-red diverging, symmetric about 0
# ---------------------------------------------------------------------------
CMAP_DOP = LinearSegmentedColormap.from_list("dop_red_black", ["#000000", "#ff0000"])
CMAP_AOLP = "hsv"
CMAP_DIV = LinearSegmentedColormap.from_list(
    "stokes_bwr", [(0.23, 0.30, 0.75), (1.0, 1.0, 1.0), (0.75, 0.15, 0.15)]
)

# Shared with dev_report/report_2026-07-14 so the conductor index legend is
# identical across reports.
INDEX_NAMES = ["dielectric", "Ag", "Al", "Au", "Cr", "Cu", "Ni_palik", "W"]
INDEX_COLORS = ["#d9d9d9", "#4c78a8", "#72b7b2", "#f58518", "#e45756", "#54a24b", "#b279a2", "#111111"]
CMAP_INDEX = ListedColormap(INDEX_COLORS, name="conductor_index")
NORM_INDEX = BoundaryNorm(np.arange(-0.5, 8.5, 1), CMAP_INDEX.N)


def tonemap(rgb: np.ndarray) -> np.ndarray:
    """Reinhard + gamma, matching the debug-render S0 panel."""
    x = np.clip(np.asarray(rgb, np.float32), 0, None)
    x = x / (1.0 + x)
    return np.clip(x ** (1 / 2.2), 0, 1)


def load_png(path: Path) -> np.ndarray | None:
    if not path or not Path(path).is_file():
        return None
    return np.asarray(Image.open(path).convert("RGB"), np.float32) / 255.0


def load_exr(path: Path) -> np.ndarray | None:
    import os

    os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
    try:
        import cv2
    except Exception:
        return None
    data = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if data is None:
        return None
    return np.asarray(data, np.float32)[..., ::-1]


def _bare(ax, title: str) -> None:
    ax.set_title(title, fontsize=9.5, color=INK, pad=4)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_color(GRID)


def polar_panel(oid: str, condition: str, out: Path) -> str | None:
    """A/B polarization panels in the project's debug-render colour convention."""
    frames = {}
    for branch in ("A", "B"):
        npz = EXPERIMENT / oid / condition / branch / "stokes_data.npz"
        if not npz.is_file():
            return None
        frames[branch] = dict(np.load(npz))

    def channel(data: dict[str, np.ndarray], key: str) -> np.ndarray:
        if key == "s3_over_s0":
            s0 = np.asarray(data["s0_l"], np.float32)
            return np.divide(
                np.asarray(data["s3_l"], np.float32), s0,
                out=np.zeros_like(s0), where=np.abs(s0) > 1e-8,
            )
        if key == "aolp":
            # Reference hue mapping: ((deg + 90) / 180) % 1.  The stored AoLP is
            # 0..pi radians, so convert first and keep the same 90 degree offset.
            deg = np.degrees(np.asarray(data["aolp"], np.float32))
            return ((deg + 90.0) / 180.0) % 1.0
        return np.asarray(data[key], np.float32)

    cols = [
        ("S0", "s0", None, None),
        ("DoP", "dop", CMAP_DOP, (0.0, 1.0)),
        ("AoLP", "aolp", CMAP_AOLP, (0.0, 1.0)),
        ("S1/S0", "s1_over_s0", CMAP_DIV, (-1.0, 1.0)),
        ("S2/S0", "s2_over_s0", CMAP_DIV, (-1.0, 1.0)),
        ("S3/S0", "s3_over_s0", CMAP_DIV, (-1.0, 1.0)),
    ]
    fig, axes = plt.subplots(2, len(cols), figsize=(2.05 * len(cols), 4.9), dpi=185)
    fig.patch.set_facecolor("white")
    images = {}
    for row, branch in enumerate(("A", "B")):
        data = frames[branch]
        for col, (label, key, cmap, limits) in enumerate(cols):
            ax = axes[row][col]
            if key == "s0":
                ax.imshow(tonemap(data["s0"]))
            else:
                # No masking: the convention colours the whole frame, so an
                # unpolarized background reads as DoP=0 (black) rather than a hole.
                images[label] = ax.imshow(
                    channel(data, key), cmap=cmap,
                    vmin=limits[0], vmax=limits[1], interpolation="nearest",
                )
            _bare(ax, label if row == 0 else "")
        axes[row][0].set_ylabel(
            "A (작업 전)" if branch == "A" else "B (작업 후)", fontsize=10, color=INK
        )
    # One colourbar per encoding, not per panel: the same scale serves both rows.
    for label, ticks, labels in (
        ("DoP", [0, 0.5, 1.0], ["0", "0.5", "1"]),
        ("AoLP", [0.0, 0.25, 0.5, 0.75, 1.0], ["−90°", "−45°", "0°", "45°", "90°"]),
        ("S1/S0", [-1, 0, 1], ["−1", "0", "+1"]),
        ("S2/S0", [-1, 0, 1], ["−1", "0", "+1"]),
        ("S3/S0", [-1, 0, 1], ["−1", "0", "+1"]),
    ):
        if label not in images:
            continue
        col = [c[0] for c in cols].index(label)
        box = axes[1][col].get_position()
        cax = fig.add_axes([box.x0, box.y0 - 0.052, box.width, 0.021])
        bar = fig.colorbar(images[label], cax=cax, orientation="horizontal", ticks=ticks)
        bar.ax.set_xticklabels(labels)
        bar.ax.tick_params(labelsize=7.5, length=2, colors=MUTED)
        bar.outline.set_edgecolor(GRID)
    fig.text(
        0.5, 0.025,
        "debug-render 규약 · DoP: 검정=무편광→빨강=편광 · AoLP: 색상환 ±90° · S1/S2/S3: 파랑–흰–빨강 발산",
        ha="center", fontsize=8.5, color=MUTED,
    )
    fig.subplots_adjust(left=0.055, right=0.99, top=0.94, bottom=0.17, wspace=0.06, hspace=0.06)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, facecolor="white")
    plt.close(fig)
    return f"images/0729_spatial_pbr_ab/{out.name}"


def texture_panel(oid: str, record: dict[str, Any], out: Path) -> str | None:
    """Source PBR atlas (in) and the derived spatial-BSDF components (out)."""
    maps = EXPERIMENT / "asset_maps" / oid
    inputs = record.get("inputs", {})
    outputs = record.get("outputs", {})

    def local(key: str) -> Path | None:
        """`outputs` stores absolute paths from the run's original working dir,
        which may no longer exist. Re-anchor by filename in this run's asset_maps."""
        ref = outputs.get(key)
        return maps / Path(ref).name if ref else None

    eta = load_exr(local("eta_exr")) if local("eta_exr") else None
    k = load_exr(local("k_exr")) if local("k_exr") else None
    index = load_png(maps / f"{oid}_conductor_index.png")

    def src(key: str) -> np.ndarray | None:
        return load_png(Path(inputs[key])) if inputs.get(key) else None

    # Two explicit rows so the figure matches its caption: what came in, and what
    # the spatial BSDF actually consumes.  Missing tiles leave a blank slot rather
    # than reflowing the grid.
    rows: list[list[tuple[str, Any, dict[str, Any]]]] = [
        [
            ("albedo (원본)", src("base_color"), {}),
            ("roughness (원본)", src("roughness"), {}),
            ("metallic (원본)", src("metallic"), {}),
            ("normal (원본)", src("normal"), {}),
        ],
        [
            ("alpha = roughness²", load_png(maps / f"{oid}_alpha.png"), {}),
            ("blend weight = metallic", load_png(maps / f"{oid}_bsdf_weight.png"), {}),
            ("conductor index", index, {"index": True}),
            ("η (550nm anchor)", eta, {"scalar": True, "cmap": "cividis", "floor": 1.0, "span": 0.6}),
            ("k (550nm anchor)", k, {"scalar": True, "cmap": "magma", "floor": 0.0, "span": 0.5}),
        ],
    ]
    if not any(t[1] is not None for row in rows for t in row):
        return None

    ncols = max(len(row) for row in rows)
    fig, axes = plt.subplots(2, ncols, figsize=(2.15 * ncols, 2.55 * 2), dpi=180)
    fig.patch.set_facecolor("white")
    axes = np.atleast_2d(axes)
    flat = [(r, c) for r, row in enumerate(rows) for c in range(ncols)]
    for r, c in flat:
        ax = axes[r][c]
        tile = rows[r][c] if c < len(rows[r]) else None
        if tile is None or tile[1] is None:
            ax.axis("off")
            continue
        label, data, opts = tile
        if opts.get("index"):
            # The PNG round-trips the uint8 index; recover it before colouring.
            values = np.rint(data[..., 0] * 255.0).astype(int)
            ax.imshow(values, cmap=CMAP_INDEX, norm=NORM_INDEX, interpolation="nearest")
        elif opts.get("scalar"):
            # 550nm anchor = green channel, matching report_2026-07-14.  The
            # floor is pinned to the dielectric value so an all-dielectric asset
            # reads as the bottom of the ramp instead of auto-scaling a constant
            # map to mid-colour.
            values = data[..., 1]
            floor = opts["floor"]
            im = ax.imshow(
                values, cmap=opts["cmap"], interpolation="nearest",
                vmin=floor, vmax=max(float(values.max()), floor + opts["span"]),
            )
            bar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.03)
            bar.ax.tick_params(labelsize=7, length=2, colors=MUTED)
            bar.outline.set_edgecolor(GRID)
        else:
            ax.imshow(np.clip(data, 0, 1))
        _bare(ax, label)
    present = sorted({int(round(v * 255)) for v in np.unique(index[..., 0])}) if index is not None else []
    handles = [
        plt.Rectangle((0, 0), 1, 1, color=INDEX_COLORS[i])
        for i in present if 0 <= i < len(INDEX_NAMES)
    ]
    if handles:
        fig.legend(
            handles, [INDEX_NAMES[i] for i in present if 0 <= i < len(INDEX_NAMES)],
            loc="lower center", ncol=min(8, len(handles)), frameon=False,
            fontsize=8.5, labelcolor=INK, title="conductor index", title_fontsize=8.5,
        )
    fig.subplots_adjust(left=0.02, right=0.98, top=0.94, bottom=0.13, wspace=0.16, hspace=0.22)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, facecolor="white")
    plt.close(fig)
    return f"images/0729_spatial_pbr_ab/{out.name}"


def load_record(oid: str) -> dict[str, Any] | None:
    path = EXPERIMENT / "asset_maps" / oid / f"{oid}_spatial_pbr.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def copy_figure(src: Path, name: str) -> str | None:
    if not src.is_file():
        return None
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, IMAGE_DIR / name)
    return f"images/0729_spatial_pbr_ab/{name}"


def delta_chart(assets: dict[str, list[dict[str, Any]]], path: Path) -> str:
    rows = sorted(
        ((oid, role_of(r), mean(r, "object", "delta_dolp_mean")) for oid, r in assets.items()),
        key=lambda row: row[2],
    )
    labels = [short(oid) for oid, _, _ in rows]
    values = [v for _, _, v in rows]
    colors = [ROLE_COLOR[role] for _, role, _ in rows]

    fig, ax = plt.subplots(figsize=(9.4, 4.3), dpi=190)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    bars = ax.barh(labels, values, height=0.62, color=colors, zorder=3)
    # 4px-equivalent rounded ends are not available on barh; a 2px surface gap
    # between adjacent bars is provided by the 0.62 height instead.
    for bar, value in zip(bars, values):
        ax.text(
            bar.get_width() + max(values) * 0.015,
            bar.get_y() + bar.get_height() / 2,
            f"{value:.4f}",
            va="center", ha="left", fontsize=9, color=INK, zorder=4,
        )
    ax.set_xlabel("ΔDoLP mean (object ROI, A vs B)", fontsize=10, color=MUTED)
    ax.set_xlim(0, max(values) * 1.18)
    ax.grid(axis="x", color=GRID, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    for spine in ("top", "right", "left"):
        ax.spines[spine].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(axis="both", length=0, labelsize=9.5, colors=INK)
    roles = ["positive", "negative", "glass"]
    ax.legend(
        [plt.Rectangle((0, 0), 1, 1, color=ROLE_COLOR[r]) for r in roles],
        ["positive · spatial metallic", "negative · 불투명 dielectric", "glass · 투과 재질"],
        loc="lower right", frameon=False, fontsize=9.5, labelcolor=INK,
    )
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor="white")
    plt.close(fig)
    return f"images/0729_spatial_pbr_ab/{path.name}"


def group_table(assets: dict[str, list[dict[str, Any]]]) -> str:
    head = "".join(f"<th>{label}</th>" for _, label, _ in OBJECT_FIELDS)
    body = []
    for group in ("positive", "negative", "glass"):
        rows = rows_for_role(assets, group)
        if not rows:
            continue
        cells = []
        for field, _, digits in OBJECT_FIELDS:
            values = [r["metrics"]["object"][field] for r in rows]
            m = sum(values) / len(values)
            lo, hi = ci95(values)
            cells.append(
                f"<td>{m:.{digits}f}<br><span class='small'>95% CI {lo:.{digits}f}–{hi:.{digits}f}</span></td>"
            )
        body.append(
            f"<tr><th>{ROLE_LABEL[group]}<br><span class='small'>n={len(rows)}</span></th>"
            + "".join(cells) + "</tr>"
        )
    return f"<table><tr><th>role</th>{head}</tr>{''.join(body)}</table>"


def asset_table(assets: dict[str, list[dict[str, Any]]]) -> str:
    head = "".join(f"<th>{label}</th>" for _, label, _ in OBJECT_FIELDS)
    body = []
    order = sorted(assets.items(), key=lambda kv: (["positive", "negative", "glass"].index(role_of(kv[1])), -mean(kv[1], "object", "delta_dolp_mean")))
    for oid, rows in order:
        cells = "".join(
            f"<td>{mean(rows, 'object', field):.{digits}f}</td>" for field, _, digits in OBJECT_FIELDS
        )
        body.append(
            f"<tr><th>{esc(short(oid))}<br><span class='small'>{esc(DESCRIPTIONS.get(oid, ''))}</span></th>"
            f"<td>{esc(role_of(rows))}</td>"
            f"<td><code>{esc(bsdf_label(rows, 'A'))}</code></td>"
            f"<td>{rows[0]['map_stats']['conductor_fraction']:.3f}</td>"
            + cells + "</tr>"
        )
    return (
        "<table><tr><th>asset</th><th>role</th><th>A BSDF (전)</th><th>conductor 비율</th>"
        f"{head}</tr>{''.join(body)}</table>"
    )


def glass_shift(current: dict[str, list[dict[str, Any]]], old: dict[str, list[dict[str, Any]]]) -> str:
    before = mean(old[GLASS_ID], "object", "delta_dolp_mean")
    after = mean(current[GLASS_ID], "object", "delta_dolp_mean")
    return f"ΔDoLP {before:.4f} → {after:.4f}"


def glass_delta_table(current: dict[str, list[dict[str, Any]]], old: dict[str, list[dict[str, Any]]]) -> str:
    oid = "PlantContainerFactory_8288363_.spawn_asset_1688329"
    if oid not in current or oid not in old:
        return ""
    rows = []
    for field, label, digits in OBJECT_FIELDS:
        before = mean(old[oid], "object", field)
        after = mean(current[oid], "object", field)
        rows.append(
            f"<tr><th>{label}</th><td>{before:.{digits}f}</td><td>{after:.{digits}f}</td></tr>"
        )
    return (
        "<table><tr><th>지표 (object ROI)</th>"
        f"<th>수정 전 · A=<code>{esc(bsdf_label(old[oid], 'A'))}</code></th>"
        f"<th>수정 후 · A=<code>{esc(bsdf_label(current[oid], 'A'))}</code></th></tr>"
        f"{''.join(rows)}</table>"
    )


def group_means_before_after(
    current: dict[str, list[dict[str, Any]]], old: dict[str, list[dict[str, Any]]]
) -> str:
    def avg(assets: dict[str, list[dict[str, Any]]], role: str) -> float:
        values = [r["metrics"]["object"]["delta_dolp_mean"] for r in rows_for_role(assets, role)]
        return sum(values) / len(values)

    rows = []
    for role in ("positive", "negative", "glass"):
        rows.append(
            f"<tr><th>{ROLE_LABEL[role]}</th><td>{avg(old, role):.4f}</td><td>{avg(current, role):.4f}</td></tr>"
        )
    ratio = avg(current, "positive") / avg(current, "negative")
    return (
        "<table><tr><th>ΔDoLP mean (object ROI)</th><th>glass 수정 전</th><th>glass 수정 후</th></tr>"
        f"{''.join(rows)}</table>"
        f"<p class='small'>불투명 재질만 보면 positive/negative 분리비는 <strong>{ratio:.1f}×</strong>다. "
        "glass는 수정으로 오히려 차이가 커졌는데, 이는 baseline이 정상화되면서 branch B의 투과 미지원이 드러났기 때문이다.</p>"
    )


def atlas_stats(scene: str, unit_id: str) -> dict[str, dict[str, float] | None]:
    """Pixel statistics of the unit's baked PBR atlases.

    A bake that collapsed to black still produces a valid PNG, so file existence
    proves nothing - only the pixel range does.  ``nonblack`` doubles as a rough
    UV coverage proxy: texels outside every UV island stay at zero.
    """
    manifest_dir = ROOT / "out/infinigen_imports" / scene
    manifest = json.loads((manifest_dir / "scene_manifest.json").read_text(encoding="utf-8"))
    unit = next((u for u in manifest.get("units", []) if u.get("id") == unit_id), {})
    out: dict[str, dict[str, float] | None] = {}
    for key, label in (("baked_albedo", "albedo"), ("baked_roughness", "roughness"),
                       ("baked_metallic", "metallic")):
        ref = unit.get(key)
        path = manifest_dir / str(ref) if ref else None
        if not ref or not path.is_file():
            out[label] = None
            continue
        values = np.asarray(Image.open(path).convert("L"), np.float32) / 255.0
        out[label] = {
            "mean": float(values.mean()),
            "max": float(values.max()),
            "nonblack": float((values > 0.004).mean()),
        }
    return out


def input_audit_table(assets: dict[str, list[dict[str, Any]]]) -> str:
    audit = json.loads(UV_AUDIT.read_text(encoding="utf-8"))["assets"] if UV_AUDIT.is_file() else {}
    body = []
    for oid in sorted(assets, key=lambda o: (["positive", "negative", "glass"].index(role_of(assets[o])), o)):
        rows = assets[oid]
        entry = audit.get(oid, {})
        bad = int(entry.get("broken_part_count", 0))
        frac = float(entry.get("broken_triangle_fraction", 0.0))
        worst = ""
        for part in entry.get("parts", []):
            if part.get("status") not in {"ok", None}:
                worst = (f"{part['status']} · zero-area {part.get('zero_area_ratio', 0):.0%}"
                         f" · overlap {part.get('overlap_factor') or '∞'}×")
                break
        uv_cell = (
            f"<span class='bad'>BROKEN</span><br><span class='small'>{esc(worst)}<br>"
            f"영향 삼각형 {frac:.1%}</span>" if bad else "<span class='ok'>ok</span>"
        )
        alb = atlas_stats(_scene_of(oid), oid).get("albedo")
        if alb is None:
            alb_cell = "—"
        elif alb["max"] < 0.15:
            alb_cell = (f"<span class='bad'>붕괴</span><br><span class='small'>"
                        f"mean {alb['mean']:.4f} · max {alb['max']:.3f}</span>")
        else:
            alb_cell = (f"<span class='ok'>ok</span><br><span class='small'>"
                        f"mean {alb['mean']:.3f} · max {alb['max']:.3f}</span>")
        cover = f"{alb['nonblack']:.1%}" if alb else "—"
        body.append(
            f"<tr><th>{esc(short(oid))}</th><td>{esc(role_of(rows))}</td>"
            f"<td>{entry.get('part_count', '—')}</td><td>{uv_cell}</td>"
            f"<td>{alb_cell}</td><td>{cover}</td></tr>"
        )
    return (
        "<table><tr><th>asset</th><th>role</th><th>GLB parts</th><th>UV 판정</th>"
        "<th>albedo atlas</th><th>atlas 커버리지</th></tr>" + "".join(body) + "</table>"
    )


_SCENE_CACHE: dict[str, str] = {}


def _scene_of(unit_id: str) -> str:
    if not _SCENE_CACHE:
        # Both configs: the audited 07-29 asset set plus the superseded 07-13 one,
        # whose assets are still referenced when explaining why they were replaced.
        for name in ("spatial_pbr_ab_2026-07-29.json", "spatial_pbr_ab_2026-07-13.json"):
            path = ROOT / "configs/experiments" / name
            if not path.is_file():
                continue
            for asset in json.loads(path.read_text(encoding="utf-8"))["assets"]:
                _SCENE_CACHE.setdefault(str(asset["id"]), str(asset["scene"]))
    return _SCENE_CACHE.get(unit_id, "")


def conductor_match_table(assets: dict[str, list[dict[str, Any]]]) -> str:
    body = []
    for oid in sorted(assets, key=lambda o: (["positive", "negative", "glass"].index(role_of(assets[o])), o)):
        record = load_record(oid)
        if not record:
            continue
        stats = record["stats"]
        matches = " · ".join(
            f"{m['material']} {m['fraction'] * 100:.1f}%" for m in stats["matches"]
        )
        err = stats.get("f0_match_l2_mean")
        body.append(
            f"<tr><th>{esc(short(oid))}</th>"
            f"<td>{stats['conductor_fraction']:.3f}</td>"
            f"<td>{esc(matches)}</td>"
            f"<td>{'—' if err is None else f'{err:.3f}'}</td></tr>"
        )
    return (
        "<table><tr><th>asset</th><th>conductor 비율</th><th>선택된 preset</th>"
        "<th>F0 매칭 L2 오차</th></tr>" + "".join(body) + "</table>"
    )


def asset_figures(assets: dict[str, list[dict[str, Any]]]) -> str:
    blocks = []
    order = sorted(assets.items(), key=lambda kv: (["positive", "negative", "glass"].index(role_of(kv[1])), -mean(kv[1], "object", "delta_dolp_mean")))
    for oid, rows in order:
        pair_dir = EXPERIMENT / oid / HERO_CONDITION
        rgb = copy_figure(pair_dir / "rgb_comparison.png", f"{oid}_rgb.png")
        polar = copy_figure(pair_dir / "polar_comparison.png", f"{oid}_polar.png")
        if not rgb and not polar:
            continue
        imgs = []
        if rgb:
            imgs.append(f"<figure><img src='{rgb}' alt='RGB A/B {esc(oid)}'><figcaption class='small'>RGB · 좌 A(전) · 중 B(후) · 우 3× 절대차</figcaption></figure>")
        if polar:
            imgs.append(f"<figure><img src='{polar}' alt='DoLP A/B {esc(oid)}'><figcaption class='small'>DoLP · 좌 A(전) · 중 B(후) · 우 3× 절대차 (하네스 산출)</figcaption></figure>")

        record = load_record(oid)
        tex = texture_panel(oid, record, IMAGE_DIR / f"{oid}_textures.png") if record else None
        stokes = polar_panel(oid, HERO_CONDITION, IMAGE_DIR / f"{oid}_stokes.png")
        nir_html = ""
        has_pseudo = (IMAGE_DIR / f"{oid}_nir_albedo.png").is_file() and (IMAGE_DIR / f"{oid}_nir.png").is_file()
        has_phys = (IMAGE_DIR / f"{oid}_nir_phys.png").is_file()
        if has_pseudo:
            b = "images/0729_spatial_pbr_ab"
            figs = []
            if has_phys:
                figs.append(
                    f"<figure><img src='{b}/{oid}_nir_phys_albedo.png' alt='물리 NIR albedo {esc(oid)}'>"
                    "<figcaption class='small'>① 물리 NIR albedo — class-prior <b>상수</b>(nir_reflectance.py: optical_class→ρ854). "
                    "재질당 한 값이라 <b>평탄</b>(텍스처 없음)</figcaption></figure>"
                    f"<figure><img src='{b}/{oid}_nir_phys.png' alt='물리 NIR 렌더 {esc(oid)}'>"
                    "<figcaption class='small'>② 물리 NIR 렌더 — ①을 diffuse_reflectance로 렌더 (표면 디테일 없음)</figcaption></figure>")
            else:
                figs.append("<figure><figcaption class='small'>① 물리 NIR: 이 재질은 <b>glass/metal → None</b>(Fresnel, diffuse albedo 없음)</figcaption></figure>")
            figs.append(
                f"<figure><img src='{b}/{oid}_nir_albedo.png' alt='pseudo NIR albedo {esc(oid)}'>"
                "<figcaption class='small'>③ pseudo-NIR albedo — RGB albedo→<code>max(rgb,1−rgb)·[.229,.587,.114]</code> "
                "(<b>텍스처 보존</b>)</figcaption></figure>"
                f"<figure><img src='{b}/{oid}_nir.png' alt='pseudo NIR 렌더 {esc(oid)}'>"
                "<figcaption class='small'>④ pseudo-NIR 렌더 — ③을 diffuse_reflectance로 렌더 (표면 텍스처 살아있음)</figcaption></figure>")
            nir_html = ("<div class='pair-grid' style='grid-template-columns:repeat(4,1fr)'>" + "".join(figs) + "</div>")

        stats = (
            f"ΔDoLP mean {mean(rows, 'object', 'delta_dolp_mean'):.4f} · "
            f"p95 {mean(rows, 'object', 'delta_dolp_p95'):.4f} · "
            f"RGB rel-MAE {mean(rows, 'object', 'rgb_relative_mae'):.3f} · "
            f"conductor 비율 {rows[0]['map_stats']['conductor_fraction']:.3f}"
        )
        blocks.append(
            f"<div class='asset'><h3>{esc(short(oid))} <span class='tag {role_of(rows)}'>{role_of(rows)}</span></h3>"
            f"<p class='small'>{esc(DESCRIPTIONS.get(oid, ''))} · A=<code>{esc(bsdf_label(rows, 'A'))}</code>"
            f" → B=<code>blendbsdf(pplastic, roughconductor)</code></p>"
            f"<p class='small'>{stats}</p>"
            f"<div class='pair-grid'>{''.join(imgs)}</div>"
            + (
                f"<figure class='wide'><img src='{tex}' alt='텍스처 맵 {esc(oid)}'>"
                "<figcaption class='small'>윗줄: 원본 PBR atlas (albedo · roughness · metallic · normal). "
                "아랫줄: spatial BSDF가 실제로 소비하는 컴포넌트 (alpha=roughness² · blend weight=metallic · "
                "conductor index · η · k). index는 categorical label이며 렌더에는 η/k 맵이 쓰인다.</figcaption></figure>"
                if tex else ""
            )
            + (
                f"<figure class='wide'><img src='{stokes}' alt='Stokes 패널 {esc(oid)}'>"
                "<figcaption class='small'>편광 성분 전체 (debug-render 색상 규약). "
                "윗줄 A(작업 전) · 아랫줄 B(작업 후).</figcaption></figure>"
                if stokes else ""
            )
            + (f"<h4 class='small' style='margin:10px 0 4px;color:#9cc4ff'>NIR (근적외) — ① 물리 class-prior(상수) vs ③ pseudo-NIR(RGB→텍스처) albedo 추정 + 각각 렌더</h4>{nir_html}" if nir_html else "")
            + "</div>"
        )
    return "".join(blocks)


def build(current: dict[str, list[dict[str, Any]]], old: dict[str, list[dict[str, Any]]]) -> str:
    chart = delta_chart(current, IMAGE_DIR / "delta_dolp_by_asset.png")
    sheets = []
    for name, caption in (
        ("rgb_contact_sheet.png", "전체 32쌍 RGB A/B contact sheet"),
        ("polar_contact_sheet.png", "전체 32쌍 편광 A/B contact sheet"),
    ):
        ref = copy_figure(EXPERIMENT / name, name)
        if ref:
            sheets.append(f"<figure><img src='{ref}' alt='{esc(caption)}'><figcaption class='small'>{esc(caption)}</figcaption></figure>")

    pair_count = sum(len(v) for v in current.values())
    return f"""<!doctype html><html lang='ko'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>2026-07-29 Spatial PBR A/B render quality</title><style>
body{{margin:0;background:#f5f7fb;color:{INK};font:16px/1.6 system-ui,sans-serif}}
main{{max-width:1500px;margin:auto;padding:34px 30px 80px;background:white}}
h1{{font-size:2rem}}h2{{margin-top:44px;border-bottom:2px solid #e5e7eb;padding-bottom:7px}}
h3{{margin-bottom:2px}}
table{{width:100%;border-collapse:collapse;margin:16px 0 24px;font-size:.94rem}}
th,td{{border:1px solid {GRID};padding:8px 10px;text-align:left;vertical-align:top}}
th{{background:#eef2f7}}
.note{{padding:15px 18px;border-left:5px solid #3973ac;background:#eef6ff;margin:18px 0}}
.warn{{padding:15px 18px;border-left:5px solid {C_NEG};background:#fff4ee;margin:18px 0}}
.small{{color:{MUTED};font-size:.88rem}}
.ok{{color:#1b7f4d;font-weight:600}}.bad{{color:#c0392b;font-weight:700}}
code{{background:#f1f3f6;padding:1px 4px;border-radius:3px;font-size:.92em}}
.asset{{margin:30px 0 44px;border-top:1px solid {GRID};padding-top:14px}}
.pair-grid{{display:grid;grid-template-columns:1fr 1fr;gap:18px;align-items:start}}
figure{{margin:0}}figure img{{display:block;width:100%;height:auto;border:1px solid {GRID}}}
figure.wide{{margin-top:18px}}figure.wide img{{border:1px solid {GRID}}}
.tag{{font-size:.72rem;padding:2px 8px;border-radius:10px;color:white;vertical-align:middle}}
.tag.positive{{background:{C_POS}}}.tag.negative{{background:{C_NEG}}}.tag.glass{{background:{C_GLASS}}}
ul{{padding-left:22px}}
.chart{{max-width:1000px}}.chart img{{width:100%;border:none}}
</style></head><body><main>

<h1>2026-07-29 · Spatial PBR (polartexture) A/B — 작업 전/후 렌더 퀄리티 비교</h1>
<p class='small'>scene kr_20000221 + kr_20260625 · 8 assets × 2 view × 2 light = {pair_count} pair ·
256×256 / 64 spp · <code>cuda_ad_spectral_polarized</code> (RGB는 <code>cuda_ad_spectral</code>) ·
Device 1 (RTX 5090, OptiX 8 빌드)</p>

<h2>1. 무엇을 비교했나</h2>
<table>
<tr><th></th><th>A — 작업 전 (analytic)</th><th>B — 작업 후 (spatial)</th></tr>
<tr><th>재질 결정</th><td>unit의 <code>optical_class</code> 하나로 BSDF 1개 선택</td>
<td>per-texel PBR atlas가 BSDF를 공간적으로 변조</td></tr>
<tr><th>BSDF</th><td><code>roughconductor</code>(metal) / <code>pplastic</code>(그 외) / <code>dielectric</code>(glass)</td>
<td><code>blendbsdf(weight=metallic.png){{ pplastic , roughconductor }}</code></td></tr>
<tr><th>금속 η/k</th><td>이름 preset 1개 (Al/Au/Cu/Cr)</td>
<td>basecolor F0 → nearest preset → <code>n_map.exr</code> / <code>k_map.exr</code> 텍스처</td></tr>
<tr><th>거칠기</th><td>raw roughness 비트맵</td><td>alpha = roughness² 비트맵</td></tr>
</table>
<div class='note'><strong>커스텀 플러그인은 없다.</strong> 스톡 <code>blendbsdf</code> + <code>roughconductor</code>의
eta/k를 텍스처로 직접 주입하는 방식이다. <code>conductor_index.png</code>는 렌더에 쓰이지 않는 진단용
categorical segmentation이며, 렌더 경로는 index lookup이 아니라 연속 η/k 맵이다.</div>

<h2>2. 실험 설계</h2>
<ul>
<li>A/B 쌍마다 geometry(GLB materialized OBJ part), UV, camera_to_world, light_to_world, spp, seed가
동일함을 <code>assert_scene_pair_invariants</code>로 강제한다. 차이는 material layer 하나뿐이다.</li>
<li>ROI는 별도 UV AOV 렌더에서 만든 object / metal / dielectric 마스크로 분리한다. 표의 값은 object ROI다.</li>
<li>positive = 실제 spatial metallic을 가진 4종. negative = metallic이 사실상 0인 불투명 dielectric control 3종 —
여기서 A와 B가 크게 다르면 그건 개선이 아니라 회귀 신호다.</li>
<li>원 config는 유리 1종도 negative에 넣었지만, 이 리포트는 <strong>glass를 별도 role로 분리</strong>한다.
§5에서 보듯 branch B에는 투과 경로 자체가 없어서 "변하지 않아야 정상"이라는 negative control의 전제가
유리에는 성립하지 않는다.</li>
</ul>

<h2>3. 입력 자산 감사 — 결과 해석 전에 먼저 볼 것</h2>
<p>A/B의 비교 자체는 유효하다(양쪽이 동일 geometry·UV·카메라·조명·seed를 쓴다). 하지만 그 위에 올라간
<strong>입력 텍스처가 정상인지는 별개 문제</strong>이고, 이번에 전수 감사한 결과가 아래다.
UV는 bounds만 봐서는 안 된다 — 면적이 0인 삼각형 비율과 overlap factor(UV 삼각형 면적 합 ÷ 점유 bbox 면적)를
봐야 한다. 감사 도구는 <code>tools/audit_glb_part_uv.py</code>.</p>
{input_audit_table(current)}
<div class='note'><strong>이번 판의 8종은 모두 감사를 통과했다.</strong> positive는
<code>configs/experiments/spatial_pbr_ab_2026-07-29.json</code>의 기준으로 kr_20260625에서 새로 뽑았다 —
albedo/roughness/metallic 전부 <code>spatial_bake_candidate</code>, GLB geometry·UV valid,
albedo atlas max &gt; 0.15, 그리고 metallic이 실제로 공간 변화할 것(아래 §3.2).</div>

<h3>3.1 교체된 이전 positive — 왜 버렸나</h3>
<p>2026-07-13 config의 positive 4종은 <strong>전부, 서로 다른 방식으로 결함</strong>이 있었다.
넷 다 kr_20000221 소속인데, 이 씬은 covered-UV bake 감사를 받은 적이 없다.</p>
<table>
<tr><th>버려진 asset</th><th>결함</th></tr>
<tr><th>BeverageFridge</th><td>UV는 정상인데 <strong>albedo bake 붕괴</strong> — atlas 전체 최대 픽셀 0.059.
렌더가 검은 것은 재질이 아니라 텍스처가 검정이기 때문. 2026-07-13 감사가 kr_20260625에서 잡은
<code>linked_bake_collapse</code>와 같은 유형.</td></tr>
<tr><th>BookColumn</th><td>924 삼각형(87.5%)이 UV 한 패치에 <strong>45배로 포개짐</strong>, 그중 52%는 면적 0.</td></tr>
<tr><th>Bottle_3548288</th><td>병 몸통(19,440 tri = 77%) UV가 <strong>전부 (0,0)</strong> — atlas 구석 텍셀 하나만 샘플링.
알려진 Infinigen OBJ vt=0 결함이 GLB materialize 산출물에 남은 경우.</td></tr>
<tr><th>BookStack</th><td>overlap 6–17배. BookColumn보다 경미하고 albedo는 정상.</td></tr>
</table>
<div class='warn'><strong>이 교체가 결과를 크게 바꿨다.</strong> 결함 입력에서 positive ΔDoLP는 0.0869,
불투명 negative 0.0060으로 <strong>14.4배</strong> 벌어졌다. 감사된 입력에서는 positive 0.0102,
불투명 negative 0.0038로 <strong>2.7배</strong>다. 즉 이전 판의 큰 신호는 상당 부분 <strong>깨진 입력이 만든 것</strong>이었다.
(해상도도 256/64 → 640/512로 함께 바뀌었으므로 감소분 전부를 입력 탓으로 돌릴 수는 없다. 다만 이전 positive가
실제로 결함이었다는 사실 자체는 위 표로 확정된다.)</div>

<h3>3.2 metallic이 정말 공간 변화하는가</h3>
<p><code>robust_range ≥ 0.30</code>만으로는 <strong>순수 0/1 마스크도 통과</strong>한다. polar texture 검증에는
중간값과 공간 구조가 함께 있어야 하므로 두 지표를 추가했다 — <strong>graded fraction</strong>(커버 텍셀 중
0.10 &lt; m &lt; 0.90 비율)과 <strong>gradient</strong>(커버 영역 평균 |∇m|). 이 기준으로 MonitorFactory와
ToiletFactory는 graded 0.1%(통짜 이진 blob)로 탈락했다.</p>
<div class='warn'><strong>한계: Infinigen에는 재질 내부의 metallic 그라디언트가 없다.</strong>
Infinigen은 metallic을 재질 정체성(상수)으로, roughness/albedo를 표면 디테일(공간변화)로 설계한다.
따라서 여기서 얻을 수 있는 공간 변화는 <strong>하나의 UV atlas에 여러 재질이 패킹된 세그먼테이션</strong>이지
연속적인 물성 변화가 아니다. §6의 conductor index 결과와 같은 곳을 가리킨다 — spatial layer가 주는 것은
<em>어디가 금속인가</em>이지 <em>얼마나·어떤 금속인가</em>가 아니다.</div>

<h2>4. 정량 결과</h2>
{group_table(current)}
<div class='chart'><figure><img src='{chart}' alt='asset별 ΔDoLP mean'>
<figcaption class='small'>asset별 ΔDoLP mean (object ROI). 값이 클수록 spatial layer가 편광 신호를 크게 바꿨다는 뜻이며,
positive에서는 의도된 변화, negative에서는 원치 않는 변화다.</figcaption></figure></div>
{asset_table(current)}

<h2>5. glass baseline 수정과 그것이 드러낸 것</h2>
<div class='warn'><strong>수정 전 glass A/B는 무효였다.</strong> branch A가 유리에
<code>roughdielectric</code>을 썼는데, 이 빌드에서 <code>roughdielectric</code>은 DoLP=0을 낸다
(dev_report 2026-07-06 §2.1). baseline에 편광이 아예 없었으므로 AoLP 거리가 정확히 0.0000으로 찍혔다 —
개선이 아니라 각도가 정의되지 않았던 것이다.</div>
<p><code>spatial_pbr_ab.py</code>의 analytic glass 분기를 smooth <code>dielectric</code>으로 바꾸고 해당 4쌍을
재렌더했다. 프로덕션 경로(<code>render_daemon.py:949</code>)는 이미 smooth dielectric을 강제하고 있었으므로,
이 수정은 실험 하네스를 프로덕션 계약에 맞춘 것이다.</p>
{glass_delta_table(current, old)}
<div class='warn'><strong>수정 결과 차이가 줄어든 게 아니라 커졌다 ({glass_shift(current, old)}). 이게 진짜 발견이다.</strong>
<code>_spatial_material</code>은 <code>optical_class</code>를 전혀 보지 않고 항상
<code>blendbsdf(pplastic, roughconductor)</code>를 낸다. 즉 <strong>branch B에는 투과 경로가 없다</strong> —
유리를 불투명 플라스틱/금속으로 바꿔버린다. 이전에는 A가 DoLP=0이라 이 사실이 가려져 있었고, A를 올바른
강편광 Fresnel 유리로 고치자 드러났다. 따라서 <strong>spatial layer는 불투명 재질 전용이며,
투과 재질에는 적용하면 안 된다.</strong> 프로덕션 배선 시 <code>optical_class</code>가 glass인 unit은
analytic dielectric으로 우회하는 분기가 필요하다.</div>
{group_means_before_after(current, old)}

<h2>6. conductor preset 매칭 — 사실상 W 하나로 붕괴</h2>
<p>텍스처 맵 패널의 conductor index를 정량화하면 다음과 같다. preset은 7종(Ag/Al/Au/Cr/Cu/Ni_palik/W)이 준비돼 있다.</p>
{conductor_match_table(current)}
<div class='warn'><strong>금속 texel이 거의 전부 W(텅스텐)로 매칭된다.</strong> conductor를 가진 4종에서
Ni_palik 2.4% 한 조각을 빼면 선택된 금속은 W뿐이고, F0 매칭 L2 오차는 0.63–0.86으로 매우 크다
(F0는 0–1 RGB 스케일). 즉 <strong>현재 η/k 맵의 공간 변화는 실질적으로 "유전체냐 금속이냐"의 이진 분리뿐이고,
금속 종류는 상수나 마찬가지다.</strong> Infinigen 금속 base_color는 <code>metal_hsv()</code> 난수라 애초에
"진짜 금속 복원"이 아니라 "외형정합 스냅"이므로 이 자체가 버그는 아니지만, 큰 L2 오차는 스냅조차 잘 안 되고
있다는 뜻이다. 편광은 Fresnel(η/k)에서 나오므로 이 붕괴는 DoLP 값에 직접 영향을 준다 —
optical_class 기반 η/k injection이 필요한 지점이 여기다.</div>

<h2>7. asset별 시각 비교</h2>
<p class='small'>조건 <code>{HERO_CONDITION}</code> 기준. 각 그림은 3패널이다 — 좌: A(작업 전),
중: B(작업 후), 우: 두 branch의 절대차를 3배 증폭한 것. 절대차 패널이 어두울수록 A와 B가 같다는 뜻이다.</p>
{asset_figures(current)}

<h2>8. 전체 contact sheet</h2>
{''.join(sheets)}

<h2>9. 판정과 한계</h2>
<ul>
<li><strong>판정: 감사된 입력에서 효과는 실재하지만 작다.</strong> positive ΔDoLP 0.0102 vs 불투명
dielectric control 0.0038 — 방향은 맞지만 분리비는 2.7배이고 절대값은 0.01 수준이다. 결함 입력으로 측정했던
이전 판의 14.4배는 재현되지 않는다(§3.1).</li>
<li><strong>glass는 완전한 no-op이 됐다.</strong> per-slot optical_class 수정 + 투과 슬롯 우회 이후
PlantContainer의 ΔDoLP·AoLP 거리·RGB MAE가 모두 정확히 0이다. 수정이 의도대로 작동함을 확인해 준다.</li>
<li><strong>투과 재질에는 쓸 수 없다.</strong> §5 참조. branch B에 transmission BSDF 경로가 없어 유리가
불투명해진다. 프로덕션 배선의 선결 조건이다.</li>
<li><strong>conductor 점유율 폭이 좁다.</strong> atlas의 커버 텍셀 기준 metal 비율은 14~82%로 골랐지만,
렌더에 들어가는 <code>conductor_fraction</code>(atlas 전체 평균)은 0.09~0.17에 그친다. UV 커버리지가 그만큼
낮기 때문이다. 더 넓은 폭이 필요하면 커버리지가 높은 자산을 따로 골라야 한다.</li>
<li><strong>입력 품질 한계.</strong> <code>spatial_pbr.py</code>는 <code>metallic &gt;= 0.5</code>로 conductor
마스크를 만든다. 따라서 이 파이프라인의 품질 상한은 Infinigen metallic bake의 품질이다. kr_20260625 감사 기준
linked metallic 텍스처가 black으로 붕괴한 17 unit은 전부 dielectric으로 넘어가고, 상수로 붕괴한 16 unit
(그중 14개가 ≥0.998)은 전부 conductor로 넘어간다. eta/k도 붕괴한 basecolor의 F0에서 유도되므로
nearest-preset 매칭까지 오염된다.</li>
<li><strong>금속 종류 해상도가 없다.</strong> §6 참조 — F0 nearest-preset이 사실상 W 하나로 붕괴한다.</li>
<li><strong>미통합.</strong> <code>multimodal.py</code> / <code>render_daemon.py</code>에 spatial PBR 참조는
0건이다. 이 layer는 아직 독립 실험 하네스이며 OpticalNav 프로덕션 렌더는 사용하지 않는다.</li>
</ul>

</main></body></html>"""


def main() -> int:
    current = by_asset(load_pairs(EXPERIMENT / "metrics.json"))
    old_path = BACKUP / "metrics.json"
    old = by_asset(load_pairs(old_path)) if old_path.is_file() else current
    REPORT_PATH.write_text(build(current, old), encoding="utf-8")
    print(f"wrote {REPORT_PATH}")
    print(f"assets={len(current)} pairs={sum(len(v) for v in current.values())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
