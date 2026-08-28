#!/usr/bin/env bash
set -euo pipefail

# Build Device-2 Mitsuba from the NAS source checkout into host-local storage.
# Do not put CMake/Ninja outputs or Python extensions under /jarvis.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${ROBOMITUBA_MITSUBA_BUILD_DIR:-${HOME:-/tmp}/robomituba-build/mitsuba3-optix7}"
PYTHON="${ROBOMITUBA_MITSUBA_PYTHON:-/root/miniconda3/envs/mitsuba_optix7/bin/python}"
NINJA="${CMAKE_MAKE_PROGRAM:-$(command -v ninja)}"
# Keep the legacy variants and add the RGB Stokes transport target required by
# OpticalNav's rgb_stokes_12 contract. Override for smaller diagnostic builds.
MITSUBA_VARIANTS="${ROBOMITUBA_MITSUBA_VARIANTS:-scalar_rgb;scalar_spectral;cuda_ad_rgb;cuda_ad_spectral;cuda_ad_rgb_polarized;cuda_ad_spectral_polarized}"
MITSUBA_ENABLE_EMBREE="${ROBOMITUBA_MITSUBA_ENABLE_EMBREE:-ON}"

# ``mitsuba.conf`` is generated only once by upstream CMake.  Passing a new
# ``-DMI_DEFAULT_VARIANTS`` afterwards has no effect while that file exists,
# which can leave a seemingly successful but stale build without a newly
# requested variant (notably cuda_ad_rgb_polarized for rgb_stokes_12).
config_matches_requested_variants() {
  local config_path="$1"
  "$PYTHON" - "$config_path" "$MITSUBA_VARIANTS" <<'PY'
import re
import sys

path, requested_raw = sys.argv[1:]
requested = [item for item in requested_raw.split(";") if item]
text = open(path, encoding="utf-8").read()
match = re.search(r'"enabled"\s*:\s*\[(.*?)\]', text, flags=re.DOTALL)
if match is None:
    print("[mitsuba-build] existing mitsuba.conf has no enabled-variant list", file=sys.stderr)
    raise SystemExit(1)
enabled = re.findall(r'"([^"]+)"', match.group(1))
if enabled != requested:
    print("[mitsuba-build] configured variants differ", file=sys.stderr)
    print(f"[mitsuba-build]   configured: {';'.join(enabled)}", file=sys.stderr)
    print(f"[mitsuba-build]   requested:  {';'.join(requested)}", file=sys.stderr)
    raise SystemExit(1)
PY
}

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
MITSUBA_CONF="$BUILD_DIR/mitsuba.conf"
if [[ -f "$MITSUBA_CONF" ]] && ! config_matches_requested_variants "$MITSUBA_CONF"; then
  # Preserve any hand-edited configuration for inspection, then remove the
  # generated file so CMake recreates it from MI_DEFAULT_VARIANTS below.
  # A normal CMake reconfigure otherwise deliberately retains this file.
  BACKUP_CONF="$BUILD_DIR/mitsuba.conf.before-variant-refresh"
  cp -f "$MITSUBA_CONF" "$BACKUP_CONF"
  rm -f "$MITSUBA_CONF"
  echo "[mitsuba-build] refreshed stale variant config (backup: $BACKUP_CONF)"
fi

echo "[mitsuba-build] source: $REPO_ROOT/modules/mitsuba3-optix7"
echo "[mitsuba-build] local build: $BUILD_DIR"
echo "[mitsuba-build] Python: $PYTHON"
echo "[mitsuba-build] variants: $MITSUBA_VARIANTS"
echo "[mitsuba-build] Embree: $MITSUBA_ENABLE_EMBREE"

cmake -S "$REPO_ROOT/modules/mitsuba3-optix7" -B "$BUILD_DIR" -G Ninja \
  -DCMAKE_MAKE_PROGRAM="$NINJA" \
  -DPython_EXECUTABLE="$PYTHON" \
  -DPython_ROOT_DIR="$(dirname "$(dirname "$PYTHON")")" \
  -DPYTHON_EXECUTABLE="$PYTHON" \
  -DMI_DEFAULT_VARIANTS="$MITSUBA_VARIANTS" \
  -DMI_ENABLE_EMBREE="$MITSUBA_ENABLE_EMBREE"

cmake --build "$BUILD_DIR" --parallel "${ROBOMITUBA_BUILD_JOBS:-2}"
if [[ ! -s "$DRJIT_EXT" ]]; then
  echo "[mitsuba-build] ERROR: drjit extension missing or empty: $DRJIT_EXT" >&2
  exit 1
fi

export ROBOMITUBA_MITSUBA_BUILD_DIR="$BUILD_DIR"
export ROBOMITUBA_MITSUBA_PYTHONPATH="$BUILD_DIR/python"
PYTHONPATH="$BUILD_DIR/python${PYTHONPATH:+:$PYTHONPATH}" \
  "$PYTHON" - "$MITSUBA_VARIANTS" <<'PY'
import sys
import mitsuba as mi

requested = [item for item in sys.argv[1].split(";") if item]
available = list(mi.variants())
missing = [item for item in requested if item not in available]
print("[mitsuba-build]", mi.__file__)
print("[mitsuba-build] variants:", available)
if missing:
    raise SystemExit(
        "[mitsuba-build] ERROR: requested variants were not built: "
        + "; ".join(missing)
    )
PY

echo "[mitsuba-build] ready: $BUILD_DIR/python"
