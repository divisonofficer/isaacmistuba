from __future__ import annotations

from mitsuba_converter.ir_material_mix import audit_material_mix


def _record(route: str, value: float | None = None, *, fallback: bool = False, replacement: bool = False) -> dict:
    runtime = {"mode": route}
    if value is not None:
        runtime["value"] = [value]
    return {
        "material_id": 7, "object_id": "object", "source_material": "fixture",
        "fallback_channels": ["metallic"] if fallback else [], "replacement": replacement,
        "channel_runtime_sources": {"metallic": runtime},
        "effective_inputs": {"metallic": {"route": route, "artifact": "atlas.png"}},
    }


def test_material_mix_counts_effective_constant_and_texture_without_semantic_guessing() -> None:
    report = audit_material_mix({"schema": "robomituba.ir_principled_material_contract.v2", "materials": [
        _record("constant", 1.0), _record("constant", .5), _record("texture"),
        _record("surrogate_zero", 0.0, replacement=True), _record("constant", 1.0, fallback=True),
    ]})
    assert report["status"] == "passed"
    assert report["high_metallic_constant_count"] == 1
    assert report["texture_metallic_count"] == 1
    assert report["excluded_count"] == 2


def test_material_mix_fails_when_no_authored_metal_candidate_exists() -> None:
    report = audit_material_mix({"materials": [_record("constant", 0.2), _record("surrogate_zero", 0.0, replacement=True)]})
    assert report["status"] == "failed"
    assert report["failures"] == ["no_authored_high_metallic_candidate"]


def test_v4_contract_rejects_uniform_fractional_and_srgb_metallic() -> None:
    fractional = _record("constant", 0.35)
    fractional["metallic_contract"] = {
        "schema": "robomituba.metallic_contract.v2", "family": "conductor",
        "representation": "scalar", "encoding": "linear_scalar", "color_space": "sRGB",
        "source": "generated", "approximation": "none", "generator_id": "bad", "seed": 1,
    }
    report = audit_material_mix({
        "schema": "robomituba.ir_principled_material_contract.v4",
        "materials": [fractional, _record("constant", 1.0)],
    })
    assert report["status"] == "failed"
    assert any("uniform_fractional" in failure for failure in report["failures"])
    assert any("color_space" in failure for failure in report["failures"])
