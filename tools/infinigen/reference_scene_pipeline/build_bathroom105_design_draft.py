"""User request: distinguish 102main bath from mirrored101, using real products.
Bounded one-room style pilot. No WC/door changes and no unvalidated recolouring.
"""
import bpy,hashlib,json,math
from pathlib import Path
from mathutils import Matrix,Vector
R=Path(__file__).resolve().parents[3];D=R/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';P=D/'bathroom105_native_products_v2';B=R/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';S=B/'scene_candidate_r104_draft.blend';O=B/'scene_candidate_r105_draft.blend';sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

def bounds(objects,matrices):
 points=[matrices[o]@v.co for o in objects for v in o.data.vertices]
 return Vector(tuple(min(p[k] for p in points) for k in range(3))),Vector(tuple(max(p[k] for p in points) for k in range(3)))
def world(obj):
 assert not obj.constraints
 return obj.matrix_basis.copy() if obj.parent is None else world(obj.parent)@obj.matrix_parent_inverse@obj.matrix_basis

def main():
 assert not O.exists();before=sha(S);audit=json.loads((P/'saved_source_audit.json').read_text());assert audit['pass'] and sha(P/'review_studio.blend')==audit['source_sha256'];scope=json.loads((P/'review_scope.json').read_text());bpy.ops.wm.open_mainfile(filepath=str(S))
 key='102_bathroom2_vanity';old=[o for o in bpy.context.scene.objects if o.type=='MESH' and (o.get('program_key')==key or str(o.get('program_key','')).startswith(key+'_'))];assert len(old)==2,[(o.name,o.get('program_key')) for o in old];oldmatrices={o:world(o) for o in old};lo,hi=bounds(old,oldmatrices);oldbounds=[list(lo),list(hi)];fz=.11453469842672348;wallx=21.3839653-.0015
 wc_before={o.name:([list(v) for v in o.matrix_basis],hashlib.sha256(repr([tuple(v.co) for v in o.data.vertices]).encode()).hexdigest()) for o in bpy.context.scene.objects if o.type=='MESH' and str(o.get('program_key','')).endswith('_wc')};assert len(wc_before)==10
 removed=[];owned=set(old)
 for obj in old:owned.update(obj.children_recursive)
 for obj in owned:
  removed.append({'object':obj.name,'type':obj.type,'key':obj.get('program_key'),'parent':obj.parent.name if obj.parent else None,'materials':[m.name for m in getattr(obj.data,'materials',[]) if m],'faces':len(obj.data.polygons) if obj.type=='MESH' else None})
 # Replace the complete explicitly parented assembly, including its old tap/
 # handles/formed basin. Keeping child hardware would leave floating duplicates.
 def depth(obj):
  n=0
  while obj.parent is not None:n+=1;obj=obj.parent
  return n
 for obj in sorted(owned,key=depth,reverse=True):bpy.data.objects.remove(obj,do_unlink=True)
 placed=[]
 for role,asset_id in [('vanity','HSSD_fbe362e4c8053cb93331a40b2741687f60795ec3'),('mirror','HSSD_xxxxb8ef2baaxd21fx4695xbdc3x4dde2486271d')]:
  row=next(r for r in scope['assets'] if r['id']==asset_id)
  with bpy.data.libraries.load(str(P/'review_studio.blend'),link=False) as (src,dst):dst.objects=row['objects']
  objects=dst.objects;original=[world(o) for o in objects];matrices={o:Matrix.Rotation(-math.pi/2,4,'Z')@m for o,m in zip(objects,original)}
  a,b=bounds(objects,matrices)
  # Entire native product: faucet mounting backs meet actual east-wall tile plane.
  target_floor=fz if role=='vanity' else fz+1.275
  delta=Vector((wallx-.001-b.x,3.75-(a.y+b.y)/2,target_floor-a.z));final={o:Matrix.Translation(delta)@m for o,m in matrices.items()}
  for j,o in enumerate(objects):
   bpy.context.scene.collection.objects.link(o);o.parent=None;o.matrix_world=final[o];o.name=f'Bath105_102_main_{role}_{j}';o['program_key']=key if role=='vanity' else key+'_mirror';o['audit_kind']='furniture';o['original_asset_id']=asset_id;o['reference_scene_owner']='dual_unit_residential_floor_03'
  a,b=bounds(objects,final)
  if not(a.x>=lo.x-.00001 and a.y>=lo.y-.00001 and b.y<=hi.y+.00001 and b.x<21.3839653):
   (D/'bathroom105_fit_rejection.json').write_text(json.dumps({'role':role,'native_bbox_m':[list(a),list(b)],'old_bbox_m':oldbounds,'reason':'Do not save product outside verified envelope'},indent=2)+'\n')
   raise AssertionError((role,'Native fixture leaves intended floor envelope'))
  placed.append({'role':role,'asset_id':asset_id,'objects':[o.name for o in objects],'bbox_m':[list(a),list(b)],'native_basis_change':'rigid rotation/translation only, original mesh/UV/materials','outside_old_envelope_only_toward_wall_m':max(0,b.x-hi.x),'actual_wall_tile_back_gap_m':wallx-b.x})
 wc_after={o.name:([list(v) for v in o.matrix_basis],hashlib.sha256(repr([tuple(v.co) for v in o.data.vertices]).encode()).hexdigest()) for o in bpy.context.scene.objects if o.type=='MESH' and str(o.get('program_key','')).endswith('_wc')};assert wc_before==wc_after
 bpy.ops.wm.save_as_mainfile(filepath=str(O));assert sha(S)==before
 report={'source':str(S),'source_sha256':before,'draft':str(O),'draft_sha256':sha(O),'old_vanity_bbox_m':oldbounds,'removed_complete_old_parts':removed,'native_products':placed,'unchanged_ten_wc_meshes_and_poses':True,'unchanged_doors_and_global_lights':True,'emissive_geometry_note':'Old joined mirror LED strip removed as part of complete old fixture; no equal-lighting claim for local emitter geometry. Exposure and renderer policy remain matched.','status':'UNACCEPTED_ONE_ROOM_DESIGN_PILOT','remaining':['Verify actual wall mounting/pipe connections and saved-source product identity/collision','Matched102bathroom render and101style context comparison','Extend coherent variants to other mirrored bathrooms only after this room trial','All ten-room navigation/full-source visual review still required'],'photorealism_accepted':False,'dataset_promoted':False}
 (D/'bathroom105_draft_build.json').write_text(json.dumps(report,indent=2)+'\n');print('BATH105_NATIVE_DESIGN_DRAFT_SAVED',flush=True)

if __name__=='__main__':main()
