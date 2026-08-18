#!/usr/bin/env python3
"""Interactive wizard: generate an Infinigen indoor scene, then import it.

Run it with no args and answer the prompts:

    python scripts/infinigen_wizard.py

It asks for archetype / room type (single-room) / furnishing density / stage / seed, then:
  1. generates a VALID procedural floor plan + scene.blend via infinigen_gen.py
  2. (optionally) runs run_infinigen_import.sh to land an OpticalNav scene.

WHY a wizard: the 8-digit AABBCCDD seed encodes archetype+density, which fights
the habit of typing today's date (e.g. 20260629) as a memorable seed. The wizard
lets you pick archetype/density EXPLICITLY and forces them via --floor-plan +
num_floating override, so the seed is free to be a date-based naming handle.
"""

from __future__ import annotations

import datetime
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

ARCHETYPES = {
    "apartment": "gen_apartment",   # 거실 중심 radial + 복도 + open LDK
    "office": "gen_office_modern_hybrid_v1",  # 180–300㎡ 현대 hybrid office suite
    "single_room": "single_room",    # 방 하나 + entrance + exterior window
}
ROOM_TYPES = {
    "living-room": "거실",
    "bedroom": "침실",
    "kitchen": "주방",
    "bathroom": "욕실",
    "dining-room": "식당",
    "closet": "드레스룸/수납실",
    "hallway": "복도",
    "garage": "차고",
    "balcony": "발코니",
    "utility": "다용도실",
    "staircase-room": "계단실",
    "warehouse": "창고",
    "office": "개인 사무실",
    "meeting-room": "회의실",
    "open-office": "오픈 오피스",
    "break-room": "휴게실",
    "restroom": "공용 화장실",
    "factory-office": "공장 사무실",
}
# furnishing density -> compose_indoors.num_floating (mirrors infinigen_gen.parse_seed)
DENSITIES = {
    "model_house": 8,        # 거의 빈 모델하우스
    "normal_lived_in": 18,   # 보통 생활감
    "family_home": 28,       # 물건 많은 가정집
    "storage_heavy": 40,     # 창고급
}
OFFICE_STYLES = ["modern_basic_v1", "modern_glass_v1"]
STAGES = ["full", "layout"]  # full = 가구 solve, layout = 벽만(빠른 확인)


# --- prompt helpers --------------------------------------------------------

def _ask(prompt: str, default: str) -> str:
    try:
        ans = input(f"{prompt} [{default}]: ").strip()
    except EOFError:
        ans = ""
    return ans or default


def _pick(prompt: str, options: list[str], default: str) -> str:
    print(f"\n{prompt}")
    for i, opt in enumerate(options, 1):
        mark = "  (기본)" if opt == default else ""
        print(f"  {i}) {opt}{mark}")
    while True:
        raw = _ask("번호 또는 이름", default)
        if raw in options:
            return raw
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1]
        print("  ! 유효한 번호/이름을 입력하세요.")


def _yesno(prompt: str, default: bool) -> bool:
    d = "Y/n" if default else "y/N"
    raw = _ask(f"{prompt} ({d})", "").lower()
    if not raw:
        return default
    return raw in ("y", "yes", "1", "true")


def _ask_seed() -> str:
    today = datetime.date.today().strftime("%Y%m%d")
    print("\nseed (씬 디렉터리/파일명에 쓰임; archetype·density는 위에서 이미 고정됨)")
    print(f"  엔터=오늘 날짜 {today} · 'r'=랜덤 · 또는 8자리 직접 입력")
    while True:
        raw = _ask("seed", today)
        if raw.lower() == "r":
            import random
            seed = f"{random.randint(0, 99999999):08d}"
            print(f"  → 랜덤 seed {seed}")
            return seed
        if raw.isdigit() and len(raw) == 8:
            return raw
        print("  ! 8자리 숫자 / 빈칸(오늘) / r(랜덤) 중 하나로 입력하세요.")


# --- run -------------------------------------------------------------------

def _run(cmd: list[str]) -> int:
    print("\n$ " + " ".join(cmd))
    return subprocess.run(cmd, cwd=str(REPO)).returncode


def _parse_args(argv):
    import argparse
    ap = argparse.ArgumentParser(
        description="Infinigen 실내 씬 마법사 (생성 → import). "
                    "플래그를 모두 주고 --yes 면 비대화식(서버/배치)으로 동작.")
    ap.add_argument("--archetype", choices=list(ARCHETYPES))
    ap.add_argument("--density", choices=list(DENSITIES))
    ap.add_argument("--logical-seed", default=None)
    ap.add_argument("--variation-id", type=int, default=0)
    ap.add_argument("--anchor-richness", choices=("minimal", "balanced", "rich", "storage"), default="balanced")
    ap.add_argument("--surface-clutter", choices=("low", "balanced", "rich", "storage"), default="balanced")
    ap.add_argument("--office-style", choices=OFFICE_STYLES, default="modern_basic_v1")
    ap.add_argument("--graph-max-nodes", type=int, default=70)
    ap.add_argument("--graph-heading-count", type=int, default=24)
    ap.add_argument("--graph-min-node-spacing", type=float, default=0.25)
    ap.add_argument("--graph-robot-radius", type=float, default=0.30)
    ap.add_argument("--room-type", choices=list(ROOM_TYPES), default=None,
                    help="single_room 모드의 방 타입")
    ap.add_argument("--stage", choices=STAGES)
    ap.add_argument("--seed", help="8자리 seed, 'today', 또는 'random'")
    ap.add_argument("--import", dest="do_import", action="store_true", default=None)
    ap.add_argument("--no-import", dest="do_import", action="store_false")
    ap.add_argument("--bake-pbr", action="store_true", default=None)
    ap.add_argument("--scene-id", default=None)
    ap.add_argument("-y", "--yes", action="store_true",
                    help="프롬프트 없이 진행(미지정 값은 기본값 사용).")
    return ap.parse_args(argv)


def _resolve_seed(spec: str | None) -> str:
    today = datetime.date.today().strftime("%Y%m%d")
    if spec in (None, "", "today"):
        return today
    if spec == "random":
        import random
        return f"{random.randint(0, 99999999):08d}"
    if spec.isdigit() and len(spec) == 8:
        return spec
    raise SystemExit(f"[wizard] 잘못된 seed: {spec!r} (8자리 / today / random)")


def main(argv=None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    auto = args.yes
    print("=" * 64)
    print("  Infinigen 실내 씬 마법사  (생성 → import)")
    print("=" * 64)

    # Resolve (and remember) the infinigen env python; prompt + persist if missing.
    import infinigen_env
    try:
        py = infinigen_env.resolve_python(prompt=not auto, persist=True)
        print(f"infinigen env: {py}")
    except (SystemExit, FileNotFoundError) as e:
        print(e)
        return 1

    archetype = args.archetype or ("apartment" if auto else
                                   _pick("1. archetype (방 구조)", list(ARCHETYPES), "apartment"))
    office_style = args.office_style
    if archetype == "office" and not auto and "--office-style" not in (argv if argv is not None else sys.argv[1:]):
        office_style = _pick("2. Office style", OFFICE_STYLES, "modern_basic_v1")
    room_type = args.room_type
    if archetype == "single_room" and room_type is None:
        room_type = "living-room" if auto else _pick("2. 방 타입", list(ROOM_TYPES), "living-room")
    density_prompt = "3. 가구 밀도" if archetype in {"single_room", "office"} else "2. 가구 밀도"
    density = args.density or ("normal_lived_in" if auto else
                               _pick(density_prompt, list(DENSITIES), "normal_lived_in"))
    stage_prompt = "4. stage" if archetype == "single_room" else "3. stage"
    stage = args.stage or ("full" if auto else _pick(stage_prompt, STAGES, "full"))
    seed = _resolve_seed(args.seed) if (args.seed or auto) else _ask_seed()

    if args.do_import is not None:
        do_import = args.do_import
    else:
        import_prompt = "5" if archetype == "single_room" else "4"
        do_import = True if auto else _yesno(f"\n{import_prompt}. 생성 후 OpticalNav import 까지 진행?", True)
    bake_pbr = bool(args.bake_pbr)
    if do_import and args.bake_pbr is None and not auto:
        bake_pbr = _yesno("   └ PBR(roughness/normal/metallic) 베이크? (~4배 느림)", False)

    floor_plan = ARCHETYPES[archetype]
    num_floating = DENSITIES[density]
    room_suffix = f"_{room_type.replace('-', '_')}" if archetype == "single_room" else ""
    out_dir = REPO / "data" / "infinigen_generated" / "outputs" / f"kr_{seed}_{archetype}{room_suffix}" / stage
    scene_id = args.scene_id or f"infinigen_{archetype}{room_suffix}_{seed}"

    print("\n" + "-" * 64)
    print("요약")
    print(f"  archetype     : {archetype}  (--floor-plan {floor_plan})")
    if archetype == "office":
        print(f"  office style  : {office_style}")
        print("  graph profile : "
              f"nodes={args.graph_max_nodes}, headings={args.graph_heading_count}, "
              f"spacing={args.graph_min_node_spacing:g}m, robot={args.graph_robot_radius:g}m")
        if office_style == "modern_glass_v1":
            print("  glass contract: 3 deterministic structural partitions (no graph overlay)")
    if archetype == "single_room":
        print(f"  room type     : {room_type} ({ROOM_TYPES[room_type]})")
    print(f"  density       : {density}  (num_floating={num_floating})")
    print(f"  stage         : {stage}")
    print(f"  seed          : {seed}")
    print(f"  출력 디렉터리 : {out_dir.relative_to(REPO)}")
    if do_import:
        print(f"  import scene  : {scene_id}  (bake_pbr={bake_pbr})")
    print("-" * 64)
    if not auto and not _yesno("진행할까요?", True):
        print("취소됨.")
        return 1

    # ── 1) generate ──────────────────────────────────────────────────────────
    gen_cmd = [
        sys.executable, "scripts/infinigen_gen.py",
        "--seed", seed,
        "--logical-seed", str(args.logical_seed or seed),
        "--variation-id", str(args.variation_id),
        "--density", density,
        "--anchor-richness", args.anchor_richness,
        "--surface-clutter", args.surface_clutter,
        *( ["--office-style", office_style] if archetype == "office" else [] ),
        "--graph-max-nodes", str(args.graph_max_nodes),
        "--graph-heading-count", str(args.graph_heading_count),
        "--graph-min-node-spacing", str(args.graph_min_node_spacing),
        "--graph-robot-radius", str(args.graph_robot_radius),
        "--floor-plan", floor_plan,
        *( ["--room-type", room_type] if archetype == "single_room" else [] ),
        "--stage", stage,
        "--out", str(out_dir),
        "--run",
    ]
    rc = _run(gen_cmd)
    if rc != 0:
        print(f"\n[!] 생성 실패 (exit {rc}). import 중단.")
        return rc
    blend = out_dir / "scene.blend"
    if not (blend.exists() or (out_dir / "scene.blend1").exists()):
        print(f"\n[!] scene.blend 가 {out_dir} 에 없습니다. import 중단.")
        return 2
    print(f"\n[ok] 생성 완료 → {out_dir.relative_to(REPO)}")

    # ── 2) import ────────────────────────────────────────────────────────────
    if not do_import:
        print("\nimport 생략. 나중에:")
        print(f"  bash apps/run_infinigen_import.sh {out_dir.relative_to(REPO)} --scene-id {scene_id}")
        return 0

    imp_cmd = ["bash", "apps/run_infinigen_import.sh", str(out_dir),
               "--scene-id", scene_id]
    if bake_pbr:
        imp_cmd.append("--bake-pbr")
    rc = _run(imp_cmd)
    if rc != 0:
        print(f"\n[!] import 실패 (exit {rc}).")
        return rc
    print(f"\n[ok] 완료 — OpticalNav scene '{scene_id}' 준비됨.")
    if archetype == "office":
        graph_cmd = [
            sys.executable, "apps/opticalnav.py", "graph", "build",
            "--dataset", "out/opticalnav/opticalnav-v0.2", "--scene-id", scene_id,
            "--seed", seed, "--max-nodes", str(args.graph_max_nodes),
            "--heading-count", str(args.graph_heading_count),
            "--min-node-spacing", str(args.graph_min_node_spacing),
            "--robot-radius", str(args.graph_robot_radius),
        ]
        rc = _run(graph_cmd)
        if rc != 0:
            print(f"\n[!] OpticalNav graph build 실패 (exit {rc}).")
            return rc
        if office_style == "modern_glass_v1":
            source_manifest = out_dir / "office_layout_manifest.json"
            scene_dir = REPO / "out" / "opticalnav" / "opticalnav-v0.2" / "scenes" / scene_id
            audit_cmd = [sys.executable, "scripts/audit_modern_office_graph.py",
                         "--source-manifest", str(source_manifest), "--scene-dir", str(scene_dir),
                         "--out", str(out_dir / "modern_office_graph_audit.json")]
            rc = _run(audit_cmd)
            if rc != 0:
                print(f"\n[!] Modern Glass structural graph audit 실패 (exit {rc}).")
                return rc
            print("[ok] Modern Glass structural graph audit 통과")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n중단됨.")
        raise SystemExit(130)
