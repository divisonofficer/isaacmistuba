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
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

from floorplan_gen import wide_glass_office_metadata
from office_run_state import (
    digest as state_digest,
    new_state,
    pid_is_alive,
    process_matches_candidate,
    read_json as read_run_state,
    state_path as office_state_path,
    stop_recorded_candidate,
    update_state as update_office_state,
    write_json_atomic as write_run_state,
)

REPO = Path(__file__).resolve().parent.parent

ARCHETYPES = {
    # Native graph/contour solving gives varied full-house outlines and room
    # connectivity. ``gen_apartment`` remains an explicit legacy key for
    # reproducibility of previously generated scenes.
    "apartment": "apartment_natural_v1",
    "office": "gen_office_modern_glass_v2",  # 400–550㎡ glass-partitioned office
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
OFFICE_PROFILES = {
    "modern_glass_office_v2": {
        "floor_plan": "gen_office_modern_glass_v2", "style": "modern_glass_v2",
        "description": "400–550㎡ · 3–4 work bays · 10 structural glass partitions",
    },
    # Explicit legacy selection only: existing published v1 seed contract is
    # retained, but new office runs no longer silently use it.
    "modern_hybrid_v1": {
        "floor_plan": "gen_office_modern_hybrid_v1", "style": "modern_glass_v1",
        "description": "legacy 180–300㎡ · 3 structural glass partitions",
    },
}
OFFICE_STYLES = ["modern_glass_v2", "modern_glass_v1", "modern_basic_v1"]
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
    print("\n$ " + " ".join(str(part) for part in cmd))
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
    ap.add_argument("--placement-profile", choices=("legacy_clutter_v1", "upstream_residential_v1", "collision_aware_clutter_v1"),
                    default="legacy_clutter_v1")
    ap.add_argument(
        "--ir-material-profile",
        choices=("standard", "principled_rich_v1"),
        default="standard",
        help="Opt-in IR material generator profile. The default leaves Infinigen material pools unchanged.",
    )
    ap.add_argument("--office-profile", choices=list(OFFICE_PROFILES), default="modern_glass_office_v2")
    ap.add_argument("--office-style", choices=OFFICE_STYLES, default=None)
    ap.add_argument("--office-max-attempts", type=int, default=6)
    ap.add_argument("--repair-existing", dest="repair_existing", action="store_true", default=True,
                    help="Repair an existing candidate scene.blend before spending time on a new generation (default).")
    ap.add_argument("--no-repair-existing", dest="repair_existing", action="store_false",
                    help="Do not attempt Blender-side repair of an existing candidate blend.")
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
    ap.add_argument("--status", action="store_true", help="Office v2 run-state/heartbeat를 표시하고 종료합니다.")
    ap.add_argument("--stop", action="store_true", help="기록된 Office v2 candidate process group에 SIGINT를 보냅니다.")
    ap.add_argument("--resume", action="store_true", help="중단된 Office v2 candidate를 동일 deterministic seed로 다시 시작합니다.")
    ap.add_argument("--retry-terminal", action="store_true",
                    help="수정된 solver/config를 명시적으로 적용해 terminal Office v2 run을 같은 seed로 재시작합니다.")
    ap.add_argument("--adopt-interrupted", action="store_true",
                    help="기존 pre-v2 interrupted attempt directories를 상태 파일에 보존만 합니다 (렌더 재시작 안 함).")
    ap.add_argument("--force", action="store_true", help="--stop 시 SIGTERM을 사용합니다 (기본은 graceful SIGINT).")
    ap.add_argument("-y", "--yes", action="store_true",
                    help="프롬프트 없이 진행(미지정 값은 기본값 사용).")
    return ap.parse_args(argv)


def _attempt_seed(logical_seed: str, attempt: int) -> str:
    digest = hashlib.sha256(f"{logical_seed}:modern_glass_office_v2:{attempt}".encode("utf-8")).digest()
    return f"{int.from_bytes(digest[:8], 'big') % 100_000_000:08d}"


def _write_json_atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _utc_stamp() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _archive_path(path: Path, *, suffix: str) -> Path:
    archived = path.with_name(f"{path.name}.{suffix}_{_utc_stamp()}")
    sequence = 1
    while archived.exists():
        archived = path.with_name(f"{path.name}.{suffix}_{_utc_stamp()}_{sequence:02d}")
        sequence += 1
    return archived


def _candidate_attempt_number(path: Path) -> int | None:
    """Return attempt number from live or archived candidate directory names."""
    match = re.match(r"^attempt_(\d+)(?:\.|$)", path.name)
    return int(match.group(1)) if match else None


def _office_contract(*, args, seed: str, density: str, floor_plan: str, office_style: str,
                     out_dir: Path) -> dict:
    return {
        "schema": "robomituba.office_candidate_contract.v2",
        "logical_seed": str(args.logical_seed or seed),
        "floor_plan": floor_plan,
        "office_profile": args.office_profile,
        "office_style": office_style,
        "density": density,
        "anchor_richness": args.anchor_richness,
        "surface_clutter": args.surface_clutter,
        "max_attempts": int(args.office_max_attempts),
        "stage": args.stage,
        "output": str(out_dir),
        "workstation_layout_contract": "robomituba.office_workstation_layout.v1",
        "solver_policy": "room_local_chair_quota_postsolve_pairing_v1",
    }


def _prepare_office_state(*, root: Path, contract: dict, logical_seed: str,
                          max_attempts: int, resume: bool,
                          retry_terminal: bool = False) -> tuple[Path, dict]:
    path = office_state_path(root)
    existing = read_run_state(path)
    wanted_digest = state_digest(contract)
    if existing is not None:
        if existing.get("contract_digest") != wanted_digest:
            raise ValueError("existing Office v2 run-state has a different contract; choose a new output or inspect/archive it")
        if existing.get("status") == "published":
            return path, existing
        if not resume:
            raise RuntimeError("Office v2 run already has incomplete state; use --status, --stop, or --resume")
        terminal_statuses = {
            "generation_failed", "solver_stalled", "unsatisfied_solver",
            "preflight_error", "contract_error", "audit_failed",
        }
        if existing.get("status") in terminal_statuses and not retry_terminal:
            raise RuntimeError(
                f"Office v2 run is terminal ({existing.get('status')}); do not resume the same contract/output. "
                "Create a new output or change the generation contract after fixing the cause. "
                "Use --retry-terminal only after an explicit implementation/configuration fix."
            )
        if existing.get("status") in terminal_statuses and retry_terminal:
            # Terminal solver failures are deterministic by default.  This
            # explicit escape hatch is for an operator who fixed the solver
            # or configuration in-place and wants to reuse the same seed.
            existing.setdefault("history", []).append({
                "at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "note": f"explicit retry-terminal from {existing.get('status')}",
                "stage": existing.get("stage", "generation"), "status": "interrupted",
            })
            existing["status"] = "interrupted"
            existing["termination_reason"] = None
            existing["process"] = None
        # Never let two wizard controllers generate the same candidate tree.
        # A stale state file is recoverable, but a live matching process must
        # be stopped explicitly before a resume is allowed.
        if existing.get("status") == "running":
            process = existing.get("process") or {}
            try:
                pid = int(process["pid"])
                candidate = Path(str(process["candidate_dir"])).resolve()
            except (KeyError, TypeError, ValueError):
                pid = 0
                candidate = None
            if pid > 0 and candidate is not None and pid_is_alive(pid) and process_matches_candidate(pid, candidate):
                raise RuntimeError(
                    f"Office v2 candidate is still running (pid={pid}); use --stop before --resume"
                )
            hazards = existing.setdefault("hazards", [])
            marker = "stale_running_state"
            if marker not in hazards:
                hazards.append(marker)
            existing.setdefault("history", []).append({
                "at": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
                "note": "resume adopted stale running state; recorded process was not live/matching",
                "stage": existing.get("stage", "generation"), "status": "interrupted",
            })
        existing.setdefault("execution", {}).setdefault("resume_requests", 0)
        existing["execution"]["resume_requests"] += 1
        return path, existing

    # The jobs stopped before this contract existed. Preserve that fact rather
    # than treating their old attempt JSON as a live run.
    stale_attempts = root / "office_generation_attempts.json"
    if stale_attempts.exists():
        archived = _archive_path(stale_attempts, suffix="stale")
        os.replace(stale_attempts, archived)
    state = new_state(
        run_id=f"office-{logical_seed}-{uuid.uuid4().hex[:12]}", contract=contract,
        logical_seed=logical_seed, max_attempts=max_attempts, root=root,
    )
    attempts_root = root / "attempts"
    if resume and attempts_root.exists():
        state["status"] = "interrupted"
        state["stage"] = "generation"
        state["historical_log_unavailable"] = True
        state["history"].append({"at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "note": "adopted interrupted pre-v2 candidate directories"})
    write_run_state(path, state)
    return path, state


def _workstation_layout_ok(path: Path, manifest: Path) -> tuple[bool, str]:
    value = read_run_state(path)
    if value is None:
        return False, "workstation_layout.json is missing or invalid"
    if value.get("status") != "passed":
        return False, f"workstation layout status={value.get('status')!r}"
    if not value.get("layout_digest") or not value.get("mappings"):
        return False, "workstation layout has no digest or mappings"
    try:
        source = json.loads(manifest.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return False, "office layout manifest is missing or invalid"
    expected = hashlib.sha256(json.dumps({**source, "room_ids": sorted(json.loads((manifest.parent / str(source.get("source_floor_plan") or "floor_plan.json")).read_text(encoding="utf-8")).get("rooms", {}))}, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    if value.get("source_manifest_digest") != expected:
        return False, "workstation layout was produced for a different floor-plan/manifest"
    return True, "ok"


def _link_or_copy(source: str, destination: str) -> str:
    """Clone accepted candidate files without doubling its multi-GB payload."""
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)
    return destination


def _publish_existing_office_candidate(*, candidate: Path, out_dir: Path, root: Path,
                                       attempt: int, candidate_seed: str,
                                       state_file: Path, state: dict) -> int:
    """Atomically promote a post-processed candidate without re-solving it."""
    if out_dir.exists():
        raise FileExistsError(f"refusing to replace existing accepted output: {out_dir}")
    staging = root / ".full.staging"
    if staging.exists():
        shutil.rmtree(staging)
    shutil.copytree(candidate, staging, copy_function=_link_or_copy)
    # Blender creates multi-GB recovery backups.  They are useful in the
    # attempt archive but are not part of the accepted candidate.
    (staging / "scene.blend1").unlink(missing_ok=True)
    audit_path = staging / "office_population_audit.json"
    selected_audit = json.loads(audit_path.read_text(encoding="utf-8"))
    selected_audit.pop("records", None)
    selected_audit["source_blend"] = "scene.blend"
    selected_audit["source_manifest"] = "office_layout_manifest.json"
    _write_json_atomic(audit_path, selected_audit)
    for name in ("kr_preset.json", "office_layout_manifest.json"):
        path = staging / name
        if not path.exists():
            continue
        value = json.loads(path.read_text(encoding="utf-8"))
        value["selected_attempt"] = attempt
        value["effective_scene_seed"] = candidate_seed
        value["office_population_audit"] = {
            "path": "office_population_audit.json", "status": "passed",
            "audit_digest": selected_audit.get("audit_digest"),
        }
        _write_json_atomic(path, value)
    os.replace(staging, out_dir)
    attempts_doc = {
        "schema": "robomituba.office_generation_attempts.v2",
        "logical_seed": state.get("logical_seed"),
        "selected_attempt": attempt,
        "attempts": [{"attempt": attempt, "effective_scene_seed": candidate_seed,
                       "path": str(candidate.relative_to(root)),
                       "generation_exit_code": 0, "audit_status": "passed",
                       "audit_digest": selected_audit.get("audit_digest"),
                       "published": True, "adopted_existing": True}],
    }
    _write_json_atomic(root / "office_generation_attempts.json", attempts_doc)
    update_office_state(state_file, state, status="published", stage="published",
                        note=f"candidate {attempt} repaired and promoted atomically",
                        selected_attempt=attempt, next_attempt=attempt + 1, process=None)
    print(f"[ok] repaired Office candidate {attempt} promoted without regeneration: {out_dir}")
    return 0


def _repair_existing_office_candidate(*, candidate: Path, office_style: str,
                                      state_file: Path, state: dict) -> bool:
    """Repair a saved candidate without re-running the expensive Infinigen solve.

    Blender writes to a sibling temporary blend.  The original candidate is
    replaced only after the subprocess exits successfully, so a crash leaves
    the generated scene available for inspection and another retry.
    """
    blend = candidate / "scene.blend"
    manifest = candidate / "office_layout_manifest.json"
    if not blend.is_file() or not manifest.is_file():
        return False
    repair_output = candidate / "scene.blend.repaired"
    repair_output.unlink(missing_ok=True)
    update_office_state(
        state_file, state, status="running", stage="repair_existing",
        note=f"repairing existing candidate {candidate.name} without regeneration",
    )
    command = [
        sys.executable, "tools/infinigen/run_bundled_blender.py",
        "--background", str(blend), "--python-exit-code", "3",
        "--python", "tools/infinigen/repair_office_candidate.py", "--",
        "--manifest", str(manifest), "--output-folder", str(candidate),
        "--style", office_style, "--save-path", str(repair_output),
    ]
    rc = _run(command)
    if rc != 0 or not repair_output.is_file():
        update_office_state(
            state_file, state, status="audit_failed", stage="repair_existing",
            note=f"existing candidate repair failed rc={rc}",
        )
        return False
    os.replace(repair_output, blend)
    (candidate / "scene.blend1").unlink(missing_ok=True)
    audit = candidate / "office_population_audit.json"
    update_office_state(
        state_file, state, status="audit", stage="population_audit",
        note=f"existing candidate repaired; running population audit",
    )
    audit_rc = _run([
        sys.executable, "tools/infinigen/run_bundled_blender.py",
        "--background", str(blend), "--python-exit-code", "3",
        "--python", "tools/infinigen/blender_audit_office_population.py", "--",
        "--manifest", str(manifest), "--workstation-layout",
        str(candidate / "workstation_layout.json"), "--out", str(audit),
    ])
    if audit_rc != 0 or not audit.is_file():
        update_office_state(
            state_file, state, status="audit_failed", stage="population_audit",
            note=f"repaired candidate audit failed rc={audit_rc}",
        )
        return False
    try:
        audit_value = json.loads(audit.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        audit_value = {}
    if audit_value.get("status") != "passed":
        update_office_state(
            state_file, state, status="audit_failed", stage="population_audit",
            note=f"repaired candidate audit status={audit_value.get('status')!r}",
        )
        return False
    return True


def _run_wide_office_candidates(*, args, seed: str, density: str, floor_plan: str,
                                office_style: str, out_dir: Path,
                                infinigen_python: Path, state_file: Path,
                                state: dict, resume: bool) -> int:
    """Generate/audit v2 candidates and atomically publish the first pass."""
    if args.stage != "full":
        # Layout-only generation intentionally has no furniture population to
        # audit.  It still uses the v2 floor-plan/profile contracts.
        return _run([
            sys.executable, "scripts/infinigen_gen.py", "--seed", seed,
            "--logical-seed", str(args.logical_seed or seed), "--variation-id", str(args.variation_id),
            "--density", density, "--anchor-richness", args.anchor_richness,
            "--surface-clutter", args.surface_clutter, "--office-style", office_style,
            "--office-max-attempts", "1", "--graph-max-nodes", str(args.graph_max_nodes),
            "--graph-heading-count", str(args.graph_heading_count),
            "--graph-min-node-spacing", str(args.graph_min_node_spacing),
            "--graph-robot-radius", str(args.graph_robot_radius), "--floor-plan", floor_plan,
            "--stage", args.stage, "--out", str(out_dir), "--run",
        ])
    if args.office_max_attempts < 1:
        raise ValueError("--office-max-attempts must be >= 1")
    root = out_dir.parent
    if state.get("status") == "published":
        print(f"[ok] already published accepted office: {out_dir}")
        return 0
    existing_audit = out_dir / "office_population_audit.json"
    if (out_dir / "scene.blend").is_file() and existing_audit.is_file():
        existing = json.loads(existing_audit.read_text(encoding="utf-8"))
        if existing.get("status") == "passed" and existing.get("profile") == "modern_glass_office_v2":
            print(f"[ok] already published accepted office: {out_dir}")
            return 0
    if out_dir.exists():
        raise FileExistsError(f"existing incomplete accepted-output path: {out_dir}; inspect or choose a new seed")

    # A completed Blender scene can outlive a failed post-process/audit.  Try
    # to repair that scene before invoking the multi-hour Infinigen solver.
    # The repair is opt-out and is deliberately limited to candidates with a
    # layout manifest; incomplete solver output still follows normal retry
    # policy below.
    if getattr(args, "repair_existing", True):
        for candidate in sorted((root / "attempts").glob("attempt_*")):
            if not (candidate / "scene.blend").is_file() or not (candidate / "office_layout_manifest.json").is_file():
                continue
            audit_path = candidate / "office_population_audit.json"
            try:
                audit_value = json.loads(audit_path.read_text(encoding="utf-8")) if audit_path.is_file() else {}
            except (OSError, json.JSONDecodeError):
                audit_value = {}
            # A passed audit is handled by the existing fast adoption path;
            # only missing/failed audits need Blender-side repair.
            if audit_value.get("status") == "passed" and audit_value.get("profile") == "modern_glass_office_v2":
                continue
            if _repair_existing_office_candidate(
                candidate=candidate, office_style=office_style,
                state_file=state_file, state=state,
            ):
                print(f"[repair] candidate {candidate.name} repaired; continuing with audit", flush=True)
                break

    # A saved scene may have failed only in post-processing or audit.  Prefer a
    # repaired, self-consistent candidate over restarting the expensive solver.
    for candidate in sorted((root / "attempts").glob("attempt_*")):
        attempt = _candidate_attempt_number(candidate)
        if attempt is None:
            continue
        manifest = candidate / "office_layout_manifest.json"
        layout = candidate / "workstation_layout.json"
        audit = candidate / "office_population_audit.json"
        if not ((candidate / "scene.blend").is_file() and manifest.is_file() and audit.is_file()):
            continue
        if not _workstation_layout_ok(layout, manifest)[0]:
            continue
        try:
            manifest_value = json.loads(manifest.read_text(encoding="utf-8"))
            value = json.loads(audit.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if manifest_value.get("logical_seed") not in {None, str(args.logical_seed or seed)}:
            continue
        if value.get("status") != "passed" or value.get("profile") != "modern_glass_office_v2":
            continue
        candidate_seed = _attempt_seed(str(args.logical_seed or seed), attempt)
        return _publish_existing_office_candidate(
            candidate=candidate, out_dir=out_dir, root=root, attempt=attempt,
            candidate_seed=candidate_seed, state_file=state_file, state=state,
        )

    # This catches registry/coverage mistakes before the first candidate spends
    # minutes solving rooms and then fails in its first object-addition move.
    preflight = _run([
        str(infinigen_python), "scripts/preflight_wide_glass_office_v2.py",
        "--seed", seed,
    ])
    if preflight != 0:
        update_office_state(state_file, state, status="generation_failed", stage="preflight",
                            note="Office v2 preflight failed", termination_reason="preflight_error")
        print("[!] Office v2 preflight failed; no candidate generation was started.")
        return preflight

    attempts_root = root / "attempts"
    attempts: list[dict] = []
    logical_seed = str(args.logical_seed or seed)
    generation_failures = 0
    audit_failures = 0
    start_attempt = int(state.get("next_attempt") or 1)
    for attempt in range(start_attempt, args.office_max_attempts + 1):
        candidate_seed = _attempt_seed(logical_seed, attempt)
        candidate = attempts_root / f"attempt_{attempt:02d}"
        manifest = candidate / "office_layout_manifest.json"
        layout = candidate / "workstation_layout.json"
        scene_ready = (candidate / "scene.blend").is_file() and _workstation_layout_ok(layout, manifest)[0]
        if candidate.exists() and not scene_ready:
            archived = _archive_path(candidate, suffix="interrupted" if resume else "previous")
            os.replace(candidate, archived)
            print(f"[retry] preserved prior incomplete candidate -> {archived}")
        state["current_attempt"] = attempt
        state["next_attempt"] = attempt
        attempts_entry = state.setdefault("attempts", {}).setdefault(f"attempt_{attempt:02d}", {})
        # A deterministic candidate can be resumed after a transient or
        # terminal attempt.  Do not carry terminal metadata into the new
        # planned/running record: otherwise operators see ``status=running``
        # together with the previous ``returncode=1`` and may mistake an
        # active solver for a failed process.  The terminal result remains in
        # the append-only history/attempts archive written before this reset.
        attempts_entry.update({
            "candidate_dir": str(candidate.resolve()),
            "effective_scene_seed": candidate_seed,
            "status": "planned",
            "returncode": None,
            "failure_kind": None,
            "generation_exit_code": None,
        })
        update_office_state(state_file, state, status="planned", stage="generation",
                            note=f"candidate {attempt}/{args.office_max_attempts} planned",
                            termination_reason=None, returncode=None, process=None)
        command = [
            sys.executable, "scripts/infinigen_gen.py", "--seed", candidate_seed,
            "--logical-seed", logical_seed, "--variation-id", str(args.variation_id),
            "--density", density, "--anchor-richness", args.anchor_richness,
            "--surface-clutter", args.surface_clutter, "--office-style", office_style,
            "--office-max-attempts", "1", "--graph-max-nodes", str(args.graph_max_nodes),
            "--graph-heading-count", str(args.graph_heading_count),
            "--graph-min-node-spacing", str(args.graph_min_node_spacing),
            "--graph-robot-radius", str(args.graph_robot_radius), "--floor-plan", floor_plan,
            "--stage", "full", "--out", str(candidate), "--office-run-state", str(state_file),
            "--office-run-id", str(state["run_id"]), "--run",
        ]
        rc = 0 if scene_ready else _run(command)
        # ``infinigen_gen.py`` owns the child log tracker and writes the
        # terminal reason to the shared run-state file.  ``state`` is the
        # wizard's in-memory snapshot, so reading it here used to leave
        # ``termination_reason`` stale and misclassify deterministic solver
        # failures as transient crashes.  Reload the atomic state before
        # deciding whether a same-seed retry is allowed.
        latest_state = read_run_state(state_file)
        if latest_state is not None:
            state.clear()
            state.update(latest_state)
        initial_reason = state.get("termination_reason")
        # A Blender/process crash is the only generation failure eligible for
        # one same-seed retry.  Preserve its artefacts and re-run the exact
        # candidate rather than burning a different deterministic layout seed.
        if rc != 0 and initial_reason not in {"solver_stalled", "unsatisfied_solver", "preflight_error", "contract_error"} and rc != 130:
            if candidate.exists():
                transient = _archive_path(candidate, suffix="transient")
                os.replace(candidate, transient)
                print(f"[retry] transient candidate failure preserved -> {transient}")
            state.setdefault("execution", {}).setdefault("transient_retries", 0)
            state["execution"]["transient_retries"] += 1
            update_office_state(state_file, state, status="planned", stage="generation",
                                note=f"candidate {attempt} transient same-seed retry")
            rc = _run(command)
        record = {"attempt": attempt, "effective_scene_seed": candidate_seed,
                  "path": str(candidate.relative_to(root)), "generation_exit_code": rc}
        if rc != 0:
            generation_failures += 1
            reason = state.get("termination_reason")
            record["failure_kind"] = reason or "generation_failed"
            attempts_entry.update({"status": record["failure_kind"], "returncode": rc})
            state.setdefault("execution", {}).setdefault("terminal_failures", 0)
            state["execution"]["terminal_failures"] += 1
            update_office_state(state_file, state, status=record["failure_kind"], stage="generation",
                                note=f"candidate {attempt} failed: {record['failure_kind']}",
                                next_attempt=attempt)
            # Solver configuration errors are deterministic.  Retrying six
            # seeds only hides the defective constraint graph and wastes hours.
            if record["failure_kind"] in {"solver_stalled", "unsatisfied_solver", "preflight_error", "contract_error"}:
                attempts.append(record)
                _write_json_atomic(root / "office_generation_attempts.json", {
                    "schema": "robomituba.office_generation_attempts.v2", "logical_seed": logical_seed,
                    "selected_attempt": None, "attempts": attempts,
                })
                print(f"[!] terminal Office configuration failure: {record['failure_kind']}; no further seeds will run.")
                return rc or 3
            # A same-seed transient retry was already attempted above.  Do not
            # misclassify infrastructure failure as an unlucky room-layout
            # candidate and cascade through six seeds.
            attempts.append(record)
            _write_json_atomic(root / "office_generation_attempts.json", {
                "schema": "robomituba.office_generation_attempts.v2", "logical_seed": logical_seed,
                "selected_attempt": None, "attempts": attempts,
            })
            print("[!] candidate generation failed after its same-seed retry; no further seeds will run.")
            return rc or 3
        elif not (candidate / "scene.blend").is_file():
            generation_failures += 1
            record["failure_kind"] = "generation_missing_scene_blend"
            attempts_entry.update({"status": record["failure_kind"]})
        else:
            okay, explanation = _workstation_layout_ok(candidate / "workstation_layout.json", candidate / "office_layout_manifest.json")
            if not okay:
                generation_failures += 1
                record["failure_kind"] = "workstation_layout_failed"
                record["workstation_layout_error"] = explanation
                attempts_entry.update({"status": record["failure_kind"], "error": explanation})
                update_office_state(state_file, state, status="generation_failed", stage="workstation_layout",
                                    note=f"candidate {attempt}: {explanation}", next_attempt=attempt)
                attempts.append(record)
                _write_json_atomic(root / "office_generation_attempts.json", {
                    "schema": "robomituba.office_generation_attempts.v2", "logical_seed": logical_seed,
                    "selected_attempt": None, "attempts": attempts,
                })
                return 3
            audit = candidate / "office_population_audit.json"
            update_office_state(state_file, state, status="audit", stage="population_audit",
                                note=f"candidate {attempt} scene+workstation layout ready")
            rc = _run([
                sys.executable, "tools/infinigen/run_bundled_blender.py", "--background", str(candidate / "scene.blend"),
                "--python-exit-code", "3", "--python", "tools/infinigen/blender_audit_office_population.py", "--",
                "--manifest", str(candidate / "office_layout_manifest.json"),
                "--workstation-layout", str(candidate / "workstation_layout.json"), "--out", str(audit),
            ])
            record["audit_exit_code"] = rc
            if audit.is_file():
                value = json.loads(audit.read_text(encoding="utf-8"))
                record["audit_status"] = value.get("status")
                record["audit_digest"] = value.get("audit_digest")
            if rc == 0 and record.get("audit_status") == "passed":
                if out_dir.exists():
                    raise FileExistsError(f"refusing to replace existing accepted output: {out_dir}")
                staging = root / ".full.staging"
                if staging.exists():
                    shutil.rmtree(staging)
                shutil.copytree(candidate, staging, copy_function=_link_or_copy)
                (staging / "scene.blend1").unlink(missing_ok=True)
                selected_audit = json.loads((staging / "office_population_audit.json").read_text(encoding="utf-8"))
                selected_audit.pop("records", None)
                # Candidate paths are diagnostic-only; the promoted bundle must
                # be self-contained and not retain an absolute attempt path.
                selected_audit["source_blend"] = "scene.blend"
                selected_audit["source_manifest"] = "office_layout_manifest.json"
                _write_json_atomic(staging / "office_population_audit.json", selected_audit)
                selected_layout = json.loads((staging / "office_layout_manifest.json").read_text(encoding="utf-8"))
                for name in ("kr_preset.json", "office_layout_manifest.json"):
                    path = staging / name
                    value = json.loads(path.read_text(encoding="utf-8"))
                    value["selected_attempt"] = attempt
                    value["effective_scene_seed"] = candidate_seed
                    value["office_population_audit"] = {
                        "path": "office_population_audit.json", "status": "passed",
                        "audit_digest": selected_audit["audit_digest"],
                    }
                    _write_json_atomic(path, value)
                os.replace(staging, out_dir)
                record["published"] = True
                attempts_entry.update({"status": "published", "audit_digest": selected_audit["audit_digest"]})
                attempts.append(record)
                _write_json_atomic(root / "office_generation_attempts.json", {
                    "schema": "robomituba.office_generation_attempts.v2", "logical_seed": logical_seed,
                    "selected_attempt": attempt, "attempts": attempts,
                })
                office_meta = selected_layout.get("footprint_area_m2")
                print(f"[ok] office candidate {attempt}/{args.office_max_attempts} passed; published {out_dir}")
                print("[ok] selected office: "
                      f"{office_meta if office_meta is not None else 'unknown'}m² · "
                      f"{selected_audit.get('work_bay_rooms', [])!s} · 10 partitions / 20 panes")
                update_office_state(state_file, state, status="published", stage="published",
                                    note=f"candidate {attempt} promoted atomically", selected_attempt=attempt,
                                    next_attempt=attempt + 1, process=None)
                return 0
            audit_failures += 1
            record["failure_kind"] = "population_audit_failed"
            attempts_entry.update({"status": "audit_failed", "audit_digest": record.get("audit_digest")})
            update_office_state(state_file, state, status="audit_failed", stage="population_audit",
                                note=f"candidate {attempt} population audit failed", next_attempt=attempt + 1)
        attempts.append(record)
        _write_json_atomic(root / "office_generation_attempts.json", {
            "schema": "robomituba.office_generation_attempts.v2", "logical_seed": logical_seed,
            "selected_attempt": None, "attempts": attempts,
        })
    print(f"[!] Office generation did not publish a candidate: generation failures={generation_failures}, "
          f"population-audit failures={audit_failures}; import 중단.")
    update_office_state(state_file, state, status="generation_failed", stage="generation",
                        note="candidate retry budget exhausted", process=None)
    return 3


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
    auto = args.yes or args.status or args.stop or args.resume or args.retry_terminal or args.adopt_interrupted
    print("=" * 64)
    print("  Infinigen 실내 씬 마법사  (생성 → import)")
    print("=" * 64)

    raw_argv = argv if argv is not None else sys.argv[1:]
    archetype = args.archetype or ("office" if (args.status or args.stop or args.resume or args.retry_terminal or args.adopt_interrupted) else "apartment" if auto else
                                   _pick("1. archetype (방 구조)", list(ARCHETYPES), "apartment"))
    office_profile = args.office_profile
    if archetype == "office" and not auto and "--office-profile" not in raw_argv:
        office_profile = _pick("2. Office profile", list(OFFICE_PROFILES), "modern_glass_office_v2")
    office_style = args.office_style or (OFFICE_PROFILES[office_profile]["style"] if archetype == "office" else None)
    if archetype == "office" and not auto and "--office-style" not in raw_argv:
        # Profile owns the default.  Only ask when the user explicitly selects
        # a style flag, avoiding accidental downgrade to compact v1.
        office_style = OFFICE_PROFILES[office_profile]["style"]
    room_type = args.room_type
    if archetype == "single_room" and room_type is None:
        room_type = "living-room" if auto else _pick("2. 방 타입", list(ROOM_TYPES), "living-room")
    density_prompt = "3. 가구 밀도" if archetype in {"single_room", "office"} else "2. 가구 밀도"
    density = args.density or ("normal_lived_in" if auto else
                               _pick(density_prompt, list(DENSITIES), "normal_lived_in"))
    stage_prompt = "4. stage" if archetype == "single_room" else "3. stage"
    stage = args.stage or ("full" if auto else _pick(stage_prompt, STAGES, "full"))
    # Candidate generation consumes the parsed namespace, whereas the summary
    # above consumes this resolved local default. Keep both representations in
    # sync so an omitted --stage follows the default full/audited path.
    args.stage = stage
    seed = _resolve_seed(args.seed) if (args.seed or auto) else _ask_seed()

    if args.do_import is not None:
        do_import = args.do_import
    else:
        import_prompt = "5" if archetype == "single_room" else "4"
        do_import = True if auto else _yesno(f"\n{import_prompt}. 생성 후 OpticalNav import 까지 진행?", True)
    bake_pbr = bool(args.bake_pbr)
    if do_import and args.bake_pbr is None and not auto:
        bake_pbr = _yesno("   └ PBR(roughness/normal/metallic) 베이크? (~4배 느림)", False)

    floor_plan = OFFICE_PROFILES[office_profile]["floor_plan"] if archetype == "office" else ARCHETYPES[archetype]
    num_floating = DENSITIES[density]
    room_suffix = f"_{room_type.replace('-', '_')}" if archetype == "single_room" else ""
    # Do not let the new default native profile share an output/import name
    # with a previously generated legacy ``gen_apartment`` scene of the same
    # logical seed. Existing output paths remain unchanged for every legacy
    # floor-plan choice.
    floor_profile_suffix = "_natural_v1" if floor_plan == "apartment_natural_v1" else ""
    placement_suffix = "" if args.placement_profile == "legacy_clutter_v1" else f"_{args.placement_profile}"
    out_dir = REPO / "data" / "infinigen_generated" / "outputs" / f"kr_{seed}_{archetype}{room_suffix}{floor_profile_suffix}{placement_suffix}" / stage
    scene_id = args.scene_id or f"infinigen_{archetype}{room_suffix}{floor_profile_suffix}_{seed}"

    state_file = None
    office_state = None
    if archetype == "office" and office_profile == "modern_glass_office_v2":
        root = out_dir.parent
        if args.status or args.stop:
            state_file = office_state_path(root)
            office_state = read_run_state(state_file)
            if office_state is None:
                print(f"[office] no v2 run state at {state_file}; legacy attempt directories may be inspected but cannot be signalled safely.")
                return 1
            if args.stop:
                ok, message = stop_recorded_candidate(office_state, force=args.force)
                if ok:
                    office_state.setdefault("execution", {}).setdefault("graceful_stops", 0)
                    office_state["execution"]["graceful_stops"] += 1
                update_office_state(
                    state_file, office_state,
                    status="interrupted" if ok else office_state.get("status", "running"),
                    stage=office_state.get("stage", "generation"), note=message,
                    termination_reason="user_stop" if ok else office_state.get("termination_reason"),
                    process=None if ok else office_state.get("process"),
                )
                print(f"[office] stop {'ok' if ok else 'failed'}: {message}")
                return 0 if ok else 2
            print(json.dumps(office_state, ensure_ascii=False, indent=2))
            return 0
        contract = _office_contract(args=args, seed=seed, density=density, floor_plan=floor_plan,
                                    office_style=office_style, out_dir=out_dir)
        try:
            state_file, office_state = _prepare_office_state(
                root=root, contract=contract, logical_seed=str(args.logical_seed or seed),
                max_attempts=args.office_max_attempts,
                resume=args.resume or args.adopt_interrupted or args.retry_terminal,
                retry_terminal=args.retry_terminal,
            )
        except (ValueError, RuntimeError) as exc:
            print(f"[office] {exc}")
            return 2
        if args.adopt_interrupted:
            attempts_root = root / "attempts"
            diagnostic_candidates = [str(path.relative_to(root)) for path in sorted(attempts_root.iterdir())] if attempts_root.exists() else []
            update_office_state(
                state_file, office_state, status="interrupted", stage="generation",
                note="recorded pre-v2 interrupted diagnostic artefacts",
                historical_log_unavailable=True, diagnostic_candidates=diagnostic_candidates,
            )
            print(f"[office] adopted interrupted pre-v2 candidate artefacts -> {state_file}")
            return 0

    print("\n" + "-" * 64)
    print("요약")
    print(f"  archetype     : {archetype}  (--floor-plan {floor_plan})")
    if archetype == "office":
        print(f"  office profile: {office_profile} ({OFFICE_PROFILES[office_profile]['description']})")
        print(f"  office style  : {office_style}")
        print("  graph profile : "
              f"nodes={args.graph_max_nodes}, headings={args.graph_heading_count}, "
              f"spacing={args.graph_min_node_spacing:g}m, robot={args.graph_robot_radius:g}m")
        if office_style == "modern_glass_v2":
            expected = wide_glass_office_metadata(int(seed))
            print(f"  expected area : {expected['footprint_area_m2']:.0f}m² · "
                  f"work bays={expected['work_bay_count']} · reception/support=1")
            print(f"  glass contract: 10 structural partitions / 20 panes · population retries={args.office_max_attempts}")
        elif office_style == "modern_glass_v1":
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

    # Resolve (and remember) the Infinigen Python only for operations that
    # actually launch Blender. --status/--stop above remain usable even when a
    # host's generation environment has been moved or is unavailable.
    import infinigen_env
    try:
        py = infinigen_env.resolve_python(prompt=not auto, persist=True)
        print(f"infinigen env: {py}")
    except (SystemExit, FileNotFoundError) as e:
        if state_file is not None and office_state is not None:
            update_office_state(state_file, office_state, status="generation_failed", stage="preflight",
                                note=f"Infinigen environment resolution failed: {e}", termination_reason="preflight_error")
        print(e)
        return 1

    # Material assignment modules are imported inside the generation child.
    # Use a per-wizard environment (the controller launches one wizard per
    # scene) so the opt-in profile cannot mutate the repository-wide default.
    os.environ["INFINIGEN_IR_MATERIAL_PROFILE"] = str(args.ir_material_profile)

    # ── 1) generate ──────────────────────────────────────────────────────────
    if archetype == "office" and office_profile == "modern_glass_office_v2":
        rc = _run_wide_office_candidates(
            args=args, seed=seed, density=density, floor_plan=floor_plan,
            office_style=office_style, out_dir=out_dir, infinigen_python=Path(py),
            state_file=state_file, state=office_state, resume=args.resume,
        )
    else:
        gen_cmd = [
            sys.executable, "scripts/infinigen_gen.py",
            "--seed", seed,
            "--logical-seed", str(args.logical_seed or seed),
            "--variation-id", str(args.variation_id),
            "--density", density,
            "--anchor-richness", args.anchor_richness,
            "--surface-clutter", args.surface_clutter,
            "--placement-profile", args.placement_profile,
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
    if archetype == "office" and office_profile == "modern_glass_office_v2":
        imp_cmd += ["--office-population-audit", str(out_dir / "office_population_audit.json")]
    if bake_pbr:
        imp_cmd.append("--bake-pbr")
    if state_file is not None:
        update_office_state(state_file, office_state, status="running", stage="import", note="OpticalNav import started")
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
        if state_file is not None:
            update_office_state(state_file, office_state, status="running", stage="graph_build", note="OpticalNav graph build started")
        rc = _run(graph_cmd)
        if rc != 0:
            print(f"\n[!] OpticalNav graph build 실패 (exit {rc}).")
            return rc
        if office_style in {"modern_glass_v1", "modern_glass_v2"}:
            source_manifest = out_dir / "office_layout_manifest.json"
            scene_dir = REPO / "out" / "opticalnav" / "opticalnav-v0.2" / "scenes" / scene_id
            audit_cmd = [sys.executable, "scripts/audit_modern_office_graph.py",
                         "--source-manifest", str(source_manifest), "--scene-dir", str(scene_dir),
                         "--out", str(out_dir / "modern_office_graph_audit.json")]
            if state_file is not None:
                update_office_state(state_file, office_state, status="audit", stage="graph_audit", note="Office graph audit started")
            rc = _run(audit_cmd)
            if rc != 0:
                print(f"\n[!] Modern Glass structural graph audit 실패 (exit {rc}).")
                return rc
            print("[ok] Modern Glass structural graph audit 통과")
    if state_file is not None:
        update_office_state(state_file, office_state, status="published", stage="complete", note="generation, import, and graph audit complete")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n중단됨.")
        raise SystemExit(130)
