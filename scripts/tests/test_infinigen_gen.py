"""Regression tests for wrapper floor-plan profile selection.

These tests deliberately do not invoke Blender or the Infinigen environment.
They verify the command contract that selects the native floor-plan solver.
"""

import json
from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import infinigen_gen as generator  # noqa: E402
import infinigen_wizard as wizard  # noqa: E402


def _preset(floor_plan_key: str) -> generator.AptPreset:
    return generator.AptPreset(
        seed=20_010_001,
        unit_type="84m2",
        floor_plan_key=floor_plan_key,
        density="normal_lived_in",
        num_floating=18,
        camera_profile="daytime_living_room",
        archetype="apartment",
    )


def test_natural_apartment_selects_native_floor_plan_solver(tmp_path: Path) -> None:
    command = generator.build_command(
        _preset(generator.NATIVE_APARTMENT_PROFILE),
        out=tmp_path,
        stage="layout",
        fast=False,
        floor_plan_json=None,
        extra_overrides=[],
    )
    overrides = command[command.index("-p") + 1:]

    assert not any(item.startswith("Solver.floor_plan=") for item in overrides)
    assert set(generator.NATIVE_APARTMENT_OVERRIDES) <= set(overrides)
    assert "RoomConstants.n_stories=1" in overrides
    assert "RoomConstants.fixed_contour=False" in overrides


def test_legacy_apartment_retains_predefined_json_contract(tmp_path: Path) -> None:
    plan = tmp_path / "floor_plan.json"
    command = generator.build_command(
        _preset("gen_apartment"),
        out=tmp_path,
        stage="layout",
        fast=False,
        floor_plan_json=plan,
        extra_overrides=[],
    )
    overrides = command[command.index("-p") + 1:]

    assert f"Solver.floor_plan='{plan}'" in overrides
    assert not any(item == "RoomConstants.fixed_contour=False" for item in overrides)


def test_natural_apartment_dry_run_writes_native_profile_metadata(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "infinigen_gen.py",
            "--seed", "20260828",
            "--floor-plan", generator.NATIVE_APARTMENT_PROFILE,
            "--stage", "layout",
            "--out", str(tmp_path),
        ],
    )

    assert generator.main() == 0

    metadata = json.loads((tmp_path / "kr_preset.json").read_text())
    assert metadata["floor_plan_mode"] == "native_solver"
    assert metadata["floor_plan_source"] is None
    assert metadata["native_floor_plan_profile"]["stories"] == 1
    assert not (tmp_path / "floor_plan.json").exists()


def test_wizard_defaults_apartment_to_natural_native_profile() -> None:
    assert wizard.ARCHETYPES["apartment"] == generator.NATIVE_APARTMENT_PROFILE
