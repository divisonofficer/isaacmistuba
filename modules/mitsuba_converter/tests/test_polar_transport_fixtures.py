from __future__ import annotations

import importlib.util
from pathlib import Path


def test_canonical_transport_fixtures_use_closed_dielectric_and_backing() -> None:
    script = Path(__file__).resolve().parents[3] / "apps" / "render_polar_transport_fixtures.py"
    spec = importlib.util.spec_from_file_location("polar_transport_fixtures", script)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)

    assert set(module.FIXTURES) == {"glass_window", "glass_bottle", "back_silvered_mirror"}
    assert all("thindielectric" not in body for body in module.FIXTURES.values())
    assert "type='conductor'" in module.FIXTURES["back_silvered_mirror"]
    assert "type='dielectric'" in module.FIXTURES["back_silvered_mirror"]
