"""Correct semantic donor error revealed by first eye-level render."""
from pathlib import Path
import sys,json
T=Path(__file__).parent;sys.argv=['slots06_07_restaurant_dining_fix.py','--','large_restaurant_floor_07'];src=(T/'slots06_07_furnish.py').read_text().split('if seed==48712506:')[0].replace("out=W/'furnished_r1.blend'","out=W/'furnished_r4.blend'").replace("str(W/'full/scene.blend')","str(W/'furnished_r3.blend')");exec(compile(src,str(T/'slots06_07_furnish.py'),'exec'))
inv=json.loads((W/'native_product_inventory_r3.json').read_text());chair=json.loads((D/'native_products/dining_chair_manifest.json').read_text());objs,mats,lo,hi,prof=get(chair);points=[o.matrix_world@v.co for o in objs for v in o.data.vertices];upper=[v for v in points if v.z>lo.z+(hi.z-lo.z)*.70];back=Vector((sum(v.x for v in upper)/len(upper)-(lo.x+hi.x)/2,sum(v.y for v in upper)/len(upper)-(lo.y+hi.y)/2,0));assert back.length>.03;backangle=math.atan2(back.y,back.x);old=[p for p in inv['products'] if p['label']=='native_dining_chair']
for p in old:
 x,y,z=p['placement_xyz_m'];source_angle=p['yaw_radians'];desired_back_angle=-math.pi/2 if abs(source_angle)<.1 else math.pi/2
 for name in p['objects']:bpy.data.objects.remove(bpy.data.objects[name],do_unlink=True)
 place(chair,x,y,desired_back_angle-backangle,label='native_wood_dining_chair')
for objs,*rest in templates.values():
 for o in objs:bpy.data.objects.remove(o,do_unlink=True)
ceiling=bpy.data.materials.new('Reference_inferred_warm_ivory_ceiling');ceiling.use_nodes=True;b=ceiling.node_tree.nodes.get('Principled BSDF');b.inputs['Base Color'].default_value=(.44,.36,.25,1);b.inputs['Roughness'].default_value=.85
for o in bpy.data.objects:
 if o.type=='MESH' and o.name.endswith('.ceiling'):o.data.materials.clear();o.data.materials.append(ceiling)
# Explicit inferred stained finish on actual native oak product, preserving source bitmap bytes and UVs.
tables=[p for p in inv['products'] if p['label']=='native_dining_table'];materials={m for p in tables for name in p['objects'] for m in bpy.data.objects[name].data.materials if m}
for m in materials:
 if not m.use_nodes:continue
 for b in [n for n in m.node_tree.nodes if n.type=='BSDF_PRINCIPLED']:
  socket=b.inputs['Base Color']
  if socket.is_linked:
   source=socket.links[0].from_socket;mix=m.node_tree.nodes.new('ShaderNodeMixRGB');mix.blend_type='MULTIPLY';mix.inputs[0].default_value=1;mix.inputs[2].default_value=(.25,.14,.075,1);m.node_tree.links.new(source,mix.inputs[1]);m.node_tree.links.new(mix.outputs[0],socket)
  else:socket.default_value=(.13,.06,.025,1)
  b.inputs['Roughness'].default_value=.5
bpy.context.view_layer.update()
for p in rows:
 points=[bpy.data.objects[name].matrix_world@v.co for name in p['objects'] for v in bpy.data.objects[name].data.vertices];p['saved_mesh_bounds_xyz_m']=[[min(v[k] for v in points) for k in range(3)],[max(v[k] for v in points) for k in range(3)]];p['floor_support_error_m']=p['saved_mesh_bounds_xyz_m'][0][2]-floor;assert abs(p['floor_support_error_m'])<1e-4
inv['products']=[p for p in inv['products'] if p['label']!='native_dining_chair']+rows;inv['scope']+=' r4 corrects first-render semantic error: real office swivel chairs replaced by real reclaimed wood/metal Windsor dining chairs at unchanged native size. Backrest centroid used to orient seats inward. Actual table native UV/image preserved with explicitly inferred dark stain multiplier. Warm ivory ceiling replaces native mint paint.'
images=[]
for im in {n.image for m in bpy.data.materials if m.use_nodes for n in m.node_tree.nodes if n.type=='TEX_IMAGE' and n.image}:images.append(preserve_native_packed_image(im))
inv['images']=images;bpy.ops.wm.save_as_mainfile(filepath=str(out));(W/'native_product_inventory_r4.json').write_text(json.dumps(inv,indent=2));(W/'dining_donor_correction_r4.json').write_text(json.dumps({'trigger':'Direct eye-level r1 render reveals swivel office chairs semantically wrong for restaurant','removed_asset':'B06W5XBL3D','new_asset':chair,'native_backrest_direction_xy':list(back)[:2],'scope':'Native genuine furniture geometry; inferred dark stain and warm ceiling optical finish, not original commercial reference product','photorealism_accepted':False},indent=2));(W/'furnished_r4_views.json').write_text((W/'furnished_r3_views.json').read_text());print('R4_DINING_DONOR_CORRECTED',len(rows),flush=True)
