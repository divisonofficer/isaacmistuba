#!/usr/bin/env python3.10
"""Install the `cglab_conference_room` OpticalNav scene from its floor-plan spec.

The CG-Lab conference room is a long, shallow glass-walled meeting room. This
script encodes the measured spec (pillars / segments / waypoints, in cm) and
builds an OpticalNav AuthoringMap (in meters), then runs the shared install
pipeline (compile → sync → materialize render scene) so the scene shows up in
the editor under project ``opticalnav-v0.2``.

Geometry (closed perimeter, clockwise from origin P1 at bottom-left):
  left side  : glass walls (S1,S2) + glass door (S3)        x = 0
  top wall   : glass walls (S4-S9)                          y = 2.665
  right side : glass windows (S10-S12)                      x = 6.10
  bottom     : concrete walls (S13-S17, stepped notch)

Furniture / pillars / lights are approximate (spec marks them 실측 필요) and can
be nudged in the editor.

    python apps/install_cglab_conference_room.py [--force]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (
    REPO_ROOT / "modules" / "navigation_dataset" / "src",
    REPO_ROOT / "modules" / "robomituba_bridge" / "src",
    REPO_ROOT / "modules" / "mitsuba_converter" / "src",
):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from navigation_dataset.authoring_map import (  # noqa: E402
    AuthoringCameraRig,
    AuthoringCameraRigSensor,
    AuthoringEnvironment,
    AuthoringGeometry,
    AuthoringMap,
    AuthoringMaterial,
    AuthoringNavigationFlags,
    AuthoringObject,
    AuthoringRegion,
    authoring_map_to_payload,
    validate_authoring_map,
)
from navigation_dataset.office_sample import install_shared_office_sample  # noqa: E402

PROJECT_ID = "opticalnav-v0.2"
SCENE_ID = "cglab_conference_room"
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "opticalnav" / "cglab_conference_room_authoring_map.json"

WALL_H = 2.4
GLASS_H = 2.4
DOOR_H = 2.3


ROOM_X_MAX_M = 6.10  # east-west extent (P10 at x=610cm)


def cm(x: float) -> float:
    return round(x / 100.0, 4)


def mx(x_m: float) -> float:
    """Mirror an x-coordinate east<->west (spec orientation was reversed in the editor)."""
    return round(ROOM_X_MAX_M - x_m, 4)


# --- Pillars / waypoints (cm) -------------------------------------------------
PTS_CM: dict[str, tuple[float, float]] = {
    "P1": (0, 0), "P2": (0, 93), "P3": (0, 186.5), "P4": (0, 266.5),
    "P5": (106, 266.5), "P6": (212, 266.5), "P7": (318, 266.5), "P8": (424, 266.5),
    "P9": (530, 266.5), "P10": (610, 266.5), "P11": (610, 204.33), "P12": (610, 142.17),
    "WP1": (610, 80), "WP2": (558, 80), "WP3": (558, 46), "WP4": (98.6, 46), "WP5": (98.6, 59),
}
PT = {k: [mx(cm(v[0])), cm(v[1])] for k, v in PTS_CM.items()}  # x mirrored east<->west

# Steel pillar footprints (width_cm, depth_cm) from spec.
PILLAR_WD = {
    "P1": (12, 4.5), "P2": (12, 4.5), "P3": (12, 4.5), "P4": (12, 12),
    "P5": (4.5, 12), "P6": (4.5, 12), "P7": (4.5, 12), "P8": (4.5, 12), "P9": (4.5, 12),
    "P10": (4.5, 12), "P11": (12, 4.5), "P12": (12, 4.5),
}

# Perimeter segments: (id, a, b, kind, label)
SEGMENTS = [
    ("S1", "P1", "P2", "glass_wall", "유리벽1"),
    ("S2", "P2", "P3", "glass_wall", "유리벽2"),
    ("S3", "P3", "P4", "glass_door", "유리 여닫이문"),
    ("S4", "P4", "P5", "glass_wall", "유리벽5"),
    ("S5", "P5", "P6", "glass_wall", "유리벽6"),
    ("S6", "P6", "P7", "glass_wall", "유리벽7"),
    ("S7", "P7", "P8", "glass_wall", "유리벽8"),
    ("S8", "P8", "P9", "glass_wall", "유리벽9"),
    ("S9", "P9", "P10", "glass_wall", "유리벽10"),
    ("S10", "P10", "P11", "glass_window", "유리창문1"),
    ("S11", "P11", "P12", "glass_window", "유리창문2"),
    ("S12", "P12", "WP1", "glass_window", "유리창문3"),
    ("S13", "WP1", "WP2", "concrete_wall", "콘크리트벽(가로)"),
    ("S14", "WP2", "WP3", "concrete_wall", "콘크리트벽(세로 돌출)"),
    ("S15", "WP3", "WP4", "concrete_wall", "콘크리트벽(긴 가로)"),
    ("S16", "WP4", "WP5", "concrete_wall", "콘크리트벽(13cm)"),
    ("S17", "WP5", "P1", "concrete_wall", "콘크리트벽(103cm, 폐곡선 완성)"),
]

# kind → (object_type, material, hazard_type, thickness_m, height_m, instruction)
SEG_KIND = {
    "glass_wall":    ("glass_wall", "clear_glass", "transparent_obstacle", 0.05, GLASS_H, False),
    "glass_door":    ("glass_door", "clear_glass", "glass_door", 0.04, DOOR_H, True),
    "glass_window":  ("glass_wall", "glass_window", "transparent_obstacle", 0.05, GLASS_H, False),
    "concrete_wall": ("wall", "painted_wall", None, 0.12, WALL_H, False),
}


def _line(seg_id, a, b, kind, label):
    otype, material, hazard, thick, height, instr = SEG_KIND[kind]
    return AuthoringObject(
        id=seg_id,
        type=otype,
        label=label,
        placement="line",
        geometry=AuthoringGeometry(type="line", start=PT[a], end=PT[b], height_m=height, thickness_m=thick),
        material=material,
        navigation=AuthoringNavigationFlags(
            blocks_navigation=True,
            hazard_type=hazard,
            include_in_hazard_mask=bool(hazard),
            instruction_candidate=instr,
        ),
    )


def _pillar(pid):
    w, d = PILLAR_WD[pid]
    return AuthoringObject(
        id=f"pillar_{pid.lower()}",
        type="landmark",
        label=f"철기둥 {pid}",
        placement="point",
        geometry=AuthoringGeometry(type="point", center=PT[pid], size_m=[cm(w), WALL_H, cm(d)]),
        material="hpbrdf_2025:aluminum",
        navigation=AuthoringNavigationFlags(blocks_navigation=True),
    )


def _point(oid, otype, label, center, size, material, *, blocks=True, instruction=False,
           base_height_m=0.0, is_emitter=False, emitter_radiance=None, emitter_intensity=1.0):
    return AuthoringObject(
        id=oid,
        type=otype,
        label=label,
        placement="point",
        geometry=AuthoringGeometry(type="point", center=center, size_m=size, base_height_m=base_height_m),
        material=material,
        navigation=AuthoringNavigationFlags(blocks_navigation=blocks, instruction_candidate=instruction),
        is_emitter=is_emitter,
        emitter_radiance=emitter_radiance,
        emitter_intensity=emitter_intensity,
    )


def build_map() -> AuthoringMap:
    objects: list[AuthoringObject] = []
    objects += [_line(*s) for s in SEGMENTS]
    objects += [_pillar(p) for p in PILLAR_WD]

    # Furniture (approximate; spec marks 실측 필요). x mirrored east<->west.
    objects.append(_point("F1_table", "table", "타원 회의 테이블", [mx(0.7), 1.33], [1.0, 0.75, 2.4], "wood", instruction=True))
    chair_spots = [(1.5, 0.8), (1.5, 1.3), (1.5, 1.85), (1.5, 2.35), (2.25, 1.05), (2.25, 1.65)]
    for i, (x, y) in enumerate(chair_spots, 1):
        mat = "fabric"  # mint/white shells share a generic preset; recolour in editor
        objects.append(_point(f"F_chair_{i:02d}", "chair", f"의자 {i}", [mx(x), y], [0.5, 0.85, 0.5], mat))
    objects.append(_point("F2_whiteboard", "landmark", "대형 유리 화이트보드", [mx(0.1), 1.3], [0.05, 1.2, 2.4], "clear_glass", blocks=False))
    objects.append(_point("F3_whiteboard_small", "landmark", "소형 화이트보드", [mx(0.1), 2.35], [0.05, 0.6, 0.8], "clear_glass", blocks=False))
    objects.append(_point("F4_dehumidifier", "landmark", "제습기", [mx(0.45), 2.4], [0.4, 0.9, 0.4], "painted_wall"))
    objects.append(_point("F5_air_purifier", "landmark", "공기청정기", [mx(5.7), 1.0], [0.4, 1.0, 0.4], "painted_wall"))

    # Ceiling light strips (interior lighting beyond the constant ambient).
    objects.append(_point("ceil_light_1", "landmark", "천장 조명1", [mx(2.0), 1.3], [1.2, 0.06, 0.2], "painted_wall",
                          blocks=False, base_height_m=2.35, is_emitter=True, emitter_radiance=[15.0, 14.0, 12.0], emitter_intensity=1.2))
    objects.append(_point("ceil_light_2", "landmark", "천장 조명2", [mx(4.5), 1.3], [1.2, 0.06, 0.2], "painted_wall",
                          blocks=False, base_height_m=2.35, is_emitter=True, emitter_radiance=[15.0, 14.0, 12.0], emitter_intensity=1.2))

    regions = [
        AuthoringRegion(
            id="floor_main", type="traversable", label="회의실 바닥", placement="rectangle",
            geometry=AuthoringGeometry(type="rectangle", bounds=[0.2, 0.9, 5.9, 2.5]),
            floor_material_id="wood",
        ),
        AuthoringRegion(
            id="goal_window", type="goal", label="창측 목표", placement="rectangle",
            geometry=AuthoringGeometry(type="rectangle", bounds=[mx(5.85), 1.2, mx(5.4), 1.9]),
        ),
    ]

    def mat(mid, category, strategy, caps=("rgb",)):
        return AuthoringMaterial(
            material_id=mid, category=category,
            render_binding={"kind": "preset", "bsdf_strategy": strategy, "capabilities": {c: True for c in caps}},
        )

    materials = [
        mat("clear_glass", "transparent", "dielectric", ("rgb", "nir", "polarization")),
        mat("glass_window", "transparent", "dielectric", ("rgb", "nir", "polarization")),
        mat("painted_wall", "opaque", "roughplastic"),
        mat("wood", "opaque", "roughplastic"),
        mat("fabric", "opaque", "roughplastic"),
        # Steel pillars use the measured HPBRDF-2025 aluminum (channel-split RGB).
        AuthoringMaterial(
            material_id="hpbrdf_2025:aluminum", category="measured",
            render_binding={
                "kind": "measured", "dataset_id": "hpbrdf_2025", "material_id": "aluminum",
                "bsdf_strategy": "measured_polarized", "channels_dir": "data/hpbrdf_2025/channels/aluminum",
                "capabilities": {"rgb": True, "nir": True, "polarization": True},
            },
        ),
    ]

    camera_rig = AuthoringCameraRig(
        rig_id="cglab_conf_default",
        base_frame="base_link",
        sensors=[
            AuthoringCameraRigSensor(
                sensor_id="rgb_front", label="RGB Front", modality="rgb",
                mount={"xyz_m": [0.18, 1.0, 0.0], "rpy_deg": [0.0, 0.0, 0.0]},
                fov_deg=70.0, resolution=[1280, 720], clip_range=[0.05, 80.0],
            ),
            AuthoringCameraRigSensor(
                sensor_id="pol_front", label="Polarization Front", modality="polarization",
                mount={"xyz_m": [0.16, 1.02, -0.04], "rpy_deg": [0.0, 0.0, 0.0]},
                fov_deg=70.0, resolution=[1280, 720], clip_range=[0.05, 80.0],
            ),
        ],
    )

    return AuthoringMap(
        scene_id=SCENE_ID,
        unit="meter",
        objects=objects,
        regions=regions,
        materials=materials,
        environment=AuthoringEnvironment(mode="constant", radiance=[0.9, 0.92, 0.95], intensity=0.9),
        camera_rig=camera_rig,
        settings={
            "map_w": 7,
            "map_h": 4,
            "grid_size_m": 0.25,
            "default_wall_height_m": WALL_H,
            "default_wall_thickness_m": 0.08,
            "room_shell_enabled": True,
            "auto_floor_enabled": True,
            "default_floor_material_id": "wood",
            "default_ceiling_material_id": "painted_wall",
        },
        metadata={"created_by": "install_cglab_conference_room.py", "scene_kind": "conference_room",
                  "source": "cglab floor-plan spec (cm)"},
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true", help="Overwrite an existing scene.")
    ap.add_argument("--no-materialize", action="store_true", help="Skip render_scene.xml materialization.")
    args = ap.parse_args()

    amap = build_map()
    validate_authoring_map(amap, require_compile_ready=True)
    print(f"[ok] authoring map valid: {len(amap.objects)} objects, {len(amap.regions)} regions")

    FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    import json
    FIXTURE_PATH.write_text(json.dumps(authoring_map_to_payload(amap), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ok] wrote fixture: {FIXTURE_PATH.relative_to(REPO_ROOT)}")

    result = install_shared_office_sample(
        REPO_ROOT, project_id=PROJECT_ID, scene_id=SCENE_ID,
        fixture_path=FIXTURE_PATH, force=args.force, materialize_render_scene=not args.no_materialize,
    )
    print(f"[ok] installed scene '{SCENE_ID}' → {Path(result.scene_dir).relative_to(REPO_ROOT)}")
    print(f"     render_scene: {result.render_scene_status}")
    print(f"     written: {[Path(p).name for p in result.written_files]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
