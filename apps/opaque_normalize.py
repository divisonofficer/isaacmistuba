#!/usr/bin/env python3
"""Resolve glass/mirror material slots of an imported Infinigen scene to opaque
substitutions (Stage 1 of the inverse-rendering dataset MODE — pure data, no render).

Reads the Infinigen ``scene_manifest.json`` + ``configs/datasets/
opaque_substitution_rules.json`` and writes ``opaque_substitutions.json`` next to the
manifest (the authoritative per-(unit,slot,material) substitution record).

    python apps/opaque_normalize.py \
        --manifest out/infinigen_imports/kr_20260730_single_room_kitchen/scene_manifest.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for _m in ("robomituba_bridge", "mitsuba_converter"):
    sys.path.insert(0, str(REPO / "modules" / _m / "src"))

from mitsuba_converter.opaque_normalize import build_substitutions, load_rules  # noqa: E402

DEFAULT_RULES = REPO / "configs/datasets/opaque_substitution_rules.json"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manifest", required=True, help="Infinigen scene_manifest.json path")
    ap.add_argument("--rules", default=str(DEFAULT_RULES), help="substitution rules JSON")
    ap.add_argument("--out", default=None, help="output path (default: opaque_substitutions.json beside manifest)")
    a = ap.parse_args()

    manifest_path = Path(a.manifest)
    manifest = json.loads(manifest_path.read_text())
    rules = load_rules(a.rules)
    doc = build_substitutions(manifest, rules)

    out = Path(a.out) if a.out else manifest_path.parent / "opaque_substitutions.json"
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2))

    print(f"[opaque] scene={doc['scene_id']} · {doc['substitution_count']} slots substituted "
          f"(near-delta floored {doc['near_delta_floored']})")
    print(f"[opaque] by factory: {json.dumps(doc['by_factory'], ensure_ascii=False)}")
    print(f"[opaque] by semantic: {json.dumps(doc['by_semantic'], ensure_ascii=False)}")
    print(f"[opaque] wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
