#!/usr/bin/env python3
"""Apply/resume the Modern Office post-process to an existing Infinigen blend.

Run this only through Blender, normally via ``tools/infinigen/run_bundled_blender.py``.
It exists because Infinigen saves the generated scene before Robomituba's office
style pass; a style-pass exception must not require another multi-hour scene
generation.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import bpy

# Blender does not put the ``--python`` script's directory on sys.path when
# launched through a wrapper executable.  The generator itself runs with the
# repository scripts directory injected by Infinigen, while this standalone
# recovery tool must make that dependency explicit.
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from infinigen_modern_office_style import apply_office_style


def _arguments() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--style", choices=("modern_basic_v1", "modern_glass_v1", "modern_glass_v2"), required=True)
    parser.add_argument(
        "--save-as", type=Path,
        help="optional target blend; defaults to the currently opened blend",
    )
    return parser.parse_args(argv)


def main() -> int:
    args = _arguments()
    manifest = args.manifest.resolve()
    if not manifest.is_file():
        raise FileNotFoundError(f"office layout manifest is absent: {manifest}")
    opened_blend = str(bpy.data.filepath)
    if args.save_as is not None:
        destination = args.save_as.resolve()
    elif opened_blend:
        destination = Path(opened_blend).resolve()
    else:
        raise RuntimeError("no opened blend and no --save-as target")
    result = apply_office_style(manifest, args.style)
    bpy.ops.wm.save_as_mainfile(filepath=str(destination))
    print(
        f"[robomituba] modern office style applied to {destination}: {result}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
