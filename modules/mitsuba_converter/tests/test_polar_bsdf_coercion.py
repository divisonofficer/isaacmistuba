"""Forbidden (DoLP=0) analytic BSDFs must be consumed into the polarizing trio
(dielectric / roughconductor / pplastic) on the polar path, and must never be
marked polar-capable. Guards the dev_report 2026-07-06 §2.1 root cause."""
from mitsuba_converter import render_daemon as rd


def test_forbidden_bsdfs_not_in_polar_allowlist():
    for dead in ("roughdielectric", "thindielectric", "plastic", "roughplastic"):
        assert dead not in rd._POLAR_RGB_ANALYTIC_BSDFS
    assert rd._POLAR_RGB_ANALYTIC_BSDFS == {"pplastic", "dielectric", "conductor", "roughconductor"}


def test_binding_resolver_coerces_to_trio():
    coerce = {
        "roughdielectric": "dielectric", "thindielectric": "dielectric",
        "plastic": "pplastic", "roughplastic": "pplastic",
        "diffuse": "pplastic", "principled": "pplastic", "measured": "pplastic",
        "dielectric": "dielectric", "roughconductor": "roughconductor", "pplastic": "pplastic",
    }
    for inp, exp in coerce.items():
        r = rd._analytic_fallback_from_binding({"bsdf_strategy": inp})
        assert r["bsdf_strategy"] == exp, f"{inp} -> {r['bsdf_strategy']} (want {exp})"
        # after coercion the surface is a genuine polarizing type
        assert r["bsdf_strategy"] in rd._POLAR_RGB_ANALYTIC_BSDFS
        assert r["capabilities"].get("polarization") is True


def test_substitution_table_covers_all_forbidden():
    for dead in ("roughdielectric", "thindielectric", "plastic", "roughplastic"):
        assert rd._POLAR_BSDF_SUBSTITUTION[dead] in rd._POLAR_RGB_ANALYTIC_BSDFS
