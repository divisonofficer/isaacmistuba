"""Robomituba Isaac Extension — omni.ext entry point.

Register via Isaac Sim's extension manager or add the apps/
directory to the extension search paths in kit configuration.

Extension ID: robomituba.isaac_extension
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure apps/ sibling packages are importable inside Isaac Sim
_APPS_DIR = Path(__file__).resolve().parent.parent
if str(_APPS_DIR) not in sys.path:
    sys.path.insert(0, str(_APPS_DIR))

try:
    import omni.ext  # type: ignore
    _OMNI_AVAILABLE = True
except ImportError:
    _OMNI_AVAILABLE = False


if _OMNI_AVAILABLE:
    class RobomitubaIsaacExtension(omni.ext.IExt):
        """Robomituba render integration for Isaac Sim.

        Adds a UI panel that captures the live stage state and sends it
        to the Mitsuba render daemon for high-quality sensor rendering.
        """

        def on_startup(self, ext_id: str) -> None:  # noqa: N802
            try:
                from isaac_extension.ui_panel import RobomitubaPanel
            except ImportError:  # pragma: no cover - Isaac runtime fallback
                from ui_panel import RobomitubaPanel
            self._panel = RobomitubaPanel()

        def on_shutdown(self) -> None:  # noqa: N802
            if hasattr(self, "_panel") and self._panel is not None:
                self._panel.destroy()
                self._panel = None
else:
    # Stub for import outside Isaac Sim (e.g. unit tests)
    class RobomitubaIsaacExtension:  # type: ignore[no-redef]
        """Stub used outside Isaac Sim."""

        def on_startup(self, ext_id: str) -> None:
            pass

        def on_shutdown(self) -> None:
            pass
