#!/usr/bin/env python3
"""Audit UV/material-slot integrity after OpticalNav render-scene materialization."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from mitsuba_converter.geometry_contract import audit_scene_geometry_contract
from mitsuba_converter.render_daemon import _apply_scene_geometry_overrides


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    scene_dir = args.scene_dir.resolve()
    payload = json.loads((scene_dir / "authoring_map.json").read_text(encoding="utf-8"))
    payload, overrides = _apply_scene_geometry_overrides(payload, scene_dir)
    report = audit_scene_geometry_contract(scene_dir, payload)
    report["geometry_overrides"] = overrides
    out = args.out or scene_dir / "geometry_contract_audit.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(out)
    return 0 if all(row.get("status") == "ok" for row in report["objects"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
