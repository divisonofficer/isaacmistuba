#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from mitsuba_converter.ir_scene_content import audit_scene_content


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate generated scene content against a room program")
    parser.add_argument("--authoring-map", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--room-type", required=True)
    parser.add_argument("--profile", choices=("balanced", "anchor_rich", "structural", "research_balanced"), default="balanced")
    parser.add_argument("--source-blend", type=Path)
    parser.add_argument("--registry-root", type=Path, action="append", default=[])
    args = parser.parse_args()
    digest = None
    if args.source_blend:
        hasher = hashlib.sha256()
        with args.source_blend.open("rb") as stream:
            for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
                hasher.update(chunk)
        digest = hasher.hexdigest()
    result = audit_scene_content(json.loads(args.authoring_map.read_text(encoding="utf-8")), room_type=args.room_type,
                                 profile=args.profile, source_scene_digest=digest)
    duplicates = []
    registry_paths = []
    for root in args.registry_root:
        if root.is_dir():
            registry_paths.extend(root.glob("*/scene_content_audit.json"))
            registry_paths.extend(root.glob("*/quality/scene_content_audit.json"))
    if digest:
        for path in registry_paths:
            if path.resolve() == args.out.resolve():
                continue
            try:
                previous = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if previous.get("status") == "passed" and previous.get("source_scene_digest") == digest:
                duplicates.append(path.parent.name)
    if duplicates:
        result["duplicate_source_datasets"] = sorted(duplicates)
        result["failures"].append("duplicate_source_scene")
        result["status"] = "failed"
    digest_payload = {key: value for key, value in result.items() if key != "audit_digest"}
    result["audit_digest"] = hashlib.sha256(json.dumps(digest_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.out.with_suffix(args.out.suffix + ".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(args.out)
    print(json.dumps(result, ensure_ascii=False))
    # Keep a failed audit inspectable; the controller decides whether this is a
    # hard failure or a deterministic new-variation retry.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
