"""Copy original semantic HSSD native product files, no geometry invention."""
import csv,json,hashlib,shutil
from pathlib import Path
R=Path(__file__).resolve().parents[3];rows={r['id']:r for r in csv.DictReader(open('/bean/datasets/hssd/hssd-hab/semantics/objects.csv'))}
ids={'island':'09b6f703f78d35692bc3e251c75ccdc131b8f55c','desk':'3be598222ead1f8c2186660e3b0bda9a8a10a1c8','wardrobe':'0486ae7dd0b011240a162dc0ff1d96e2cac23dca','bath':'4106160be8e18d73aa704da0ed993aed8175b4d4','sink_cabinet':'0356ddbfa55a90611ee1f6ecbf851dd5b8d3cee9','kitchen_unit':'10444a1165c1745f960eb6183d24dd05b60e781f','oven':'00b0d5e167ae6b42666de010025efad4506563f1','washer':'00b285ed70673826ccb6941929a64abfaf5f9239'}
for scene in ['skyline_penthouse_08','double_height_duplex_09']:
 d=R/'data/venue_refs/floor_plans_v3'/scene;entries={};a=d/'native_assets';a.mkdir(exist_ok=True)
 for role,id in ids.items():
  s=Path('/bean/datasets/hssd/hssd-hab/objects')/id[0]/(id+'.glb');p=a/(id+'.glb');assert s.exists();shutil.copy2(s,p) if not p.exists() else None;sha=hashlib.sha256(p.read_bytes()).hexdigest();assert sha==hashlib.sha256(s.read_bytes()).hexdigest();entries[role]={'id':id,'path':str(p.relative_to(R)),'source_sha256':sha,'source_file':str(s),'semantic_name':rows[id]['name'],'aligned_dims_yup_m':rows[id]['aligned.dims'],'profile_policy':'Original native linked materials retained; invalid constant IOR<=0 repaired explicitly to1.5 only; default material role/visual quality unverified'}
 (d/'native_assets_r002.json').write_text(json.dumps(entries,indent=2))
