#!/usr/bin/env bash
set -euo pipefail

# Install Infinigen's public Python dependencies while skipping private/SSH
# editable requirements that fail in containers without GitHub credentials.
#
# Defaults match the current Robomituba/Infinigen dev container:
#   INFINIGEN_DIR=/root/module/infinigen
#   INFINIGEN_PYTHON=/root/miniconda3/envs/infinigen/bin/python
#
# Usage:
#   bash scripts/install_infinigen_deps.sh
#   INFINIGEN_DIR=/path/to/infinigen INFINIGEN_PYTHON=/path/to/python bash scripts/install_infinigen_deps.sh
#
# Options:
#   --no-local-install   Do not run "pip install -e $INFINIGEN_DIR --no-deps"
#   --keep-gin-package   Do not uninstall the unrelated "gin" package first
#   --dry-run            Print commands without executing them

INFINIGEN_DIR="${INFINIGEN_DIR:-/root/module/infinigen}"
INFINIGEN_PYTHON="${INFINIGEN_PYTHON:-/root/miniconda3/envs/infinigen/bin/python}"
INSTALL_LOCAL=1
REMOVE_WRONG_GIN=1
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-local-install)
      INSTALL_LOCAL=0
      ;;
    --keep-gin-package)
      REMOVE_WRONG_GIN=0
      ;;
    --dry-run)
      DRY_RUN=1
      ;;
    -h|--help)
      sed -n '1,24p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 2
      ;;
  esac
  shift
done

REQ_FILE="$INFINIGEN_DIR/requirements.txt"
PUBLIC_REQ="/tmp/infinigen_requirements_public.txt"

run() {
  echo "+ $*"
  if [[ "$DRY_RUN" -eq 0 ]]; then
    "$@"
  fi
}

if [[ ! -x "$INFINIGEN_PYTHON" ]]; then
  echo "Missing Python executable: $INFINIGEN_PYTHON" >&2
  exit 1
fi

if [[ ! -f "$REQ_FILE" ]]; then
  echo "Missing requirements.txt: $REQ_FILE" >&2
  exit 1
fi

echo "# INFINIGEN_DIR    = $INFINIGEN_DIR"
echo "# INFINIGEN_PYTHON = $INFINIGEN_PYTHON"
echo "# requirements     = $REQ_FILE"

if [[ "$REMOVE_WRONG_GIN" -eq 1 ]]; then
  # "gin" is a Git index parser on PyPI. Infinigen needs "gin-config", which
  # provides the importable "gin" module used by @gin.configurable.
  run "$INFINIGEN_PYTHON" -m pip uninstall -y gin
fi

echo "# Writing public-only requirements to $PUBLIC_REQ"
if [[ "$DRY_RUN" -eq 0 ]]; then
  grep -v "git+ssh" "$REQ_FILE" > "$PUBLIC_REQ"
else
  echo "+ grep -v \"git+ssh\" \"$REQ_FILE\" > \"$PUBLIC_REQ\""
fi

run "$INFINIGEN_PYTHON" -m pip install -r "$PUBLIC_REQ"

if [[ "$INSTALL_LOCAL" -eq 1 ]]; then
  run "$INFINIGEN_PYTHON" -m pip install -e "$INFINIGEN_DIR" --no-deps
fi

run "$INFINIGEN_PYTHON" - <<'PY'
import cv2
import gin
import trimesh

print("ok: import gin/cv2/trimesh")
print("gin:", gin.__file__)
print("cv2:", cv2.__version__)
print("trimesh:", trimesh.__version__)
PY
