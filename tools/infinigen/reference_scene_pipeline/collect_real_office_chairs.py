"""Copy actual product assets and dependencies into project; never use external paths at render time."""
import pathlib,json,shutil,hashlib,struct
ROOT=pathlib.Path(__file__).resolve().parents[3];out=ROOT/'assets/opticalnav_curated/office_reference_real_chairs';assert not out.exists();out.mkdir();sources=[pathlib.Path('/bean/ir_dataset/abo_v1/abo_object_index.json'),ROOT/'vendor_datasets/hssd_objects/hssd_object_index.json'];prefixes=['B06W5XBL3D','B016ID34BO','HSSD_005b673d5ded782d54b'];entries=[]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
for idx in sources:
 for e in json.loads(idx.read_text())['objects']:
  if not any(e['id'].startswith(x) for x in prefixes):continue
  src=pathlib.Path(e['path']);dest=out/e['id'];dest.mkdir();target=dest/src.name;shutil.copyfile(src,target);assert sha(src)==sha(target);deps=[]
  if src.suffix=='.gltf':doc=json.loads(src.read_text())
  else:
   with src.open('rb') as f:
    magic,version,size=struct.unpack('<III',f.read(12));assert magic==0x46546c67 and version==2;length,kind=struct.unpack('<II',f.read(8));assert kind==0x4e4f534a;doc=json.loads(f.read(length))
  for kind in ['buffers','images']:
   for item in doc.get(kind,[]):
    uri=item.get('uri','')
    if not uri or uri.startswith('data:'):continue
    rel=pathlib.Path(uri);assert not rel.is_absolute() and '..' not in rel.parts;original=src.parent/rel;copied=dest/rel;copied.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(original,copied);assert sha(original)==sha(copied);deps.append({'uri':uri,'sha256':sha(copied)})
  native={**e,'original_path':str(src),'path':str(target),'original_index':str(idx),'source_sha256':sha(src),'copied_sha256':sha(target),'dependencies':deps,'visual_acceptance':False};entries.append(native)
assert len(entries)==3
license=pathlib.Path('/bean/ir_dataset/abo_v1/LICENSE-CC-BY-4.0.txt');shutil.copyfile(license,out/license.name)
report={'assets':entries,'project_local_runtime_dependencies':True,'attribution':'Amazon Berkeley Objects (ABO),CC BY4.0;original product names andIDs preserved. HSSD Margot derived asset provenance/index andinferred material registry values preserved,not claimed measuredPBR.','abo_license_file':str(out/license.name),'license_sha256':sha(out/license.name),'scope':'Three real source chair candidates copied byte-for-byte;no geometry/material replacement orscene integration. Native materials andactual shape must be visually reviewed. Inferred HSSD PBR fields explicitly retained asmetadata.','photorealism_accepted':False};p=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02/real_chair_candidates';p.mkdir(exist_ok=True);(p/'asset_candidates_manifest.json').write_text(json.dumps(report,indent=2)+'\n');print('Copied3 actual chair candidates;allruntime dependencies projectlocal.')
