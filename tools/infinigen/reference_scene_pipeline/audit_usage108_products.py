"""Verify studio geometry/UV against native products and all packed images against source bytes."""
import bpy,json,hashlib,struct,sys,collections
from pathlib import Path
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(Path(__file__).parent));from curated_gltf_materials import import_curated_gltf,preserve_native_packed_image
D=R/'data/venue_refs/floor_plans_v3/commercial_office_floor_02/usage108_products';S=D/'review_studio.blend';sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest();source_sha=sha(S);entries=json.load(open(D/'asset_manifest.json'))['assets'];bpy.ops.wm.open_mainfile(filepath=str(S));errors=[];rows=[]
def fingerprint(o):
 h=hashlib.sha256();h.update(repr(([tuple(v.co) for v in o.data.vertices],[tuple(f.vertices) for f in o.data.polygons],[[tuple(x.uv) for x in uv.data] for uv in o.data.uv_layers])).encode());return h.hexdigest()
original={e['id']:collections.Counter(fingerprint(o) for o in bpy.context.scene.objects if o.type=='MESH' and o.get('original_asset_id')==e['id']) for e in entries};allowed=set()
for e in entries:
 for dep in e['dependencies']:allowed.add(dep['sha256'])
 path=R/e['path']
 if path.suffix=='.glb':
  raw=path.read_bytes();length,kind=struct.unpack('<II',raw[12:20]);doc=json.loads(raw[20:20+length]);binlen,bintype=struct.unpack('<II',raw[20+length:28+length]);blob=raw[28+length:28+length+binlen]
  for im in doc.get('images',[]):
   if 'bufferView' in im:
    v=doc['bufferViews'][im['bufferView']];offset=v.get('byteOffset',0);allowed.add(hashlib.sha256(blob[offset:offset+v['byteLength']]).hexdigest())
images=[]
for im in {n.image for m in bpy.data.materials if m.use_nodes for n in m.node_tree.nodes if n.type=='TEX_IMAGE' and n.image}:
 rec=preserve_native_packed_image(im);rec['native_encoded_bytes_match']=rec['packed_sha256'] in allowed;images.append(rec)
 if not rec['native_encoded_bytes_match']:errors.append('Non-native encoded image:'+im.name)
for e in entries:
 new,objects,profile=import_curated_gltf(e,repair_nonpositive_ior=1.5);actual=collections.Counter(fingerprint(o) for o in objects);ok=actual==original[e['id']];rows.append({'id':e['id'],'studio_mesh_count':sum(original[e['id']].values()),'native_geometry_uv_identical':ok,'native_triangles':e['triangles']})
 if not ok:errors.append(e['id']+':native_geometry_uv_changed')
assert sha(S)==source_sha;report={'source':str(S),'source_sha256':source_sha,'assets':rows,'images':images,'errors':errors,'pass':not errors,'scope':'Actual native local vertices/polygons/UV multisets and encoded image bytes preserved. No image-based material/shape orroom placement acceptance.'};(D/'saved_source_audit.json').write_text(json.dumps(report,indent=2));assert not errors,errors;print('USAGE_PRODUCT_SOURCE_AUDIT_PASS',flush=True)
