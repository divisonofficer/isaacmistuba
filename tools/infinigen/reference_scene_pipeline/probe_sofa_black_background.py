"""First-hit geometry evidence for black region;straight continuation is not refractive transport."""
import bpy,json,math
from pathlib import Path
from mathutils import Vector
ROOT=Path(__file__).resolve().parents[3];source=ROOT/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full/scene_candidate_r46.blend';ref=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';bpy.ops.wm.open_mainfile(filepath=str(source));dg=bpy.context.evaluated_depsgraph_get();origin=Vector((2.05,7.25,1.15));target=Vector((.78,7.85,.78));R=(target-origin).to_track_quat('-Z','Y');rows=[]
for px,py in [(.90,.40),(.85,.43),(.96,.36)]:
 x=(2*px-1)*math.tan(math.radians(54)/2);y=(1-2*py)*math.tan(math.radians(54)/2)*3/4;direction=(R@Vector((x,y,-1))).normalized();p=origin.copy();hits=[]
 for depth in range(5):
  hit,pos,normal,index,o,matrix=bpy.context.scene.ray_cast(dg,p,direction,distance=100)
  if not hit:hits.append({'miss':'world','direction':list(direction)});break
  mat=o.data.materials[o.data.polygons[index].material_index] if o.type=='MESH' and index>=0 and o.data.materials else None;hits.append({'object':o.name,'program_key':o.get('program_key'),'face':index,'material':mat.name if mat else None,'position':list(pos),'normal':list(normal)});p=pos+direction*.001
 rows.append({'pixel_fraction':[px,py],'straight_hits':hits})
world=[]
for n in bpy.context.scene.world.node_tree.nodes:
 if n.type=='BACKGROUND':world.append({'node':n.name,'type':n.type,'color':list(n.inputs['Color'].default_value),'strength':n.inputs['Strength'].default_value,'color_link':[x.from_node.name for x in n.inputs['Color'].links]})
 elif n.type=='TEX_SKY':world.append({'node':n.name,'type':n.type,'sky_type':n.sky_type,'sun_elevation':n.sun_elevation,'sun_rotation':n.sun_rotation,'sun_disc':n.sun_disc})
(ref/'sofa_black_background_probe_r46.json').write_text(json.dumps({'source':str(source),'rays':rows,'world':world,'scope':'First-hit geometry and straight continuation only,doesnot model glass refraction or shading opacity;not a light transport diagnosis by itself.'},indent=2));print(json.dumps({'rays':rows,'world':world},indent=2))
