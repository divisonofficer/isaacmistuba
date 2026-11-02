"""Whole restaurant functional dressing after reviewed r4 six-view suite."""
from pathlib import Path
import sys,json
T=Path(__file__).parent;sys.argv=['slots06_07_restaurant_dressing.py','--','large_restaurant_floor_07'];src=(T/'slots06_07_furnish.py').read_text().split('if seed==48712506:')[0].replace("out=W/'furnished_r1.blend'","out=W/'furnished_r5.blend'").replace("str(W/'full/scene.blend')","str(W/'furnished_r4_materials.blend')");exec(compile(src,str(T/'slots06_07_furnish.py'),'exec'))
inv=json.loads((W/'native_product_inventory_r4_materials.json').read_text());es={e['role']:e for e in json.loads((D/'native_products/functional_dressing_manifest.json').read_text())['assets']}
for x,y in [(3.8,11.2),(3.8,14.1)]:place(es['prep_island'],x,y,math.pi/2,label='native_kitchen_prep_island')
place(es['banquette'],1.12,4.7,0,label='native_valencia_banquette')
plants=json.loads((R/'data/venue_refs/floor_plans_v3/commercial_office_floor_02/plants113_products/asset_manifest.json').read_text())['assets'];bonsai=plants[0];trees=json.loads((R/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03/real_indoor_tree_candidates/asset_manifest.json').read_text())['assets'];tree=next(e for e in trees if '95d1e189' in e['id'])
for x,y in [(20.7,6.6),(20.7,10.5),(3.5,6.5),(9.8,2)]:place(tree,x,y,label='native_ficus_floor_tree')
for table in [p for p in inv['products'] if p['label']=='native_dining_table']:
 x,y,z=table['placement_xyz_m'];floor=table['saved_mesh_bounds_xyz_m'][1][2];place(bonsai,x,y,label='native_table_centerpiece');rows[-1]['support_surface_z_m']=floor;rows[-1]['support_objects']=table['objects']
floor=.11
for objs,*rest in templates.values():
 for o in objs:bpy.data.objects.remove(o,do_unlink=True)
# Native Infinigen factory generation; manufacturing dimensions chosen before mesh generation, not downscaling a donor.
sys.path.insert(0,str(R/'modules/infinigen'));sys.path.append('/root/miniconda3/envs/infinigen/lib/python3.11/site-packages')
from infinigen.assets.objects.tableware.plate import PlateFactory
from infinigen.assets.objects.tableware.wineglass import WineglassFactory
f=PlateFactory(48712507);f.scale=.27;f.has_inside=False;plate=f.create_asset();f.finalize_assets([plate]);plate.name='Native_PlateFactory_270mm_template'
g=WineglassFactory(48712508);g.scale=.16;g.z_length=1.25;g.z_cup=.42;g.z_mid=.95;g.x_end=.25;g.x_top=.3;g.x_mid=.33;g.x_neck=.015;glass=g.create_asset();g.finalize_assets([glass]);glass.name='Native_WineglassFactory_200mm_template'
# Deterministic ceramic/glass optical role; native factory solids/modifiers are retained and evaluated below.
ceramic=bpy.data.materials.new('Native_tableware_inferred_white_glazed_porcelain');ceramic.use_nodes=True;b=ceramic.node_tree.nodes.get('Principled BSDF');b.inputs['Base Color'].default_value=(.8,.78,.72,1);b.inputs['Roughness'].default_value=.18;b.inputs['IOR'].default_value=1.5
clear=bpy.data.materials.new('Native_tableware_inferred_clear_glass_IOR1_5');clear.use_nodes=True;b=clear.node_tree.nodes.get('Principled BSDF');b.inputs['Base Color'].default_value=(.96,.98,1,1);b.inputs['Roughness'].default_value=.045;b.inputs['IOR'].default_value=1.5;b.inputs['Transmission Weight'].default_value=1
for template,mat in [(plate,ceramic),(glass,clear)]:
 bpy.context.view_layer.objects.active=template;template.select_set(True)
 for mod in list(template.modifiers):bpy.ops.object.modifier_apply(modifier=mod.name)
 template.data.materials.clear();template.data.materials.append(mat)
 template.select_set(False)
pts={o:[o.matrix_world@v.co for v in o.data.vertices] for o in [plate,glass]};native=[]
def tableware(template,x,y,height,support,kind):
 pp=pts[template];lo=Vector([min(p[k] for p in pp) for k in range(3)]);hi=Vector([max(p[k] for p in pp) for k in range(3)]);o=template.copy();o.data=template.data;bpy.context.scene.collection.objects.link(o);o.name=f'Native_Infinigen_{kind}_{len(native):03d}';o.location+=Vector((x-(lo.x+hi.x)/2,y-(lo.y+hi.y)/2,height-lo.z));native.append({'label':'native_infinigen_'+kind,'asset_id':template.name,'source':'modules/infinigen/infinigen/assets/objects/tableware/'+('plate.py' if template==plate else 'wineglass.py'),'native_dimensions_xyz_m':list(hi-lo),'native_scale_preserved':True,'placement_xyz_m':[x,y,height],'yaw_radians':0,'polygons':len(o.data.polygons),'objects':[o.name],'support_surface_z_m':height,'support_objects':support,'material_profile':'Explicit inferred porcelain/glass role; not measured optical material'})
for table in [p for p in inv['products'] if p['label']=='native_dining_table']:
 x,y,z=table['placement_xyz_m'];height=table['saved_mesh_bounds_xyz_m'][1][2]
 for xx in [-.65,.65]:
  for yy in [-.26,.26]:
   tableware(plate,x+xx,y+yy,height,table['objects'],'dinner_plate');tableware(glass,x+xx+.24,y+yy*.58,height,table['objects'],'stemmed_glass')
for o in [plate,glass]:bpy.data.objects.remove(o,do_unlink=True)
rows+=native;bpy.context.view_layer.update()
for p in rows:
 pp=[bpy.data.objects[name].matrix_world@v.co for name in p['objects'] for v in bpy.data.objects[name].data.vertices];lo=[min(v[k] for v in pp) for k in range(3)];hi=[max(v[k] for v in pp) for k in range(3)];p['saved_mesh_bounds_xyz_m']=[lo,hi];p['floor_support_error_m']=lo[2]-p.get('support_surface_z_m',.11);assert abs(p['floor_support_error_m'])<1e-4
inv['products']+=rows;inv['scope']+=' r5 reviewed r4 whole scene: genuine native kitchenprep islands,Valencia banquette,full-size ficus trees and native high-poly bonsai tabletop products. Dinner plates and stemmed glasses generated by local native Infinigen factories at authored manufacture dimensions270mm/200mm before generation; no donor shrink. Tabletop/floor support actual-mesh verified. Still missing servingfood,cutlery,commercial ventilation and practical pendant assemblies.';inv['images']=[preserve_native_packed_image(im) for im in {n.image for m in bpy.data.materials if m.use_nodes for n in m.node_tree.nodes if n.type=='TEX_IMAGE' and n.image}];bpy.ops.wm.save_as_mainfile(filepath=str(out));(W/'native_product_inventory_r5.json').write_text(json.dumps(inv,indent=2));views=json.loads((W/'furnished_r4_materials_views.json').read_text());
for v in views:
 if v['name']=='south_restroom':v['location']=[20.8,2.5,1.6];v['target']=[18,2.5,.75]
views += [{'name':'north_restroom','location':[21.5,14.2,1.6],'target':[20,16,.8],'hfov':75,'render_width':640,'samples':16},{'name':'accessible_restroom','location':[1.5,2.4,1.6],'target':[1,.8,.6],'hfov':80,'render_width':640,'samples':16}];(W/'furnished_r5_views.json').write_text(json.dumps(views,indent=2));print('RESTAURANT_NATIVE_DRESSING_SAVED',len(rows),'native additions',flush=True)
