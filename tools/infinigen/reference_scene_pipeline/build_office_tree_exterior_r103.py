"""Real native-scale tree instances outside the office, bounded exterior trial."""
import bpy,json,hashlib,math
from pathlib import Path
from mathutils import Matrix,Vector
R=Path(__file__).resolve().parents[3];D=R/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';B=R/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full'
S=B/'scene_candidate_r102.blend';out=B/'scene_candidate_r103.blend';assert not out.exists();sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest();before=sha(S)
lib=D/'outdoor_tree_candidates/review_studio.blend';info=json.loads((D/'outdoor_tree_candidates/scope.json').read_text());assert sha(lib)==info['source_sha256'];entry=next(x for x in info['assets'] if x['id']=='PH_tree_small_02')
bpy.ops.wm.open_mainfile(filepath=str(S));existing={o.name:([list(x) for x in o.matrix_world],o.data.name if o.data else None,[m.name if m else None for m in o.data.materials] if o.type=='MESH' else []) for o in bpy.context.scene.objects}
with bpy.data.libraries.load(str(lib),link=False) as (src,dst):dst.objects=list(entry['objects'])
prototype=dst.objects[0];bpy.context.scene.collection.objects.link(prototype);bpy.context.view_layer.update()
points=[prototype.matrix_world@Vector(p) for p in prototype.bound_box];lo=Vector([min(p[k] for p in points) for k in range(3)]);hi=Vector([max(p[k] for p in points) for k in range(3)]);center=Vector(((lo.x+hi.x)/2,(lo.y+hi.y)/2,lo.z));native=prototype.matrix_world.copy();norm=Matrix.Translation(-center)@native
placements=[(2,30,13),(8,29,79),(14,31,161),(24,2.5,29),(25,7,97),(24,13.5,201),(26,20,289),(-8,5,41),(-7,12,137),(-7,19,247),(3,-8,53),(12,-9,193)]
records=[]
for i,(x,y,deg) in enumerate(placements):
 obj=prototype if i==0 else prototype.copy()
 if i:bpy.context.scene.collection.objects.link(obj)
 obj.name=f'Office02_r103_real_tree_{i:02}';obj.matrix_world=Matrix.Translation((x,y,-.02))@Matrix.Rotation(math.radians(deg),4,'Z')@norm
 obj['environment_asset']=True;obj['original_asset_id']=entry['id'];obj['reference_role']='exterior_tree';obj['native_scale_preserved']=True
 pts=[obj.matrix_world@Vector(v) for v in obj.bound_box];low=[min(p[k] for p in pts) for k in range(3)];high=[max(p[k] for p in pts) for k in range(3)]
 assert high[0]<-.5 or low[0]>16.5 or high[1]<-.5 or low[1]>22.5
 records.append({'object':obj.name,'matrix':[list(v) for v in obj.matrix_world],'bounds_lo':low,'bounds_hi':high,'native_faces':len(obj.data.polygons),'shared_mesh':obj.data.name})
# A real planar grade surface, not a proxy building or furnishing. Exterior-only ring excludes office.
verts=[(-80,-80,-.02),(96,-80,-.02),(96,102,-.02),(-80,102,-.02),(0,0,-.02),(16,0,-.02),(16,22,-.02),(0,22,-.02)]
mesh=bpy.data.meshes.new('Office02_r103_exterior_grade');mesh.from_pydata(verts,[],[(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)])
mat=bpy.data.materials.new('Office02_r103_diagnostic_ground');mat.use_nodes=True;bs=mat.node_tree.nodes.get('Principled BSDF');bs.inputs['Base Color'].default_value=(.095,.115,.065,1);bs.inputs['Roughness'].default_value=.92;mesh.materials.append(mat)
ground=bpy.data.objects.new(mesh.name,mesh);bpy.context.scene.collection.objects.link(ground);ground['environment_asset']=True;ground['reference_role']='exterior_grade'
for name,signature in existing.items():
 o=bpy.data.objects[name];actual=([list(x) for x in o.matrix_world],o.data.name if o.data else None,[m.name if m else None for m in o.data.materials] if o.type=='MESH' else []);assert actual==signature,name
for im in bpy.data.images:
 if im.source=='FILE' and not im.packed_file:im.pack()
bpy.ops.wm.save_as_mainfile(filepath=str(out));assert sha(S)==before
meta=json.loads((D/'realism_refinement_r102.json').read_text());meta.update(source=str(S),source_sha256=before,candidate=str(out),candidate_sha256=sha(out),change='Only12native-scale real2M-triangle tree instances and exterior grade ring; existing interior/data/transforms/material bindings preserved, world/source lights/cameras unchanged.',exterior_trees={'asset':entry,'prototype_blend':str(lib),'prototype_sha256':sha(lib),'records':records,'existing_object_count_preserved':len(existing),'grade_object':ground.name,'grade_z_m':-.02,'limitations':'Repeated single species, only foreground trees. Grade is simple diagnostic authored diffuse plane; no city/buildings, scanned landscape, terrain relief or reference-complete exterior. Does not implement held HDR99 or pink modular facade. Full visual and ground/source audits required.'},photorealism_accepted=False)
(D/'realism_refinement_r103.json').write_text(json.dumps(meta,indent=2))
