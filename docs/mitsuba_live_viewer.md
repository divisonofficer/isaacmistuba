# Mitsuba Live Viewer

`/live-viewer` remains the browser-side raster free-fly editor. The separate
`/mitsuba-live-viewer` route consumes JPEG frames from an isolated Mitsuba
daemon; it does not submit dataset-render jobs.

## Profiles

| Profile | Launcher | Default GPU | Port | Purpose |
| --- | --- | ---: | ---: | --- |
| Classic, Device 1 / OptiX 8 | `scripts/run_live_viewer_optix8.sh` | 0 | 8766 | Resident `cuda_rgb` reference path |
| Classic, Device 2 / OptiX 7 | `scripts/run_live_viewer_optix7.sh` | 7 | 8766 | Legacy cluster path |
| Frozen, Device 1 / OptiX 8 | `scripts/run_live_viewer_frozen_optix8.sh` | 0 | 8767 | Upstream Dr.Jit `freeze` replay experiment |
| Frozen, Device 2 / OptiX 7 | `scripts/run_live_viewer_frozen_optix7.sh` | 6 | 8767 | Legacy isolated-build path |

Start each launcher on the render host after setting its host-local build path.
The two launchers take a per-GPU lock and refuse to share a GPU. Open
`/mitsuba-live-viewer?backend=classic` or `?backend=frozen`; an explicit
`live_host=host:port` is available when the web UI and render host differ.

## Frozen preflight

The OptiX 8 frozen launcher requires CUDA driver API 12.2
(`cuDriverGetVersion >= 12020`), active Dr.Jit CUDA, `scalar_rgb` and
`cuda_rgb`, OptiX scene initialization, and an upstream `dr.freeze`
record/replay smoke. `cuda_rgb_polarized` adds an allowed-BSDF smoke when that
variant exists, but is not required for the RGB live stream. The launcher logs
build paths and Mitsuba/Dr.Jit revisions before serving frames.

On the current RTX 5090 host, start the existing host-local OptiX 8 build with
`scripts/run_live_viewer_frozen_optix8.sh`. The upstream adapter requires no
private Mitsuba C++ patch and therefore does not require a separate frozen
build. A one-GPU host can run either the Classic or Frozen daemon at once; the
launchers intentionally reject sharing a GPU. Use distinct
`ROBOMITUBA_LIVE_PREVIEW_GPU_INDEX` values on multi-GPU hosts.

The OptiX 7 CUDA-11.8 downlevel script remains only for a separately
documented, unsupported legacy fork and is not invoked by the OptiX 8 build.
