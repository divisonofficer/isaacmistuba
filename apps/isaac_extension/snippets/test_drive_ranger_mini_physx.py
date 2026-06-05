"""Run inside Isaac Sim Script Editor after dragging RangerMiniPhysX.usda into an empty stage."""
import importlib

import omni.kit.app
import omni.timeline
import omni.usd
from pxr import Gf, PhysicsSchemaTools, Sdf, UsdPhysics

import isaac_extension.ranger_mini_stage as rms

rms = importlib.reload(rms)
stage = omni.usd.get_context().get_stage()

if not stage.GetPrimAtPath("/World/PhysicsScene").IsValid():
    scene = UsdPhysics.Scene.Define(stage, Sdf.Path("/World/PhysicsScene"))
    scene.CreateGravityDirectionAttr().Set(Gf.Vec3f(0.0, 0.0, -1.0))
    scene.CreateGravityMagnitudeAttr().Set(9.81)

if not stage.GetPrimAtPath("/World/RangerMiniFlatGround").IsValid():
    PhysicsSchemaTools.addGroundPlane(
        stage,
        "/World/RangerMiniFlatGround",
        "Z",
        20.0,
        Gf.Vec3f(0.0, 0.0, 0.0),
        Gf.Vec3f(0.5, 0.5, 0.5),
    )

print(rms.validate_ranger_mini_physx(stage, "/World"))

timeline = omni.timeline.get_timeline_interface()
timeline.play()
app = omni.kit.app.get_app()
for _ in range(5):
    app.update()

handle = rms.bind_ranger_mini_articulation(stage, "/World")
for _ in range(120):
    rms.drive_ranger_mini_cmd_vel(
        stage,
        "/World",
        linear_x=0.5,
        angular_z=0.0,
        articulation_handle=handle,
    )
    app.update()

print("Ranger Mini PhysX forward test command applied for 120 frames.")
