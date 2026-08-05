#!/usr/bin/env python3
"""spatial-PBR A/B 자산에 HYBRID(class-prior + 구조 전이) NIR albedo 렌더를 추가한다 (C안).

A(constant/physical) = flat class-prior      -> render_nir_physical_spatial_pbr.py
B(pseudo)            = max(rgb,1-rgb)·w       -> render_nir_albedo_spatial_pbr.py
C(hybrid, 이 파일)   = nir_reflectance.synthesize_nir_texture:
    D(x)=standardize(logL − LPF(logL));  rho=clip[μ_c(1+β_c·D), min_c, max_c]
  → 클래스 prior가 평균/범위를 정하고 RGB atlas는 국소 구조만 공급(β_c per class).
  metal/glass는 albedo_channel=False(Fresnel)라 제외.
출력: dev_report/images/0729_spatial_pbr_ab/<oid>_nir_hybrid_albedo.png + <oid>_nir_hybrid.png
env: LD_LIBRARY_PATH=... PYTHONPATH=build/mitsuba3-optix7/python python=openusd_pip
"""
import sys, re, json
import numpy as np
from pathlib import Path
from PIL import Image

for m in ('robomituba_bridge', 'mitsuba_converter', 'navigation_dataset'):
    sys.path.insert(0, f'modules/{m}/src')
import mitsuba as mi
mi.set_variant('cuda_ad_rgb_polarized')
from mitsuba_converter.multimodal import RenderConfig, render_modalities
from mitsuba_converter.nir_reflectance import physical_material_for, synthesize_nir_texture, nir_reflectance

E = Path('out/spatial_pbr_ab/2026-07-29-final-640-512')
IMG = Path('dev_report/images/0729_spatial_pbr_ab')
HN = Path('/tmp/claude-1000/pbr_hybridnir'); HN.mkdir(parents=True, exist_ok=True)
man = json.load(open('out/infinigen_imports/kr_20260625/scene_manifest.json'))
units = {u['id']: u for u in man['units']}
assets = sorted([p.name for p in (E / 'asset_maps').iterdir() if p.is_dir()])


def cam(t):
    m = re.search(r'<sensor[^>]*>.*?<matrix value="([^"]+)"', t, re.S)
    return np.array([float(x) for x in m.group(1).split()], np.float32).reshape(4, 4)


def srgb_to_linear(a):
    return np.where(a <= 0.04045, a / 12.92, ((a + 0.055) / 1.055) ** 2.4)


cfg = RenderConfig(width=512, height=512, path_spp=512, polar_spp=512, aov_spp=1, path_max_depth=8)
for oid in assets:
    u = units.get(oid, {})
    slots = u.get('material_slots') or [{'name': '?', 'optical_class': u.get('optical_class', 'diffuse')}]
    sh = slots[0].get('name', '?'); oc = slots[0].get('optical_class', 'diffuse')
    pmat, conf = physical_material_for(sh, oc)
    info = nir_reflectance(pmat, 854)
    if not info['albedo_channel']:
        print(f'  {oid}: {pmat} glass/metal → hybrid NIR None(Fresnel), skip'); continue
    cand = sorted(E.glob(f'{oid}/front*/A/scene.xml'))
    if not cand:
        continue
    t = cand[0].read_text(); C = cam(t)
    bc = re.findall(r'value="([^"]*_basecolor\.png)"', t)
    src = bc[0] if bc and Path(bc[0]).exists() else str(E / 'asset_maps' / oid / f'{oid}_basecolor.png')
    rgb = srgb_to_linear(np.asarray(Image.open(src).convert('RGB'), np.float32) / 255.0)
    nir = synthesize_nir_texture(rgb, pmat, 854)          # (H,W) hybrid NIR albedo
    htex = HN / f'{oid}_hybridnir.png'
    Image.fromarray((np.repeat(np.clip(nir, 0, 1)[..., None], 3, -1) * 255).astype(np.uint8)).save(htex)
    Image.fromarray((np.clip(nir, 0, 1) * 255).astype(np.uint8)).save(IMG / f'{oid}_nir_hybrid_albedo.png')
    for b in set(bc):
        t = t.replace(b, str(htex))
    ts = HN / f'{oid}_scene.xml'; ts.write_text(t)
    try:
        res = render_modalities(str(ts), C, 45.0, ['rgb'], out_dir=HN / oid, config=cfg,
                                variant='cuda_ad_rgb_polarized')
        rr = np.asarray(res.results['rgb'].array, np.float32)[..., :3]
        v = (rr * np.array([0.2126, 0.7152, 0.0722])).sum(-1)
        v = v / max(np.percentile(v, 99.5), 1e-6)
        Image.fromarray((np.clip(v, 0, 1) ** (1 / 2.2) * 255).astype(np.uint8)).save(IMG / f'{oid}_nir_hybrid.png')
        print(f'  {oid}: hybrid NIR OK (pmat={pmat} μ={info["mean"]:.2f} β={info["rgb_structure_weight"]:.2f} '
              f'albedo std={float(nir.std()):.3f})')
    except Exception as e:
        print(f'  {oid}: FAIL {e}')
print('done')
