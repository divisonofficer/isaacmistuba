"""Preserve physical edges while interpolating native curved ceramic/fruit normals."""
import argparse,hashlib,json,math
from pathlib import Path
import bpy,bmesh
import numpy as np
ROOT=Path(__file__).resolve().parents[3];p=argparse.ArgumentParser();p.add_argument('--scene',choices=['office','residential'],required=True);a=p.parse_args();office=a.scene=='office';scene='commercial_office_floor_02' if office else 'dual_unit_residential_floor_03';seed=48712502 if office else 48712503;previous=17 if office else 18;revision=18 if office else 19;base=ROOT/'out/infinigen_v2'/f'kr_{scene}_{seed}'/'full';ref=ROOT/'data/venue_refs/floor_plans_v3'/scene;source=base/f'scene_review_r{previous}_packed.blend';out=base/f'scene_candidate_r{revision}.blend';assert not out.exists();bpy.ops.wm.open_mainfile(filepath=str(source));changes=[]
def coordinates_hash(mesh):
 coordinates=np.empty(len(mesh.vertices)*3,dtype=np.float32);mesh.vertices.foreach_get('co',coordinates);return hashlib.sha256(coordinates.tobytes()).hexdigest()
for o in bpy.data.objects:
 if o.type!='MESH' or o.get('reference_scene_owner')!=scene:continue
 slots={i for i,m in enumerate(o.data.materials) if m and m.get('reference_pbr_kind')=='glazed_ceramic'}
 if '/fruit/' in o.get('library_source',''):slots=set(range(len(o.data.materials)))
 if not slots:continue
 old=coordinates_hash(o.data);before=sum(p.use_smooth for p in o.data.polygons);bm=bmesh.new();bm.from_mesh(o.data)
 for face in bm.faces:
  if face.material_index in slots:face.smooth=True
 for edge in bm.edges:
  if not any(face.material_index in slots for face in edge.link_faces):continue
  edge.smooth=len(edge.link_faces)==2 and edge.calc_face_angle(0)<math.radians(35)
 bm.to_mesh(o.data);bm.free();o.data.update();after=coordinates_hash(o.data);assert before<=sum(p.use_smooth for p in o.data.polygons);assert old==after,'Shading pass must not move geometry'
 changes.append({'object':o.name,'faces':len(o.data.polygons),'smooth_faces_before':before,'smooth_faces_after':sum(p.use_smooth for p in o.data.polygons),'unchanged_vertex_sha256':old,'sharp_edge_threshold_degrees':35})
bpy.ops.wm.save_as_mainfile(filepath=str(out));(ref/f'normal_refinement_r{revision}.json').write_text(json.dumps({'source':str(source),'candidate':str(out),'changes':changes,'geometry_coordinates_unchanged':True,'visual_acceptance':False},indent=2));print(json.dumps({'saved':str(out),'curved_objects':len(changes)}),flush=True)
