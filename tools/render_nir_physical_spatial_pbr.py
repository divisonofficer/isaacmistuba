#!/usr/bin/env python3
"""spatial-PBR A/B 자산에 물리(class-prior) NIR albedo 렌더를 추가한다.

nir_reflectance.py의 optical_class→ρ854(class-prior 상수)를 flat 텍스처로 만들어
A 브랜치 pplastic diffuse_reflectance에 넣어 렌더. metal/glass는 None(Fresnel)이라 제외.
출력: dev_report/images/0729_spatial_pbr_ab/<oid>_nir_phys_albedo.png + <oid>_nir_phys.png
pseudo 버전은 tools/render_nir_albedo_spatial_pbr.py 참고. render_modalities 필수(raw render=검정).
"""
import sys, re, numpy as np
from pathlib import Path
from PIL import Image
for m in ('robomituba_bridge','mitsuba_converter','navigation_dataset'): sys.path.insert(0,f'modules/{m}/src')
import mitsuba as mi, json
mi.set_variant('cuda_ad_rgb_polarized')
from mitsuba_converter.multimodal import RenderConfig, render_modalities
from mitsuba_converter.nir_reflectance import nir_scalar_reflectance
E=Path('out/spatial_pbr_ab/2026-07-29-final-640-512'); IMG=Path('dev_report/images/0729_spatial_pbr_ab')
PN=Path('/tmp/claude-1000/pbr_physnir'); PN.mkdir(parents=True,exist_ok=True)
man=json.load(open('out/infinigen_imports/kr_20260625/scene_manifest.json')); units={u['id']:u for u in man['units']}
assets=sorted([p.name for p in (E/'asset_maps').iterdir() if p.is_dir()])
def cam(t):
    m=re.search(r'<sensor[^>]*>.*?<matrix value="([^"]+)"',t,re.S); return np.array([float(x) for x in m.group(1).split()],np.float32).reshape(4,4)
cfg=RenderConfig(width=512,height=512,path_spp=512,polar_spp=512,aov_spp=1,path_max_depth=8)
for oid in assets:
    u=units.get(oid,{}); slots=u.get('material_slots') or [{'name':'?','optical_class':u.get('optical_class','diffuse')}]
    sh=slots[0].get('name','?'); oc=slots[0].get('optical_class','diffuse')
    scal=nir_scalar_reflectance(sh,oc,854)
    if scal is None:
        print(f'  {oid}: glass/metal → 물리 NIR None(Fresnel), 건너뜀'); continue
    cand=sorted(E.glob(f'{oid}/front*/A/scene.xml'))
    if not cand: continue
    t=cand[0].read_text(); C=cam(t)
    bc=re.findall(r'value="([^"]*_basecolor\.png)"',t)
    src=bc[0] if bc and Path(bc[0]).exists() else str(E/'asset_maps'/oid/f'{oid}_basecolor.png')
    sz=Image.open(src).size
    flat=np.full((sz[1],sz[0]),float(scal),np.float32)
    ftex=PN/f'{oid}_physnir.png'; Image.fromarray((np.repeat(np.clip(flat,0,1)[...,None],3,-1)*255).astype(np.uint8)).save(ftex)
    Image.fromarray((np.clip(flat,0,1)*255).astype(np.uint8)).save(IMG/f'{oid}_nir_phys_albedo.png')  # flat gray
    for b in set(bc): t=t.replace(b,str(ftex))
    ts=PN/f'{oid}_scene.xml'; ts.write_text(t)
    try:
        res=render_modalities(str(ts),C,45.0,['rgb'],out_dir=PN/oid,config=cfg,variant='cuda_ad_rgb_polarized')
        rgb=np.asarray(res.results['rgb'].array,np.float32)[...,:3]
        v=(rgb*np.array([0.2126,0.7152,0.0722])).sum(-1); v=v/max(np.percentile(v,99.5),1e-6)
        Image.fromarray((np.clip(v,0,1)**(1/2.2)*255).astype(np.uint8)).save(IMG/f'{oid}_nir_phys.png')
        print(f'  {oid}: 물리 NIR OK (ρ={scal} flat, {oc})')
    except Exception as e:
        print(f'  {oid}: FAIL {e}')
print('done')
