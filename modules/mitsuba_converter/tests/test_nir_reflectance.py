import numpy as np

from mitsuba_converter import nir_reflectance as nr


def test_mapping_optical_class_strong():
    assert nr.physical_material_for("shader_whatever", "glass") == ("clear_glass", "high")
    assert nr.physical_material_for("brushed_metal.1", "metal_aluminum")[0] == "bare_metal"


def test_mapping_shader_keywords():
    assert nr.physical_material_for("shader_mollusk.007", "diffuse")[0] == "shell_calcite"
    assert nr.physical_material_for("shader_coral", "diffuse")[0] == "shell_calcite"
    assert nr.physical_material_for("shader_succulent", "diffuse")[0] == "vegetation_leaf"
    assert nr.physical_material_for("shader_bone.002", "diffuse")[0] == "shell_calcite"
    # unknown dielectric fallback (not grayscale-RGB)
    assert nr.physical_material_for("shader_mystery", "diffuse")[0] == "unknown_dielectric"


def test_shell_mineral_is_low_confidence():
    # decorative shells are often painted resin -> must not be asserted high-confidence
    _, conf = nr.physical_material_for("shader_mollusk", "diffuse")
    assert conf == "low"


def test_metal_glass_have_no_diffuse_albedo():
    for pmat in ("bare_metal", "clear_glass"):
        info = nr.nir_reflectance(pmat)
        assert info["albedo_channel"] is False
    # synthesise returns None -> caller must use Fresnel/transmission path
    rgb = np.random.rand(8, 8, 3).astype(np.float32)
    assert nr.synthesize_nir_texture(rgb, "bare_metal") is None
    assert nr.synthesize_nir_texture(rgb, "clear_glass") is None
    assert nr.nir_scalar_reflectance("shader_glass", "glass") is None


def test_vegetation_nir_is_not_f_of_rgb():
    """Two leaf regions with very different visible green must land at ~the same
    NIR reflectance (red-edge plateau), i.e. NIR is NOT derived from RGB."""
    dark_green = np.tile(np.array([0.03, 0.12, 0.03], np.float32), (16, 16, 1))
    bright_green = np.tile(np.array([0.05, 0.55, 0.05], np.float32), (16, 16, 1))
    a = nr.synthesize_nir_texture(dark_green, "vegetation_leaf")
    b = nr.synthesize_nir_texture(bright_green, "vegetation_leaf")
    # both near the class mean, and their gap is far smaller than the RGB gap
    mean = nr.nir_reflectance("vegetation_leaf")["mean"]
    assert abs(a.mean() - mean) < 0.05 and abs(b.mean() - mean) < 0.05
    rgb_gap = bright_green[..., 1].mean() - dark_green[..., 1].mean()  # ~0.43
    nir_gap = abs(b.mean() - a.mean())
    assert nir_gap < 0.2 * rgb_gap


def test_structure_transfer_scales_with_alpha():
    """High rgb_structure_weight (wood) transfers more RGB spatial pattern than
    low (vegetation)."""
    rgb = np.zeros((16, 16, 3), np.float32)
    rgb[:8] = 0.1
    rgb[8:] = 0.6  # a bright/dark split
    wood = nr.synthesize_nir_texture(rgb, "wood")        # alpha ~0.55
    veg = nr.synthesize_nir_texture(rgb, "vegetation_leaf")  # alpha ~0.05
    wood_contrast = wood[8:].mean() - wood[:8].mean()
    veg_contrast = veg[8:].mean() - veg[:8].mean()
    assert wood_contrast > veg_contrast > 0


def test_output_is_clipped_linear():
    rgb = np.full((8, 8, 3), 10.0, np.float32)  # absurdly bright
    out = nr.synthesize_nir_texture(rgb, "ceramic")
    assert out.dtype == np.float32
    assert out.max() <= 0.95 and out.min() >= 0.0


def test_band_940_available():
    i854 = nr.nir_reflectance("vegetation_leaf", 854)
    i940 = nr.nir_reflectance("vegetation_leaf", 940)
    assert i854["band"] == 854 and i940["band"] == 940
    assert 0 < i940["mean"] <= 1


def test_pseudo_nir_preserves_texture_and_range():
    # V-shape: extremes -> bright, mid-gray -> darkest; texture (spatial variance) survives
    rgb = np.array([[[0.0, 0, 0], [0.5, 0.5, 0.5], [1, 1, 1], [0.2, 0.8, 0.1]]], np.float32)
    out = nr.pseudo_nir_albedo(rgb)
    assert out.shape == (1, 4)
    assert abs(out[0, 0] - out[0, 2]) < 1e-6          # black and white both -> 0.93
    assert out[0, 1] < out[0, 0]                        # mid-gray is the darkest
    assert 0.46 <= out.min() and out.max() <= 0.931    # weights sum 0.93
    # a textured input keeps variance (unlike the class-prior constant)
    tex = np.random.default_rng(0).random((16, 16, 3)).astype(np.float32)
    assert nr.pseudo_nir_albedo(tex).std() > 0.02


def test_pseudo_nir_accepts_2d():
    assert nr.pseudo_nir_albedo(np.array([[0.3, 0.7]], np.float32)).shape == (1, 2)


def test_hybrid_preserves_texture_at_class_mean():
    # a textured albedo -> NIR keeps structure (not flat) BUT centered on class prior
    rng = np.random.default_rng(1)
    base = 0.4 + 0.15 * rng.random((48, 48))
    base3 = np.repeat(base[..., None], 3, -1)
    out = nr.synthesize_nir_texture(base3, "wood")
    info = nr.nir_reflectance("wood")
    assert out.std() > 0.05                                   # texture NOT washed flat
    assert abs(out.mean() - info["mean"]) < 0.08              # mean ≈ class prior (physics)
    assert out.min() >= info["min"] - 1e-3 and out.max() <= min(info["max"], 0.95) + 1e-3
    # low-structure class transfers LESS RGB texture than a high one
    low = nr.synthesize_nir_texture(base3, "printed_surface")
    assert low.std() < out.std()
