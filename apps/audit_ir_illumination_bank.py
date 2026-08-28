#!/usr/bin/env python3
from __future__ import annotations
import argparse
import sys
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parents[1]
for source in (REPO_ROOT / "modules" / "mitsuba_converter" / "src", REPO_ROOT / "modules" / "robomituba_bridge" / "src"):
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))
from mitsuba_converter.ir_illumination import audit_bank

parser = argparse.ArgumentParser()
parser.add_argument("--out", type=Path, required=True)
parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
args = parser.parse_args()
result = audit_bank(args.repo_root.resolve(), args.out.resolve())
print(f"[ir-lighting] verified {len(result['assets'])} HDRIs / {len(result['conditions'])} conditions digest={result['manifest_digest'][:16]}")
