"""Helpers for spawning and controlling Ranger Mini robots from the Isaac panel."""
from __future__ import annotations

from pathlib import Path
from typing import Any

_APPS_DIR = Path(__file__).resolve().parent.parent

PHYSX_ASSET_REL_PATH = "assets/robots/ranger_mini_v3/isaac_physx/ranger_mini_v3_physx.usd"
ISAAC_URDF_REL_PATH = "assets/robots/ranger_mini_v3/isaac_urdf/ranger_mini_v3.urdf"
VISUAL_ONLY_PHYSICS_STATUS = "visual_only_use_isaac_urdf_importer"
RANGER_MINI_PHYSX_JOINTS = (
    "fr_steering_joint",
    "fl_steering_joint",
    "rr_steering_joint",
    "rl_steering_joint",
    "fr_wheel",
    "fl_wheel",
    "rr_wheel",
    "rl_wheel",
)
RANGER_MINI_STEERING_JOINTS = RANGER_MINI_PHYSX_JOINTS[:4]
RANGER_MINI_WHEEL_JOINTS = RANGER_MINI_PHYSX_JOINTS[4:]


def _log_debug(message: str) -> None:
    line = f"[RangerMiniStage] {message}"
    try:
        import carb  # type: ignore

        carb.log_info(line)
    except Exception:
        pass
    print(line)


def _require_pxr():
    from pxr import Gf, Sdf, Usd, UsdGeom  # type: ignore

    return Gf, Sdf, Usd, UsdGeom


class _FallbackArticulationAction:
    def __init__(self, *, joint_positions: Any = None, joint_velocities: Any = None, joint_indices: Any = None) -> None:
        self.joint_positions = joint_positions
        self.joint_velocities = joint_velocities
        self.joint_indices = joint_indices


def _attr_value(prim: Any, name: str, default: Any = None) -> Any:
    attr = prim.GetAttribute(name)
    if not attr:
        return default
    value = attr.Get()
    return default if value is None else value


def _repo_root() -> Path:
    import os

    for env_name in ("ROBOMITUBA_LOCAL_REPO_ROOT", "ROBOMITUBA_ROOT", "ROBOMITUBA_WINDOWS_REPO_ROOT"):
        value = os.environ.get(env_name)
        if value:
            return Path(value)
    return Path(__file__).resolve().parents[2]


def ranger_mini_physx_asset_status(repo_root: str | Path | None = None) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else _repo_root()
    path = root / PHYSX_ASSET_REL_PATH
    return {
        "asset_path": str(path),
        "asset_rel_path": PHYSX_ASSET_REL_PATH,
        "exists": path.exists(),
        "manual_import_required": not path.exists(),
    }


def require_ranger_mini_physx_asset(repo_root: str | Path | None = None) -> Path:
    status = ranger_mini_physx_asset_status(repo_root)
    path = Path(str(status["asset_path"]))
    if not status["exists"]:
        raise RuntimeError(
            "Missing Ranger Mini PhysX USD. Import "
            "assets/robots/ranger_mini_v3/isaac_urdf/ranger_mini_v3.urdf with Isaac URDF Importer "
            f"and save the generated articulation USD to {PHYSX_ASSET_REL_PATH}."
        )
    return path


def _set_import_config_value(config: Any, name: str, value: Any) -> None:
    setter = getattr(config, f"set_{name}", None)
    if callable(setter):
        setter(value)
        return
    setattr(config, name, value)


def import_ranger_mini_urdf_to_physx_asset(
    repo_root: str | Path | None = None,
    *,
    urdf_path: str | Path | None = None,
    dest_path: str | Path | None = None,
) -> dict[str, Any]:
    """Create the Ranger Mini PhysX USD through Isaac's URDF importer.

    This must run inside Isaac Sim with the `isaacsim.asset.importer.urdf` extension enabled.
    It is intentionally a one-shot asset generation helper, not a runtime visual-to-physics converter.
    """
    root = Path(repo_root) if repo_root is not None else _repo_root()
    urdf = Path(urdf_path) if urdf_path is not None else root / ISAAC_URDF_REL_PATH
    dest = Path(dest_path) if dest_path is not None else root / PHYSX_ASSET_REL_PATH
    if not urdf.exists():
        raise RuntimeError(f"Missing Ranger Mini Isaac URDF package: {urdf}")
    dest.parent.mkdir(parents=True, exist_ok=True)

    try:
        import omni.kit.commands  # type: ignore
    except Exception as exc:
        raise RuntimeError(f"Isaac URDF importer commands are unavailable: {exc}") from exc

    status, import_config = omni.kit.commands.execute("URDFCreateImportConfig")
    if not status:
        raise RuntimeError("URDFCreateImportConfig failed.")

    _set_import_config_value(import_config, "merge_fixed_joints", False)
    _set_import_config_value(import_config, "fix_base", False)
    _set_import_config_value(import_config, "self_collision", False)
    _set_import_config_value(import_config, "convex_decomp", False)
    _set_import_config_value(import_config, "replace_cylinders_with_capsules", False)
    _set_import_config_value(import_config, "import_inertia_tensor", True)
    _set_import_config_value(import_config, "distance_scale", 1.0)
    _set_import_config_value(import_config, "make_default_prim", True)
    _set_import_config_value(import_config, "parse_mimic", False)
    _set_import_config_value(import_config, "create_physics_scene", True)
    _set_import_config_value(import_config, "collision_from_visuals", False)

    status, articulation_path = omni.kit.commands.execute(
        "URDFParseAndImportFile",
        urdf_path=str(urdf),
        import_config=import_config,
        dest_path=str(dest),
        get_articulation_root=True,
    )
    if not status:
        raise RuntimeError(f"URDFParseAndImportFile failed for {urdf}")

    result = {
        "urdf_path": str(urdf),
        "dest_path": str(dest),
        "exists": dest.exists(),
        "articulation_path": str(articulation_path),
        "import_config": {
            "merge_fixed_joints": False,
            "fix_base": False,
            "self_collision": False,
            "convex_decomp": False,
            "import_inertia_tensor": True,
            "distance_scale": 1.0,
        },
    }
    _log_debug(
        "imported Ranger Mini URDF to PhysX USD "
        f"dest_path={result['dest_path']} articulation_path={result['articulation_path']}"
    )
    return result


def _stage_gravity_direction(stage: Any) -> tuple[float, float, float]:
    try:
        from pxr import UsdGeom  # type: ignore

        up_axis = UsdGeom.GetStageUpAxis(stage)
        if up_axis == UsdGeom.Tokens.y:
            return (0.0, -1.0, 0.0)
    except Exception:
        pass
    return (0.0, 0.0, -1.0)


def set_stage_up_axis(stage: Any, axis: str) -> dict[str, Any]:
    """Set stage up-axis explicitly when a user needs to repair imported scene metadata."""
    try:
        from pxr import UsdGeom  # type: ignore
    except Exception as exc:
        raise RuntimeError(f"USD geometry bindings are unavailable: {exc}") from exc

    normalized = str(axis).strip().lower()
    if normalized not in {"y", "z"}:
        raise RuntimeError(f"Unsupported up-axis: {axis}. Expected 'Y' or 'Z'.")
    token = UsdGeom.Tokens.y if normalized == "y" else UsdGeom.Tokens.z
    UsdGeom.SetStageUpAxis(stage, token)
    direction = _stage_gravity_direction(stage)
    physics_scene = stage.GetPrimAtPath("/World/PhysicsScene")
    if physics_scene and physics_scene.IsValid():
        attr = physics_scene.GetAttribute("physics:gravityDirection")
        if attr:
            from pxr import Gf  # type: ignore

            attr.Set(Gf.Vec3f(*direction))
    return {"up_axis": normalized.upper(), "gravity_direction": direction}


def _ensure_physics_scene(stage: Any, *, scene_path: str = "/World/PhysicsScene", gravity_magnitude: float = 9.81) -> str:
    try:
        from pxr import Gf, UsdPhysics  # type: ignore
    except Exception as exc:
        raise RuntimeError(f"USD physics bindings are unavailable: {exc}") from exc

    prim = stage.GetPrimAtPath(scene_path)
    scene = UsdPhysics.Scene(prim) if prim and prim.IsValid() else UsdPhysics.Scene.Define(stage, scene_path)
    scene.CreateGravityDirectionAttr().Set(Gf.Vec3f(*_stage_gravity_direction(stage)))
    scene.CreateGravityMagnitudeAttr().Set(float(gravity_magnitude))
    return str(scene.GetPrim().GetPath())


def _apply_collision_api(prim: Any) -> bool:
    try:
        from pxr import Sdf, UsdPhysics  # type: ignore
    except Exception:
        return False

    if not prim or not prim.IsValid():
        return False
    if not prim.HasAPI(UsdPhysics.CollisionAPI):
        UsdPhysics.CollisionAPI.Apply(prim)
    attr = prim.GetAttribute("physics:collisionEnabled")
    if not attr:
        attr = prim.CreateAttribute("physics:collisionEnabled", Sdf.ValueTypeNames.Bool)
    attr.Set(True)
    return True


def _ensure_custom_attr(prim: Any, name: str, value_type: Any, value: Any) -> None:
    attr = prim.GetAttribute(name)
    if not attr:
        attr = prim.CreateAttribute(name, value_type, custom=True)
    attr.Set(value)


def _ensure_builtin_attr(prim: Any, name: str, value_type: Any, value: Any) -> None:
    attr = prim.GetAttribute(name)
    if not attr:
        attr = prim.CreateAttribute(name, value_type)
    attr.Set(value)


def _apply_rigid_body_api(prim: Any, *, mass: float | None = None) -> bool:
    try:
        from pxr import Sdf, UsdPhysics  # type: ignore
    except Exception:
        return False

    if not prim or not prim.IsValid():
        return False
    if not prim.HasAPI(UsdPhysics.RigidBodyAPI):
        UsdPhysics.RigidBodyAPI.Apply(prim)
    _ensure_builtin_attr(prim, "physics:rigidBodyEnabled", Sdf.ValueTypeNames.Bool, True)
    if mass is not None:
        if not prim.HasAPI(UsdPhysics.MassAPI):
            UsdPhysics.MassAPI.Apply(prim)
        _ensure_builtin_attr(prim, "physics:mass", Sdf.ValueTypeNames.Float, float(mass))
    return True


def _disable_root_physics_api(prim: Any) -> None:
    try:
        from pxr import Sdf, UsdPhysics  # type: ignore
    except Exception:
        return

    if not prim or not prim.IsValid():
        return
    _ensure_builtin_attr(prim, "physics:rigidBodyEnabled", Sdf.ValueTypeNames.Bool, False)
    _ensure_builtin_attr(prim, "physics:collisionEnabled", Sdf.ValueTypeNames.Bool, False)
    for api_schema in (UsdPhysics.RigidBodyAPI, UsdPhysics.CollisionAPI, UsdPhysics.MassAPI):
        try:
            if prim.HasAPI(api_schema):
                prim.RemoveAPI(api_schema)
        except Exception:
            pass


def _set_xform_stack_reset(prim: Any, enabled: bool) -> None:
    try:
        from pxr import Sdf, UsdGeom  # type: ignore
    except Exception:
        return

    if not prim or not prim.IsValid():
        return
    UsdGeom.Xformable(prim).SetResetXformStack(bool(enabled))
    attr = prim.GetAttribute("xformOpOrder")
    if not attr:
        attr = prim.CreateAttribute("xformOpOrder", Sdf.ValueTypeNames.TokenArray)
    current = list(attr.Get() or [])
    reset_token = "!resetXformStack!"
    without_reset = [str(item) for item in current if str(item) != reset_token]
    attr.Set(([reset_token] + without_reset) if enabled else without_reset)


def _clear_xform_stack_reset(prim: Any) -> bool:
    if not prim or not prim.IsValid():
        return False
    attr = prim.GetAttribute("xformOpOrder")
    if not attr:
        return False
    current = list(attr.Get() or [])
    reset_token = "!resetXformStack!"
    if reset_token not in [str(item) for item in current]:
        return False
    attr.Set([str(item) for item in current if str(item) != reset_token])
    try:
        from pxr import UsdGeom  # type: ignore

        UsdGeom.Xformable(prim).SetResetXformStack(False)
    except Exception:
        pass
    return True


def _world_translation(stage: Any, prim: Any) -> Any:
    from pxr import Usd, UsdGeom  # type: ignore

    return UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default()).ExtractTranslation()


def _local_point_from_world(stage: Any, prim: Any, world_point: Any) -> Any:
    from pxr import Usd, UsdGeom  # type: ignore

    world_to_local = UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default()).GetInverse()
    return world_to_local.Transform(world_point)


def _set_joint_drive_attr(stage: Any, joint_path: str, attr_name: str, value: float) -> None:
    try:
        from pxr import Sdf  # type: ignore
    except Exception as exc:
        raise RuntimeError(f"USD bindings are unavailable: {exc}") from exc

    joint = stage.GetPrimAtPath(joint_path)
    if not joint or not joint.IsValid():
        raise RuntimeError(f"RangerMini joint not found: {joint_path}")
    attr = joint.GetAttribute(attr_name)
    if not attr:
        attr = joint.CreateAttribute(attr_name, Sdf.ValueTypeNames.Float)
    attr.Set(float(value))


def _is_visual_only_ranger(prim: Any) -> bool:
    return str(_attr_value(prim, "robomituba:physicsStatus", "")) == VISUAL_ONLY_PHYSICS_STATUS


def _require_not_visual_only_ranger(prim: Any) -> None:
    if _is_visual_only_ranger(prim):
        raise RuntimeError(
            "This Ranger Mini is the visual/sensor asset, not a PhysX wheel-drive articulation. "
            "Import assets/robots/ranger_mini_v3/isaac_urdf/ranger_mini_v3.urdf with Isaac URDF Importer "
            "and drive the generated physics USD instead."
        )


def _joint_prim_exists(stage: Any, robot_prim_path: str, joint_name: str) -> bool:
    return _find_descendant_prim_by_name(stage, robot_prim_path, joint_name) is not None


def _find_descendant_prim_by_name(stage: Any, root_path: str, prim_name: str) -> Any | None:
    direct = stage.GetPrimAtPath(f"{root_path}/{prim_name}")
    if direct and direct.IsValid():
        return direct
    try:
        from pxr import Usd  # type: ignore
    except Exception:
        return None
    root = stage.GetPrimAtPath(root_path)
    if not root or not root.IsValid():
        return None
    for prim in Usd.PrimRange(root):
        if prim.GetName() == prim_name:
            return prim
    return None


def _has_articulation_root_api(prim: Any) -> bool:
    if not prim or not prim.IsValid():
        return False
    try:
        from pxr import UsdPhysics  # type: ignore

        if prim.HasAPI(UsdPhysics.ArticulationRootAPI):
            return True
    except Exception:
        pass
    attr = prim.GetAttribute("physics:articulationEnabled")
    return bool(attr and attr.Get())


def _find_articulation_root_path(stage: Any, root_path: str) -> str | None:
    for candidate in (root_path, f"{root_path}/base_link"):
        if _has_articulation_root_api(stage.GetPrimAtPath(candidate)):
            return candidate
    try:
        from pxr import Usd  # type: ignore
    except Exception:
        return None
    root = stage.GetPrimAtPath(root_path)
    if not root or not root.IsValid():
        return None
    for prim in Usd.PrimRange(root):
        if _has_articulation_root_api(prim):
            return str(prim.GetPath())
    return None


def _make_articulation_action(*, joint_positions: Any, joint_velocities: Any, joint_indices: Any) -> Any:
    try:
        from isaacsim.core.utils.types import ArticulationAction  # type: ignore

        return ArticulationAction(
            joint_positions=joint_positions,
            joint_velocities=joint_velocities,
            joint_indices=joint_indices,
        )
    except Exception:
        return _FallbackArticulationAction(
            joint_positions=joint_positions,
            joint_velocities=joint_velocities,
            joint_indices=joint_indices,
        )


def _apply_articulation_action(handle: Any, action: Any) -> None:
    apply_action = getattr(handle, "apply_action", None)
    if not callable(apply_action):
        raise RuntimeError("Ranger Mini articulation handle does not expose apply_action().")
    try:
        apply_action(action)
    except TypeError:
        apply_action(control_actions=action)


def _joint_index(handle: Any, joint_name: str) -> int:
    getter = getattr(handle, "get_dof_index", None)
    if callable(getter):
        return int(getter(joint_name))
    index_map = getattr(handle, "joint_index_map", None) or getattr(handle, "joint_indices", None)
    if isinstance(index_map, dict) and joint_name in index_map:
        return int(index_map[joint_name])
    dof_names = list(getattr(handle, "dof_names", []) or [])
    if joint_name in dof_names:
        return int(dof_names.index(joint_name))
    raise RuntimeError(f"Ranger Mini articulation DOF not found: {joint_name}")


def _apply_drive_api(prim: Any) -> None:
    try:
        from pxr import UsdPhysics  # type: ignore
    except Exception:
        return

    try:
        if not prim.HasAPI(UsdPhysics.DriveAPI, "angular"):
            UsdPhysics.DriveAPI.Apply(prim, "angular")
    except Exception:
        pass


def _set_relationship_targets(prim: Any, name: str, targets: list[Any]) -> None:
    rel = prim.GetRelationship(name)
    if not rel:
        rel = prim.CreateRelationship(name, custom=False)
    rel.ClearTargets(False)
    rel.SetTargets(targets)


def _remove_existing_ranger_drive_joints(stage: Any, robot_prim_path: str) -> int:
    removed = 0
    for joint_name in (
        "fr_steer_joint",
        "fl_steer_joint",
        "rr_steer_joint",
        "rl_steer_joint",
        "fr_wheel_joint",
        "fl_wheel_joint",
        "rr_wheel_joint",
        "rl_wheel_joint",
    ):
        path = f"{robot_prim_path}/{joint_name}"
        prim = stage.GetPrimAtPath(path)
        if prim and prim.IsValid():
            stage.RemovePrim(path)
            removed += 1
    return removed


def restore_ranger_mini_visual_asset(stage: Any, robot_prim_path: str | None = None) -> dict[str, Any]:
    """Undo unsafe runtime PhysX edits on the visual Ranger asset."""
    try:
        from pxr import Sdf, Usd  # type: ignore
    except Exception as exc:
        raise RuntimeError(f"USD bindings are unavailable: {exc}") from exc

    resolved_path = resolve_ranger_mini_path(stage, robot_prim_path or "/World")
    root = stage.GetPrimAtPath(resolved_path)
    if not root or not root.IsValid():
        raise RuntimeError(f"Robot not found at {resolved_path}")

    removed_joints = _remove_existing_ranger_drive_joints(stage, resolved_path)
    reset_cleared = 0
    rigid_disabled = 0
    collision_disabled = 0
    for prim in Usd.PrimRange(root):
        if _clear_xform_stack_reset(prim):
            reset_cleared += 1
        rigid_attr = prim.GetAttribute("physics:rigidBodyEnabled")
        if rigid_attr:
            rigid_attr.Set(False)
            rigid_disabled += 1
        collision_attr = prim.GetAttribute("physics:collisionEnabled")
        if collision_attr:
            path_text = str(prim.GetPath()).lower()
            if "collision" not in path_text and "/colliders" not in path_text:
                collision_attr.Set(False)
                collision_disabled += 1
    _ensure_builtin_attr(root, "physics:rigidBodyEnabled", Sdf.ValueTypeNames.Bool, False)
    _ensure_builtin_attr(root, "physics:collisionEnabled", Sdf.ValueTypeNames.Bool, False)
    _log_debug(
        "visual asset restored "
        f"prim_path={resolved_path} removed_joints={removed_joints} "
        f"reset_cleared={reset_cleared} rigid_disabled={rigid_disabled}"
    )
    return {
        "prim_path": resolved_path,
        "removed_joints": removed_joints,
        "reset_cleared": reset_cleared,
        "rigid_disabled": rigid_disabled,
        "collision_disabled": collision_disabled,
    }


def _enable_robot_collision_prims(stage: Any, robot_prim_path: str) -> int:
    try:
        from pxr import Usd  # type: ignore
    except Exception as exc:
        raise RuntimeError(f"USD bindings are unavailable: {exc}") from exc

    root = stage.GetPrimAtPath(robot_prim_path)
    if not root or not root.IsValid():
        raise RuntimeError(f"Robot not found at {robot_prim_path}")

    enabled = 0
    for prim in Usd.PrimRange(root):
        name = prim.GetName().lower()
        path_text = str(prim.GetPath()).lower()
        if "collision" not in name and "/colliders" not in path_text:
            continue
        if prim.GetTypeName() not in {"Cube", "Cylinder", "Sphere", "Capsule", "Mesh"}:
            continue
        if _apply_collision_api(prim):
            enabled += 1
    return enabled


def _disable_visual_mesh_collision_prims(stage: Any, robot_prim_path: str) -> int:
    try:
        from pxr import Sdf, Usd, UsdGeom  # type: ignore
    except Exception as exc:
        raise RuntimeError(f"USD bindings are unavailable: {exc}") from exc

    root = stage.GetPrimAtPath(robot_prim_path)
    if not root or not root.IsValid():
        raise RuntimeError(f"Robot not found at {robot_prim_path}")

    disabled = 0
    for prim in Usd.PrimRange(root):
        if not prim.IsA(UsdGeom.Mesh):
            continue
        path_text = str(prim.GetPath()).lower()
        if "collision" in path_text or "/colliders" in path_text:
            continue
        attr = prim.GetAttribute("physics:collisionEnabled")
        if not attr:
            attr = prim.CreateAttribute("physics:collisionEnabled", Sdf.ValueTypeNames.Bool)
        attr.Set(False)
        disabled += 1
    return disabled


def _ensure_ground_collider(stage: Any, *, prim_path: str = "/World/RobomitubaGroundCollider", z: float = 0.0) -> str:
    try:
        from pxr import Gf, UsdGeom  # type: ignore
    except Exception as exc:
        raise RuntimeError(f"USD geometry bindings are unavailable: {exc}") from exc

    ground = UsdGeom.Cube.Define(stage, prim_path)
    prim = ground.GetPrim()
    ground.CreateSizeAttr(1.0)
    imageable = UsdGeom.Imageable(prim)
    imageable.CreateVisibilityAttr().Set(UsdGeom.Tokens.invisible)
    imageable.CreatePurposeAttr().Set(UsdGeom.Tokens.guide)

    xformable = UsdGeom.Xformable(prim)
    translate_ops = [op for op in xformable.GetOrderedXformOps() if op.GetOpType() == UsdGeom.XformOp.TypeTranslate]
    translate_op = translate_ops[0] if translate_ops else xformable.AddTranslateOp()
    translate_op.Set(Gf.Vec3d(0.0, 0.0, float(z) - 0.01))
    scale_ops = [op for op in xformable.GetOrderedXformOps() if op.GetOpType() == UsdGeom.XformOp.TypeScale]
    scale_op = scale_ops[0] if scale_ops else xformable.AddScaleOp()
    scale_op.Set(Gf.Vec3f(50.0, 50.0, 0.01))
    _apply_collision_api(prim)
    return str(prim.GetPath())


def _ensure_ranger_runtime_contract(stage: Any, robot_prim_path: str) -> dict[str, int]:
    try:
        from pxr import Sdf, UsdPhysics  # type: ignore
    except Exception as exc:
        raise RuntimeError(f"USD physics bindings are unavailable: {exc}") from exc
    from isaac_standalone.ranger_mini import JOINT_ORDER, RangerMiniMotionMode, RangerMiniParams

    root = stage.GetPrimAtPath(robot_prim_path)
    if not root or not root.IsValid():
        raise RuntimeError(f"Robot not found at {robot_prim_path}")
    params = RangerMiniParams()
    removed_joints = _remove_existing_ranger_drive_joints(stage, robot_prim_path)
    _disable_root_physics_api(root)
    _ensure_custom_attr(root, "robomituba:robotName", Sdf.ValueTypeNames.String, "ranger_mini_v3")
    _ensure_custom_attr(root, "robomituba:jointNames", Sdf.ValueTypeNames.StringArray, list(JOINT_ORDER))
    _ensure_custom_attr(root, "robomituba:jointPositions", Sdf.ValueTypeNames.DoubleArray, [0.0] * 8)
    _ensure_custom_attr(root, "robomituba:steeringAngles", Sdf.ValueTypeNames.DoubleArray, [0.0] * 4)
    _ensure_custom_attr(root, "robomituba:wheelSpeeds", Sdf.ValueTypeNames.DoubleArray, [0.0] * 4)
    _ensure_custom_attr(root, "robomituba:motionMode", Sdf.ValueTypeNames.Int, int(RangerMiniMotionMode.ACKERMANN))
    _ensure_custom_attr(root, "robomituba:batteryVoltage", Sdf.ValueTypeNames.Double, 48.0)
    _ensure_custom_attr(root, "robomituba:batterySoc", Sdf.ValueTypeNames.Double, 1.0)
    _ensure_custom_attr(root, "robomituba:estop", Sdf.ValueTypeNames.Bool, False)
    _ensure_custom_attr(root, "robomituba:hasError", Sdf.ValueTypeNames.Bool, False)
    _ensure_custom_attr(root, "robomituba:headingRad", Sdf.ValueTypeNames.Double, 0.0)
    _ensure_custom_attr(root, "robomituba:spawnBackend", Sdf.ValueTypeNames.String, "drag_drop_visual_upgrade")

    rigid_bodies = 0
    link_masses = {
        "base_link": params.base_mass_kg,
        "base_link/fr_steer_link": params.steer_mass_kg,
        "base_link/fl_steer_link": params.steer_mass_kg,
        "base_link/rr_steer_link": params.steer_mass_kg,
        "base_link/rl_steer_link": params.steer_mass_kg,
        "base_link/fr_steer_link/fr_wheel_link": params.wheel_mass_kg,
        "base_link/fl_steer_link/fl_wheel_link": params.wheel_mass_kg,
        "base_link/rr_steer_link/rr_wheel_link": params.wheel_mass_kg,
        "base_link/rl_steer_link/rl_wheel_link": params.wheel_mass_kg,
    }
    for relative_path, mass in link_masses.items():
        prim = stage.GetPrimAtPath(f"{robot_prim_path}/{relative_path}")
        if _apply_rigid_body_api(prim, mass=mass):
            rigid_bodies += 1
            if relative_path != "base_link":
                _set_xform_stack_reset(prim, True)
        if relative_path == "base_link" and prim and prim.IsValid():
            try:
                if not prim.HasAPI(UsdPhysics.ArticulationRootAPI):
                    UsdPhysics.ArticulationRootAPI.Apply(prim)
            except Exception:
                pass

    joint_specs = {
        "fr_steer_joint": ("Z", "base_link", "base_link/fr_steer_link", "position"),
        "fl_steer_joint": ("Z", "base_link", "base_link/fl_steer_link", "position"),
        "rr_steer_joint": ("Z", "base_link", "base_link/rr_steer_link", "position"),
        "rl_steer_joint": ("Z", "base_link", "base_link/rl_steer_link", "position"),
        "fr_wheel_joint": ("Y", "base_link/fr_steer_link", "base_link/fr_steer_link/fr_wheel_link", "velocity"),
        "fl_wheel_joint": ("Y", "base_link/fl_steer_link", "base_link/fl_steer_link/fl_wheel_link", "velocity"),
        "rr_wheel_joint": ("Y", "base_link/rr_steer_link", "base_link/rr_steer_link/rr_wheel_link", "velocity"),
        "rl_wheel_joint": ("Y", "base_link/rl_steer_link", "base_link/rl_steer_link/rl_wheel_link", "velocity"),
    }
    joints = 0
    for joint_name, (axis, body0, body1, drive_kind) in joint_specs.items():
        body0_prim = stage.GetPrimAtPath(f"{robot_prim_path}/{body0}")
        body1_prim = stage.GetPrimAtPath(f"{robot_prim_path}/{body1}")
        if not body0_prim or not body0_prim.IsValid() or not body1_prim or not body1_prim.IsValid():
            continue
        anchor_world = _world_translation(stage, body1_prim)
        joint = UsdPhysics.RevoluteJoint.Define(stage, f"{robot_prim_path}/{joint_name}")
        joint.CreateAxisAttr(axis)
        joint_prim = joint.GetPrim()
        _ensure_builtin_attr(joint_prim, "physics:jointEnabled", Sdf.ValueTypeNames.Bool, True)
        _set_relationship_targets(joint_prim, "physics:body0", [body0_prim.GetPath()])
        _set_relationship_targets(joint_prim, "physics:body1", [body1_prim.GetPath()])
        joint.CreateLocalPos0Attr().Set(_local_point_from_world(stage, body0_prim, anchor_world))
        joint.CreateLocalPos1Attr().Set(_local_point_from_world(stage, body1_prim, anchor_world))
        _apply_drive_api(joint_prim)
        if drive_kind == "position":
            _ensure_builtin_attr(joint_prim, "physics:lowerLimit", Sdf.ValueTypeNames.Float, -89.9544)
            _ensure_builtin_attr(joint_prim, "physics:upperLimit", Sdf.ValueTypeNames.Float, 89.9544)
            _ensure_builtin_attr(joint_prim, "drive:angular:targetPosition", Sdf.ValueTypeNames.Float, 0.0)
            _ensure_builtin_attr(joint_prim, "drive:angular:stiffness", Sdf.ValueTypeNames.Float, params.steering_drive_stiffness)
            _ensure_builtin_attr(joint_prim, "drive:angular:damping", Sdf.ValueTypeNames.Float, params.steering_drive_damping)
            _ensure_builtin_attr(joint_prim, "drive:angular:maxForce", Sdf.ValueTypeNames.Float, params.steering_drive_max_force)
        else:
            _ensure_builtin_attr(joint_prim, "drive:angular:targetVelocity", Sdf.ValueTypeNames.Float, 0.0)
            _ensure_builtin_attr(joint_prim, "drive:angular:stiffness", Sdf.ValueTypeNames.Float, params.wheel_drive_stiffness)
            _ensure_builtin_attr(joint_prim, "drive:angular:damping", Sdf.ValueTypeNames.Float, params.wheel_drive_damping)
            _ensure_builtin_attr(joint_prim, "drive:angular:maxForce", Sdf.ValueTypeNames.Float, params.wheel_drive_max_force)
        joints += 1

    return {"rigid_bodies": rigid_bodies, "joints": joints, "removed_joints": removed_joints}


def _robot_root_prim(stage: Any, prim_path: str) -> Any:
    prim = stage.GetPrimAtPath(prim_path)
    if prim and prim.IsValid():
        return prim
    return None


def _is_ranger_mini_prim(prim: Any) -> bool:
    if not prim or not prim.IsValid():
        return False
    if str(_attr_value(prim, "robomituba:robotName", "")) == "ranger_mini_v3":
        return True

    asset_kind = str(_attr_value(prim, "robomituba:assetKind", "")).lower()
    asset_label = str(_attr_value(prim, "robomituba:assetBrowserLabel", "")).lower()
    if asset_kind in {"robot", "robot_sensor_rig", "robot_physx"} and "ranger" in asset_label:
        return True

    name = prim.GetName().lower()
    name_suggests_ranger = "rangermini" in name or "ranger_mini" in name or ("ranger" in name and "mini" in name)
    path = str(prim.GetPath())
    stage = prim.GetStage()
    has_base_link = stage.GetPrimAtPath(f"{path}/base_link").IsValid()
    if not has_base_link:
        return False
    has_ranger_structure = any(
        stage.GetPrimAtPath(f"{path}/{child_path}").IsValid()
        for child_path in (
            "fr_steer_joint",
            "fr_steering_joint",
            "joints/fr_steering_joint",
            "fl_steer_joint",
            "fl_steering_joint",
            "joints/fl_steering_joint",
            "rr_steer_joint",
            "rr_steering_joint",
            "joints/rr_steering_joint",
            "rl_steer_joint",
            "rl_steering_joint",
            "joints/rl_steering_joint",
            "fr_wheel",
            "joints/fr_wheel",
            "fl_wheel",
            "joints/fl_wheel",
            "rr_wheel",
            "joints/rr_wheel",
            "rl_wheel",
            "joints/rl_wheel",
            "base_link/camera_front_link",
            "base_link/lidar_link",
            "base_link/fr_steer_link/fr_wheel_link",
            "base_link/fl_steer_link/fl_wheel_link",
            "base_link/rr_steer_link/rr_wheel_link",
            "base_link/rl_steer_link/rl_wheel_link",
        )
    )
    return bool(name_suggests_ranger and has_ranger_structure)


def _find_ranger_mini_paths_under(stage: Any, root_path: str | None = None) -> list[str]:
    try:
        from pxr import Usd  # type: ignore
    except Exception:
        return []

    root = stage.GetPrimAtPath(root_path) if root_path else None
    prims = Usd.PrimRange(root) if root and root.IsValid() else stage.Traverse()
    paths: list[str] = []
    for prim in prims:
        if _is_ranger_mini_prim(prim):
            paths.append(str(prim.GetPath()))
    paths.sort()
    return paths


def _stage_ranger_debug_candidates(stage: Any, root_path: str | None = None) -> list[str]:
    try:
        from pxr import Usd  # type: ignore
    except Exception:
        return []

    root = stage.GetPrimAtPath(root_path) if root_path else None
    prims = Usd.PrimRange(root) if root and root.IsValid() else stage.Traverse()
    candidates: list[str] = []
    for prim in prims:
        text = str(prim.GetPath()).lower()
        label = str(_attr_value(prim, "robomituba:assetBrowserLabel", "")).lower()
        kind = str(_attr_value(prim, "robomituba:assetKind", "")).lower()
        if "ranger" in text or "ranger" in label or kind in {"robot", "robot_sensor_rig"}:
            candidates.append(f"{prim.GetPath()}<{prim.GetTypeName()}>")
    return candidates[:12]


def resolve_ranger_mini_path(stage: Any, prim_path: str | None = None) -> str:
    """Resolve an exact Ranger prim path, or find the only Ranger below a container path."""
    if prim_path:
        prim = stage.GetPrimAtPath(prim_path)
        if _is_ranger_mini_prim(prim):
            return str(prim.GetPath())
        candidates = _find_ranger_mini_paths_under(stage, prim_path)
        if not candidates and prim_path in {"/World", "/world"}:
            candidates = _find_ranger_mini_paths_under(stage)
    else:
        candidates = _find_ranger_mini_paths_under(stage)

    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        hint = f" under {prim_path}" if prim_path else ""
        debug = _stage_ranger_debug_candidates(stage, prim_path)
        debug_hint = f" Ranger-like prims seen: {', '.join(debug)}." if debug else ""
        raise RuntimeError(
            f"No RangerMini robot found{hint}.{debug_hint} "
            "Select the Ranger root prim or run list_ranger_mini_robots(stage)."
        )
    raise RuntimeError(f"Multiple RangerMini robots found: {', '.join(candidates)}. Pass one exact robot prim path.")


def _default_spawn_path(stage: Any) -> str:
    index = 1
    while True:
        candidate = f"/World/RangerMini_{index:02d}"
        prim = stage.GetPrimAtPath(candidate)
        if not prim or not prim.IsValid():
            return candidate
        index += 1


def _viewport_based_spawn_translation(stage: Any, *, robot_index: int = 0) -> tuple[float, float, float]:
    try:
        from omni.kit.viewport.utility import get_active_viewport  # type: ignore
        from pxr import Gf, Usd, UsdGeom  # type: ignore
    except Exception:
        return (float(robot_index) * 1.2, 0.0, 0.0)

    try:
        viewport = get_active_viewport()
        if viewport is None:
            return (float(robot_index) * 1.2, 0.0, 0.0)
        camera_path = viewport.camera_path
        camera_path_str = camera_path.pathString if hasattr(camera_path, "pathString") else str(camera_path)
        camera_prim = stage.GetPrimAtPath(camera_path_str)
        if not camera_prim or not camera_prim.IsValid():
            return (float(robot_index) * 1.2, 0.0, 0.0)
        matrix = UsdGeom.Xformable(camera_prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
        origin = matrix.Transform(Gf.Vec3d(0.0, 0.0, 0.0))

        # Drop the robot at the current preview camera's XY position on the floor.
        spawn_x = float(origin[0])
        spawn_y = float(origin[1])
        spawn_z = 0.0
        if robot_index:
            spawn_x += float(robot_index) * 0.9
        return (spawn_x, spawn_y, spawn_z)
    except Exception as exc:
        _log_debug(f"viewport-based spawn fallback engaged error={exc}")
        return (float(robot_index) * 1.2, 0.0, 0.0)


def list_ranger_mini_robots(stage: Any) -> list[dict[str, Any]]:
    _, _, _, UsdGeom = _require_pxr()

    xform_cache = UsdGeom.XformCache()
    robots: list[dict[str, Any]] = []
    for prim in stage.Traverse():
        if not _is_ranger_mini_prim(prim):
            continue
        transform = xform_cache.GetLocalToWorldTransform(prim)
        translation = transform.ExtractTranslation()
        robots.append(
            {
                "prim_path": str(prim.GetPath()),
                "name": prim.GetName(),
                "translation": [float(translation[0]), float(translation[1]), float(translation[2])],
                "motion_mode": int(_attr_value(prim, "robomituba:motionMode", 0)),
                "battery_voltage": float(_attr_value(prim, "robomituba:batteryVoltage", 48.0)),
                "battery_soc": float(_attr_value(prim, "robomituba:batterySoc", 1.0)),
                "estop": bool(_attr_value(prim, "robomituba:estop", False)),
                "has_error": bool(_attr_value(prim, "robomituba:hasError", False)),
                "joint_positions": [float(v) for v in (_attr_value(prim, "robomituba:jointPositions", []) or [])],
            }
        )
    robots.sort(key=lambda item: item["prim_path"])
    return robots


def spawn_ranger_mini(stage: Any, *, prim_path: str | None = None, translation: tuple[float, float, float] | None = None) -> dict[str, Any]:
    from isaac_standalone.ranger_mini import RangerMiniRobot

    resolved_prim_path = prim_path or _default_spawn_path(stage)
    resolved_translation = translation
    if resolved_translation is None:
        resolved_translation = _viewport_based_spawn_translation(stage, robot_index=len(list_ranger_mini_robots(stage)))
    _log_debug(f"spawn requested prim_path={resolved_prim_path} translation={resolved_translation}")
    robot = RangerMiniRobot.spawn(
        stage=stage,
        prim_path=resolved_prim_path,
        translation=resolved_translation,
        use_reference=True,
    )
    state = robot.get_state()
    _log_debug(
        "spawn completed "
        f"prim_path={resolved_prim_path} motion_mode={int(state.motion_mode)} "
        f"base_pose={state.base_pose}"
    )
    return {
        "prim_path": resolved_prim_path,
        "translation": list(resolved_translation),
        "motion_mode": int(state.motion_mode),
    }


def enable_ranger_mini_physics(
    stage: Any,
    robot_prim_path: str,
    *,
    create_ground_collider: bool = True,
    gravity_magnitude: float = 9.81,
) -> dict[str, Any]:
    """Enable Isaac gravity/collision for a Ranger Mini already present in the stage."""
    robot_prim_path = resolve_ranger_mini_path(stage, robot_prim_path)
    raise RuntimeError(
        "Ranger Mini visual USD cannot be safely converted into a PhysX articulation at runtime. "
        "Do not run enable_ranger_mini_physics() on the current asset; use restore_ranger_mini_visual_asset() "
        "or re-drag the asset, then replace it with a physics-authored USD/URDF-imported articulation."
    )
    physics_scene_path = _ensure_physics_scene(stage, gravity_magnitude=gravity_magnitude)
    contract_counts = _ensure_ranger_runtime_contract(stage, robot_prim_path)
    disabled_visual_collision_count = _disable_visual_mesh_collision_prims(stage, robot_prim_path)
    collision_count = _enable_robot_collision_prims(stage, robot_prim_path)
    ground_path = None
    if create_ground_collider:
        ground_path = _ensure_ground_collider(stage)
    _log_debug(
        "physics enabled "
        f"prim_path={robot_prim_path} physics_scene={physics_scene_path} "
        f"collision_prims={collision_count} joints={contract_counts['joints']} "
        f"removed_joints={contract_counts['removed_joints']} "
        f"disabled_visual_mesh_collisions={disabled_visual_collision_count} ground={ground_path}"
    )
    return {
        "prim_path": robot_prim_path,
        "physics_scene": physics_scene_path,
        "collision_prims": collision_count,
        "disabled_visual_mesh_collisions": disabled_visual_collision_count,
        "rigid_bodies": contract_counts["rigid_bodies"],
        "joints": contract_counts["joints"],
        "removed_joints": contract_counts["removed_joints"],
        "ground_collider": ground_path,
        "gravity_magnitude": float(gravity_magnitude),
    }


def validate_ranger_mini_physx(stage: Any, robot_prim_path: str = "/World") -> dict[str, Any]:
    """Validate that a staged Ranger Mini is a real PhysX articulation, not the visual USD."""
    resolved_path = resolve_ranger_mini_path(stage, robot_prim_path)
    root = stage.GetPrimAtPath(resolved_path)
    if not root or not root.IsValid():
        raise RuntimeError(f"Ranger Mini root prim not found: {resolved_path}")
    _require_not_visual_only_ranger(root)

    missing_joints = [
        joint_name
        for joint_name in RANGER_MINI_PHYSX_JOINTS
        if not _joint_prim_exists(stage, resolved_path, joint_name)
    ]
    if missing_joints:
        raise RuntimeError(
            "Ranger Mini PhysX articulation is missing expected joints: "
            + ", ".join(missing_joints)
            + ". Re-import the URDF and save a physics-authored USD."
        )

    articulation_prim_path = _find_articulation_root_path(stage, resolved_path)
    if articulation_prim_path is None:
        raise RuntimeError(
            f"Ranger Mini prim is not marked as a PhysX articulation root: {resolved_path}. "
            "Use the URDF Importer output, not the visual asset."
        )

    return {
        "prim_path": resolved_path,
        "articulation_prim_path": articulation_prim_path,
        "articulation_root": True,
        "joint_count": len(RANGER_MINI_PHYSX_JOINTS),
        "joint_names": list(RANGER_MINI_PHYSX_JOINTS),
        "asset_status": ranger_mini_physx_asset_status(),
    }


def bind_ranger_mini_articulation(stage: Any, robot_prim_path: str = "/World") -> Any:
    """Bind the imported Ranger Mini PhysX USD to Isaac's SingleArticulation API."""
    validation = validate_ranger_mini_physx(stage, robot_prim_path)
    resolved_path = str(validation["prim_path"])
    articulation_prim_path = str(validation["articulation_prim_path"])
    try:
        from isaacsim.core.prims import SingleArticulation  # type: ignore
    except Exception as exc:
        raise RuntimeError(f"Isaac SingleArticulation API is unavailable: {exc}") from exc

    handle = SingleArticulation(prim_path=articulation_prim_path, name="robomituba_ranger_mini")
    try:
        handle.initialize()
    except Exception as exc:
        raise RuntimeError(
            "Failed to initialize Ranger Mini articulation. Start or reset physics once after loading the PhysX USD, "
            f"then retry. Details: {exc}"
        ) from exc

    joint_index_map = {joint_name: _joint_index(handle, joint_name) for joint_name in RANGER_MINI_PHYSX_JOINTS}
    for name, value in (
        ("joint_index_map", joint_index_map),
        ("robomituba_prim_path", resolved_path),
        ("robomituba_articulation_prim_path", articulation_prim_path),
    ):
        try:
            setattr(handle, name, value)
        except Exception:
            pass
    return handle


def _bound_robot(stage: Any, prim_path: str):
    from isaac_standalone.ranger_mini import RangerMiniRobot

    prim = _robot_root_prim(stage, prim_path)
    if prim is None:
        raise RuntimeError(f"Robot not found at {prim_path}")

    robot = RangerMiniRobot(prim_path=prim_path)
    _, _, _, UsdGeom = _require_pxr()
    xform_cache = UsdGeom.XformCache()
    transform = xform_cache.GetLocalToWorldTransform(prim)
    translation = transform.ExtractTranslation()
    robot.state.base_pose = [
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        float(translation[0]), float(translation[1]), float(translation[2]), 1.0,
    ]
    robot.heading_rad = float(_attr_value(prim, "robomituba:headingRad", 0.0))
    motion_mode = int(_attr_value(prim, "robomituba:motionMode", 0))
    joint_positions = [float(v) for v in (_attr_value(prim, "robomituba:jointPositions", []) or [])]
    steering_angles = [float(v) for v in (_attr_value(prim, "robomituba:steeringAngles", []) or [])]
    wheel_speeds = [float(v) for v in (_attr_value(prim, "robomituba:wheelSpeeds", []) or [])]
    robot.state.motion_mode = motion_mode
    if joint_positions:
        robot.state.joint_positions = joint_positions
    if steering_angles:
        robot.state.steering_angles = steering_angles
    if wheel_speeds:
        robot.state.wheel_speeds = wheel_speeds
    robot.state.battery_voltage = float(_attr_value(prim, "robomituba:batteryVoltage", 48.0))
    robot.state.battery_soc = float(_attr_value(prim, "robomituba:batterySoc", 1.0))
    robot.state.estop = bool(_attr_value(prim, "robomituba:estop", False))
    robot.state.has_error = bool(_attr_value(prim, "robomituba:hasError", False))
    _log_debug(
        "bound robot "
        f"prim_path={prim_path} translation={robot.state.base_pose[12:15]} "
        f"motion_mode={motion_mode}"
    )
    return robot


def command_robot(stage: Any, prim_path: str, action: str) -> dict[str, Any]:
    from isaac_standalone.ranger_mini import RangerMiniMotionMode

    prim_path = resolve_ranger_mini_path(stage, prim_path)
    _log_debug(f"command requested prim_path={prim_path} action={action}")
    robot = _bound_robot(stage, prim_path)
    if action == "forward":
        robot.set_motion_mode(int(RangerMiniMotionMode.ACKERMANN))
        robot.move(linear_speed=0.8, steering_angle=0.0)
    elif action == "backward":
        robot.set_motion_mode(int(RangerMiniMotionMode.ACKERMANN))
        robot.move(linear_speed=-0.6, steering_angle=0.0)
    elif action == "left":
        robot.turn_left(speed=0.5)
    elif action == "right":
        robot.turn_right(speed=0.5)
    elif action == "strafe_left":
        robot.set_motion_mode(int(RangerMiniMotionMode.OBLIQUE))
        robot.move(linear_speed=0.5, steering_angle=1.57079632679 / 2.0)
    elif action == "strafe_right":
        robot.set_motion_mode(int(RangerMiniMotionMode.OBLIQUE))
        robot.move(linear_speed=0.5, steering_angle=-1.57079632679 / 2.0)
    elif action == "spin_left":
        robot.spin(0.8)
    elif action == "spin_right":
        robot.spin(-0.8)
    elif action == "park":
        robot.park()
    elif action == "stop":
        robot.stop()
    else:
        raise RuntimeError(f"Unsupported RangerMini action: {action}")

    state = robot.update(1.0 / 60.0, stage=stage)
    _log_debug(
        "command completed "
        f"prim_path={prim_path} action={action} motion_mode={int(state.motion_mode)} "
        f"translation={state.base_pose[12:15] if state.base_pose else None}"
    )
    return {
        "prim_path": prim_path,
        "action": action,
        "motion_mode": int(state.motion_mode),
        "joint_positions": list(state.joint_positions),
    }


def drive_ranger_mini_physx(
    stage: Any,
    robot_prim_path: str,
    *,
    linear_speed_mps: float = 0.0,
    steering_angle_rad: float = 0.0,
    spin_speed_radps: float = 0.0,
    motion_mode: int | None = None,
    articulation_handle: Any | None = None,
) -> dict[str, Any]:
    """Apply Ranger Mini steering/wheel targets through Isaac's articulation controller."""
    from isaac_standalone.ranger_mini import RangerMiniCommand, RangerMiniMotionMode, RangerMiniParams
    from isaac_standalone.ranger_mini.kinematics import compute_joint_targets, saturate_command

    robot_prim_path = resolve_ranger_mini_path(stage, robot_prim_path)
    root = stage.GetPrimAtPath(robot_prim_path)
    if not root or not root.IsValid():
        raise RuntimeError(f"Ranger Mini root prim not found: {robot_prim_path}")
    _require_not_visual_only_ranger(root)

    if motion_mode is None:
        motion_mode = int(RangerMiniMotionMode.SPIN) if abs(float(spin_speed_radps)) > 1e-9 else int(RangerMiniMotionMode.ACKERMANN)
    params = RangerMiniParams()
    command = saturate_command(
        RangerMiniCommand(
            motion_mode=int(motion_mode),
            linear_speed_mps=float(linear_speed_mps),
            steering_angle_rad=float(steering_angle_rad),
            spin_speed_radps=float(spin_speed_radps),
        ),
        params,
    )
    targets = compute_joint_targets(command, params)

    handle = articulation_handle or bind_ranger_mini_articulation(stage, robot_prim_path)
    steering_targets = {
        "fr_steering_joint": targets.fr_steer,
        "fl_steering_joint": targets.fl_steer,
        "rr_steering_joint": targets.rr_steer,
        "rl_steering_joint": targets.rl_steer,
    }
    wheel_targets = {
        "fr_wheel": targets.fr_wheel,
        "fl_wheel": targets.fl_wheel,
        "rr_wheel": targets.rr_wheel,
        "rl_wheel": targets.rl_wheel,
    }
    ordered_joints = list(RANGER_MINI_PHYSX_JOINTS)
    joint_indices = [_joint_index(handle, joint_name) for joint_name in ordered_joints]
    try:
        import numpy as np

        joint_positions = np.full(len(ordered_joints), np.nan, dtype=float)
        joint_velocities = np.full(len(ordered_joints), np.nan, dtype=float)
        action_indices = np.array(joint_indices, dtype=np.int32)
    except Exception:
        joint_positions = [float("nan")] * len(ordered_joints)
        joint_velocities = [float("nan")] * len(ordered_joints)
        action_indices = joint_indices

    for index, joint_name in enumerate(ordered_joints):
        if joint_name in steering_targets:
            joint_positions[index] = float(steering_targets[joint_name])
        if joint_name in wheel_targets:
            joint_velocities[index] = float(wheel_targets[joint_name])

    action = _make_articulation_action(
        joint_positions=joint_positions,
        joint_velocities=joint_velocities,
        joint_indices=action_indices,
    )
    _apply_articulation_action(handle, action)

    for name, value in (
        ("robomituba:motionMode", int(command.motion_mode)),
        ("robomituba:headingRad", float(_attr_value(root, "robomituba:headingRad", 0.0))),
    ):
        attr = root.GetAttribute(name)
        if attr:
            attr.Set(value)

    _log_debug(
        "physx articulation action applied "
        f"prim_path={robot_prim_path} mode={int(command.motion_mode)} "
        f"linear={command.linear_speed_mps} steer={command.steering_angle_rad} spin={command.spin_speed_radps}"
    )
    return {
        "prim_path": robot_prim_path,
        "motion_mode": int(command.motion_mode),
        "joint_indices": {name: int(index) for name, index in zip(ordered_joints, joint_indices)},
        "steering_target_rad": {key: float(value) for key, value in steering_targets.items()},
        "wheel_target_rad_per_s": {key: float(value) for key, value in wheel_targets.items()},
    }


def drive_ranger_mini_cmd_vel(
    stage: Any,
    robot_prim_path: str,
    *,
    linear_x: float = 0.0,
    angular_z: float = 0.0,
    articulation_handle: Any | None = None,
) -> dict[str, Any]:
    """Convert ROS-style cmd_vel fields to Ranger PhysX wheel/steering drive targets."""
    from isaac_standalone.ranger_mini import RangerMiniParams, RangerMiniRosAdapter

    class _Vector:
        def __init__(self, x: float = 0.0, z: float = 0.0) -> None:
            self.x = float(x)
            self.z = float(z)

    class _Twist:
        def __init__(self, linear_x_value: float, angular_z_value: float) -> None:
            self.linear = _Vector(x=linear_x_value)
            self.angular = _Vector(z=angular_z_value)

    params = RangerMiniParams()
    command = RangerMiniRosAdapter().command_from_twist(_Twist(linear_x, angular_z), params=params)
    return drive_ranger_mini_physx(
        stage,
        robot_prim_path,
        linear_speed_mps=float(command.linear_speed_mps),
        steering_angle_rad=float(command.steering_angle_rad),
        spin_speed_radps=float(command.spin_speed_radps),
        motion_mode=int(command.motion_mode),
        articulation_handle=articulation_handle,
    )


def command_robot_physx(stage: Any, prim_path: str, action: str) -> dict[str, Any]:
    from isaac_standalone.ranger_mini import RangerMiniMotionMode

    if action == "forward":
        return drive_ranger_mini_physx(stage, prim_path, linear_speed_mps=0.8, steering_angle_rad=0.0)
    if action == "backward":
        return drive_ranger_mini_physx(stage, prim_path, linear_speed_mps=-0.6, steering_angle_rad=0.0)
    if action == "left":
        return drive_ranger_mini_physx(stage, prim_path, linear_speed_mps=0.5, steering_angle_rad=0.35)
    if action == "right":
        return drive_ranger_mini_physx(stage, prim_path, linear_speed_mps=0.5, steering_angle_rad=-0.35)
    if action == "strafe_left":
        return drive_ranger_mini_physx(
            stage,
            prim_path,
            linear_speed_mps=0.5,
            steering_angle_rad=0.78539816339,
            motion_mode=int(RangerMiniMotionMode.OBLIQUE),
        )
    if action == "strafe_right":
        return drive_ranger_mini_physx(
            stage,
            prim_path,
            linear_speed_mps=0.5,
            steering_angle_rad=-0.78539816339,
            motion_mode=int(RangerMiniMotionMode.OBLIQUE),
        )
    if action == "spin_left":
        return drive_ranger_mini_physx(stage, prim_path, spin_speed_radps=0.8, motion_mode=int(RangerMiniMotionMode.SPIN))
    if action == "spin_right":
        return drive_ranger_mini_physx(stage, prim_path, spin_speed_radps=-0.8, motion_mode=int(RangerMiniMotionMode.SPIN))
    if action == "park":
        return drive_ranger_mini_physx(stage, prim_path, motion_mode=int(RangerMiniMotionMode.PARKING))
    if action == "stop":
        return drive_ranger_mini_physx(stage, prim_path, linear_speed_mps=0.0, steering_angle_rad=0.0)
    raise RuntimeError(f"Unsupported RangerMini PhysX action: {action}")
