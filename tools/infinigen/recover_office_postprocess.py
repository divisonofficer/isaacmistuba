#!/usr/bin/env python3
"""Repair the post-process portion of a saved Office v2 candidate.

Infinigen writes ``scene.blend`` before the repository-owned workstation and
style hooks run.  If one of those hooks fails, this script lets the wizard
reuse the expensive saved scene instead of solving the room again.
It is intended to run inside the bundled Blender process with the scene
already opened via ``--background``.
"""
from __future__ import annotations

import argparse
import sys
import bpy
from pathlib import Path

# Bundled Blender does not automatically add the repository's ``scripts``
# directory to ``sys.path`` when this file is invoked from ``tools/infinigen``.
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
from infinigen_office_workstations import apply_office_workstation_layout
from infinigen_modern_office_style import apply_office_style


def main(argv=None) -> int:
    # Blender keeps script arguments after its ``--`` sentinel in sys.argv.
    # The bundled launcher intentionally forwards that sentinel unchanged.
    if argv is None:
        argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--style", default="modern_glass_v2")
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    layout = apply_office_workstation_layout(args.manifest, args.out)
    style = apply_office_style(args.manifest, args.style)
    scene_path = args.out / "scene.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(scene_path))
    print(
        f"[office-recovery] workstation pairs={len(layout['mappings'])} "
        f"layout_digest={layout['layout_digest']} style={style} scene={scene_path}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
