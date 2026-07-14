#!/usr/bin/env bash
# One-shot Infinigen → OpticalNav importer.
#
# Give it a .blend (or the scene directory) and it runs both stages:
#   Stage 1 (bpy export, infinigen env) → out/infinigen_imports/<name>/
#   Stage 2 (converter, robomituba env) → out/opticalnav/<project>/scenes/<scene-id>/
#
# Usage:
#   bash apps/run_infinigen_import.sh <scene.blend | scene-dir> [options]
#
# Options:
#   --scene-id ID        OpticalNav scene id        (default: infinigen_<dirname>)
#   --project-id ID      OpticalNav project         (default: opticalnav-v0.2)
#   --no-bake            Skip procedural material bake (explicit degraded preview mode)
#   --bake-pbr           Deprecated compatibility no-op (PBR bake is now the default)
#   --no-bake-pbr        Disable roughness/normal/metallic bake (degraded preview mode)
#   --no-glb             Disable GLB export (requires --allow-obj-fallback)
#   --allow-obj-fallback Permit legacy/incomplete manifests and OBJ render fallback
#   --no-bake-metallic   With --bake-pbr, skip the (fiddly) metallic EMIT bake
#   --bake-only          Re-bake PBR into an EXISTING scene's import (Stage 1 only, no
#                        re-import) — preserves the authoring map; busts the staged cache
#   --no-sync            Skip Stage 3 render-scene sync (don't stage webui meshes)
#   --skip-export        Reuse an existing Stage-1 manifest (only run Stage 2)
#   --room KEY           Keep only this room        (e.g. "dining-room_0/0")
#   --keep-empty-rooms   Keep unfurnished/empty rooms
#   --no-normalize-origin  Keep raw Infinigen world coords (don't snap to origin/floor)
#
# Env overrides:
#   INFINIGEN_PYTHON   python with the `bpy` module (default: infinigen conda env)
#   PYTHON             python for Stage 2 / robomituba modules (default: python3)
#
# Examples:
#   bash apps/run_infinigen_import.sh data/infinigen_generated/outputs/indoors/singleroom_furnished
#   bash apps/run_infinigen_import.sh .../singleroom_furnished/scene.blend1 --scene-id infinigen_kitchen_001 --no-bake
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"
PYTHON="${PYTHON:-python3}"

# Resolve the Infinigen env path machine-independently (see scripts/infinigen_env.py):
# source the persisted config, and if still unset, auto-detect + persist it.
[[ -f "$REPO/.infinigen_env" ]] && source "$REPO/.infinigen_env"
if [[ -z "${INFINIGEN_PYTHON:-}" ]]; then
  "$PYTHON" "$REPO/scripts/infinigen_env.py" --write >/dev/null 2>&1 || true
  [[ -f "$REPO/.infinigen_env" ]] && source "$REPO/.infinigen_env"
fi
INFINIGEN_PYTHON="${INFINIGEN_PYTHON:-$HOME/miniconda3/envs/infinigen/bin/python}"

# ── parse args ────────────────────────────────────────────────────────────────
INPUT=""
SCENE_ID=""
PROJECT_ID="opticalnav-v0.2"
BAKE=1
BAKE_PBR=1
BAKE_METALLIC=1
GLB=1
ALLOW_OBJ_FALLBACK=0
BAKE_ONLY=0
SKIP_EXPORT=0
SYNC=1
DAEMON_URL="${ROBOMITUBA_DAEMON_URL:-http://127.0.0.1:8765}"
STAGE2_EXTRA=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --scene-id)   SCENE_ID="$2"; shift 2;;
    --project-id) PROJECT_ID="$2"; shift 2;;
    --no-bake)    BAKE=0; shift;;
    --bake-pbr)   BAKE_PBR=1; shift;;
    --no-bake-pbr) BAKE_PBR=0; shift;;
    --no-glb)     GLB=0; shift;;
    --allow-obj-fallback) ALLOW_OBJ_FALLBACK=1; shift;;
    --no-bake-metallic) BAKE_METALLIC=0; shift;;
    --bake-only)  BAKE_ONLY=1; BAKE=1; BAKE_PBR=1; SKIP_EXPORT=0; shift;;
    --no-sync)    SYNC=0; shift;;
    --skip-export) SKIP_EXPORT=1; shift;;
    --room)       STAGE2_EXTRA+=(--room "$2"); shift 2;;
    --keep-empty-rooms|--no-normalize-origin) STAGE2_EXTRA+=("$1"); shift;;
    -h|--help)    sed -n '2,30p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0;;
    -*)           echo "[error] unknown option: $1" >&2; exit 2;;
    *)            INPUT="$1"; shift;;
  esac
done
if [[ -z "$INPUT" ]]; then
  echo "[error] missing <scene.blend | scene-dir>. See --help." >&2; exit 2
fi
if [[ "$GLB" == 0 && "$ALLOW_OBJ_FALLBACK" == 0 ]]; then
  echo "[error] --no-glb requires --allow-obj-fallback (default import is strict GLB)." >&2
  exit 2
fi
if [[ "$BAKE" == 0 || "$BAKE_PBR" == 0 ]]; then
  ALLOW_OBJ_FALLBACK=1
fi
[[ $ALLOW_OBJ_FALLBACK == 1 ]] && STAGE2_EXTRA+=(--allow-obj-fallback)

# ── resolve a readable .blend ─────────────────────────────────────────────────
# Infinigen's main scene.blend is often header-corrupt; the scene.blend1 backup
# is the valid file. A valid header is "BLENDER-v" / "BLENDER_v" (byte 7 is -/_).
blend_is_valid() { local h; h="$(head -c 8 "$1" 2>/dev/null || true)"; [[ "$h" == BLENDER[-_]* ]]; }

pick_blend() {
  local cand="$1"
  if [[ -d "$cand" ]]; then
    for f in "$cand/scene.blend1" "$cand/scene.blend"; do
      [[ -f "$f" ]] && blend_is_valid "$f" && { echo "$f"; return 0; }
    done
    for f in "$cand"/*.blend1 "$cand"/*.blend; do
      [[ -f "$f" ]] && blend_is_valid "$f" && { echo "$f"; return 0; }
    done
    return 1
  fi
  # a file was given
  if [[ -f "$cand" ]] && blend_is_valid "$cand"; then echo "$cand"; return 0; fi
  # corrupt/given file: try the .blend1 sibling
  local alt="${cand%.blend}.blend1"
  [[ -f "$alt" ]] && blend_is_valid "$alt" && { echo "$alt"; return 0; }
  return 1
}

BLEND="$(pick_blend "$INPUT" || true)"
if [[ -z "$BLEND" ]]; then
  echo "[error] no readable .blend found at: $INPUT" >&2
  echo "        (Infinigen scene.blend is often corrupt — use the scene.blend1 backup, or pass the scene dir.)" >&2
  exit 1
fi

# scene name from the blend's parent directory. The KR generator lays scenes out
# as <seed>/<stage>/scene.blend (e.g. kr_21606082/full/scene.blend), so the parent
# dir is a stage keyword, not the scene name — fall back to the grandparent so the
# scene isn't named "full" (which collides across seeds). Plain layouts like
# indoor_seed4/scene.blend keep their parent dir name unchanged.
PARENT_DIR="$(dirname "$(readlink -f "$BLEND")")"
DIRNAME="$(basename "$PARENT_DIR")"
case "$DIRNAME" in
  layout|full|coarse|fine)
    DIRNAME="$(basename "$(dirname "$PARENT_DIR")")";;
esac
NAME="$(echo "$DIRNAME" | tr -cs 'A-Za-z0-9._-' '_' | sed 's/^_*//;s/_*$//')"
[[ -z "$SCENE_ID" ]] && SCENE_ID="infinigen_${NAME}"
IMPORT_DIR="out/infinigen_imports/${NAME}"
MANIFEST="${IMPORT_DIR}/scene_manifest.json"

echo "═══════════════════════════════════════════════════════════════"
echo " blend     : $BLEND"
echo " import dir: $IMPORT_DIR"
echo " scene id  : $SCENE_ID   (project $PROJECT_ID)"
echo " bake      : $([[ $BAKE == 1 ]] && echo on || echo off)"
echo "═══════════════════════════════════════════════════════════════"

# ── Stage 1: bpy export ───────────────────────────────────────────────────────
if [[ "$SKIP_EXPORT" == 1 ]]; then
  echo "[stage1] skipped (--skip-export); using existing $MANIFEST"
  [[ -f "$MANIFEST" ]] || { echo "[error] manifest not found: $MANIFEST" >&2; exit 1; }
else
  [[ -x "$INFINIGEN_PYTHON" || -f "$INFINIGEN_PYTHON" ]] || {
    echo "[error] infinigen python not found: $INFINIGEN_PYTHON (set INFINIGEN_PYTHON=...)" >&2; exit 1; }
  BAKE_FLAG=(); [[ $BAKE == 1 ]] && BAKE_FLAG=(--bake)
  [[ $BAKE == 1 && $BAKE_PBR == 1 ]] && BAKE_FLAG+=(--bake-pbr)
  [[ $BAKE_PBR == 1 && $BAKE_METALLIC == 0 ]] && BAKE_FLAG+=(--no-bake-metallic)
  [[ $GLB == 0 ]] && BAKE_FLAG+=(--no-glb)
  [[ $ALLOW_OBJ_FALLBACK == 1 ]] && BAKE_FLAG+=(--allow-incomplete-pbr)
  DEFAULT_STAGING_DIR="${IMPORT_DIR}.staging.$(date +%Y%m%dT%H%M%S)-$$"
  STAGING_DIR="${INFINIGEN_EXPORT_RESUME_DIR:-$DEFAULT_STAGING_DIR}"
  STAGING_MANIFEST="${STAGING_DIR}/scene_manifest.json"
  echo "[stage1] exporting meshes/materials with bpy -> $STAGING_DIR"
  # Long-lived bpy processes are unstable on multi-GB scenes. Export bounded
  # chunks into one staging directory and merge the manifest after each chunk.
  CHUNK_SIZE="${INFINIGEN_EXPORT_CHUNK_SIZE:-40}"
  [[ "$CHUNK_SIZE" =~ ^[1-9][0-9]*$ ]] || { echo "[error] invalid INFINIGEN_EXPORT_CHUNK_SIZE=$CHUNK_SIZE" >&2; exit 2; }
  chunk_skip=0
  unit_count=0
  total_count=-1
  if [[ -n "${INFINIGEN_EXPORT_RESUME_DIR:-}" && -f "$STAGING_MANIFEST" ]]; then
    counts="$("$PYTHON" -c "import json,sys; d=json.load(open(sys.argv[1])); print(len(d.get(\"units\", [])), d.get(\"renderable_unit_count\", -1))" "$STAGING_MANIFEST")"
    read -r unit_count total_count <<< "$counts"
    chunk_skip=$unit_count
    echo "[stage1] resuming committed staging at $unit_count/$total_count units"
  fi
  while (( total_count < 0 || unit_count < total_count )); do
    before_count=$unit_count
    MERGE_FLAG=(); [[ -f "$STAGING_MANIFEST" ]] && MERGE_FLAG=(--merge)
    stage1_rc=0
    "$INFINIGEN_PYTHON" tools/infinigen/_run_bpy.py "$BLEND" \
      tools/infinigen/blender_export_scene.py -- \
      --out "$STAGING_DIR" --scene-id "$NAME" --skip "$chunk_skip" --limit "$CHUNK_SIZE" \
      "${MERGE_FLAG[@]}" "${BAKE_FLAG[@]}" || stage1_rc=$?
    [[ -f "$STAGING_MANIFEST" ]] || { echo "[error] Stage 1 chunk failed (exit $stage1_rc) before manifest update" >&2; exit 1; }
    counts="$("$PYTHON" -c "import json,sys; d=json.load(open(sys.argv[1])); print(len(d.get(\"units\", [])), d.get(\"renderable_unit_count\", -1))" "$STAGING_MANIFEST")"
    read -r unit_count total_count <<< "$counts"
    if (( unit_count <= before_count && unit_count < total_count )); then
      echo "[error] Stage 1 chunk at skip=$chunk_skip failed (exit $stage1_rc); manifest did not advance" >&2
      exit 1
    fi
    if [[ $stage1_rc -ne 0 ]]; then
      echo "[stage1] bpy exited $stage1_rc after committing chunk; continuing with a fresh process." >&2
    fi
    echo "[stage1] committed $unit_count/$total_count units"
    chunk_skip=$((chunk_skip + CHUNK_SIZE))
  done
  VALIDATE_FLAG=(); [[ $ALLOW_OBJ_FALLBACK == 1 ]] && VALIDATE_FLAG+=(--allow-obj-fallback)
  "$PYTHON" apps/import_infinigen_scene.py --manifest "$STAGING_MANIFEST" --validate-only "${VALIDATE_FLAG[@]}"
  if [[ -d "$IMPORT_DIR" ]]; then
    BACKUP_DIR="${IMPORT_DIR}.backup.$(date +%Y%m%dT%H%M%S)"
    mv "$IMPORT_DIR" "$BACKUP_DIR"
    echo "[stage1] previous import preserved at $BACKUP_DIR"
  fi
  mv "$STAGING_DIR" "$IMPORT_DIR"
  echo "[stage1] atomically promoted $IMPORT_DIR"
fi

# ── --bake-only: re-baked PBR atlases + MTL keys in place; do NOT re-run Stage 2
# (which would rebuild authoring_map and lose manual edits). The authoring map and
# render_scene.xml still reference the same meshes by path, so just bust the staged
# scene cache so the next render re-stages with the new map_Pr/map_Pm/norm.
if [[ "$BAKE_ONLY" == 1 ]]; then
  SCENE_DIR="out/opticalnav/${PROJECT_ID}/scenes/${SCENE_ID}"
  rm -rf "$SCENE_DIR/.staged_mitsuba" 2>/dev/null || true
  [[ -f "$SCENE_DIR/render_scene.xml" ]] && touch "$SCENE_DIR/render_scene.xml"
  echo "═══════════════════════════════════════════════════════════════"
  echo " ✓ bake-only done → re-baked PBR into $IMPORT_DIR"
  echo "   authoring map preserved; staged cache busted for $SCENE_DIR"
  echo "   다음 렌더부터 roughness/normal 맵이 적용됩니다."
  echo "═══════════════════════════════════════════════════════════════"
  exit 0
fi

# ── Stage 2: converter ────────────────────────────────────────────────────────
echo "[stage2] converting manifest → OpticalNav scene…"
"$PYTHON" apps/import_infinigen_scene.py \
  --manifest "$MANIFEST" \
  --scene-id "$SCENE_ID" \
  --project-id "$PROJECT_ID" \
  --force "${STAGE2_EXTRA[@]}"

# ── Stage 3: render-scene sync (stages per-scene mesh_cache for the webui viewer) ─
# Stage 2 writes authoring_map + render_scene_overlays, but the webui 3D viewer
# fetches meshes from <scene>/mesh_cache/<digest>.obj, which are only staged when
# render_scene.xml is generated — and that happens in the daemon's render-scene
# sync, not in this CLI. Without it the viewer 404s every mesh. Trigger the sync
# here when the daemon is reachable; otherwise tell the user to do it from webui.
SCENE_DIR="out/opticalnav/${PROJECT_ID}/scenes/${SCENE_ID}"
if [[ "$SYNC" == 1 ]]; then
  if "$PYTHON" - "$DAEMON_URL" "$PROJECT_ID" "$SCENE_ID" <<'PY'
import json, sys, urllib.request, urllib.error
base, project, scene = sys.argv[1], sys.argv[2], sys.argv[3]
def req(method, path, body=None, timeout=10):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(base + path, data=data, method=method,
                               headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(r, timeout=timeout)
try:
    req("GET", "/api/summary", timeout=3).read()
except Exception:
    print(f"[stage3] render daemon not reachable at {base} — skipping render-scene sync.")
    print("          Open the scene in webui and click 'Save Map' to stage meshes")
    print("          (or set ROBOMITUBA_DAEMON_URL and re-run with --skip-export).")
    sys.exit(3)
try:
    req("POST", f"/api/opticalnav/projects/{project}/scenes/{scene}/sync/render-scene", body={})
    print(f"[stage3] render-scene sync requested on {base} (async).")
    sys.exit(0)
except Exception as exc:  # noqa: BLE001
    print(f"[stage3] sync request failed: {exc} (continuing).")
    sys.exit(4)
PY
  then
    # The sync job is async; poll the filesystem until the mesh_cache is staged.
    echo "[stage3] waiting for render_scene.xml + mesh_cache (up to ~5 min)…"
    for _ in $(seq 1 150); do
      if [[ -f "${SCENE_DIR}/render_scene.xml" ]] && compgen -G "${SCENE_DIR}/mesh_cache/*.obj" >/dev/null 2>&1; then
        echo "[stage3] ✓ render_scene.xml + mesh_cache staged — webui meshes will load."
        break
      fi
      sleep 2
    done
    [[ -f "${SCENE_DIR}/render_scene.xml" ]] || echo "[stage3] (timed out waiting; check the daemon log / webui Status tab.)"
  fi
fi

echo "═══════════════════════════════════════════════════════════════"
echo " ✓ done → out/opticalnav/${PROJECT_ID}/scenes/${SCENE_ID}/"
echo "   webui에서 scene 리로드 후 'Rebuild graph' 한 번 실행하세요."
echo "═══════════════════════════════════════════════════════════════"
