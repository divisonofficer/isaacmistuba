"""Reference-required presentation equipment and acoustic ceiling finish."""
import json
from pathlib import Path
import sys
import bpy
from mathutils import Vector
from shapely.geometry import Polygon,LineString
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'tools/infinigen'))
from room_planner import proc_assets as pa
from room_planner.proc_home import OakCredenzaFactory
base=ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full'
ref=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02'
bpy.ops.wm.open_mainfile(filepath=str(base/'scene_candidate_r4.blend'))
fz=max((bpy.data.objects['office_0/9.floor'].matrix_world@Vector(c)).z for c in bpy.data.objects['office_0/9.floor'].bound_box)
cz=min(min((o.matrix_world@Vector(c)).z for c in o.bound_box) for o in bpy.data.objects if o.name.endswith('.ceiling'))
black=pa._flat('office02_presentation_screen',(.008,.012,.018),.22)
seam=pa._flat('office02_acoustic_joint',(.45,.46,.45),.85)
def cube(name,loc,size,mat):
    bpy.ops.mesh.primitive_cube_add(size=1,location=loc);o=bpy.context.object;o.name='Office02_'+name;o.dimensions=size
    bpy.ops.object.transform_apply(location=False,rotation=False,scale=True);o.data.materials.append(mat);return o
added=[]
for key,x,y in [('conference_a',.98,20),('meeting_b',6.16,20),('meeting_c',10.16,20)]:
    o=OakCredenzaFactory(48712502).spawn_asset(len(added));o.name='Office02_'+key+'_credenza';o.location=(x+.12,y,fz);o['reference_scene_owner']='commercial_office_floor_02';o['program_key']=key+'_credenza'
    bpy.context.view_layer.update();bottom=min((o.matrix_world@Vector(c)).z for c in o.bound_box);o.location.z+=fz-bottom
    cube(key+'_display',(x+.10,y,fz+1.65),(.045,1.65,.93),black);added.append(o.name)
mapping=json.loads((ref/'room_mapping.json').read_text());seams=0
for key,r in mapping.items():
    poly=Polygon(r['polygon_m']).buffer(-.16)
    x0,y0,x1,y1=poly.bounds
    for axis in (0,1):
        lo,hi=(x0,x1) if axis==0 else (y0,y1)
        k=0;v=lo+1.2
        while v<hi:
            line=LineString([(v,y0),(v,y1)]) if axis==0 else LineString([(x0,v),(x1,v)])
            intersection=line.intersection(poly)
            parts=list(intersection.geoms) if intersection.geom_type=='MultiLineString' else [intersection]
            for part in parts:
                if part.geom_type!='LineString' or part.length<.15:continue
                coords=list(part.coords);a,b=coords[0],coords[-1]
                dims=(.006,part.length,.003) if axis==0 else (part.length,.006,.003)
                o=cube('acoustic_seam',((a[0]+b[0])/2,(a[1]+b[1])/2,cz-.002),dims,seam)
                o['reference_ceiling_detail']=True;seams+=1
            v+=1.2;k+=1
out=base/'scene_candidate_r5.blend';bpy.ops.wm.save_as_mainfile(filepath=str(out))
(base/'correction_r5.json').write_text(json.dumps({'equipment':added,'ceiling_seams':seams,'visual_acceptance':False},indent=2))
