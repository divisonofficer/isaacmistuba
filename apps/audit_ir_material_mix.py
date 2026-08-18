#!/usr/bin/env python3
"""Write a deterministic final-Principled material-mix audit."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from mitsuba_converter.ir_material_mix import PROFILE, audit_material_mix


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--profile", default=PROFILE)
    args = parser.parse_args()
    result = audit_material_mix(json.loads(args.contract.read_text(encoding="utf-8")), profile=args.profile)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.out.with_suffix(args.out.suffix + ".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(args.out)
    print(json.dumps(result, ensure_ascii=False))
    # This is an audit artifact, not a process failure.  The controller reads
    # ``status`` and can retry a generated variation with a useful reason.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
