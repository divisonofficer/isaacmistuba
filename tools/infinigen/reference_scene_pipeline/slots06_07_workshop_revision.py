"""Respond to actual first views: coherent industrial shell, reduced repetition, real tooling."""
from pathlib import Path
import sys,json
T=Path(__file__).parent;sys.argv=['slots06_07_workshop_revision.py','--','industrial_workshop_floor_06'];src=(T/'slots06_07_furnish.py').read_text().split('if seed==48712506:')[0].replace("out=W/'furnished_r1.blend'","out=W/'furnished_r2.blend'").replace("str(W/'full/scene.blend')","str(W/'furnished_r1.blend')");exec(compile(src,str(T/'slots06_07_furnish.py'),'exec'))
inv=json.loads((W/'native_product_inventory_r1.json').read_text());kept=[];removed=[]
for p in inv['products']:
 x,y,z=p['placement_xyz_m'];remove=p['label']=='native_drill_press' and (x,y) not in [(5.7,15.8),(17,8),(10,1)]
 if remove:
  removed+=p['objects']
  for name in p['objects']:bpy.data.objects.remove(bpy.data.objects[name],do_unlink=True)
 else:kept.append(p)
es={e['role']:e for e in json.loads((D/'native_products/varied_machine_manifest.json').read_text())['assets']}
place(es['pallet_rack'],2,5.8,label='native_industrial_pallet_rack')
# Native bench grinder at genuine bench-top height, no rescale and no floor-floating claim.
for x,y in [(1.4,12),(4.5,9.5),(8.3,14.5),(16,15.5),(1.5,5),(10.5,3.8)]:
 support=next(p for p in kept if abs(p['placement_xyz_m'][0]-x)<.01 and abs(p['placement_xyz_m'][1]-y)<.01 and 'workbench' in p['label']);floor=.11+support['native_dimensions_xyz_m'][2];place(es['bench_grinder'],x,y,label='native_bench_grinder');rows[-1]['support_objects']=support['objects'];rows[-1]['support_surface_z_m']=floor
floor=.11
for objs,*rest in templates.values():
 for o in objs:bpy.data.objects.remove(o,do_unlink=True)
def concrete(name,base,rough):
 m=bpy.data.materials.new(name);m.use_nodes=True;n=m.node_tree.nodes;l=m.node_tree.links;b=n.get('Principled BSDF');b.inputs['Base Color'].default_value=(*base,1);b.inputs['Roughness'].default_value=rough;geo=n.new('ShaderNodeNewGeometry');tex=n.new('ShaderNodeTexNoise');tex.inputs['Scale'].default_value=2.8;tex.inputs['Detail'].default_value=5;l.new(geo.outputs['Position'],tex.inputs['Vector']);ramp=n.new('ShaderNodeValToRGB');ramp.color_ramp.elements[0].color=tuple(c*.55 for c in base)+(1,);ramp.color_ramp.elements[1].color=tuple(c*1.18 for c in base)+(1,);l.new(tex.outputs['Fac'],ramp.inputs[0]);l.new(ramp.outputs['Color'],b.inputs['Base Color']);fine=n.new('ShaderNodeTexNoise');fine.inputs['Scale'].default_value=140;l.new(geo.outputs['Position'],fine.inputs['Vector']);bump=n.new('ShaderNodeBump');bump.inputs['Strength'].default_value=.22;bump.inputs['Distance'].default_value=.002;l.new(fine.outputs['Fac'],bump.inputs['Height']);l.new(bump.outputs['Normal'],b.inputs['Normal']);return m
floor_mat=concrete('Reference_inferred_worn_industrial_concrete',(.17,.145,.11),.82);wall_mat=concrete('Reference_inferred_aged_concrete_wall',(.21,.185,.14),.85);ceiling_mat=concrete('Reference_inferred_neutral_industrial_ceiling',(.22,.205,.18),.87);arch=[]
for o in bpy.data.objects:
 if o.type!='MESH' or o.get('native_asset_id'):continue
 mat=floor_mat if o.name.endswith('.floor') else ceiling_mat if o.name.endswith('.ceiling') else wall_mat if '.wall' in o.name else None
 if mat:o.data.materials.clear();o.data.materials.append(mat);arch.append(o.name)
# Actual annular pipe surfaces/flanges/bolt heads are architectural service manufacture, not furniture placeholders.
steel=bpy.data.materials.new('Architectural_pipe_inferred_oxidized_steel');steel.use_nodes=True;b=steel.node_tree.nodes.get('Principled BSDF');b.inputs['Base Color'].default_value=(.12,.095,.065,1);b.inputs['Metallic'].default_value=.85;b.inputs['Roughness'].default_value=.58
pipe_objects=[]
def tube(name,x,z,y0,y1,outer,inner,sides=24):
 verts=[]
 for y,r in [(y0,outer),(y1,outer),(y0,inner),(y1,inner)]:
  for i in range(sides):a=i*2*math.pi/sides;verts.append((x+r*math.cos(a),y,z+r*math.sin(a)))
 faces=[]
 for i in range(sides):j=(i+1)%sides;faces += [(i,j,sides+j,sides+i),(2*sides+j,2*sides+i,3*sides+i,3*sides+j),(j,i,2*sides+i,2*sides+j),(sides+i,sides+j,3*sides+j,3*sides+i)]
 me=bpy.data.meshes.new(name);me.from_pydata(verts,[],faces);me.materials.append(steel);o=bpy.data.objects.new(name,me);bpy.context.scene.collection.objects.link(o);pipe_objects.append(o.name)
for side,xs in [('west',[.25,.5,.75]),('east',[17.25,17.5,17.75])]:
 for i,x in enumerate(xs):
  z=2.9;tube(f'Native_service_pipe_{side}_{i}',x,z,.6,16.4,.065,.057)
  for y in [1,6.7,10,16]:
   tube(f'Native_service_flange_{side}_{i}_{y}',x,z,y-.023,y+.023,.105,.057)
   for k in range(6):a=k*math.pi/3;tube(f'Native_service_hex_bolt_{side}_{i}_{y}_{k}',x+.084*math.cos(a),z+.084*math.sin(a),y-.035,y+.035,.011,.001,6)
bpy.context.view_layer.update()
for p in rows:
 points=[bpy.data.objects[name].matrix_world@v.co for name in p['objects'] for v in bpy.data.objects[name].data.vertices];lo=[min(v[k] for v in points) for k in range(3)];hi=[max(v[k] for v in points) for k in range(3)];p['saved_mesh_bounds_xyz_m']=[lo,hi];p['floor_support_error_m']=lo[2]-p.get('support_surface_z_m',.11);assert abs(p['floor_support_error_m'])<1e-4
inv['products']=kept+rows;inv['scope']+=' r2 follows first actual overview/context: remove5repeated drillpresses, add genuine bench grinders at measured actual bench-top support and one genuine pallet rack. Source heavy military machines still unavailable. Architectural annular steel service pipes/flanges/hex bolts authored at full size; not furniture proxies. Concrete optical palette inferred from supplied reference.';inv['images']=[preserve_native_packed_image(im) for im in {n.image for m in bpy.data.materials if m.use_nodes for n in m.node_tree.nodes if n.type=='TEX_IMAGE' and n.image}];bpy.ops.wm.save_as_mainfile(filepath=str(out));(W/'native_product_inventory_r2.json').write_text(json.dumps(inv,indent=2));(W/'workshop_reference_revision_r2.json').write_text(json.dumps({'trigger':'Actual first overview and west eye-level images','removed_repeated_drill_objects':removed,'architectural_material_objects':arch,'architectural_pipe_objects':pipe_objects,'limits':['No genuine matching large military machine assembly acquired','Real HSSD benches/drills are low-detail compared with requested manufacture; not claimed high-poly completion','Floor/door-strip support audit excludes full exact collision and pipe wall-penetration acceptance'],'photorealism_accepted':False},indent=2));views=json.loads((W/'furnished_r1_views.json').read_text());(W/'furnished_r2_views.json').write_text(json.dumps(views,indent=2));print('WORKSHOP_REFERENCE_REVISION_SAVED',len(inv['products']),len(pipe_objects),flush=True)
