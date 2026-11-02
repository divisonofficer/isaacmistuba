"""Copy three existing detailed table products and verified native dependencies into project."""
import json,hashlib,shutil,struct
from pathlib import Path
R=Path(__file__).resolve().parents[3];D=R/'data/venue_refs/floor_plans_v3/commercial_office_floor_02/real_table_candidates';D.mkdir(exist_ok=True);A=R/'assets/opticalnav_curated/office_reference_real_tables';assert not A.exists();A.mkdir(parents=True);source=json.load(open(R/'data/venue_refs/floor_plans_v3/commercial_office_floor_02/wood_finish105_pilot/selected_table_source_entries.json'));entries=[];sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
for e in source:
 src=Path(e['path']);dest=A/e['id'];dest.mkdir();out=dest/src.name;shutil.copyfile(src,out);assert sha(src)==sha(out)
 if src.suffix=='.gltf':doc=json.load(open(src))
 else:
  with src.open('rb') as f:
   magic,version,size=struct.unpack('<III',f.read(12));assert magic==0x46546c67 and version==2;length,kind=struct.unpack('<II',f.read(8));assert kind==0x4e4f534a;doc=json.loads(f.read(length))
 deps=[]
 for group in ['buffers','images']:
  for x in doc.get(group,[]):
   uri=x.get('uri','')
   if not uri or uri.startswith('data:'):continue
   rel=Path(uri);assert not rel.is_absolute() and '..' not in rel.parts;target=dest/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src.parent/rel,target);assert sha(target)==sha(src.parent/rel);deps.append({'uri':uri,'sha256':sha(target)})
 entries.append({**e,'original_path':str(src),'path':str(out.relative_to(R)),'source_sha256':sha(src),'copied_sha256':sha(out),'dependencies':deps,'visual_acceptance':False})
license=Path('/bean/ir_dataset/abo_v1/LICENSE-CC-BY-4.0.txt');shutil.copyfile(license,A/license.name)
(D/'asset_manifest.json').write_text(json.dumps({'assets':entries,'attribution':'ABO productB07H8PNQXF:Amazon Berkeley Objects,CC BY4.0,license copied. HSSD products:source IDs/index names andnative material metadata retained;inferred parameters explicitly retained,not measuredBRDF.','scope':'Byte-identical actualproduct meshes/UV/native textures,all runtime files projectlocal. No room adoption orphoto acceptance.'},indent=2));print('COPIED3_REAL_TABLES',flush=True)
