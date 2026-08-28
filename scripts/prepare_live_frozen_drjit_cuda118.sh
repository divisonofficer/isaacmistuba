#!/usr/bin/env bash
set -euo pipefail

# Downlevel only the Dr.Jit-core builtin CUDA kernels used by the isolated
# frozen-viewer fork. The production Device 2 Mitsuba build is never touched.
: "${ROBOMITUBA_LIVE_FREEZE_SOURCE_DIR:=/root/robomituba-live-freeze/mitsuba3}"
: "${ROBOMITUBA_CUDA118_ROOT:=/usr/local/cuda-11.8}"

core_dir="$ROBOMITUBA_LIVE_FREEZE_SOURCE_DIR/ext/drjit/ext/drjit-core"
resources_dir="$core_dir/resources"
nvcc="$ROBOMITUBA_CUDA118_ROOT/bin/nvcc"

for required in "$nvcc" /usr/bin/gcc-11 "$resources_dir/Makefile" "$resources_dir/kernels.cu"; do
  if [[ ! -e "$required" ]]; then
    echo "[live-frozen-cuda118] required path is missing: $required" >&2
    exit 2
  fi
done

cuda_version="$($nvcc --version | rg -o 'release [0-9]+\.[0-9]+' | head -1 || true)"
if [[ "$cuda_version" != "release 11.8" ]]; then
  echo "[live-frozen-cuda118] expected CUDA 11.8 nvcc, got: ${cuda_version:-unknown}" >&2
  exit 2
fi

make -C "$resources_dir" kernels_75.lz4

ptx="$resources_dir/kernels_75.ptx"
if ! rg -q '^\.version 7\.' "$ptx" || ! rg -q '^\.target sm_75$' "$ptx"; then
  echo "[live-frozen-cuda118] unexpected PTX target:" >&2
  sed -n '1,16p' "$ptx" >&2
  exit 2
fi

patch_dir="${ROBOMITUBA_LIVE_FREEZE_PATCH_DIR:-/root/robomituba-live-freeze/patches}"
mkdir -p "$patch_dir"
git -C "$core_dir" diff -- resources/Makefile src/cuda_core.cpp \
  > "$patch_dir/drjit-core-cuda118-compute75.patch"

echo "[live-frozen-cuda118] nvcc=$nvcc"
echo "[live-frozen-cuda118] $(rg '^\.version|^\.target' "$ptx" | tr '\n' ' ')"
echo "[live-frozen-cuda118] patch=$patch_dir/drjit-core-cuda118-compute75.patch"
