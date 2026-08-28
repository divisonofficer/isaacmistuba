"""Versioned scene-variation and furnishing-density policy."""
from __future__ import annotations

import hashlib

POLICY_VERSION = "room-content-v1"
SURFACE_CLUTTER = {"low": 8, "balanced": 18, "rich": 28, "storage": 40}
ANCHOR_TO_LEGACY_DENSITY = {"minimal": "model_house", "balanced": "normal_lived_in",
                            "rich": "family_home", "storage": "storage_heavy"}


def effective_scene_seed(logical_seed: str | int, room_type: str, variation_id: int,
                         version: str = POLICY_VERSION) -> int:
    payload = f"{int(logical_seed):08d}|{room_type}|{int(variation_id)}|{version}".encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") % 100_000_000
