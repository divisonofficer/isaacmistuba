# Render process split

This note documents the development launch commands that separate the UI/control backend from the GPU render queue.

## Backend only

```bash
apps/run_control_backend_dev.sh
```

Defaults:

- URL: `http://127.0.0.1:8765`
- `ROBOMITUBA_BACKEND_ONLY=1`
- render queue and Mitsuba workers are disabled in this process
- `/health` reports `backend_only=true` and `render_queue_enabled=false`

Use this when editing authoring maps, environment maps, render readiness, scene sync metadata, or other control-plane state without letting the backend grab GPUs.

## GPU render queue

```bash
scripts/run_render_queue_optix7.sh
```

Defaults:

- URL: `http://127.0.0.1:8766`
- `ROBOMITUBA_BACKEND_ONLY=0`
- `ROBOMITUBA_RENDER_GPU_INDICES=0,1,2,3`
- `ROBOMITUBA_RENDER_WORKER_COUNT=4`
- `ROBOMITUBA_TEXTURE_MAX_RESOLUTION=1024`
- `ROBOMITUBA_DISABLE_CPU_FALLBACK=1`
- `ROBOMITUBA_RENDER_INPROCESS=0`

Use this as the GPU-owning process. It keeps the OptiX7 worker environment and queue policy together.

To use the render queue as the all-in-one daemon on the old port:

```bash
RENDER_QUEUE_PORT=8765 scripts/run_render_queue_optix7.sh
```

## Compatibility

`apps/run_control_plane_dev.sh` and `scripts/run_daemon_optix7.sh` are intentionally left in place for the current all-in-one flow.

The current split is process-safe but not yet a full remote-queue architecture: the backend-only process blocks local render submissions rather than forwarding them to the queue daemon. The next architectural step is a backend-to-render-queue URL/proxy boundary.
