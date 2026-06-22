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
#   --no-bake            Skip procedural material bake (faster, grayscale-ish)
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
INFINIGEN_PYTHON="${INFINIGEN_PYTHON:-/home/jinnyeong/miniconda3/envs/infinigen/bin/python}"
PYTHON="${PYTHON:-python3}"

# ── parse args ────────────────────────────────────────────────────────────────
INPUT=""
SCENE_ID=""
PROJECT_ID="opticalnav-v0.2"
BAKE=1
SKIP_EXPORT=0
STAGE2_EXTRA=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --scene-id)   SCENE_ID="$2"; shift 2;;
    --project-id) PROJECT_ID="$2"; shift 2;;
    --no-bake)    BAKE=0; shift;;
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

# scene name from the blend's parent directory
DIRNAME="$(basename "$(dirname "$(readlink -f "$BLEND")")")"
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
  echo "[stage1] exporting meshes/materials with bpy (this can take several minutes)…"
  # bpy frequently segfaults during interpreter/teardown AFTER the manifest is
  # already written (conda bpy on WSL). Don't let that non-zero exit abort the
  # pipeline under `set -e`; the manifest-exists guard below is the real check.
  stage1_rc=0
  "$INFINIGEN_PYTHON" tools/infinigen/_run_bpy.py "$BLEND" \
    tools/infinigen/blender_export_scene.py -- \
    --out "$IMPORT_DIR" "${BAKE_FLAG[@]}" || stage1_rc=$?
  if [[ $stage1_rc -ne 0 && -f "$MANIFEST" ]]; then
    echo "[stage1] bpy exited $stage1_rc (likely a teardown segfault) but the manifest was written — continuing." >&2
  fi
  [[ -f "$MANIFEST" ]] || { echo "[error] Stage 1 failed (exit $stage1_rc) and produced no manifest: $MANIFEST" >&2; exit 1; }
fi

# ── Stage 2: converter ────────────────────────────────────────────────────────
echo "[stage2] converting manifest → OpticalNav scene…"
"$PYTHON" apps/import_infinigen_scene.py \
  --manifest "$MANIFEST" \
  --scene-id "$SCENE_ID" \
  --project-id "$PROJECT_ID" \
  --force "${STAGE2_EXTRA[@]}"

echo "═══════════════════════════════════════════════════════════════"
echo " ✓ done → out/opticalnav/${PROJECT_ID}/scenes/${SCENE_ID}/"
echo "   webui에서 scene 리로드 후 'Rebuild graph' 한 번 실행하세요."
echo "═══════════════════════════════════════════════════════════════"
