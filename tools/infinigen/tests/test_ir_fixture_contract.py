from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "infinigen"))
sys.path.insert(0, str(REPO / "modules" / "navigation_dataset" / "src"))

from ir_fixture_contract import KELVIN_QUANTUM, resolve_fixture_subset  # noqa: E402
from navigation_dataset.ir_indoor_fixtures import blackbody_linear_rgb  # noqa: E402

SPEC = {
    "groups": {
        "ceiling": {"on_probability": 1.0, "energy_scale": 1.0},
        "lamp": {"on_probability": 0.5, "energy_scale": 1.3,
                 "color_temperature_k": 2700, "color_temperature_jitter_k": 250},
        "accent": {"on_probability": 0.3, "energy_scale": 1.0},
    },
    "subset_seed": 7, "subset_salt": "cond_a", "min_on_per_room": 0,
}


def _fixtures(n: int = 40, room: str = "r0") -> list[dict]:
    out = []
    for i in range(n):
        group = ("ceiling", "lamp", "accent")[i % 3]
        out.append({"fixture_id": f"{group}:{room}:{i:04x}", "group": group, "room_id": room})
    return out


def _resolve(fx, spec=SPEC, **kw):
    return resolve_fixture_subset(fx, spec, scene_id="scene", condition_id="cond_a",
                                  rig_digest="d" * 16, blackbody=blackbody_linear_rgb, **kw)


def test_absent_spec_leaves_every_fixture_alone() -> None:
    out = resolve_fixture_subset(_fixtures(), None, scene_id="s", condition_id="c", rig_digest="d")
    assert out["applied"] is False and out["on"] == [] and out["off"] == []


def test_resolution_is_deterministic() -> None:
    assert _resolve(_fixtures())["on"] == _resolve(_fixtures())["on"]


def test_removing_one_fixture_does_not_flip_any_other() -> None:
    """The reason this is hash-derived rather than drawn from an RNG stream.

    An RNG whose draw order follows the inventory would repaint a whole scene
    whenever a single light was added or removed.
    """
    full = _fixtures(40)
    before = _resolve(full)["fixtures"]
    reduced = [f for f in full if f["fixture_id"] != full[7]["fixture_id"]]
    after = _resolve(reduced)["fixtures"]
    for fid, row in after.items():
        assert row["on"] == before[fid]["on"], fid
        assert row["color_temperature_k"] == before[fid]["color_temperature_k"], fid


def test_a_different_condition_gives_a_different_subset() -> None:
    a = _resolve(_fixtures())["on"]
    other = {**SPEC, "subset_salt": "cond_b"}
    b = resolve_fixture_subset(_fixtures(), other, scene_id="scene", condition_id="cond_b",
                               rig_digest="d" * 16, blackbody=blackbody_linear_rgb)["on"]
    assert a != b


def test_group_probabilities_are_honoured() -> None:
    out = _resolve(_fixtures(300))["fixtures"]
    by = {}
    for row in out.values():
        by.setdefault(row["group"], []).append(row["on"])
    assert all(by["ceiling"]), "on_probability 1.0 must keep every ceiling fixture"
    for group, target in (("lamp", 0.5), ("accent", 0.3)):
        rate = sum(by[group]) / len(by[group])
        assert abs(rate - target) < 0.12, (group, rate)


def test_a_group_the_condition_omits_is_untouched() -> None:
    fx = _fixtures(9) + [{"fixture_id": "portal:r0:ffff", "group": "portal", "room_id": "r0"}]
    out = _resolve(fx)
    assert "portal:r0:ffff" not in out["fixtures"]
    assert "portal:r0:ffff" not in out["on"] and "portal:r0:ffff" not in out["off"]


def test_min_on_per_room_repairs_a_fully_dark_room() -> None:
    """A room drawing every switchable fixture off would render black."""
    dark = {"groups": {"lamp": {"on_probability": 0.0, "energy_scale": 1.0}},
            "subset_seed": 1, "subset_salt": "x", "min_on_per_room": 1}
    fx = [{"fixture_id": f"lamp:r{r}:{i}", "group": "lamp", "room_id": f"r{r}"}
          for r in range(3) for i in range(4)]
    out = resolve_fixture_subset(fx, dark, scene_id="s", condition_id="c",
                                 rig_digest="d", blackbody=blackbody_linear_rgb)
    for room in ("r0", "r1", "r2"):
        on = [f for f in out["on"] if f.split(":")[1] == room]
        assert len(on) == 1, room
    assert len(out["forced_on"]) == 3
    # And the repair is deterministic.
    again = resolve_fixture_subset(fx, dark, scene_id="s", condition_id="c",
                                   rig_digest="d", blackbody=blackbody_linear_rgb)
    assert again["forced_on"] == out["forced_on"]


def test_kelvin_is_quantised_so_a_digest_cannot_drift() -> None:
    out = _resolve(_fixtures(60))["fixtures"]
    lamps = [r for r in out.values() if r["group"] == "lamp"]
    assert lamps
    for row in lamps:
        k = row["color_temperature_k"]
        assert k % KELVIN_QUANTUM == pytest.approx(0.0, abs=1e-9), k
        assert 2450 <= k <= 2950, k
        assert row["color_linear_rgb"] == list(blackbody_linear_rgb(k))


def test_a_group_without_a_temperature_keeps_its_prepared_colour() -> None:
    out = _resolve(_fixtures(30))["fixtures"]
    ceilings = [r for r in out.values() if r["group"] == "ceiling"]
    assert ceilings and all(r["color_linear_rgb"] is None for r in ceilings)
