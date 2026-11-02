"""Saved-source toiletry shelf/label checks;doesnot certify closure physics orwhole-scene QA."""
import bpy,json,argparse,hashlib
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree

def evaluated_points_faces(o,parent,deps):
 ev=o.evaluated_get(deps);me=ev.to_mesh();M=parent.matrix_world.inverted()@o.matrix_world;points=[M@v.co for v in me.vertices];faces=[tuple(f.vertices) for f in me.polygons];ev.to_mesh_clear();return points,faces

def overlap_count(a,b,parent,deps):
 ap,af=evaluated_points_faces(a,parent,deps);bp,bf=evaluated_points_faces(b,parent,deps);return len(BVHTree.FromPolygons(ap,af).overlap(BVHTree.FromPolygons(bp,bf)))

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--blend',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);args=ap.parse_args();src=args.blend.resolve()
 with bpy.data.libraries.load(str(src),link=False) as (a,b):b.objects=[n for n in a.objects if 'ShowerEnclosureFactory' in n or n.startswith('NativeToiletry68_')]
 objects=[o for o in b.objects if o]
 for o in objects:bpy.context.collection.objects.link(o)
 bpy.context.view_layer.update();deps=bpy.context.evaluated_depsgraph_get();showers=[o for o in objects if o.type=='MESH' and 'ShowerEnclosureFactory' in o.name];details=[o for o in objects if o.name.startswith('NativeToiletry68_')];rows=[];errors=[]
 if details:
  if len(showers)!=8 or len(details)!=120:errors.append({'reason':'expected8 showers and24x5 native detail parts','counts':[len(showers),len(details)]})
  for parent in showers:
   me=parent.data;shelf_fs=[f for f in me.polygons if f.material_index==3];ids={i for f in shelf_fs for i in f.vertices};assert len(shelf_fs)==6 and len(ids)==8;shelf_pts=[me.vertices[i].co for i in ids];lo=Vector([min(v[k] for v in shelf_pts) for k in range(3)]);hi=Vector([max(v[k] for v in shelf_pts) for k in range(3)]);tree=BVHTree.FromPolygons([v.co.copy() for v in me.vertices],[tuple(f.vertices) for f in shelf_fs])
   for group in range(3):
    parts=[o for o in details if o.parent==parent and o.get('toiletry_group')==group];bodies=[o for o in parts if any(m and m.name.startswith('ToiletryNative_body_') for m in o.data.materials)];labels=[o for o in parts if any(m and m.name.startswith('ToiletryNative_label_') for m in o.data.materials)]
    if len(parts)!=5 or len(bodies)!=1 or len(labels)!=1:errors.append({'parent':parent.name,'group':group,'reason':'ambiguous native assembly','counts':[len(parts),len(bodies),len(labels)]});continue
    points=[]
    for o in parts:points+=evaluated_points_faces(o,parent,deps)[0]
    low=Vector([min(v[k] for v in points) for k in range(3)]);high=Vector([max(v[k] for v in points) for k in range(3)]);center=(low+high)/2;hit,n,index,d=tree.ray_cast(Vector((center.x,center.y,low.z+.002)),Vector((0,0,-1)),.1);gap=low.z-hit.z if hit else None;overlap=overlap_count(bodies[0],labels[0],parent,deps);inside=lo.x<=low.x<=high.x<=hi.x and lo.y<=low.y<=high.y<=hi.y;passed=inside and gap is not None and abs(gap)<2e-6 and overlap==0;row={'parent':parent.name,'group':group,'support_gap_m':gap,'xy_inside_actual_shelf':inside,'body_label_triangle_overlap_count':overlap,'pass':passed};rows.append(row)
    if not passed:errors.append(row)
 else:rows.append({'status':'not_applicable','note':'No reviewed native-profile toiletries;legacy cylinders are notcertified bythis gate.'})
 report={'source':str(src),'source_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),'auditor_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'records':rows,'errors':errors,'photorealism_accepted':False,'scope':'Saved evaluated24x5 parts,actual shelf ray andXY footprint,body/label triangle intersection. No cap/thread/fluid/hinge simulation orwhole-scene collisions/navigation/photo certification.'};args.out.write_text(json.dumps(report,indent=2));print(json.dumps({'records':len(rows),'errors':len(errors)}),flush=True);return bool(errors)
if __name__=='__main__':raise SystemExit(main())
