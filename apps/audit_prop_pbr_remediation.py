#!/usr/bin/env python3
"""Audit a prepared IR scene for small-prop PBR remediation candidates."""
from __future__ import annotations
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "modules" / "navigation_dataset" / "src"))
from navigation_dataset.ir_prop_pbr import canonical_digest, prop_eligibility

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--contract", type=Path, required=True)
    p.add_argument("--dataset", type=Path, help="optional rendered child/parent root for visible-pixel counts")
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    contract = json.loads(a.contract.read_text(encoding="utf-8"))
    visible = Counter()
    if a.dataset and (a.dataset / "index.jsonl").is_file():
        for line in (a.dataset / "index.jsonl").read_text(encoding="utf-8").splitlines():
            row = json.loads(line); rel = (row.get("paths") or {}).get("material_id")
            if rel:
                image = cv2.imread(str(a.dataset / rel), cv2.IMREAD_UNCHANGED)
                if image is not None:
                    for value, count in zip(*np.unique(image, return_counts=True)): visible[int(value)] += int(count)
    rows = []
    for record in contract.get("materials") or []:
        unit = {"id": record.get("object_id"), "blender_name": record.get("blender_name"), "kind": record.get("kind")}
        eligibility = prop_eligibility(unit, str(record.get("source_material") or ""), str(record.get("semantic_class") or "none"))
        source_valid = bool(record.get("source_valid"))
        if source_valid: action = "retain_source_authored"
        elif eligibility["eligible"]: action = "curated_remediate"
        else: action = "exclude_or_surrogate"
        rows.append({"material_id": record.get("material_id"), "object_id": record.get("object_id"),
                     "source_material": record.get("source_material"), "source_valid": source_valid,
                     "fallback_channels": record.get("fallback_channels") or [], "replacement_reasons": record.get("replacement_reasons") or [],
                     "eligibility": eligibility, "recommended_action": action,
                     "visible_pixels": int(visible.get(int(record.get("material_id") or -1), 0))})
    payload = {"schema": "robomituba.ir_prop_pbr_remediation_audit.v1", "contract": str(a.contract),
               "dataset": str(a.dataset) if a.dataset else None, "records": rows,
               "counts": dict(Counter(row["recommended_action"] for row in rows))}
    payload["audit_digest"] = canonical_digest(payload)
    a.out.parent.mkdir(parents=True, exist_ok=True); a.out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({"out": str(a.out), "counts": payload["counts"], "audit_digest": payload["audit_digest"]}))
    return 0
if __name__ == "__main__": raise SystemExit(main())
