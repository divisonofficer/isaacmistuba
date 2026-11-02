"""Source-bound diagnostic of rejected settled cloth08; never resimulates or integrates."""
import bpy,json,hashlib,math
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
r=Path('/jarvis/project/robomituba');ref=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';src=ref/'garment_roof_hanger_settled08.blend';out=ref/'settled_hanger08_diagnostic';assert not out.exists();out.mkdir();bpy.ops.wm.open_mainfile(filepath=str(src));shirt=bpy.data.objects['Native_neck_clearance_fit_shirt'];wire=bpy.data.objects['Measured shoulder wire'];proof=json.loads((ref/'garment_roof_hanger_settled08_job.json').read_text());assert not proof['geometry_gate_pass'];points=[v.co.copy() for v in shirt.data.vertices];faces=[tuple(f.vertices) for f in shirt.data.polygons];tree=BVHTree.FromPolygons(points,faces);sets=[set(f) for f in faces];coords=[{tuple(round(float(c),7) for c in points[i]) for i in f} for f in faces];pairs=[(i,j) for i,j in tree.overlap(tree) if j>i and not sets[i]&sets[j] and not coords[i]&coords[j]];bins={'upper_neck_shoulders':0,'mid_body':0,'lower_body':0};samples=[]
for i,j in pairs:
 c=sum((points[k] for k in faces[i]+faces[j]),Vector())/len(faces[i]+faces[j]);zone='upper_neck_shoulders' if c.z>-.14 else 'mid_body' if c.z>-.33 else 'lower_body';bins[zone]+=1
 if len(samples)<30:samples.append({'faces':[i,j],'centroid':list(c),'zone':zone})
for o in list(bpy.data.objects):
 if o not in [shirt,wire]:bpy.data.objects.remove(o,do_unlink=True)
for o,color,name in [(shirt,(.32,.38,.43,1),'Neutral failed cloth08'),(wire,(.6,.025,.015,1),'Red measured wire08')]:
 for mod in list(o.modifiers):
  if mod.type in ['CLOTH','COLLISION']:o.modifiers.remove(mod)
 o.data.materials.clear();m=bpy.data.materials.new(name);m.use_nodes=True;m.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value=color;m.node_tree.nodes['Principled BSDF'].inputs['Roughness'].default_value=.75;o.data.materials.append(m)
 for f in o.data.polygons:f.material_index=0
scene=bpy.context.scene;scene.world=scene.world or bpy.data.worlds.new('Diagnostic');scene.world.use_nodes=True;scene.world.node_tree.nodes['Background'].inputs['Strength'].default_value=.2
for name,loc,power,size in [('key',(-.5,-.6,.4),45,.5),('fill',(.4,.1,.3),15,.3)]:
 d=bpy.data.lights.new(name,'AREA');d.energy=power;d.size=size;o=bpy.data.objects.new(name,d);bpy.context.collection.objects.link(o);o.location=loc;o.rotation_euler=(Vector((0,0,-.2))-o.location).to_track_quat('-Z','Y').to_euler()
views=[{'name':'settled08_front_failure','location':[0,-.85,-.05],'target':[0,0,-.2],'hfov':55,'render_width':800,'samples':24},{'name':'settled08_neck_failure','location':[.18,-.35,.15],'target':[0,0,-.055],'hfov':65,'render_width':800,'samples':24}];(out/'views.json').write_text(json.dumps(views,indent=2));(out/'scope.json').write_text(json.dumps({'source':str(src),'source_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),'phase':'failed_settlement_geometry_diagnostic','pair_count':len(pairs),'pair_centroid_bins':bins,'pair_samples':samples,'geometry_gate_pass':False,'room_integrated':False,'photorealism_accepted':False,'scope':'Actual saved rejected frame60 geometry, no new simulation. Zone bins locate overlap candidates; not penetration-depth proof.'},indent=2));bpy.ops.wm.save_as_mainfile(filepath=str(out/'studio.blend'));print('Diagnostic saved',bins,flush=True)
