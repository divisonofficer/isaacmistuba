#!/usr/bin/env python3
"""Build a resumable, hash-locked 2K CC0 structural material corpus from Poly Haven."""
from __future__ import annotations
import argparse, hashlib, json, os, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ASSETS = """beige_wall_001 blue_plaster_wall clay_plaster concrete_wall_001 concrete_wall_005 concrete_wall_007
concrete_layers_02 grey_plaster grey_plaster_02 plaster_grey_04 plastered_wall plastered_wall_02
plastered_wall_03 white_plaster_02 white_plaster_rough_01 white_stucco worn_cracked_plaster
brick_wall_001 brick_wall_003 brick_wall_005 brick_wall_08 brick_wall_09 concrete_block_wall
concrete_block_wall_02 stone_tiles stone_tiles_02 floor_tiles_02 floor_tiles_04 granite_tile_03
tiled_floor_001 square_floor concrete_floor concrete_floor_01 concrete_floor_02 concrete_floor_worn_001
smooth_concrete_floor damaged_concrete_floor_02 wood_plank_wall wood_planks_grey weathered_planks
white_planks_clean bamboo_wall blue_painted_planks""".split()
UA = "robomituba-ir-pbr/1.0 (research dataset builder)"

def fetch_json(url: str):
    request=urllib.request.Request(url,headers={"User-Agent":UA})
    with urllib.request.urlopen(request,timeout=60) as r: return json.load(r)
def md5(path: Path):
    h=hashlib.md5()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1<<20),b''):h.update(b)
    return h.hexdigest()
def sha(path: Path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1<<20),b''):h.update(b)
    return h.hexdigest()
def download(url: str,path: Path,expected: str):
    if path.is_file() and md5(path)==expected:return
    tmp=path.with_suffix(path.suffix+'.partial'); path.parent.mkdir(parents=True,exist_ok=True)
    req=urllib.request.Request(url,headers={"User-Agent":UA})
    with urllib.request.urlopen(req,timeout=300) as r, tmp.open('wb') as w:
        while chunk:=r.read(1<<20):w.write(chunk)
    if md5(tmp)!=expected: tmp.unlink(missing_ok=True);raise RuntimeError(f"checksum mismatch {path.name}")
    os.replace(tmp,path)
def pick(files, kind):
    node=files.get(kind,{}).get('2k',{})
    for ext in ('jpg','png'):
        if ext in node:return node[ext]
    raise KeyError(f"missing 2k {kind}")
def main():
 p=argparse.ArgumentParser();p.add_argument('--out',type=Path,default=Path('/bean/ir_pbr_assets/cc0_structural_v1'));p.add_argument('--limit',type=int);p.add_argument('--workers',type=int,default=4);p.add_argument('--assets',nargs='*');a=p.parse_args()
 root=a.out.resolve(); ids=(a.assets or ASSETS); ids=ids[:a.limit] if a.limit else ids
 catalog=fetch_json('https://api.polyhaven.com/assets?t=textures'); records=[]; tasks=[]
 for aid in ids:
  if aid not in catalog: print(f'[skip] unavailable {aid}');continue
  try:
   files=fetch_json(f'https://api.polyhaven.com/files/{aid}')
   selected={'base_color':pick(files,'Diffuse'),'roughness':pick(files,'Rough'),'normal_gl':pick(files,'nor_gl')}
  except Exception as e: print(f'[skip] {aid}: {e}');continue
  maps={}; checks={}
  for key,item in selected.items():
   ext=item['url'].rsplit('.',1)[-1].split('?')[0]; rel=f'polyhaven/{aid}/{key}.{ext}'; maps[key]=rel; tasks.append((item['url'],root/rel,item['md5']))
  dims=catalog[aid].get('dimensions') or [1000,1000]
  records.append({'id':f'polyhaven_{aid}','provider':'Poly Haven','source_url':f'https://polyhaven.com/a/{aid}','asset_id':aid,'license':'CC0-1.0','maps':maps,'sha256':checks,'physical_size_m':{'width':float(dims[0])/1000,'height':float(dims[1])/1000},'semantic_compatibility':['wall','floor','ceiling','panel','column'],'scale_range':[0.25,4.0]})
 with ThreadPoolExecutor(max_workers=max(1,a.workers)) as ex:
  futures=[ex.submit(download,*task) for task in tasks]
  for n,f in enumerate(as_completed(futures),1):f.result();print(f'[download] {n}/{len(tasks)}',flush=True)
 for rec in records:
  rec['sha256']={key:sha(root/rel) for key,rel in rec['maps'].items()}
 payload={'schema':'robomituba.ir_external_structural_pbr_registry.v1','registry_version':'cc0_structural_v1','materials':records}
 out=root/'registry.lock.json'; tmp=out.with_suffix('.tmp');tmp.write_text(json.dumps(payload,indent=2)+'\n');os.replace(tmp,out)
 print(f'[done] materials={len(records)} root={root} registry={out}')
if __name__=='__main__':main()
