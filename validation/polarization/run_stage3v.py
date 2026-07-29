#!/usr/bin/env python3
"""Run the non-gated Stage 3-V studio material preview standalone, writing
dev_report/images/polar_qualify/stage3v.json (kept separate from the gated
qualification.json so the gate result is never overwritten)."""
from __future__ import annotations
import argparse
import importlib.util as _u
import json
from pathlib import Path

_here = Path(__file__).resolve().parent
_spec = _u.spec_from_file_location("q", str(_here / "qualify.py"))
q = _u.module_from_spec(_spec); _spec.loader.exec_module(q)

ap = argparse.ArgumentParser()
ap.add_argument("--spp", type=int, default=4000)
a = ap.parse_args()

r = q.stage3v_studio(spp=a.spp)
out = q.OUT_DIR / "stage3v.json"
out.write_text(json.dumps({"variant": q.VARIANT, "spp": a.spp, "stage3v": r}, indent=2))
print(f"wrote {out}")
