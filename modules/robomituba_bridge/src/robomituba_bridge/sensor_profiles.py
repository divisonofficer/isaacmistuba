"""
Real-camera sensor profile registry.

Each SensorProfile describes the physical characteristics of a camera that can be
spawned in simulation.  The profiles are derived from manufacturer datasheets:

  - JAI FS-1600D-10GE  (FS-1600D-10GE_Ver.1.6_July2023)
  - LUCID TRT053S       (TRT053S v1.40.0.0 Documentation)

Rendering-side notes
--------------------
- ``mitsuba_modalities`` lists the modality IDs (as defined in
  ``mitsuba_converter.multimodal``) that this sensor can produce.
- ``nir_wavelength_range_nm`` / ``swir_wavelength_range_nm`` are the band limits
  used when configuring the Mitsuba spectral integrator for NIR/SWIR channels.
- Resolution stored here is the *native* full-frame resolution.  Override via
  CameraSpec.resolution when spawning at a lower resolution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SpectralBand:
    name: str
    wavelength_min_nm: float
    wavelength_max_nm: float
    peak_nm: Optional[float] = None
    description: str = ""


@dataclass
class SensorProfile:
    # ── Identity ──────────────────────────────────────────────────────────────
    sensor_id: str
    display_name: str
    manufacturer: str
    model: str

    # ── Optical / imaging ─────────────────────────────────────────────────────
    sensor_type: str           # "rgb" | "nir" | "rgb_nir_dual" | "swir" | "hdr"
    resolution_wh: tuple[int, int]
    pixel_size_um: float       # μm, square pixels assumed unless noted
    bit_depth: int             # native ADC depth
    fps_max: float             # at full resolution, in frames/second
    spectral_bands: list[SpectralBand] = field(default_factory=list)

    # ── Interface / mount ─────────────────────────────────────────────────────
    interface: str = ""
    lens_mount: str = ""

    # ── Rendering hints ───────────────────────────────────────────────────────
    # Modality strings match mitsuba_converter.multimodal.SUPPORTED_MODALITIES
    mitsuba_modalities: list[str] = field(default_factory=list)
    mitsuba_variant_hint: str = "cuda_rgb"  # suggested mi.variant()

    notes: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# JAI FS-1600D-10GE
# Digital 2-CMOS Progressive Scan Bayer Color + NIR Camera
# Source: FS-1600D-10GE User Manual Ver.1.6, July 2023
# ─────────────────────────────────────────────────────────────────────────────
JAI_FS1600D = SensorProfile(
    sensor_id="jai_fs1600d_10ge",
    display_name="JAI FS-1600D-10GE (RGB+NIR)",
    manufacturer="JAI",
    model="FS-1600D-10GE",

    sensor_type="rgb_nir_dual",

    # Spec sheet p.80: "Effective image pixel 1440(H) x 1080(V)"
    # Pixel size: "3.45 μm (H) x 3.45 μm (V)"
    resolution_wh=(1440, 1080),
    pixel_size_um=3.45,

    # Max 12-bit; 226 fps measured at BayerRG8 + Mono8 @ 10 Gbps
    bit_depth=12,
    fps_max=226.0,

    spectral_bands=[
        # Sensor 0 / Stream 0  — Bayer colour (visible, IR-cut filter installed)
        # Spectral response chart p.82: peaks R≈620 nm, G≈530 nm, B≈460 nm
        SpectralBand(
            name="blue",
            wavelength_min_nm=400,
            wavelength_max_nm=520,
            peak_nm=460,
            description="Sensor 0 Bayer Blue channel",
        ),
        SpectralBand(
            name="green",
            wavelength_min_nm=480,
            wavelength_max_nm=620,
            peak_nm=530,
            description="Sensor 0 Bayer Green channel",
        ),
        SpectralBand(
            name="red",
            wavelength_min_nm=560,
            wavelength_max_nm=700,
            peak_nm=620,
            description="Sensor 0 Bayer Red channel (IR-cut prevents leakage above ~700 nm)",
        ),
        # Sensor 1 / Stream 1  — Monochrome NIR (no IR-cut filter)
        # Spectral response chart p.82: NIR curve rises from ~700 nm,
        # peaks ~780 nm, falls to near zero by ~1000 nm
        SpectralBand(
            name="nir",
            wavelength_min_nm=700,
            wavelength_max_nm=1000,
            peak_nm=780,
            description="Sensor 1 NIR monochrome channel (simultaneous with RGB)",
        ),
    ],

    interface="10GBase-T / 5GBase-T / 2.5GBase-T / 1000Base-T  (GigE Vision 2.0, IEEE 802.3af)",
    lens_mount="C-mount",

    mitsuba_modalities=["rgb", "depth", "active_nir_intensity", "hazard_mask"],
    mitsuba_variant_hint="cuda_rgb",

    notes=(
        "Dual-stream simultaneous output: Sensor 0 outputs Bayer RGB "
        "(BayerRG8/10/12 or RGB8/10/12) with an IR-cut filter; "
        "Sensor 1 outputs NIR monochrome (Mono8/10/12) without IR-cut. "
        "Both sensors share the same 1440×1080 global-shutter CMOS die. "
        "NIR binning (1×2, 2×1, 2×2) available on Sensor 1 only. "
        "Operating temp: −5 °C to +45 °C."
    ),
)


# ─────────────────────────────────────────────────────────────────────────────
# LUCID Vision Labs TRT053S  (Triton SWIR)
# Sony SenSWIR InGaAs GigE PoE SWIR camera, IP67
# Source: TRT053S v1.40.0.0 Documentation (Lucid Vision Labs, 2025)
#
# NOTE: The documentation package does not include the optical sensor spec
# table (resolution / pixel size).  Values below are derived from LUCID's
# public product page for the TRT053S (Sony IMX991-class SenSWIR, ~0.53 MP).
# Verify against the physical unit before deployment.
# ─────────────────────────────────────────────────────────────────────────────
LUCID_TRT053S = SensorProfile(
    sensor_id="lucid_trt053s",
    display_name="LUCID TRT053S (SWIR / HDR)",
    manufacturer="LUCID Vision Labs",
    model="TRT053S",

    sensor_type="swir",

    # Sony SenSWIR InGaAs ~0.53 MP  (800 × 600 estimated; confirm from product page)
    resolution_wh=(800, 600),
    pixel_size_um=5.0,   # typical InGaAs SenSWIR pixel pitch; confirm from product page

    # InGaAs ADC: typically 12-bit
    bit_depth=12,
    # GigE 1 Gbps with 800×600 ~12-bit → theoretical ~145 fps;
    # practical figure depends on firmware; listed as placeholder
    fps_max=120.0,

    spectral_bands=[
        # Sony SenSWIR InGaAs covers visible + SWIR.
        # The sensor is sensitive from ~400 nm up to ~1700 nm.
        # Primary working band for industrial SWIR use is 900–1700 nm.
        SpectralBand(
            name="visible_extended",
            wavelength_min_nm=400,
            wavelength_max_nm=900,
            description="Extended visible sensitivity of InGaAs (lower efficiency than primary SWIR band)",
        ),
        SpectralBand(
            name="swir",
            wavelength_min_nm=900,
            wavelength_max_nm=1700,
            peak_nm=1100,
            description="Primary SWIR band — glass/plastic transparent, moisture detectable",
        ),
    ],

    interface="GigE Vision (1000Base-T, PoE IEEE 802.3af/at)",
    lens_mount="C-mount",

    # "active_nir_intensity" is the closest existing modality for near-IR active imaging;
    # SWIR beyond 1000 nm requires a spectral Mitsuba variant.
    mitsuba_modalities=["active_nir_intensity", "depth"],
    mitsuba_variant_hint="cuda_spectral",

    notes=(
        "IP67 rated.  No TEC (thermoelectric cooler) — user must manage thermal "
        "dissipation.  Sony SenSWIR InGaAs sensor: captures both visible and SWIR "
        "light (400–1700 nm); glass, water, and many plastics appear transparent "
        "in the 900–1700 nm band.  Powered via PoE (IEEE 802.3af/at) or GPIO "
        "(12–24 V DC).  Operating temperature: −20 to +55 °C ambient.  "
        "RESOLUTION NOTE: 800×600 and pixel_size 5.0 μm are estimates — "
        "verify against the LUCID TRT053S product datasheet."
    ),
)


# ─────────────────────────────────────────────────────────────────────────────
# Registry
# ─────────────────────────────────────────────────────────────────────────────
SENSOR_PROFILES: dict[str, SensorProfile] = {
    JAI_FS1600D.sensor_id: JAI_FS1600D,
    LUCID_TRT053S.sensor_id: LUCID_TRT053S,
}


def get_profile(sensor_id: str) -> SensorProfile:
    """Return a SensorProfile by ID, raising KeyError if not found."""
    try:
        return SENSOR_PROFILES[sensor_id]
    except KeyError:
        available = ", ".join(SENSOR_PROFILES)
        raise KeyError(f"Unknown sensor_id {sensor_id!r}. Available: {available}") from None


def list_profiles() -> list[SensorProfile]:
    return list(SENSOR_PROFILES.values())
