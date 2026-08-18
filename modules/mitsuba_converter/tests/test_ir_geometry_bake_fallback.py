from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_builder():
    path = REPO_ROOT / "apps" / "build_ir_geometry_profile.py"
    spec = importlib.util.spec_from_file_location("build_ir_geometry_profile_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_optix_failure_resumes_checkpoints_once_on_cpu(monkeypatch) -> None:
    builder = _load_builder()
    commands: list[tuple[list[str], bool]] = []

    def fake_run(command, *, cwd, check=False):
        commands.append((list(command), check))
        return subprocess.CompletedProcess(command, 23 if len(commands) == 1 else 0)

    monkeypatch.setattr(builder.subprocess, "run", fake_run)
    command = ["blender", "--cycles-device", "OPTIX", "--bake-pbr"]
    effective, used = builder._run_bake_export_with_fallback(
        command, requested="OPTIX", fallback="CPU",
    )

    assert effective == "CPU" and used is True
    assert commands[0] == (command, False)
    fallback_command, checked = commands[1]
    assert fallback_command[fallback_command.index("--cycles-device") + 1] == "CPU"
    assert "--reuse-atlas" in fallback_command
    assert checked is True
