"""Stage-1 canonicalization: the provenance/semantics contract must hold."""
from mitsuba_converter.material_pipeline.canonicalize import canonicalize_slot


def _slot(strategy, *, optical_class=None, base_tex=None, base_factor=None,
          rough_tex=None, mr_tex=None, rough_scalar=None, metallic_scalar=None,
          metallic_tex=None, metallic_factor=None, normal_tex=None, source="glb_pbr",
          measured=None):
    return {
        "material_id": f"m_{strategy}",
        "shape_ids": ["s0"],
        "analytic_strategy": strategy,
        "optical_class": optical_class,
        "measured_role": None,
        "authoring": {"base_color_factor": base_factor, "roughness": rough_scalar,
                      "metallic": metallic_scalar},
        "extracted": {"source": source, "surface_shader_id": "x",
                      "base_color_factor": None, "base_color_texture_ref": base_tex,
                      "normal_texture_ref": normal_tex, "roughness_texture_ref": rough_tex,
                      "metallic_texture_ref": metallic_tex,
                      "metallic_roughness_texture_ref": mr_tex,
                      "roughness_factor": None, "metallic_factor": metallic_factor,
                      "opacity_factor": None},
        "measured_candidate": measured,
    }


def test_conductor_metallic_is_one_overriding_leaked_factor():
    # a hammered-metal panel: roughconductor with a leaked metallicFactor=0 must still be metallic 1
    m = canonicalize_slot(_slot("roughconductor", metallic_factor=0.0, metallic_scalar=0.0,
                                rough_tex="r.png"))
    assert m.canonical_bsdf == "roughconductor"
    met = m.parameters["metallic"]
    assert met.valid and met.value == 1.0 and met.source == "derived"


def test_smooth_dielectric_roughness_zero_not_half():
    m = canonicalize_slot(_slot("dielectric", optical_class="glass"))
    r = m.parameters["roughness_perceptual"]
    assert r.valid and r.value == 0.0 and r.source == "derived"
    a = m.parameters["microfacet_alpha"]
    assert a.valid and a.value == 0.0
    assert m.parameters["metallic"].value == 0.0


def test_lambertian_roughness_is_undefined_not_one():
    m = canonicalize_slot(_slot("diffuse"))
    r = m.parameters["roughness_perceptual"]
    assert not r.valid and r.source == "undefined"
    assert not m.parameters["microfacet_alpha"].valid


def test_microfacet_alpha_is_r_squared_for_scalar_roughness():
    m = canonicalize_slot(_slot("pplastic", rough_scalar=0.6))
    r = m.parameters["roughness_perceptual"]
    assert r.valid and abs(r.value - 0.6) < 1e-9 and r.source == "blend_authored"
    a = m.parameters["microfacet_alpha"]
    assert a.valid and abs(a.value - 0.36) < 1e-9 and a.formula == "alpha = r^2"


def test_texture_roughness_defers_alpha_to_render_no_value():
    m = canonicalize_slot(_slot("pplastic", rough_tex="rough.png"))
    r = m.parameters["roughness_perceptual"]
    assert r.valid and r.path == "rough.png" and r.source == "baked"
    a = m.parameters["microfacet_alpha"]
    assert a.valid and a.value is None and "per-texel" in a.formula


def test_base_color_authoring_beats_glb_factor():
    m = canonicalize_slot(_slot("pplastic", base_factor=[0.56, 0.57, 0.58]))
    bc = m.parameters["base_color"]
    assert bc.valid and bc.source == "blend_authored" and bc.value == [0.56, 0.57, 0.58]


def test_glass_base_color_undefined_not_faked():
    m = canonicalize_slot(_slot("dielectric", optical_class="glass"))
    bc = m.parameters["base_color"]
    assert not bc.valid and bc.source == "undefined"


def test_packed_metallic_roughness_is_flagged_for_unpack():
    m = canonicalize_slot(_slot("roughconductor", mr_tex="orm.png"))
    r = m.parameters["roughness_perceptual"]
    assert r.valid and r.path == "orm.png" and "G channel" in r.note


def test_measured_material_roughness_undefined():
    m = canonicalize_slot(_slot("measured_polarized",
                                measured={"material_id": "aluminum", "kind": "hpbrdf_2025"}))
    assert m.canonical_bsdf == "measured"
    assert not m.parameters["roughness_perceptual"].valid
    assert m.extras.get("measured_candidate", {}).get("material_id") == "aluminum"
