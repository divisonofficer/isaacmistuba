"""Fit wire to untouched native shoulder roof, never warp or snap cloth; preflight before solve."""
from pathlib import Path
import json,bpy,math
from mathutils import Vector,Matrix
from mathutils.bvhtree import BVHTree
p=Path(__file__).with_name('garment_mass_corrected_pilot03.py');code=p.read_text().split('for i in range(1):\n original=')[0].replace('garment_mass_corrected_pilot03','garment_roof_hanger_pilot');exec(compile(code,str(p),'exec'))
shirt=fresh[0];shirt.name='Untouched_native_shirt';shirt.matrix_world=Matrix.Identity(4);points=[v.co.copy() for v in shirt.data.vertices];polys=[list(f.vertices) for f in shirt.data.polygons];tree=BVHTree.FromPolygons(points,polys);radius=.0022;gap=.0027;shoulders=[]
for side in [-1,1]:
 path=[]
 for j in range(16):
  x=side*(.105+.005*j);hit,normal,index,distance=tree.ray_cast(Vector((x,0,.15)),Vector((0,0,-1)),1);assert hit is not None and hit.z>-.10,(x,hit);path.append(hit-normal.normalized()*(radius+gap))
 shoulders.append(path)
wire=shoulders[0][::-1]+[Vector((0,0,.06))]+shoulders[1];wire.append(wire[0]);segments=list(zip(wire[:-1],wire[1:]));clear=[]
for a,b in segments:
 length=(b-a).length;n=max(1,math.ceil(length/.0005));nearest=min(tree.find_nearest(a.lerp(b,k/n))[3] for k in range(n+1));clear.append(nearest-length/n/2)
sets=[set(f) for f in polys];coords=[{tuple(round(float(x),7) for x in points[k]) for k in f} for f in polys];overlap=[(i,j) for i,j in tree.overlap(tree) if j>i and not sets[i]&sets[j] and not coords[i]&coords[j]]
proof={'scope':'untouched height-fitted native shirt; curved wire fitted to actual inner shoulder roof; no cloth step','wire_radius_m':radius,'minimum_wire_centreline_surface_distance_lower_bound_m':min(clear),'required_minimum_m':.0037,'initial_nonadjacent_overlap_candidates':len(overlap),'pass':min(clear)>=.0037 and not overlap,'wire_points':[list(q) for q in wire]}
(ref/'garment_roof_hanger_pilot_preflight.json').write_text(json.dumps(proof,indent=2));assert proof['pass'],'Initial wire/body preflight failed'
c=bpy.data.curves.new('Measured shoulder wire','CURVE');c.dimensions='3D';c.bevel_depth=radius;c.bevel_resolution=3;s=c.splines.new('POLY');s.points.add(len(wire)-2)
for dst,co in zip(s.points,wire[:-1]):dst.co=(*co,1)
s.use_cyclic_u=True;hanger=bpy.data.objects.new('Measured shoulder wire',c);bpy.context.scene.collection.objects.link(hanger);bpy.context.view_layer.objects.active=hanger;hanger.select_set(True);bpy.ops.object.convert(target='MESH');hanger=bpy.context.object
pins=shirt.vertex_groups.new(name='Actual_roof_contacts');pin_rows=[]
for side in [-1,1]:
 candidates=[]
 for v in shirt.data.vertices:
  q=v.co
  if not(.11<side*q.x<.18 and q.z>-.07):continue
  distances=[]
  for a,b in segments:
   axis=b-a;t=max(0,min(1,(q-a).dot(axis)/axis.length_squared));distances.append((q-(a+t*axis)).length-radius)
  distance=min(distances)
  if .0015<=distance<=.004:candidates.append((distance,v.index))
 assert len(candidates)>=6,('insufficient true contact vertices',side,len(candidates))
 for distance,index in sorted(candidates)[:6]:pins.add([index],1,'REPLACE');pin_rows.append({'index':index,'wire_gap_m':distance})
proof['pin_contacts']=pin_rows
for o in list(bpy.data.objects):
 if o not in [shirt,hanger]:bpy.data.objects.remove(o,do_unlink=True)
shirt.data.materials.clear();m=bpy.data.materials.new('Neutral cloth diagnostic');m.use_nodes=True;bs=m.node_tree.nodes['Principled BSDF'];bs.inputs['Base Color'].default_value=(.32,.38,.43,1);bs.inputs['Roughness'].default_value=.8;shirt.data.materials.append(m)
for f in shirt.data.polygons:f.material_index=0;f.use_smooth=True
bpy.ops.wm.save_as_mainfile(filepath=str(ref/'garment_roof_hanger_pilot.blend'));(ref/'garment_roof_hanger_pilot_preflight.json').write_text(json.dumps(proof,indent=2));print('PREFLIGHT_AND_CONTACTS_PASS',len(pin_rows),flush=True)
