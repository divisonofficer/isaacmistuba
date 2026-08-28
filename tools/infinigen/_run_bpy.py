"""Open a .blend via the `bpy` PyPI module, then exec another script's main().

Usage (under the infinigen conda env which ships the bpy module):

  python tools/infinigen/_run_bpy.py <scene.blend> tools/infinigen/<script>.py -- <args...>

This lets the inspect/export scripts (written to `import bpy` and read the
already-open scene) run without the Blender binary, since the bundled binary's
libs are broken and the file opens fine through the bpy module.
"""

import os
import runpy
import sys
import traceback

import bpy  # type: ignore


def main():
    blend = sys.argv[1]
    script = sys.argv[2]
    # Rebuild sys.argv so the target script sees: [script, <its args after -->]
    rest = sys.argv[3:]
    bpy.ops.wm.open_mainfile(filepath=blend)
    sys.argv = [script] + rest
    runpy.run_path(script, run_name="__main__")


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001
        # The PyPI bpy runtime can segfault while destructing a multi-GB scene
        # after an otherwise ordinary exporter exception. Preserve the real
        # traceback and bypass only interpreter teardown on this failed path.
        traceback.print_exc()
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(1)
