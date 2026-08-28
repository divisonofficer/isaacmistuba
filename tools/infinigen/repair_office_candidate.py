#!/usr/bin/env python3
"""Repair an existing generated Office v2 blend in-place via a new file.

This script runs inside the repository's bundled Blender.  It intentionally
never overwrites the input blend: the caller passes ``--save-path`` and
atomically promotes that file only after Blender exits successfully.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))


def _layout_is_valid(path: Path) -> bool:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return value.get("status") == "passed" and bool(value.get("layout_digest")) and bool(value.get("mappings"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-folder", type=Path, required=True)
    parser.add_argument("--style", choices=("modern_glass_v2", "modern_glass_v1"), required=True)
    parser.add_argument("--save-path", type=Path, required=True)
    # Blender keeps its own command-line options in ``sys.argv`` and places
    # arguments intended for the Python script after a standalone ``--``.
    # Parsing the full argv made the repair command report all required
    # options as missing even though the launcher supplied them.
    if argv is None:
        raw = sys.argv
        argv = raw[raw.index("--") + 1:] if "--" in raw else []
    args = parser.parse_args(argv)

    manifest = args.manifest.resolve()
    output_folder = args.output_folder.resolve()
    save_path = args.save_path.resolve()
    if not manifest.is_file():
        raise FileNotFoundError(f"office layout manifest is missing: {manifest}")
    if bpy.context.scene is None:
        raise RuntimeError("Blender scene is not loaded")

    layout_path = output_folder / "workstation_layout.json"
    # Re-run the idempotent post-process even when an older layout marker says
    # ``passed``. Older candidates may predate focus-office quota repair, so
    # merely reusing their marker would let the population audit fail on a
    # missing desk/chair/monitor. The post-process keeps stable mappings and
    # only adds/removes deterministic derived assets when needed.
    from infinigen_office_workstations import apply_office_workstation_layout

    had_valid_layout = _layout_is_valid(layout_path)
    result = apply_office_workstation_layout(manifest, output_folder)
    print(
        f"[office-repair] workstation layout {'revalidated' if had_valid_layout else 'repaired'} "
        f"pairs={len(result.get('mappings') or [])} "
        f"focus_assets={len(result.get('generated_focus_assets') or [])} "
        f"digest={result.get('layout_digest')}", flush=True,
    )

    # A passed layout can predate the strict outside-room gate.  Run the
    # idempotent cleanup on every repair path, including layout reuse, before
    # applying style and saving the derived blend.
    from infinigen_office_workstations import cleanup_unassigned_primary_assets
    removed = cleanup_unassigned_primary_assets(manifest)
    if removed:
        print(f"[office-repair] removed unassigned primary assets count={len(removed)}", flush=True)

    from infinigen_modern_office_style import apply_office_style

    result = apply_office_style(manifest, args.style)
    print(f"[office-repair] office style verified: {result}", flush=True)
    save_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(save_path))
    print(f"[office-repair] saved repaired blend: {save_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
