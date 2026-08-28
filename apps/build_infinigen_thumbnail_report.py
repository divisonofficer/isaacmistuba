#!/usr/bin/env python3
"""Build a portable RGB/polarization thumbnail report for OpticalNav scenes.

The report deliberately reads the rendered observations directly.  Export job
state is included as provenance, but a successful-looking UI is never used as
evidence that a base/on camera pair is available.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from PIL import Image, ImageChops, ImageDraw, ImageOps, ImageStat


RGB_CAMERA = "opticalnav_rear_cam"
SECONDARY_RGB_CAMERA = "opticalnav_rear_cam_copy"
POLAR_CAMERA = "polar_cam"
POLAR_TILES = (
    ("polar_rgb_preview.png", "Polar RGB"),
    ("dop_red_black_colorbar.png", "DoLP"),
    ("aolp_rainbow_colorbar.png", "AoLP"),
    ("s1_over_s0_bwr_colorbar.png", "S1/S0"),
    ("s2_over_s0_bwr_colorbar.png", "S2/S0"),
)


@dataclass(frozen=True)
class Observation:
    variant: str
    vp_id: str
    heading_id: str
    manifest: Path
    directory: Path
    rgb: Path | None
    secondary_rgb: Path | None
    polar_files: tuple[Path, ...]


@dataclass(frozen=True)
class Candidate:
    scene_id: str
    vp_id: str
    heading_id: str
    base: Observation
    perturbed: Observation
    region: str
    score: float


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return default


def _path_key(manifest: Path) -> tuple[str, str] | None:
    parts = manifest.parts
    try:
        vp_index = next(i for i, item in enumerate(parts) if item.startswith("vp_"))
    except StopIteration:
        return None
    if vp_index + 1 >= len(parts) or not parts[vp_index + 1].startswith("h_"):
        return None
    return parts[vp_index], parts[vp_index + 1]


def _variant_for_manifest(manifest: Path, root: Path) -> str:
    relative = manifest.relative_to(root)
    parts = {part.lower() for part in relative.parts}
    if root.name in {"observations_perturbed", "perturbed"} or {"perturbed", "on"} & parts:
        return "perturbed"
    return "base"


def _sensor_files(observation_dir: Path, camera_id: str, names: Iterable[str]) -> tuple[Path, ...]:
    names = tuple(names)
    for layout in ("sensors", "cameras"):
        sensor_dir = observation_dir / layout / camera_id
        found = tuple(path for name in names if (path := sensor_dir / name).is_file())
        if found:
            return found
    if camera_id == POLAR_CAMERA:
        return tuple(path for name in names if (path := observation_dir / name).is_file())
    return ()


def _sample_view_keys(
    scene_dir: Path, *, nodes_per_region: int | None, headings_per_node: int | None,
) -> list[tuple[str, str]]:
    graph = _read_json(scene_dir / "viewpoint_graph.json", {})
    regions, positions = _regions(scene_dir), _viewpoint_positions(scene_dir)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for node in graph.get("nodes", []):
        grouped.setdefault(_region_for(positions.get(str(node.get("node_id"))), regions), []).append(node)
    selected_nodes = []
    for nodes in grouped.values():
        ordered = sorted(nodes, key=lambda node: str(node.get("node_id")))
        if nodes_per_region is not None and len(ordered) > nodes_per_region:
            indices = {round(index * (len(ordered) - 1) / max(1, nodes_per_region - 1)) for index in range(nodes_per_region)}
            ordered = [ordered[index] for index in sorted(indices)]
        selected_nodes.extend(ordered)
    keys = []
    for node in selected_nodes:
        headings = sorted(node.get("headings", []), key=lambda heading: str(heading.get("heading_id")))
        if headings_per_node is not None and len(headings) > headings_per_node:
            indices = {round(index * (len(headings) - 1) / max(1, headings_per_node - 1)) for index in range(headings_per_node)}
            headings = [headings[index] for index in sorted(indices)]
        keys.extend((str(node.get("node_id")), str(heading.get("heading_id"))) for heading in headings)
    return keys


def collect_observations(
    scene_dir: Path, *, nodes_per_region: int | None = None, headings_per_node: int | None = None,
) -> dict[tuple[str, str, str], Observation]:
    """Collect observations via graph keys, avoiding a costly output-tree scan."""
    collected: dict[tuple[str, str, str], Observation] = {}
    view_keys = _sample_view_keys(scene_dir, nodes_per_region=nodes_per_region, headings_per_node=headings_per_node)
    roots = [scene_dir / "observations", scene_dir / "observations_perturbed"]
    version_root = scene_dir / "observations" / "versions"
    if version_root.is_dir():
        for version in version_root.iterdir():
            roots.extend((version / "base", version / "perturbed"))
    for root in roots:
        if not root.is_dir():
            continue
        for key in view_keys:
            observation_dir = root / key[0] / key[1]
            manifest = observation_dir / "manifest.json"
            if not manifest.is_file():
                manifest = observation_dir / "sensors" / "_sensor_index.json"
                observation_dir = manifest.parent.parent
            if not manifest.is_file():
                continue
            variant = _variant_for_manifest(manifest, root)
            rgb = _sensor_files(observation_dir, RGB_CAMERA, ("rgb.png",))
            secondary = _sensor_files(observation_dir, SECONDARY_RGB_CAMERA, ("rgb.png",))
            polar = _sensor_files(observation_dir, POLAR_CAMERA, (name for name, _ in POLAR_TILES))
            item = Observation(variant, key[0], key[1], manifest, observation_dir, rgb[0] if rgb else None,
                               secondary[0] if secondary else None, polar)
            map_key = (variant, *key)
            prior = collected.get(map_key)
            item_quality = (bool(item.rgb), bool(item.secondary_rgb), len(item.polar_files), manifest.stat().st_mtime_ns)
            prior_quality = ((bool(prior.rgb), bool(prior.secondary_rgb), len(prior.polar_files), prior.manifest.stat().st_mtime_ns)
                             if prior else None)
            if prior is None or item_quality > prior_quality:
                collected[map_key] = item
    # A compact export can retain valid RGB/polar preview pairs even when the
    # original observation directory was compacted.  Leave placeholders for
    # those graph keys so archive hydration can supply the portable previews.
    for vp_id, heading_id in view_keys:
        for variant, directory_name in (("base", "observations"), ("perturbed", "observations_perturbed")):
            map_key = (variant, vp_id, heading_id)
            if map_key not in collected:
                directory = scene_dir / directory_name / vp_id / heading_id
                collected[map_key] = Observation(variant, vp_id, heading_id, directory / "archive_preview", directory,
                                                  None, None, ())
    return collected


def _regions(scene_dir: Path) -> list[tuple[str, tuple[float, float, float, float]]]:
    payload = _read_json(scene_dir / "authoring_map.json", {})
    result = []
    for region in payload.get("regions", []):
        bounds = region.get("geometry", {}).get("bounds")
        if isinstance(bounds, list) and len(bounds) == 4:
            result.append((str(region.get("label") or region.get("id")), tuple(map(float, bounds))))
    return result


def _viewpoint_positions(scene_dir: Path) -> dict[str, tuple[float, float]]:
    payload = _read_json(scene_dir / "viewpoint_graph.json", {})
    positions = {}
    for node in payload.get("nodes", []):
        position = node.get("position")
        if isinstance(position, list) and len(position) >= 2:
            positions[str(node.get("node_id"))] = (float(position[0]), float(position[1]))
    return positions


def _region_for(position: tuple[float, float] | None, regions: list[tuple[str, tuple[float, float, float, float]]]) -> str:
    if position is None:
        return "Unassigned"
    x, y = position
    for label, (min_x, min_y, max_x, max_y) in regions:
        if min_x <= x <= max_x and min_y <= y <= max_y:
            return label
    return "Unassigned"


def image_difference_score(base: Path, perturbed: Path) -> float:
    with Image.open(base) as left, Image.open(perturbed) as right:
        left_small = ImageOps.fit(left.convert("RGB"), (192, 144), Image.Resampling.BILINEAR)
        right_small = ImageOps.fit(right.convert("RGB"), (192, 144), Image.Resampling.BILINEAR)
        return sum(ImageStat.Stat(ImageChops.difference(left_small, right_small)).mean) / (3 * 255)


def _score_sample(candidates: list[Candidate], budget: int) -> list[Candidate]:
    """Score a spatially diverse bounded sample, keeping CIFS reads predictable."""
    if len(candidates) <= budget:
        return [replace(item, score=image_difference_score(item.base.rgb, item.perturbed.rgb)) for item in candidates]
    grouped: dict[str, list[Candidate]] = {}
    for item in candidates:
        grouped.setdefault(item.region, []).append(item)
    per_region = max(1, budget // len(grouped))
    sample = []
    for group in grouped.values():
        ordered = sorted(group, key=lambda item: (item.vp_id, item.heading_id))
        indices = {round(index * (len(ordered) - 1) / max(1, per_region - 1)) for index in range(per_region)}
        sample.extend(ordered[index] for index in sorted(indices))
    sample = sample[:budget]
    return [replace(item, score=image_difference_score(item.base.rgb, item.perturbed.rgb)) for item in sample]


def collect_candidates(
    scene_id: str, scene_dir: Path, *, score_budget: int = 48,
    nodes_per_region: int | None = None, headings_per_node: int | None = None,
    polar_archive: Path | None = None, archive_cache: Path | None = None,
) -> tuple[list[Candidate], dict[str, int]]:
    observations = collect_observations(scene_dir, nodes_per_region=nodes_per_region, headings_per_node=headings_per_node)
    if archive_cache is not None:
        observations = hydrate_polar_thumbnails_from_archive(observations, polar_archive, archive_cache, scene_id)
    positions, regions = _viewpoint_positions(scene_dir), _regions(scene_dir)
    stats = {"base": 0, "perturbed": 0, "paired": 0, "renderable_pairs": 0, "secondary_rgb_pairs": 0, "score_sampled": 0}
    for observation in observations.values():
        stats[observation.variant] += 1
    candidates = []
    for (_, vp_id, heading_id), base in sorted(observations.items()):
        if base.variant != "base":
            continue
        perturbed = observations.get(("perturbed", vp_id, heading_id))
        if perturbed is None:
            continue
        stats["paired"] += 1
        if not (base.rgb and perturbed.rgb and base.polar_files and perturbed.polar_files):
            continue
        stats["renderable_pairs"] += 1
        if base.secondary_rgb and perturbed.secondary_rgb:
            stats["secondary_rgb_pairs"] += 1
        candidates.append(Candidate(
            scene_id, vp_id, heading_id, base, perturbed,
            _region_for(positions.get(vp_id), regions), 0.0,
        ))
    scored = _score_sample(candidates, score_budget)
    stats["score_sampled"] = len(scored)
    return scored, stats


def select_candidates(candidates: list[Candidate], limit: int) -> list[Candidate]:
    """Prefer a different traversable region before taking another high-score view."""
    ranked = sorted(candidates, key=lambda item: (-item.score, item.region, item.vp_id, item.heading_id))
    selected, used_regions, used_viewpoints = [], set(), set()
    for candidate in ranked:
        if len(selected) >= limit:
            break
        if candidate.region in used_regions or candidate.vp_id in used_viewpoints:
            continue
        selected.append(candidate)
        used_regions.add(candidate.region)
        used_viewpoints.add(candidate.vp_id)
    for candidate in ranked:
        if len(selected) >= limit:
            break
        if candidate.vp_id in used_viewpoints:
            continue
        selected.append(candidate)
        used_viewpoints.add(candidate.vp_id)
    return selected


def exclude_candidates(
    candidates: list[Candidate], excluded: set[tuple[str, str, str]], excluded_viewpoints: set[tuple[str, str]],
) -> list[Candidate]:
    return [item for item in candidates if (item.scene_id, item.vp_id, item.heading_id) not in excluded
            and (item.scene_id, item.vp_id) not in excluded_viewpoints]


def _polar_sheet(files: tuple[Path, ...], destination: Path) -> None:
    if len(files) == 1 and files[0].name == "polar_thumbnail.webp":
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(files[0], destination)
        return
    source_by_name = {path.name: path for path in files}
    chosen = [(label, source_by_name[name]) for name, label in POLAR_TILES if name in source_by_name]
    tile_width, tile_height, label_height, columns = 180, 120, 22, 3
    rows = max(1, (len(chosen) + columns - 1) // columns)
    sheet = Image.new("RGB", (columns * tile_width, rows * (tile_height + label_height)), (15, 23, 42))
    draw = ImageDraw.Draw(sheet)
    for index, (label, source) in enumerate(chosen):
        with Image.open(source) as image:
            tile = ImageOps.contain(image.convert("RGB"), (tile_width, tile_height), Image.Resampling.LANCZOS)
        x, y = (index % columns) * tile_width, (index // columns) * (tile_height + label_height)
        sheet.paste(tile, (x + (tile_width - tile.width) // 2, y + (tile_height - tile.height) // 2))
        draw.text((x + 5, y + tile_height + 3), label, fill=(226, 232, 240))
    destination.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(destination, "WEBP", quality=84, method=6)


def _difference_image(base: Path, perturbed: Path, destination: Path) -> None:
    with Image.open(base) as left, Image.open(perturbed) as right:
        size = (min(left.width, right.width), min(left.height, right.height))
        diff = ImageChops.difference(left.convert("RGB").resize(size), right.convert("RGB").resize(size))
        diff.save(destination)


def materialize_candidate(candidate: Candidate, asset_root: Path, report_root: Path) -> dict[str, str]:
    prefix = f"{candidate.scene_id}/{candidate.vp_id}_{candidate.heading_id}"
    paths = {
        "rgb_off": asset_root / f"{prefix}_rgb_off.png",
        "rgb_on": asset_root / f"{prefix}_rgb_on.png",
        "difference": asset_root / f"{prefix}_rgb_absdiff.png",
        "polar_off": asset_root / f"{prefix}_polar_off.webp",
        "polar_on": asset_root / f"{prefix}_polar_on.webp",
    }
    if all(path.is_file() for path in paths.values()):
        return {key: path.relative_to(report_root).as_posix() for key, path in paths.items()}
    for key in ("rgb_off", "rgb_on"):
        paths[key].parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(candidate.base.rgb, paths["rgb_off"])
    shutil.copy2(candidate.perturbed.rgb, paths["rgb_on"])
    _difference_image(candidate.base.rgb, candidate.perturbed.rgb, paths["difference"])
    _polar_sheet(candidate.base.polar_files, paths["polar_off"])
    _polar_sheet(candidate.perturbed.polar_files, paths["polar_on"])
    return {key: path.relative_to(report_root).as_posix() for key, path in paths.items()}


def materialize_gallery_candidate(candidate: Candidate, asset_root: Path, report_root: Path) -> dict[str, str]:
    """Keep the 50-item review gallery light by referring to source RGB PNGs."""
    return {
        "rgb_off": os.path.relpath(candidate.base.rgb, report_root).replace("\\", "/"),
        "rgb_on": os.path.relpath(candidate.perturbed.rgb, report_root).replace("\\", "/"),
    }


def _export_status(exports_dir: Path, scene_id: str) -> dict[str, Any] | None:
    statuses = []
    for directory in exports_dir.glob(f"export-{scene_id}-*/export_status.json"):
        payload = _read_json(directory, {})
        statuses.append((payload.get("created_at", ""), directory.parent.name, payload))
    if not statuses:
        return None
    _, job_id, payload = max(statuses)
    return {"job_id": job_id, "status": payload.get("status", "unknown"), "profile": payload.get("export_profile"),
            "updated_at": payload.get("updated_at"), "message": payload.get("message")}


def _polar_archive(exports_dir: Path, scene_id: str) -> Path | None:
    candidates = sorted(exports_dir.glob(f"export-{scene_id}-*/*_core.zip"))
    return candidates[-1] if candidates else None


def load_evidence_selection(path: Path) -> tuple[str, list[Candidate], list[Candidate], dict[str, Any]]:
    """Load explicitly reviewed final picks and the complete candidate gallery."""
    payload = _read_json(path, {})
    scene_id = str(payload.get("scene_id") or "")
    selected = payload.get("recommended_final_six")
    rows = payload.get("candidates")
    if not scene_id or not isinstance(selected, list) or not isinstance(rows, list):
        raise ValueError(f"{path} is not an apartment candidate-pool manifest")
    def make_candidate(row: dict[str, Any]) -> Candidate:
        base_rgb, perturbed_rgb = Path(row["base_rgb"]), Path(row["perturbed_rgb"])
        base_polar = tuple(Path(value) for value in row["base_polar"])
        perturbed_polar = tuple(Path(value) for value in row["perturbed_polar"])
        required = (base_rgb, perturbed_rgb, *base_polar, *perturbed_polar)
        missing = [str(item) for item in required if not item.is_file()]
        if missing:
            raise ValueError(f"Evidence selection has missing source files: {missing[0]}")
        vp_id, heading_id = str(row["vp_id"]), str(row["heading_id"])
        base = Observation("base", vp_id, heading_id, base_rgb, base_rgb.parents[2], base_rgb, None, base_polar)
        perturbed = Observation("perturbed", vp_id, heading_id, perturbed_rgb, perturbed_rgb.parents[2], perturbed_rgb, None, perturbed_polar)
        return Candidate(scene_id, vp_id, heading_id, base, perturbed, str(row["room"]), float(row["rgb_difference_score"]))
    gallery = [make_candidate(row) for row in rows]
    by_key = {(item.vp_id, item.heading_id): item for item in gallery}
    recommended = [by_key[(str(row["vp_id"]), str(row["heading_id"]))] for row in selected]
    return scene_id, recommended, gallery, {"source": str(path), "sampling": payload.get("sampling", {}), "rows": rows,
                                             "recommended_rows": selected}


def hydrate_polar_thumbnails_from_archive(
    observations: dict[tuple[str, str, str], Observation], archive: Path | None, cache: Path, scene_id: str,
) -> dict[tuple[str, str, str], Observation]:
    """Use compact-export preview sheets only when raw polar previews are absent."""
    if archive is None:
        return observations
    hydrated = dict(observations)
    with zipfile.ZipFile(archive) as source:
        names = set(source.namelist())
        for key, observation in observations.items():
            variant_dir = "observations_perturbed" if observation.variant == "perturbed" else "observations"
            prefix = f"scenes/{scene_id}/{variant_dir}/{observation.vp_id}/{observation.heading_id}/sensors"
            rgb = observation.rgb
            if rgb is None:
                for camera_id in (RGB_CAMERA, SECONDARY_RGB_CAMERA):
                    member = f"{prefix}/{camera_id}/rgb.webp"
                    if member in names:
                        destination = cache / observation.variant / observation.vp_id / observation.heading_id / f"{camera_id}_rgb.webp"
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        destination.write_bytes(source.read(member))
                        rgb = destination
                        break
            polar_files = observation.polar_files
            member = f"{prefix}/{POLAR_CAMERA}/polar_thumbnail.webp"
            if not polar_files and member in names:
                destination = cache / observation.variant / observation.vp_id / observation.heading_id / "polar_thumbnail.webp"
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(source.read(member))
                polar_files = (destination,)
            hydrated[key] = replace(observation, rgb=rgb, polar_files=polar_files)
    return hydrated


def _esc(value: Any) -> str:
    return html.escape(str(value))


def render_report(rows: list[dict[str, Any]], output: Path) -> None:
    sections = []
    for row in rows:
        status = row["export_status"] or {"job_id": "no export job found", "status": "not started", "profile": "—", "updated_at": "—", "message": "—"}
        cards = []
        def make_card(item: dict[str, Any]) -> str:
            images = "".join(f'<figure><img src="{_esc(item["assets"][key])}" loading="lazy"><figcaption>{label}</figcaption></figure>'
                             for key, label in (("rgb_off", "RGB off"), ("rgb_on", "RGB on"), ("difference", "RGB |off−on|"), ("polar_off", "Polar off"), ("polar_on", "Polar on")))
            evidence = item.get("evidence") or {}
            overlay = (f'{_esc(evidence.get("likely_overlay_type", ""))} · {_esc(evidence.get("likely_overlay_id", ""))}'
                       if evidence else "")
            rationale = _esc(evidence.get("selection_rationale") or evidence.get("exposure_rationale") or "")
            return (f'<article><h3>{_esc(item["region"])} · {_esc(item["vp_id"])} / {_esc(item["heading_id"])}</h3>'
                    f'<p>normalized RGB change: <b>{item["score"]:.3f}</b> {overlay}<br>{rationale}</p><div class="thumbs">{images}</div></article>')
        cards = [make_card(item) for item in row["selected"]]
        gallery = row.get("gallery", [])
        gallery_html = ""
        if gallery:
            gallery_cards = []
            for item in gallery:
                evidence = item["evidence"]
                images = "".join(f'<figure><img src="{_esc(item["assets"][key])}" loading="lazy"><figcaption>{label}</figcaption></figure>'
                                 for key, label in (("rgb_off", "RGB off"), ("rgb_on", "RGB on")))
                gallery_cards.append(f'<article class="gallery-card"><h3>{_esc(item["region"])} · {_esc(item["vp_id"])} / {_esc(item["heading_id"])}</h3>'
                                     f'<p>{_esc(evidence["likely_overlay_type"])} · {_esc(evidence["likely_overlay_id"])} · Δ {_esc(f"{item["score"]:.3f}")}</p><div class="thumbs">{images}</div></article>')
            gallery_html = f'<details><summary>Reviewed candidate gallery ({len(gallery)} complete RGB+polar off/on pairs; RGB comparison view)</summary><div class="gallery">{"".join(gallery_cards)}</div></details>'
        stats = row["stats"]
        provisional = " provisional" if status["status"] != "succeeded" else ""
        sections.append(f'''<section><h2>{_esc(row["scene_id"])}<span class="tag{provisional}">{_esc(status["status"])}</span></h2>
<p class="mut">Export <code>{_esc(status["job_id"])}</code> · profile {_esc(status["profile"])} · {_esc(status["message"] or "")}</p>
<div class="metrics"><span>base scanned <b>{stats["base"]}</b></span><span>on scanned <b>{stats["perturbed"]}</b></span><span>paired <b>{stats["paired"]}</b></span><span>RGB+polar-ready <b>{stats["renderable_pairs"]}</b></span><span>change-scored <b>{stats["score_sampled"]}</b></span><span>selected <b>{len(row["selected"])}</b></span></div>
{''.join(cards) if cards else '<div class="notice">No complete RGB+polar base/on pair is currently available. This section will populate on regeneration after the source observations are complete.</div>'}{gallery_html}</section>''')
    output.write_text(f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Infinigen optical dataset thumbnails</title><style>
:root{{--bg:#0d1117;--panel:#161d27;--line:#2c3849;--fg:#e8edf4;--mut:#a5b0bf;--blue:#78abff;--warn:#f4c95d}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 system-ui,sans-serif}}main{{max-width:1500px;margin:auto;padding:38px 24px 72px}}h1{{margin:0}}h2{{border-top:1px solid var(--line);padding-top:28px;margin-top:44px}}h3{{margin:0 0 2px;color:var(--blue)}}.mut{{color:var(--mut)}}.tag{{font-size:12px;border:1px solid #48d597;border-radius:99px;padding:3px 8px;margin-left:10px;color:#58dba2}}.tag.provisional{{border-color:var(--warn);color:var(--warn)}}.metrics{{display:flex;flex-wrap:wrap;gap:10px;margin:14px 0 18px}}.metrics span,.notice{{background:var(--panel);border:1px solid var(--line);border-radius:9px;padding:8px 12px;color:var(--mut)}}.metrics b{{color:var(--fg);margin-left:5px}}article{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px;margin:16px 0}}article p{{margin:0 0 10px;color:var(--mut)}}.thumbs{{display:grid;grid-template-columns:repeat(5,minmax(150px,1fr));gap:10px}}figure{{margin:0;background:#0a0f16;border-radius:7px;overflow:hidden}}img{{display:block;width:100%;height:154px;object-fit:contain}}figcaption{{padding:5px 7px;color:var(--mut);font-size:12px}}code{{background:#202a38;padding:2px 5px;border-radius:3px}}details{{margin-top:28px}}summary{{cursor:pointer;color:var(--blue);font-weight:700;background:var(--panel);border:1px solid var(--line);padding:12px;border-radius:9px}}.gallery{{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:12px;margin-top:12px}}.gallery-card{{margin:0}}.gallery-card .thumbs{{grid-template-columns:repeat(2,minmax(130px,1fr))}}.gallery-card img{{height:130px}}@media(max-width:820px){{.thumbs{{grid-template-columns:repeat(2,1fr)}}}}</style>
<main><h1>Infinigen OpticalNav dataset thumbnails</h1><p class="mut">Generated {datetime.now(UTC).isoformat()} · optical overlay off/on pairs · RGB and polarization previews. This is a dataset-quality summary, not an evaluation of polarization performance.</p>{''.join(sections)}</main></html>''')


def build_report(
    project: Path, scenes: list[str], output: Path, assets: Path, selection_manifest: Path, limit: int,
    score_budget: int = 48, nodes_per_region: int | None = 1, headings_per_node: int | None = 4,
    excluded: set[tuple[str, str, str]] | None = None, excluded_viewpoints: set[tuple[str, str]] | None = None,
    evidence_selection: Path | None = None, reuse_selection: Path | None = None, reuse_scenes: set[str] | None = None,
    export_status_overrides: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    rows = []
    evidence_by_scene: dict[str, tuple[list[Candidate], dict[str, Any]]] = {}
    if evidence_selection is not None:
        scene_id, candidates, gallery, evidence = load_evidence_selection(evidence_selection)
        evidence_by_scene[scene_id] = (candidates, gallery, evidence)
    previous_rows = {str(row.get("scene_id")): row for row in _read_json(reuse_selection, {}).get("scenes", [])} if reuse_selection else {}
    with tempfile.TemporaryDirectory(prefix="robomituba-thumbnail-report-") as temporary:
        archive_cache = Path(temporary)
        for scene_id in scenes:
            if scene_id in (reuse_scenes or set()):
                if scene_id not in previous_rows:
                    raise ValueError(f"No {scene_id} row in reuse selection {reuse_selection}")
                rows.append(previous_rows[scene_id])
                print(f"[report] reused {scene_id} from prior selection", flush=True)
                continue
            print(f"[report] scanning {scene_id}", flush=True)
            scene_dir = project / "scenes" / scene_id
            evidence = None
            if scene_id in evidence_by_scene:
                candidates, gallery_candidates, evidence = evidence_by_scene[scene_id]
                stats = {"base": len(candidates), "perturbed": len(candidates), "paired": len(candidates), "renderable_pairs": len(candidates), "secondary_rgb_pairs": 0, "score_sampled": len(candidates)}
                selected = candidates[:limit]
            else:
                candidates, stats = collect_candidates(
                    scene_id, scene_dir, score_budget=score_budget, nodes_per_region=nodes_per_region,
                    headings_per_node=headings_per_node, polar_archive=_polar_archive(project / "exports", scene_id),
                    archive_cache=archive_cache / scene_id,
                )
                candidates = exclude_candidates(candidates, excluded or set(), excluded_viewpoints or set())
                selected = select_candidates(candidates, limit)
            print(f"[report] {scene_id}: {len(selected)} selected from {stats['renderable_pairs']} ready pairs", flush=True)
            selected_rows = []
            for candidate in selected:
                print(f"[report] materializing {scene_id} {candidate.vp_id}/{candidate.heading_id}", flush=True)
                selected_rows.append({"vp_id": candidate.vp_id, "heading_id": candidate.heading_id, "region": candidate.region,
                                      "score": candidate.score, "assets": materialize_candidate(candidate, assets, output.parent),
                                      "base_manifest": str(candidate.base.manifest), "perturbed_manifest": str(candidate.perturbed.manifest),
                                      "evidence": next((item for item in (evidence or {}).get("rows", []) if item["vp_id"] == candidate.vp_id and item["heading_id"] == candidate.heading_id), None)})
            gallery_rows = []
            if evidence:
                for index, candidate in enumerate(gallery_candidates, start=1):
                    print(f"[report] gallery {scene_id} {index}/{len(gallery_candidates)} {candidate.vp_id}/{candidate.heading_id}", flush=True)
                    gallery_rows.append({"vp_id": candidate.vp_id, "heading_id": candidate.heading_id, "region": candidate.region,
                                         "score": candidate.score, "assets": materialize_gallery_candidate(candidate, assets, output.parent),
                                         "evidence": next(item for item in evidence["rows"] if item["vp_id"] == candidate.vp_id and item["heading_id"] == candidate.heading_id)})
            rows.append({"scene_id": scene_id, "stats": stats, "selected": selected_rows, "gallery": gallery_rows,
                         "export_status": (export_status_overrides or {}).get(scene_id)
                         or _export_status(project / "exports", scene_id)})
    output.parent.mkdir(parents=True, exist_ok=True)
    render_report(rows, output)
    payload = {"schema": "robomituba.infinigen_thumbnail_report.v1", "generated_at": datetime.now(UTC).isoformat(),
               "project": str(project), "output": str(output), "asset_root": str(assets),
               "excluded": [":".join(value) for value in sorted(excluded or set())],
               "excluded_viewpoints": [":".join(value) for value in sorted(excluded_viewpoints or set())],
               "evidence_selection": str(evidence_selection) if evidence_selection else None, "scenes": rows}
    selection_manifest.write_text(json.dumps(payload, indent=2) + "\n")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path("out/opticalnav/opticalnav-v0.2"))
    parser.add_argument("--scene", action="append", dest="scenes", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--selection-manifest", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=6)
    parser.add_argument("--score-budget", type=int, default=48, help="Maximum RGB base/on pairs opened for change ranking per scene")
    parser.add_argument("--nodes-per-region", type=int, default=1, help="Evenly sampled viewpoint nodes per room; 0 scans every node")
    parser.add_argument("--headings-per-node", type=int, default=4, help="Evenly sampled headings per chosen node; 0 scans every heading")
    parser.add_argument("--exclude", action="append", default=[], metavar="SCENE:VP:HEADING", help="Exclude one report pair; repeatable")
    parser.add_argument("--exclude-vp", action="append", default=[], metavar="SCENE:VP", help="Exclude all headings for one viewpoint; repeatable")
    parser.add_argument("--evidence-selection", type=Path, help="Reviewed candidate-pool JSON; uses its recommended_final_six exactly")
    parser.add_argument("--reuse-selection", type=Path, help="Prior report selection JSON used to preserve a scene without rereading sources")
    parser.add_argument("--reuse-scene", action="append", default=[], metavar="SCENE", help="Reuse this scene row from --reuse-selection; repeatable")
    parser.add_argument("--export-status-overrides", type=Path,
                        help="JSON object keyed by scene ID; each value supplies report export status provenance")
    return parser.parse_args()


def parse_exclusions(values: list[str]) -> set[tuple[str, str, str]]:
    excluded = set()
    for value in values:
        parts = value.split(":")
        if len(parts) != 3 or not all(parts):
            raise ValueError(f"Invalid --exclude {value!r}; expected SCENE:VP:HEADING")
        excluded.add(tuple(parts))
    return excluded


def parse_excluded_viewpoints(values: list[str]) -> set[tuple[str, str]]:
    excluded = set()
    for value in values:
        parts = value.split(":")
        if len(parts) != 2 or not all(parts):
            raise ValueError(f"Invalid --exclude-vp {value!r}; expected SCENE:VP")
        excluded.add(tuple(parts))
    return excluded


def main() -> None:
    args = parse_args()
    try:
        excluded = parse_exclusions(args.exclude)
        excluded_viewpoints = parse_excluded_viewpoints(args.exclude_vp)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    build_report(
        args.project, args.scenes, args.output, args.assets, args.selection_manifest, args.limit, args.score_budget,
        None if args.nodes_per_region == 0 else args.nodes_per_region,
        None if args.headings_per_node == 0 else args.headings_per_node,
        excluded,
        excluded_viewpoints,
        args.evidence_selection,
        args.reuse_selection,
        set(args.reuse_scene),
        _read_json(args.export_status_overrides, {}) if args.export_status_overrides else None,
    )
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
