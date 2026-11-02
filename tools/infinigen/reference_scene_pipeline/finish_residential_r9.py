"""Reference finishing: real bedside lamps, matte walls and textile micro-relief."""
import json,sys,math
from pathlib import Path
import bpy
from mathutils import Vector
from material_detail import paint,noise,bump,range_value
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'tools/infinigen'))
from room_planner import proc_assets as pa
base=ROOT/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';ref=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03'
bpy.ops.wm.open_mainfile(filepath=str(base/'scene_candidate_r8.blend'))
wall=paint();brass=pa._flat('res03_lamp_brass',(.42,.30,.13),.30,.8);shade=pa._flat('res03_lamp_linen',(.78,.73,.62),.9)
added=[]
def tag(o,key):
 o.name='Residential03_r9_'+key;o['reference_scene_owner']='dual_unit_residential_floor_03';o['program_key']=key;o['audit_kind']='fixture';added.append(o.name);return o
def cyl(key,loc,r,depth,mat):
 bpy.ops.mesh.primitive_cylinder_add(vertices=32,radius=r,depth=depth,location=loc);o=bpy.context.object;o.data.materials.append(mat);return tag(o,key)
for o in list(bpy.data.objects):
 if o.type=='MESH' and o.name.endswith('.wall') and not o.name.startswith('bathroom'):
  o.data.materials.clear();o.data.materials.append(wall)
 if o.get('program_key','').endswith('_nightstand'):
  pts=[o.matrix_world@Vector(c) for c in o.bound_box];top=max(v.z for v in pts);x=sum(v.x for v in pts)/8;y=sum(v.y for v in pts)/8;key=o.get('program_key')
  cyl(key+'_lamp_base',(x,y,top+.012),.085,.024,brass);cyl(key+'_lamp_stem',(x,y,top+.14),.013,.25,brass)
  # Hollow linen frustum, with real rim thickness rather than solid cone.
  verts=[];n=40
  for radius,z in [(.135,top+.20),(.105,top+.42),(.102,top+.42),(.132,top+.20)]:
   verts += [(x+radius*math.cos(i*2*math.pi/n),y+radius*math.sin(i*2*math.pi/n),z) for i in range(n)]
  faces=[]
  for k in range(4):
   for i in range(n):faces.append((k*n+i,k*n+(i+1)%n,((k+1)%4)*n+(i+1)%n,((k+1)%4)*n+i))
  me=bpy.data.meshes.new('hollow_linen_shade');me.from_pydata(verts,[],faces);me.materials.append(shade);sh=bpy.data.objects.new('shade',me);bpy.context.scene.collection.objects.link(sh);tag(sh,key+'_lamp_shade')
  ld=bpy.data.lights.new(key+'_bulb','POINT');ld.energy=7;ld.color=(1,.79,.57);ld.shadow_soft_size=.065;lo=bpy.data.objects.new(ld.name,ld);bpy.context.scene.collection.objects.link(lo);lo.location=(x,y,top+.30)
# Retain textile colour. Fine weave affects roughness and shading normals.
textiles=[]
for m in bpy.data.materials:
 if not m.use_nodes or not m.name.startswith(('ir_sfb_cream','ir_sfb_white','ir_sfb_throw','ir_sfb_oat','ir_sfb_greige','ir_sfb_petrol','ir_ss_','res03_rug_linen')):continue
 n=m.node_tree.nodes;l=m.node_tree.links;bs=next((x for x in n if x.type=='BSDF_PRINCIPLED'),None)
 if bs is None:continue
 geo=n.new('ShaderNodeNewGeometry');weave=noise(n,l,geo.outputs['Position'],380,(1,1.8,1));l.new(bump(n,l,weave,.00045,.65),bs.inputs['Normal']);l.new(range_value(n,l,weave,.68,.96),bs.inputs['Roughness']);bs.inputs['Sheen Weight'].default_value=.25;textiles.append(m.name)
# Complementary kitchen views cover actual worktops and fixtures.
views=json.loads((base/'review_views_r1.json').read_text())
for unit in (101,102):
 x=lambda v:21.5-v if unit==102 else v
 views.append({'name':f'{unit}_kitchen_worktop_reverse','location':[x(6.9),5.70,1.60],'target':[x(8.45),4.45,1.10],'hfov':80})
(base/'review_views_r9.json').write_text(json.dumps(views,indent=2))
out=base/'scene_candidate_r9.blend';assert not out.exists();bpy.ops.wm.save_as_mainfile(filepath=str(out))
(ref/'finishing_r9.json').write_text(json.dumps({'source':'scene_candidate_r8.blend','added_lamp_parts':added,'textile_materials':textiles,'physical_checks':'pending rerun','visual_acceptance':False},indent=2))
