"""Run inside Isaac Sim Script Editor to generate the Ranger Mini PhysX USD."""
import importlib

import isaac_extension.ranger_mini_stage as rms

rms = importlib.reload(rms)

result = rms.import_ranger_mini_urdf_to_physx_asset(
    repo_root="D:/robomituba_asset_cache",
)
print(result)

print("Next: drag RangerMiniPhysX.usda into an empty stage, press Play, then run:")
print(
    'import omni.usd, isaac_extension.ranger_mini_stage as rms\n'
    'stage = omni.usd.get_context().get_stage()\n'
    'print(rms.validate_ranger_mini_physx(stage, "/World"))\n'
    'handle = rms.bind_ranger_mini_articulation(stage, "/World")\n'
    'rms.drive_ranger_mini_cmd_vel(stage, "/World", linear_x=0.5, angular_z=0.0, articulation_handle=handle)'
)
