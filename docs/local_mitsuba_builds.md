# Host-local Mitsuba builds

The repository source is shared through `/jarvis` (NAS), but Mitsuba and Dr.Jit
binaries are ABI- and GPU-specific. Never configure CMake or write Python
extensions below `/jarvis/project/robomituba/build`.

## Device 2 (OptiX 7)

The default local output is:

```text
$HOME/robomituba-build/mitsuba3-optix7
```

Configure and build from the NAS source checkout with:

```bash
ROBOMITUBA_BUILD_JOBS=2 scripts/build_mitsuba_optix7_local.sh
```

The script selects the `mitsuba_optix7` Python environment, uses the local
Ninja/CMake tree, serializes same-host builds with `.build.lock`, removes
truncated extensions, and verifies the compiled variants before returning.

Override the location explicitly when a host has a dedicated local SSD:

```bash
ROBOMITUBA_MITSUBA_BUILD_DIR=/local/ssd/robomituba/mitsuba3-optix7 \
  scripts/build_mitsuba_optix7_local.sh
```

## Render launchers

`scripts/run_daemon_optix7.sh`,
`scripts/run_render_queue_optix7.sh`, and
`apps/run_control_plane_dev.sh` use the host-local path by default.
`ROBOMITUBA_MITSUBA_BUILD_DIR` and `ROBOMITUBA_MITSUBA_PYTHONPATH` remain
explicit overrides for unusual installations. Device 1 and Device 2 also have
separate `ROBOMITUBA_DEVICE1_MITSUBA_BUILD_DIR` and
`ROBOMITUBA_DEVICE2_MITSUBA_BUILD_DIR` defaults.

A daemon startup log prints the selected build path. A worker must import
Mitsuba from that path before accepting render work.
