"""user_settings.py — Per-machine user preferences for the daemon.

Reads / writes ``~/.robomituba/settings.json``. Currently holds dataset
storage path overrides so large datasets (e.g. hpBRDF, 182 GB) can land on
a different mount than the repo (e.g. /mnt/d on WSL2 setups where the
repo lives on the C: drive).

Schema::

    {
      "dataset_storage_overrides": {
        "<dataset_id>": "/absolute/path/to/dataset_root"
      }
    }
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

_SETTINGS_LOCK = threading.Lock()


def settings_path() -> Path:
    """Location of the user settings JSON. Honors ROBOMITUBA_SETTINGS env var."""
    override = os.environ.get("ROBOMITUBA_SETTINGS")
    if override:
        return Path(override)
    return Path.home() / ".robomituba" / "settings.json"


def load_user_settings() -> dict[str, Any]:
    p = settings_path()
    if not p.exists():
        return {}
    try:
        with _SETTINGS_LOCK:
            return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_user_settings(data: dict[str, Any]) -> None:
    p = settings_path()
    with _SETTINGS_LOCK:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)


def get_dataset_storage_override(dataset_id: str) -> str | None:
    """Return the absolute override path for ``dataset_id``, or None."""
    settings = load_user_settings()
    overrides = settings.get("dataset_storage_overrides") or {}
    val = overrides.get(dataset_id)
    if isinstance(val, str) and val.strip():
        return val.strip()
    return None


# Sensible bounds — below 16 spp the noise is unusable; above 16384 a
# preview takes minutes per material on a fast GPU.
MIN_PREVIEW_SPP = 16
MAX_PREVIEW_SPP = 16384


def get_material_preview_spp(default: int = 2048) -> int:
    """Return the user-configured spp for material previews (curated +
    measured). Falls back to ``default`` when unset or out of bounds."""
    settings = load_user_settings()
    val = settings.get("material_preview_spp")
    if isinstance(val, bool):
        return default
    if isinstance(val, (int, float)):
        n = int(val)
        if MIN_PREVIEW_SPP <= n <= MAX_PREVIEW_SPP:
            return n
    return default


def resolve_dataset_path(
    repo_root: Path,
    dataset_id: str,
    native_file: str,
    dataset_local_root: str | None = None,
) -> Path:
    """Resolve where a dataset file actually lives on disk.

    Without an override, returns ``repo_root / native_file`` (legacy behavior).

    With an override, the dataset's ``local_root`` (e.g. ``data/hpbrdf_2025``)
    in ``native_file`` gets replaced by the override path. The subpath after
    ``local_root`` is preserved so dataset structure stays intact::

        native_file:           data/hpbrdf_2025/raw/Aluminum.hpbrdf
        local_root:            data/hpbrdf_2025
        override:              /mnt/d/hpbrdf
        →                       /mnt/d/hpbrdf/raw/Aluminum.hpbrdf
    """
    if not native_file:
        return repo_root / native_file
    override = get_dataset_storage_override(dataset_id)
    if not override:
        return repo_root / native_file
    override_root = Path(override).expanduser()
    if dataset_local_root:
        try:
            relative = Path(native_file).relative_to(dataset_local_root)
            return override_root / relative
        except ValueError:
            pass
    return override_root / Path(native_file).name
