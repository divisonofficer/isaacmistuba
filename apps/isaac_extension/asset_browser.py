"""Isaac Content Browser helpers for RoboMitsuba assets."""
from __future__ import annotations

import os
import webbrowser
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    env_root = os.environ.get("ROBOMITUBA_ROOT") or os.environ.get("ROBOMITUBA_WINDOWS_REPO_ROOT")
    if env_root:
        return Path(env_root)
    return Path(__file__).resolve().parents[2]


def robomituba_asset_root(repo_root: str | Path | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else _repo_root()
    return root / "assets" / "isaac_browser"


def ranger_mini_asset_dir(repo_root: str | Path | None = None) -> Path:
    return robomituba_asset_root(repo_root) / "Robots" / "AgileX" / "RangerMini"


def register_robomituba_asset_root(repo_root: str | Path | None = None) -> dict[str, Any]:
    """Best-effort registration of the local RoboMitsuba asset folder.

    Isaac's browser APIs differ across Kit/Isaac releases. This helper tries
    known browser/bookmark hooks and returns a diagnostic payload instead of
    raising, so extension startup remains robust.
    """

    asset_root = robomituba_asset_root(repo_root).resolve()
    result: dict[str, Any] = {
        "asset_root": str(asset_root),
        "exists": asset_root.exists(),
        "registered": False,
        "method": None,
        "error": None,
    }
    if not asset_root.exists():
        result["error"] = "asset root does not exist"
        return result

    # Common Kit browser service patterns. Keep these dynamic because not all
    # Isaac builds ship the same content browser extension.
    attempts = (
        ("omni.kit.browser.core", "get_instance"),
        ("omni.kit.browser.folder.core", "get_instance"),
        ("omni.kit.browser.asset", "get_instance"),
    )
    for module_name, factory_name in attempts:
        try:
            module = __import__(module_name, fromlist=[factory_name])
            factory = getattr(module, factory_name, None)
            browser = factory() if callable(factory) else None
            if browser is None:
                continue
            for method_name in ("add_bookmark", "add_folder", "add_root", "add_location"):
                method = getattr(browser, method_name, None)
                if not callable(method):
                    continue
                try:
                    method("RoboMitsuba", str(asset_root))
                except TypeError:
                    method(str(asset_root))
                result.update({"registered": True, "method": f"{module_name}.{method_name}"})
                return result
        except Exception as exc:
            result["error"] = str(exc)

    return result


def open_ranger_mini_asset_folder(repo_root: str | Path | None = None) -> dict[str, Any]:
    folder = ranger_mini_asset_dir(repo_root).resolve()
    payload = {"asset_dir": str(folder), "exists": folder.exists(), "opened": False}
    if not folder.exists():
        return payload
    try:
        if os.name == "nt":
            os.startfile(str(folder))  # type: ignore[attr-defined]
        else:
            webbrowser.open(folder.as_uri())
        payload["opened"] = True
    except Exception as exc:
        payload["error"] = str(exc)
    return payload
