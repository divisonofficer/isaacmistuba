#!/usr/bin/env bash
set -euo pipefail

# Build Device-2 Mitsuba from the NAS source checkout into host-local storage.
# Do not put CMake/Ninja outputs or Python extensions under /jarvis.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${ROBOMITUBA_MITSUBA_BUILD_DIR:-${HOME:-/tmp}/robomituba-build/mitsuba3-optix7}"
PYTHON="${ROBOMITUBA_MITSUBA_PYTHON:-/root/miniconda3/envs/mitsuba_optix7/bin/python}"
NINJA="${CMAKE_MAKE_PROGRAM:-$(command -v ninja)}"

if [[ ! -x "$PYTHON" ]]; then
  echo "[mitsuba-build] Python not found: $PYTHON" >&2
  exit 1
fi
if [[ ! -x "$NINJA" ]]; then
  echo "[mitsuba-build] Ninja not found: $NINJA" >&2
  exit 1
fi

case "$BUILD_DIR" in
  /jarvis/*)
    echo "[mitsuba-build] ERROR: build output must be host-local, got $BUILD_DIR" >&2
    exit 2
    ;;
esac

mkdir -p "$BUILD_DIR"
# A second shell on the same host must not configure/build this directory in
# parallel. The lock itself is local alongside the build artifacts.
exec 9>"$BUILD_DIR/.build.lock"
flock 9

DRJIT_EXT="$BUILD_DIR/python/drjit/drjit_ext.cpython-310-x86_64-linux-gnu.so"
if [[ -e "$DRJIT_EXT" && ! -s "$DRJIT_EXT" ]]; then
  echo "[mitsuba-build] removing truncated extension: $DRJIT_EXT"
  rm -f "$DRJIT_EXT"
fi
if [[ -f "$BUILD_DIR/mitsuba.conf" ]] && grep -q 'scalar_rgb,scalar_spectral' "$BUILD_DIR/mitsuba.conf"; then
  echo "[mitsuba-build] removing stale comma-separated mitsuba.conf"
  rm -f "$BUILD_DIR/mitsuba.conf"
fi

echo "[mitsuba-build] source: $REPO_ROOT/modules/mitsuba3-optix7"
echo "[mitsuba-build] local build: $BUILD_DIR"
echo "[mitsuba-build] Python: $PYTHON"

cmake -S "$REPO_ROOT/modules/mitsuba3-optix7" -B "$BUILD_DIR" -G Ninja \
  -DCMAKE_MAKE_PROGRAM="$NINJA" \
  -DPython_EXECUTABLE="$PYTHON" \
  -DPython_ROOT_DIR="$(dirname "$(dirname "$PYTHON")")" \
  -DPYTHON_EXECUTABLE="$PYTHON" \
  -DMI_DEFAULT_VARIANTS="scalar_rgb;scalar_spectral;cuda_ad_rgb;cuda_ad_spectral;cuda_ad_spectral_polarized"

cmake --build "$BUILD_DIR" --parallel "${ROBOMITUBA_BUILD_JOBS:-2}"
if [[ ! -s "$DRJIT_EXT" ]]; then
  echo "[mitsuba-build] ERROR: drjit extension missing or empty: $DRJIT_EXT" >&2
  exit 1
fi

export ROBOMITUBA_MITSUBA_BUILD_DIR="$BUILD_DIR"
export ROBOMITUBA_MITSUBA_PYTHONPATH="$BUILD_DIR/python"
PYTHONPATH="$BUILD_DIR/python${PYTHONPATH:+:$PYTHONPATH}" \
  "$PYTHON" -c 'import mitsuba as mi; print("[mitsuba-build]", mi.__file__); print("[mitsuba-build] variants:", mi.variants())'

echo "[mitsuba-build] ready: $BUILD_DIR/python"
