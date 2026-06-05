"""Generate Ranger Mini PhysX USD from Isaac's standalone Python.

Run with:
    C:/isaac_sim_win/python.bat C:/isaac_sim_win/extsUser/isaac_extension/snippets/generate_ranger_mini_physx_standalone.py
"""
from isaacsim import SimulationApp

kit = SimulationApp({"headless": True})

import importlib
import importlib.util
import sys
from pathlib import Path

import omni.kit.app

EXT_USER = "C:/isaac_sim_win/extsUser"
if EXT_USER not in sys.path:
    sys.path.insert(0, EXT_USER)

manager = omni.kit.app.get_app().get_extension_manager()
manager.set_extension_enabled_immediate("isaacsim.asset.importer.urdf", True)

stage_module = Path(EXT_USER) / "isaac_extension" / "ranger_mini_stage.py"
spec = importlib.util.spec_from_file_location("ranger_mini_stage_standalone", stage_module)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Could not load {stage_module}")
rms = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rms)
result = rms.import_ranger_mini_urdf_to_physx_asset(repo_root="D:/robomituba_asset_cache")
print(result)

kit.update()
kit.close()
