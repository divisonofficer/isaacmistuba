import bpy,json
from pathlib import Path
R=Path(__file__).resolve().parents[3];W=R/'out/infinigen_v2/kr_large_restaurant_floor_07_48712507';out=W/'furnished_r3.blend';assert not out.exists();bpy.ops.wm.open_mainfile(filepath=str(W/'furnished_r2.blend'));changed=[]
def tile(name,c1,c2,width,rough):
 m=bpy.data.materials.new(name);m.use_nodes=True;n=m.node_tree.nodes;l=m.node_tree.links;b=n.get('Principled BSDF');b.inputs['Roughness'].default_value=rough;b.inputs['IOR'].default_value=1.48;pos=n.new('ShaderNodeNewGeometry');brick=n.new('ShaderNodeTexBrick');brick.inputs['Color1'].default_value=(*c1,1);brick.inputs['Color2'].default_value=(*c2,1);brick.inputs['Mortar'].default_value=(.14,.12,.09,1);brick.inputs['Scale'].default_value=1;brick.inputs['Mortar Size'].default_value=.006;brick.inputs['Brick Width'].default_value=width;brick.inputs['Row Height'].default_value=width;brick.offset=0;l.new(pos.outputs['Position'],brick.inputs['Vector']);l.new(brick.outputs['Color'],b.inputs['Base Color']);bump=n.new('ShaderNodeBump');bump.inputs['Strength'].default_value=.12;bump.inputs['Distance'].default_value=.003;l.new(brick.outputs['Fac'],bump.inputs['Height']);l.new(bump.outputs['Normal'],b.inputs['Normal']);return m
terracotta=tile('Reference_inferred_terracotta_450mm',(.34,.09,.035),(.27,.065,.025),.45,.73);stone=tile('Reference_inferred_cream_stone_600mm',(.55,.45,.3),(.64,.56,.4),.6,.42)
wall=bpy.data.materials.new('Reference_inferred_warm_plaster');wall.use_nodes=True;b=wall.node_tree.nodes.get('Principled BSDF');b.inputs['Base Color'].default_value=(.27,.20,.12,1);b.inputs['Roughness'].default_value=.81
for o in bpy.data.objects:
 if o.type!='MESH' or o.get('native_asset_id'):continue
 if o.name.endswith('.floor'):
  old=[x.name for x in o.data.materials];o.data.materials.clear();o.data.materials.append(stone if o.name.startswith('bathroom') else terracotta);changed.append({'object':o.name,'before':old,'after':[x.name for x in o.data.materials]})
 elif '.wall' in o.name:
  old=[x.name for x in o.data.materials];o.data.materials.clear();o.data.materials.append(wall);changed.append({'object':o.name,'before':old,'after':[wall.name]})
# Opening-strip audit found actual table hull within0.3m of northWCportal. Shift entire native cluster0.4m west.
inv=json.loads((W/'native_product_inventory_r2.json').read_text());moved=[]
for p in inv['products']:
 x,y,z=p['placement_xyz_m']
 if 16.7<=x<=18.5 and 12.7<=y<=14.5 and p['label'] in ['native_dining_table','native_dining_chair']:
  for name in p['objects']:bpy.data.objects[name].location.x-=.4
  p['placement_xyz_m'][0]-=.4;p['saved_mesh_bounds_xyz_m'][0][0]-=.4;p['saved_mesh_bounds_xyz_m'][1][0]-=.4;moved+=p['objects']
bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(out));(W/'native_product_inventory_r3.json').write_text(json.dumps(inv,indent=2));(W/'architectural_palette_r3.json').write_text(json.dumps({'trigger':'Direct r1 overview critique: random carpet/purple WC inconsistent with source orange terracotta/cream stone','changes':changed,'opening_audit_correction_moved_objects':moved,'material_authority':'Visually inferred from original, not measured optical data; product texture bytes/UV untouched','photorealism_accepted':False},indent=2));views=json.loads((W/'furnished_r2_views.json').read_text());
for v in views:v['render_width']=768 if v.get('overview') else 640;v['samples']=16
(W/'furnished_r3_views.json').write_text(json.dumps(views,indent=2));print('PALETTE_R3_SAVED',len(changed),len(moved),flush=True)
