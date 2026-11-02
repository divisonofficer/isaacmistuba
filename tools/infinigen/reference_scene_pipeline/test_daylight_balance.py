"""Controlled light-ratio experiment: same geometry/materials/world, less uniform ceiling fill."""
import argparse,bpy,json,hashlib,numpy as np
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];p=argparse.ArgumentParser();p.add_argument('--scene',choices=['office','residential'],required=True);a=p.parse_args();office=a.scene=='office';scene='commercial_office_floor_02' if office else 'dual_unit_residential_floor_03';seed=48712502 if office else 48712503;old,rev=(24,25) if office else (30,31);base=ROOT/'out/infinigen_v2'/f'kr_{scene}_{seed}/full';ref=ROOT/'data/venue_refs/floor_plans_v3'/scene;source=base/f'scene_candidate_r{old}.blend';out=base/f'scene_candidate_r{rev}.blend';assert not out.exists();before=hashlib.sha256(source.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(source))
def geometry_hash():
 h=hashlib.sha256()
 for o in sorted(bpy.data.objects,key=lambda o:o.name):
  if o.type!='MESH':continue
  vertices=np.empty(len(o.data.vertices)*3,dtype=np.float32);o.data.vertices.foreach_get('co',vertices);h.update(o.name.encode());h.update(vertices.tobytes());h.update(np.asarray(o.matrix_world,dtype=np.float32).tobytes())
 return h.hexdigest()
original=geometry_hash();lights=[]
for o in bpy.data.objects:
 if o.type!='LIGHT':continue
 ratio=None
 if office and o.name.startswith(('office02_area','office02_support_area')):ratio=.5
 elif not office and o.name.startswith('res03_area_'):
  key=o.name[len('res03_area_'):]
  if any(t in key for t in ('master','bedroom','living','kitchen','balcony')):ratio=.5
  elif 'dressing' in key:ratio=.6
 if ratio is not None:
  oldenergy=o.data.energy;o.data.energy*=ratio;lights.append({'name':o.name,'before_w':oldenergy,'after_w':o.data.energy})
assert geometry_hash()==original;bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(source.read_bytes()).hexdigest()==before
(ref/f'realism_refinement_r{rev}.json').write_text(json.dumps({'source':str(source),'candidate':str(out),'experiment':'Reduce uniform ceiling fill relative to unchanged window/sky sources. No exposure, material, geometry or world change.','lights':lights,'unchanged_geometry_sha256':original,'photorealism_accepted':False,'requires':'Same-camera A/B; darker alone is not success.'},indent=2));print(json.dumps({'saved':str(out),'lights_changed':len(lights)}),flush=True)
