"""Per-scene material-override sidecar.

Persists agent-driven (or UI-driven) BRDF overrides to a JSON file next to
the Mitsuba scene XML so they survive daemon restarts and are available even
when no live Isaac session is open. The sidecar is loaded into a
``SceneOverrideSpec`` at render time via :func:`merge_into_spec`.

File layout::

    <xml_dir>/<xml_stem>.material_overrides.json
    {
      "schema": "robomituba.material_overrides.v1",
      "scene_id": "moorelane",
      "mitsuba_scene_ref": "out/.../scene_curated_shell_furniture_sanitized.xml",
      "updated_at": "2026-04-27T08:40:00+00:00",
      "overrides": {
        "/xml/shape_0012": {
          "bsdf_type": "curated",
          "material_id": "aluminum",
          "tier": 3,
          "rationale": "RoofSheetMetal — no Al in tier 1/2",
          "source": "agent_v1",
          "extras": {"curated_bsdf_spec": {...}, ...},
          "updated_at": "2026-04-27T08:40:00+00:00"
        },
        ...
      }
    }
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from robomituba_bridge import (
    BsdfOverride,
    SceneOverrideSpec,
    resolve_repo_path,
    to_repo_relative_posix,
)


SCHEMA_VERSION = "robomituba.material_overrides.v1"


@dataclass
class StoredOverride:
    """A single per-prim override entry written to the sidecar."""

    prim_path: str
    bsdf_type: str
    dataset_id: str | None = None
    material_id: str | None = None
    measured_file_path: str | None = None
    base_color: list[float] | None = None
    roughness: float | None = None
    metallic: float | None = None
    ior: float | None = None
    material: str | None = None  # conductor name ("Al", "Cu", ...)
    tier: int | None = None
    rationale: str | None = None
    source: str = "agent_v1"
    updated_at: str = ""
    extras: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        # prim_path is the dict key in the sidecar — drop it from value to avoid
        # duplication and the chance of disagreement.
        payload.pop("prim_path", None)
        return {k: v for k, v in payload.items() if v not in (None, "", [], {})}

    @classmethod
    def from_payload(cls, prim_path: str, payload: Mapping[str, Any]) -> "StoredOverride":
        return cls(
            prim_path=prim_path,
            bsdf_type=str(payload.get("bsdf_type") or ""),
            dataset_id=payload.get("dataset_id"),
            material_id=payload.get("material_id"),
            measured_file_path=payload.get("measured_file_path"),
            base_color=list(payload["base_color"]) if payload.get("base_color") else None,
            roughness=payload.get("roughness"),
            metallic=payload.get("metallic"),
            ior=payload.get("ior"),
            material=payload.get("material"),
            tier=payload.get("tier"),
            rationale=payload.get("rationale"),
            source=str(payload.get("source") or "unknown"),
            updated_at=str(payload.get("updated_at") or ""),
            extras=dict(payload.get("extras") or {}),
        )

    def to_bsdf_override(self) -> BsdfOverride:
        return BsdfOverride(
            bsdf_type=self.bsdf_type,
            base_color=list(self.base_color) if self.base_color else None,
            roughness=self.roughness,
            metallic=self.metallic,
            ior=self.ior,
            material=self.material,
            measured_file_path=self.measured_file_path,
            dataset_id=self.dataset_id,
            material_id=self.material_id,
            extras=dict(self.extras or {}),
        )


def overrides_path_for_scene(repo_root: str | Path, mitsuba_scene_ref: str) -> Path:
    """Return the absolute sidecar path for a scene's Mitsuba XML ref."""
    xml_path = resolve_repo_path(repo_root, mitsuba_scene_ref)
    return xml_path.with_name(f"{xml_path.stem}.material_overrides.json")


def overrides_ref_for_scene(repo_root: str | Path, mitsuba_scene_ref: str) -> str:
    """Return the repo-relative POSIX path for the sidecar (for catalog refs)."""
    return to_repo_relative_posix(repo_root, overrides_path_for_scene(repo_root, mitsuba_scene_ref))


def load_overrides(
    repo_root: str | Path,
    mitsuba_scene_ref: str,
) -> dict[str, StoredOverride]:
    """Load the sidecar for a scene; returns ``{}`` when the file is missing."""
    path = overrides_path_for_scene(repo_root, mitsuba_scene_ref)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    raw = payload.get("overrides")
    if not isinstance(raw, Mapping):
        return {}
    out: dict[str, StoredOverride] = {}
    for prim_path, entry in raw.items():
        if not isinstance(entry, Mapping):
            continue
        prim_path_s = str(prim_path)
        if not prim_path_s:
            continue
        out[prim_path_s] = StoredOverride.from_payload(prim_path_s, entry)
    return out


def save_overrides(
    repo_root: str | Path,
    mitsuba_scene_ref: str,
    overrides: Mapping[str, StoredOverride],
    *,
    scene_id: str | None = None,
) -> Path:
    """Write the sidecar to disk; returns the absolute path written."""
    path = overrides_path_for_scene(repo_root, mitsuba_scene_ref)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "scene_id": scene_id or "",
        "mitsuba_scene_ref": mitsuba_scene_ref,
        "updated_at": _utc_now_iso(),
        "overrides": {
            prim_path: stored.to_payload()
            for prim_path, stored in overrides.items()
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def merge_overrides(
    existing: Mapping[str, StoredOverride],
    incoming: Iterable[StoredOverride],
) -> dict[str, StoredOverride]:
    """Last-write-wins overlay: incoming entries replace existing ones per prim."""
    merged: dict[str, StoredOverride] = dict(existing)
    for stored in incoming:
        if not stored.updated_at:
            stored.updated_at = _utc_now_iso()
        merged[stored.prim_path] = stored
    return merged


def merge_into_spec(
    spec: SceneOverrideSpec,
    stored: Mapping[str, StoredOverride],
    *,
    prefer_sidecar: bool = True,
) -> SceneOverrideSpec:
    """Layer sidecar entries onto an existing ``SceneOverrideSpec``.

    ``prefer_sidecar=True`` (the default) means the persisted sidecar wins for
    prims it covers — matches the agent's intent that explicit on-disk picks
    override anything coming from a stale Isaac session. Set to ``False`` to
    use sidecar entries only as a fallback for prims the spec hasn't covered.
    """
    if not stored:
        return spec
    bsdf_overrides = dict(spec.bsdf_overrides or {})
    for prim_path, entry in stored.items():
        if not prefer_sidecar and prim_path in bsdf_overrides:
            continue
        bsdf_overrides[prim_path] = entry.to_bsdf_override()
    spec.bsdf_overrides = bsdf_overrides
    return spec


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
