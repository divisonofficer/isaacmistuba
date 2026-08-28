from pathlib import Path

from scripts.infinigen_gen import AptPreset, build_command


def _preset() -> AptPreset:
    return AptPreset(
        seed=20260828,
        unit_type="84m2",
        floor_plan_key="single_room",
        density="normal_lived_in",
        num_floating=8,
        camera_profile="daytime_living_room",
        archetype="single_room",
        room_type="kitchen",
    )


def _command(profile: str) -> list[str]:
    return build_command(
        _preset(), out=Path("/tmp/paper-style-pilot"), stage="full", fast=False,
        floor_plan_json=Path("/tmp/paper-style-pilot/floor_plan.json"),
        extra_overrides=[], placement_profile=profile,
    )


def test_upstream_profile_disables_post_solver_floating_objects() -> None:
    command = _command("upstream_residential_v1")
    assert "compose_indoors.floating_objs_enabled=False" in command
    assert not any(value.startswith("compose_indoors.num_floating=") for value in command)


def test_collision_aware_profile_enables_both_collision_domains() -> None:
    command = _command("collision_aware_clutter_v1")
    assert "compose_indoors.floating_objs_enabled=True" in command
    assert "compose_indoors.num_floating=8" in command
    assert "compose_indoors.enable_collision_floating=True" in command
    assert "compose_indoors.enable_collision_solved=True" in command


def test_legacy_profile_preserves_current_collision_contract() -> None:
    command = _command("legacy_clutter_v1")
    assert "compose_indoors.floating_objs_enabled=True" in command
    assert "compose_indoors.enable_collision_floating=False" in command
    assert "compose_indoors.enable_collision_solved=False" in command
