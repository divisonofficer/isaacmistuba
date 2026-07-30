#!/usr/bin/env python3
"""spatial-PBR A/B 자산에 NIR albedo 합성 + NIR 렌더를 추가한다.

각 자산의 RGB albedo atlas(<oid>_basecolor.png)에서 pseudo-NIR albedo 텍스처를
  nir = max(rgb, 1-rgb) · [0.229, 0.587, 0.114]   (텍스처 디테일 보존)
로 만들고, A 브랜치 scene.xml의 pplastic diffuse_reflectance를 그 텍스처로 교체해
동일 카메라·조명·geometry로 NIR을 렌더(render_modalities)한다. 출력은
dev_report/images/0729_spatial_pbr_ab/<oid>_nir_albedo.png(텍스처) + <oid>_nir.png(렌더).

Env(Device 1): LD_LIBRARY_PATH=/home/jinnyeong/driver-dist:/usr/lib/wsl/lib
  PYTHONPATH=build/mitsuba3-optix7/python  python=~/miniconda3/envs/openusd_pip/bin/python
"""
import sys, re, numpy as np
from pathlib import Path
from PIL import Image
for _m in ('robomituba_bridge','mitsuba_converter','navigation_dataset'): sys.path.insert(0,f'modules/{_m}/src')
import mitsuba as mi
mi.set_variant('cuda_ad_rgb_polarized')
from mitsuba_converter.multimodal import RenderConfig, render_modalities
E=Path('out/spatial_pbr_ab/2026-07-29-final-640-512')
IMG=Path('dev_report/images/0729_spatial_pbr_ab'); PN=Path('/tmp/claude-1000/pbr_pseudonir'); PN.mkdir(parents=True,exist_ok=True)
assets=sorted([p.name for p in (E/'asset_maps').iterdir() if p.is_dir()])
def cam_from_xml(t):
    m=re.search(r'<sensor[^>]*>.*?<transform name="to_world">\s*<matrix value="([^"]+)"',t,re.S)
    vals=[float(x) for x in m.group(1).split()]; return np.array(vals,np.float32).reshape(4,4)
def gray(x): return (np.clip(x,0,1)*255).astype(np.uint8)
for oid in assets:
    cand=sorted(E.glob(f'{oid}/front*/A/scene.xml'))
    if not cand: continue
    t=cand[0].read_text(); cam=cam_from_xml(t)
    bc=re.findall(r'value="([^"]*_basecolor\.png)"',t)
    src=bc[0] if bc and Path(bc[0]).exists() else str(E/'asset_maps'/oid/f'{oid}_basecolor.png')
    a=np.asarray(Image.open(src).convert('RGB')).astype(np.float32)/255.0
    interm=np.maximum(a,1-a); pn=np.clip(interm[...,0]*0.229+interm[...,1]*0.587+interm[...,2]*0.114,0,1)
    pnpath=PN/f'{oid}_pseudonir.png'; Image.fromarray((np.repeat(pn[...,None],3,-1)*255).astype(np.uint8)).save(pnpath)
    Image.fromarray(gray(pn)).save(IMG/f'{oid}_nir_albedo.png')
    for b in set(bc): t=t.replace(b,str(pnpath))
    ts=PN/f'{oid}_nir_scene.xml'; ts.write_text(t)
    cfg=RenderConfig(width=512,height=512,path_spp=512,polar_spp=512,aov_spp=1,path_max_depth=8)
    try:
        res=render_modalities(str(ts),cam,45.0,['rgb'],out_dir=PN/oid,config=cfg,variant='cuda_ad_rgb_polarized')
        rgb=np.asarray(res.results['rgb'].array,np.float32)[...,:3]
        v=(rgb*np.array([0.2126,0.7152,0.0722])).sum(-1); v=v/max(np.percentile(v,99.5),1e-6)
        Image.fromarray((np.clip(v,0,1)**(1/2.2)*255).astype(np.uint8)).save(IMG/f'{oid}_nir.png')
        print(f'  {oid}: NIR OK mean_render={v.mean():.3f} albedo={pn.mean():.3f}')
    except Exception as e:
        import traceback; print(f'  {oid}: FAIL {e}'); traceback.print_exc()
print('done')
