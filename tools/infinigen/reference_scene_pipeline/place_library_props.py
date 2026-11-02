"""Native library props at physical size with triangle-mesh support contacts."""
import argparse,json,math
from pathlib import Path
import bpy
from mathutils import Vector,Matrix
from mathutils.bvhtree import BVHTree
from surface_realism import glazed_ceramic,enrich,add,signed,clamp
from material_detail import material,noise
ROOT=Path(__file__).resolve().parents[3];LIB=ROOT/'data/object_library_v2'
p=argparse.ArgumentParser();p.add_argument('--scene',choices=['office','residential'],required=True);a=p.parse_args();office=a.scene=='office';scene='commercial_office_floor_02' if office else 'dual_unit_residential_floor_03';seed=48712502 if office else 48712503;previous=16 if office else 17;revision=17 if office else 18;base=ROOT/'out/infinigen_v2'/f'kr_{scene}_{seed}'/'full';ref=ROOT/'data/venue_refs/floor_plans_v3'/scene;out=base/f'scene_candidate_r{revision}.blend';assert not out.exists();bpy.ops.wm.open_mainfile(filepath=str(base/f'scene_candidate_r{previous}.blend'))
removed_modifiers=[]
for o in bpy.data.objects:
 if o.type=='MESH' and (len(o.data.polygons)>20000 or 'shower' in o.get('program_key','')):
  for mod in list(o.modifiers):
   if mod.name in ('realistic_manufactured_edge','surface_weighted_normals'):removed_modifiers.append([o.name,mod.name]);o.modifiers.remove(mod)
# Reduce only the additional metal variation. Preserve measured scan response.
for m in bpy.data.materials:
 if m.get('reference_pbr_kind')!='bare_metal' or not m.use_nodes:continue
 n=m.node_tree.nodes;l=m.node_tree.links;bs=next((x for x in n if x.type=='BSDF_PRINCIPLED'),None)
 if not bs:continue
 scan=next((x for x in n if x.type=='MAP_RANGE' and abs(x.inputs['To Min'].default_value-.24)<1e-5 and abs(x.inputs['To Max'].default_value-.34)<1e-5),None)
 if not scan:continue
 geo=n.new('ShaderNodeNewGeometry');rough=scan.outputs['Result']
 for scale,amplitude in [(1.2,.002),(24,.001),(950,.0004)]:rough=add(n,l,rough,signed(n,l,noise(n,l,geo.outputs['Position'],scale),amplitude))
 l.new(clamp(n,l,rough,.03,.8),bs.inputs['Roughness'])
ceramic=bpy.data.materials.get('Realism_glazed_warm_white') or glazed_ceramic();cover,*_=material('Library_neutral_book_cover',(.19,.24,.23),.6);enrich(cover,'paint');pages,*_=material('Library_book_pages',(.76,.74,.68),.82);enrich(pages,'paint')
records=[]
def bounds(o):return [o.matrix_world@Vector(c) for c in o.bound_box]
def target(key):return next(o for o in bpy.data.objects if o.get('program_key')==key)
def surface(parent,x,y):
 verts=[parent.matrix_world@v.co for v in parent.data.vertices];polys=[list(p.vertices) for p in parent.data.polygons];tree=BVHTree.FromPolygons(verts,polys);top=max(v.z for v in verts);hit=tree.ray_cast(Vector((x,y,top+.2)),Vector((0,0,-1)),2)
 assert hit[0] is not None,(parent.name,x,y)
 return hit[0].z

def spawn(file,key,x,y,z,parent,height=None,width=None,yaw=0,finish=None):
 with bpy.data.libraries.load(str(LIB/file),link=False) as (src,dst):assert 'ir_obj' in src.objects;dst.objects=['ir_obj']
 o=dst.objects[0];bpy.context.scene.collection.objects.link(o);original=o.matrix_world.copy();pts=bounds(o);lo=[min(v[i] for v in pts) for i in range(3)];hi=[max(v[i] for v in pts) for i in range(3)];factor=height/(hi[2]-lo[2]) if height else width/max(hi[0]-lo[0],hi[1]-lo[1]);pivot=Vector(((lo[0]+hi[0])/2,(lo[1]+hi[1])/2,lo[2]));o.matrix_world=Matrix.Translation((x,y,z))@Matrix.Rotation(yaw,4,'Z')@Matrix.Scale(factor,4)@Matrix.Translation(-pivot)@original
 o.name='Library_'+scene+'_'+key;o['reference_scene_owner']=scene;o['program_key']=key;o['audit_kind']='tabletop_prop';o['support_object']=parent.name;o['support_z']=z;o['library_source']=str(LIB/file)
 if finish=='ceramic':o.data.materials.clear();o.data.materials.append(ceramic)
 if finish=='book':
  for slot in o.material_slots:slot.material=cover if slot.material and 'text' in slot.material.name else pages
 records.append({'object':o.name,'source':str(LIB/file),'support':parent.name,'support_z':z,'scale':factor,'height':max(v.z for v in bounds(o))-min(v.z for v in bounds(o))});return o

def fruit_plate(table,key,dx=.35):
 pts=bounds(table);x=sum(v.x for v in pts)/8+dx;y=sum(v.y for v in pts)/8
 plate=spawn('dishes/plate_005.blend',key+'_fruit_plate',x,y,surface(table,x,y),table,width=.27,finish='ceramic')
 for i,angle in enumerate((0,2*math.pi/3,4*math.pi/3)):
  xx=x+.045*math.cos(angle);yy=y+.045*math.sin(angle);spawn(f'fruit/fruitapple_{i+1:03}.blend',key+f'_fruit_{i}',xx,yy,surface(plate,xx,yy)+.0005,plate,height=.085,yaw=angle)
if office:
 for o in list(bpy.data.objects):
  if o.get('program_key') in ('mug_body','mug_interior','mug_handle'):bpy.data.objects.remove(o,do_unlink=True)
 worktops=[o for o in bpy.data.objects if o.get('program_key')=='coffee_worktop'];worktop=max(worktops,key=lambda o:o.location.y)
 for i,y in enumerate((5.25,6.05,6.27)):spawn(f'drinkware/cup_{i+1:03}.blend',f'library_coffee_cup_{i}',14.04,y,surface(worktop,14.04,y),worktop,height=.095,yaw=.15*i,finish='ceramic')
 fruit_plate(target('breakout_table'),'breakout')
else:
 for unit in (101,102):
  fruit_plate(target(f'{unit}_dining_table'),str(unit),.35 if unit==101 else -.35)
  coffee=target(f'{unit}_living_coffee_table');pts=bounds(coffee);x=sum(v.x for v in pts)/8;y=sum(v.y for v in pts)/8
  for old in list(bpy.data.objects):
   if old.get('program_key')==f'{unit}_coffee_book':bpy.data.objects.remove(old,do_unlink=True)
  spawn('books/book_003.blend',f'{unit}_library_coffee_book',x+.10,y,surface(coffee,x+.10,y),coffee,height=.018,yaw=.18 if unit==101 else -.18,finish='book')
bpy.data.orphans_purge(do_recursive=True);bpy.ops.wm.save_as_mainfile(filepath=str(out));(ref/f'library_props_r{revision}.json').write_text(json.dumps({'source':f'scene_candidate_r{previous}.blend','candidate':str(out),'library':'data/object_library_v2/index.json','placements':records,'removed_unsafe_generic_modifiers':removed_modifiers,'labels':'Native product label materials replaced with unbranded ceramic or abstract neutral book covers','support_method':'World-space triangle ray against exported support meshes; all positions away from small beveled edges','visual_acceptance':False},indent=2));print(json.dumps({'saved':str(out),'library_instances':len(records),'removed_unsafe_modifiers':len(removed_modifiers)}),flush=True)
