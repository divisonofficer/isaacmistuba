#!/usr/bin/env bash
# Shared runtime guards for the isolated Mitsuba live-viewer daemons.
# Source this file from a launcher; do not execute it directly.

live_viewer_reserve_gpu() {
  local gpu="$1"
  local label="$2"
  if [[ ! "$gpu" =~ ^[0-9]+$ ]]; then
    echo "[live-viewer] $label requires one numeric GPU index, got '$gpu'" >&2
    return 2
  fi

  local lock="/tmp/robomituba-live-viewer-gpu-${gpu}.lock"
  if [[ -d "$lock" ]]; then
    local owner_pid=""
    if [[ -f "$lock/pid" ]]; then
      owner_pid="$(<"$lock/pid")"
    fi
    if [[ "$owner_pid" =~ ^[0-9]+$ ]] && kill -0 "$owner_pid" 2>/dev/null; then
      echo "[live-viewer] GPU $gpu is already reserved by pid $owner_pid; $label will not share it" >&2
      return 2
    fi
    rm -rf -- "$lock"
  fi
  if ! mkdir "$lock"; then
    echo "[live-viewer] could not reserve GPU $gpu for $label" >&2
    return 2
  fi
  printf '%s\n' "$$" > "$lock/pid"
  export ROBOMITUBA_LIVE_PREVIEW_GPU_LOCK="$lock"
  trap 'rm -rf -- "${ROBOMITUBA_LIVE_PREVIEW_GPU_LOCK:-}"' EXIT INT TERM
}

live_viewer_require_cuda_driver_api() {
  local python_bin="$1"
  local minimum="$2"
  "$python_bin" - "$minimum" <<'PY'
import ctypes
import sys

minimum = int(sys.argv[1])
try:
    cuda = ctypes.CDLL("libcuda.so.1")
    version = ctypes.c_int()
    status = cuda.cuDriverGetVersion(ctypes.byref(version))
except Exception as exc:
    raise SystemExit(f"[live-frozen] cannot query cuDriverGetVersion: {type(exc).__name__}: {exc}")
if status != 0:
    raise SystemExit(f"[live-frozen] cuDriverGetVersion failed with CUDA status {status}")
if version.value < minimum:
    raise SystemExit(
        f"[live-frozen] CUDA driver API {version.value} is below required {minimum}. "
        "This pinned Dr.Jit build embeds CUDA 12.2 PTX; use an R535+ driver."
    )
print(f"[live-frozen] cuDriverGetVersion={version.value} (required>={minimum})")
PY
}

live_viewer_log_git_revision() {
  local label="$1"
  local source_dir="$2"
  if [[ -d "$source_dir/.git" ]] || git -C "$source_dir" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    printf '[live-viewer] %s_revision=%s\n' "$label" "$(git -C "$source_dir" rev-parse HEAD)"
  else
    printf '[live-viewer] %s_revision=unavailable source=%s\n' "$label" "$source_dir"
  fi
}
