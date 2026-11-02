"""Resolve CPU-importable lossless decoded native assets;retain original GLB receipts."""
import json,hashlib,shutil
from pathlib import Path
R=Path(__file__).resolve().parents[3];roots=[p for p in Path('/bean/datasets/hssd/derived_alpha').iterdir() if p.is_dir() and p.name.endswith('pipeline_v1')];sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
for scene in ['skyline_penthouse_08','double_height_duplex_09']:
 d=R/'data/venue_refs/floor_plans_v3'/scene;mp=d/'native_assets_r002.json';j=json.loads(mp.read_text());(d/'native_assets_original_glb_r002.json').write_text(json.dumps(j,indent=2))
 for role,e in j.items():
  src=next(r/'assets'/e['id']/'asset.gltf' for r in roots if(r/'assets'/e['id']/'asset.gltf').exists());dest=d/'native_assets_decoded'/e['id'];shutil.copytree(src.parent,dest,dirs_exist_ok=True);e['original_glb_source_sha256']=e['source_sha256'];e['path']=str((dest/'asset.gltf').relative_to(R));e['source_sha256']=sha(dest/'asset.gltf');e['decoded_source']=str(src);g=json.loads(src.read_text());e['dependencies']=[{'uri':x['uri'],'sha256':sha(dest/x['uri'])} for x in g.get('buffers',[])+g.get('images',[]) if'uri'in x and not x['uri'].startswith('data:')]
 mp.write_text(json.dumps(j,indent=2))
 for name in ['build_r002_job.json']:
  p=d/name
  if p.exists():shutil.copy2(p,d/'build_r002_attempt1_unsupported_KTX.json')
