"""Functional regions added using real native products at native size."""
from pathlib import Path
import sys,json
T=Path(__file__).parent
sys.argv=['slots06_07_restaurant_r2.py','--','large_restaurant_floor_07']
src=(T/'slots06_07_furnish.py').read_text().split('if seed==48712506:')[0].replace("out=W/'furnished_r1.blend'","out=W/'furnished_r2.blend'").replace("str(W/'full/scene.blend')","str(W/'furnished_r1.blend')")
exec(compile(src,str(T/'slots06_07_furnish.py'),'exec'))
es={e['role']:e for e in json.loads((D/'native_products/asset_manifest.json').read_text())['assets']}
for x,y,a in [(7.5,8.3,math.pi/2),(7.5,10.6,math.pi/2),(7.5,12.9,math.pi/2),(5.9,6.9,0)]:place(es['bar'],x,y,a,label='native_bar_counter')
for x,y in [(1,13),(1,14.2)]:place(es['range'],x,y,math.pi/2,label='native_range_cooker')
place(es['fridge'],1,16.5,math.pi/2,label='native_stainless_fridge');place(es['sink'],3.2,16.8,0,label='native_kitchen_sink_unit')
san=json.loads((R/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03/sanitary106_complete_products/asset_manifest.json').read_text())['assets'];toilet=next(e for e in san if e['id']=='HSSD_7ff8c2d48e8d49e2f1504bc83d16ef933cd7163b');basin=san[0]
for x,y,a in [(18,1,math.pi/2),(18,2.5,math.pi/2),(18,4,math.pi/2),(20,15,math.pi/2),(20,16.6,math.pi/2),(1,.65,0)]:place(toilet,x,y,a,label='native_fullsize_toilet')
for x,y,a in [(21.3,1.2,-math.pi/2),(21.3,3.6,-math.pi/2),(21.3,13.2,-math.pi/2),(.6,2.15,math.pi/2)]:place(basin,x,y,a,label='native_full_pedestal_basin')
for objs,*rest in templates.values():
 for o in objs:bpy.data.objects.remove(o,do_unlink=True)
# Solid sanitary partitions are architecture, not furniture proxies. Open fronts pending genuine cubicle door hardware.
mat=bpy.data.materials.new('Sanitary_partition_inferred_cream_laminate');mat.diffuse_color=(.58,.53,.4,1)
def partition(name,x0,y0,x1,y1,h=2.0):
 verts=[(x,y,z) for z in [.11,h+.11] for x,y in [(x0,y0),(x1,y0),(x1,y1),(x0,y1)]];me=bpy.data.meshes.new(name);me.from_pydata(verts,[],[(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)]);o=bpy.data.objects.new(name,me);bpy.context.scene.collection.objects.link(o);me.materials.append(mat)
for y in [1.7,3.2]:partition('South_WC_partition_'+str(y),17.15,y,19.3,y+.1)
partition('North_WC_partition',19.15,15.75,21,15.85)
bpy.context.view_layer.update()
for row in rows:
 pts=[bpy.data.objects[n].matrix_world@v.co for n in row['objects'] for v in bpy.data.objects[n].data.vertices];lo=[min(v[k] for v in pts) for k in range(3)];hi=[max(v[k] for v in pts) for k in range(3)];row['saved_mesh_bounds_xyz_m']=[lo,hi];row['floor_support_error_m']=lo[2]-.11;assert abs(row['floor_support_error_m'])<1e-4
images=[]
for im in {n.image for m in bpy.data.materials if m.use_nodes for n in m.node_tree.nodes if n.type=='TEX_IMAGE' and n.image}:images.append(preserve_native_packed_image(im))
bpy.ops.wm.save_as_mainfile(filepath=str(out));prior=json.loads((W/'native_product_inventory_r1.json').read_text());prior['products']+=rows;prior['images']=images;prior['scope']+=' r2 adds actual full-size toilets, basins, bar, range,fridge,sink. Domestic-product donor roles are explicit; not claimed equivalent to reference commercial equipment. Cubicle fronts still open, not final private restroom acceptance.';(W/'native_product_inventory_r2.json').write_text(json.dumps(prior,indent=2));views=json.loads((W/'furnished_r1_views.json').read_text());views.extend([{'name':'kitchen','location':[5,9.4,1.7],'target':[1.2,15,1.0],'hfov':76,'render_width':768},{'name':'south_restroom','location':[20,4.3,1.65],'target':[18,1.1,.75],'hfov':82,'render_width':768},{'name':'bar','location':[5.7,5,1.65],'target':[7.5,11,1],'hfov':75,'render_width':768}]);(W/'furnished_r2_views.json').write_text(json.dumps(views,indent=2));print('RESTAURANT_R2_SAVED',len(prior['products']),flush=True)
