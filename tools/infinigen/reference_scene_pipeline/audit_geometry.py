"""Actual candidate footprint/support audit; conservative hull overlap warnings.

This is not a mesh-triangle intersection or navigation certification. Record
warnings for review instead of declaring images acceptable from geometry alone.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import bpy
import numpy as np
from mathutils.bvhtree import BVHTree
from mathutils import Vector
from shapely.geometry import MultiPoint,Polygon
from shapely.ops import unary_union

ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True);ap.add_argument('--blend',type=Path)
ap.add_argument('--scene',default='commercial_office_floor_02',choices=['commercial_office_floor_02','dual_unit_residential_floor_03'])
a=ap.parse_args(sys.argv[sys.argv.index('--')+1:])
if a.blend:bpy.ops.wm.open_mainfile(filepath=str(a.blend.resolve()))
bpy.context.view_layer.update()
def corners(o):return [o.matrix_world@Vector(c) for c in o.bound_box]
def hull(o):return MultiPoint([(v.x,v.y) for v in corners(o)]).convex_hull
floor_cache={}
def floor_area(o):
    if o.name not in floor_cache:
        polys=[]
        for face in o.data.polygons:
            pts=[o.matrix_world@o.data.vertices[i].co for i in face.vertices]
            normal=(pts[1]-pts[0]).cross(pts[2]-pts[0])
            if normal.length<1e-8 or abs(normal.z)/normal.length<.5:continue
            poly=Polygon([(p.x,p.y) for p in pts])
            if poly.is_valid and poly.area>1e-8:polys.append(poly)
        assert polys,f'Cannot recover actual top surface: {o.name}'
        floor_cache[o.name]=unary_union(polys)
    return floor_cache[o.name]
floors=[o for o in bpy.data.objects if o.type=='MESH' and o.name.endswith('.floor')]
ceilings=[o for o in bpy.data.objects if o.type=='MESH' and (o.name.endswith('.ceiling') or o.get('audit_ceiling_surface',False))]
objects=[o for o in bpy.data.objects if o.type=='MESH' and o.get('reference_scene_owner')==a.scene]
floor_union=unary_union([floor_area(o) for o in floors]);records=[];errors=[];overlaps=[]
lighting=[]
for o in bpy.data.objects:
    if not (o.type=='LIGHT' and o.name.startswith(('office02_area','office02_support_area','res03_area_','Realism_','FineR'))):continue
    point=MultiPoint([(o.location.x,o.location.y)]).convex_hull
    above=[c for c in ceilings if hull(c).buffer(.02).covers(point)]
    limit=min((min(v.z for v in corners(c)) for c in above),default=None)
    good=limit is not None and o.location.z<limit-.01
    lighting.append({'object':o.name,'z':o.location.z,'containing_ceiling_z':limit,'below_ceiling':good})
    if not good:errors.append({'object':o.name,'reason':'light_not_below_measured_ceiling'})
for o in objects:
    xy=hull(o);pts=corners(o);zmin=min(p.z for p in pts)
    kind=o.get('audit_kind','furniture')
    supporting=[f for f in floors if floor_area(f).buffer(.03).covers(xy)]
    if not supporting and kind in ('furniture','ground_container','vegetation'):
        errors.append({'object':o.name,'reason':'footprint_not_inside_single_floor'})
    gap=None
    if supporting:
        top=max(max(v.z for v in corners(f)) for f in supporting);gap=zmin-top
        if kind in ('furniture','ground_container') and abs(gap)>.025:errors.append({'object':o.name,'reason':'ground_gap','gap_m':gap})
    if kind=='vegetation':
        soil_object=bpy.data.objects.get(o.get('support_object','')) if o.get('support_object') else next((s for s in objects if s.get('program_key')=='soil_'+str(o['program_key']).split('_')[-1]),None)
        if soil_object is None:errors.append({'object':o.name,'reason':'missing_soil_support'})
        else:
            # Rotated leaf bounding boxes extend below the actual petiole root.
            co=np.empty(len(o.data.vertices)*3,dtype=np.float64);o.data.vertices.foreach_get('co',co);co=co.reshape(-1,3);matrix=np.asarray(o.matrix_world,dtype=np.float64);root_points=co@matrix[:3,:3].T+matrix[:3,3];root_z=float(root_points[:,2].min())
            soil_points=[soil_object.matrix_world@v.co for v in soil_object.data.vertices]
            soil_z=max(v.z for v in soil_points);root_gap=root_z-soil_z
            if root_gap>.006:errors.append({'object':o.name,'reason':'plant_root_above_soil','gap_m':root_gap})
            if root_z<min(v.z for v in soil_points)-.003:errors.append({'object':o.name,'reason':'plant_root_below_soil_volume','gap_m':root_gap})
            root_xy=MultiPoint(root_points[root_points[:,2]<root_z+.002,:2]).convex_hull
            if not hull(soil_object).buffer(.002).covers(root_xy):errors.append({'object':o.name,'reason':'plant_root_outside_soil_footprint'})
    if kind=='container_contents':
        host=bpy.data.objects.get(o.get('support_object',''))
        if host is None:errors.append({'object':o.name,'reason':'missing_container_support'})
        else:
            points=[o.matrix_world@v.co for v in o.data.vertices];hp=[host.matrix_world@v.co for v in host.data.vertices]
            ct=BVHTree.FromPolygons(points,[list(f.vertices) for f in o.data.polygons]);ht=BVHTree.FromPolygons(hp,[list(f.vertices) for f in host.data.polygons])
            if ct.overlap(ht):errors.append({'object':o.name,'reason':'contents_intersect_container_body'})
            if not hull(host).buffer(.001).covers(hull(o)) or max(v.z for v in points)>max(v.z for v in hp):errors.append({'object':o.name,'reason':'contents_outside_container_bounds'})
            low=min(v.z for v in points);bottom=[v for v in points if v.z<low+.0001];gaps=[]
            for q in bottom:
                hit=ht.ray_cast(q+Vector((0,0,.01)),Vector((0,0,-1)),.1)[0]
                if hit is not None:gaps.append(q.z-hit.z)
            if len(gaps)!=len(bottom) or not gaps or min(gaps)<-.001 or max(gaps)>.006:errors.append({'object':o.name,'reason':'contents_bottom_unsupported','gaps_m':gaps[:4]})
    records.append({'name':o.name,'key':o['program_key'],'location':list(o.location),
                    'yaw_rad':o.rotation_euler.z,'size_m':list(o.dimensions),
                    'ground_gap_m':gap,'audit_kind':kind,'floor_rooms':[f.name for f in supporting]})
for i,o in enumerate(objects):
    for other in objects[i+1:]:
        # Above-worktop fixtures and soil/root unions intentionally overlap in
        # XY. Check actual independent ground furniture and vegetation envelopes.
        ko=o.get('audit_kind','furniture');kt=other.get('audit_kind','furniture')
        if ko not in ('furniture','vegetation','ground_container') or kt not in ('furniture','vegetation','ground_container'):continue
        if {ko,kt}=={'vegetation','ground_container'}:continue
        area=hull(o).intersection(hull(other)).area
        if area>.025:overlaps.append({'a':o.name,'b':other.name,'hull_overlap_m2':area})
tabletop_support=[];support_trees={}
for o in objects:
    if o.get('audit_kind')!='tabletop_prop':continue
    parent=bpy.data.objects.get(o.get('support_object',''))
    if parent is None:
        errors.append({'object':o.name,'reason':'missing_tabletop_support_object'});continue
    coordinates=np.empty(len(o.data.vertices)*3,dtype=np.float64);o.data.vertices.foreach_get('co',coordinates);coordinates=coordinates.reshape(-1,3);matrix=np.asarray(o.matrix_world,dtype=np.float64);world=coordinates@matrix[:3,:3].T+matrix[:3,3];point=world[np.argmin(world[:,2])]
    if parent.name not in support_trees:
        vertices=[parent.matrix_world@v.co for v in parent.data.vertices];support_trees[parent.name]=BVHTree.FromPolygons(vertices,[list(p.vertices) for p in parent.data.polygons])
    hit=support_trees[parent.name].ray_cast(Vector((float(point[0]),float(point[1]),float(point[2]+.1))),Vector((0,0,-1)),.3)
    gap=float(point[2]-hit[0].z) if hit[0] is not None else None;good=gap is not None and abs(gap)<.006
    tabletop_support.append({'object':o.name,'support':parent.name,'measured_gap_m':gap,'pass':good})
    if not good:errors.append({'object':o.name,'reason':'tabletop_contact_failed','gap_m':gap})
source=Path(bpy.data.filepath)
coverage=[]
for floor in floors:
    area=floor_area(floor)
    local=[o.name for o in bpy.data.objects if o.type=='LIGHT' and o.data.energy>0
           and area.covers(MultiPoint([(o.location.x,o.location.y)]).convex_hull)
           and o.location.z<min((min(v.z for v in corners(c)) for c in ceilings if hull(c).intersects(area)),default=100)]
    coverage.append({'floor':floor.name,'practical_lights':local})
    if not local:errors.append({'object':floor.name,'reason':'no_in_room_practical_light'})
doc={'source':str(source),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'scene_id':a.scene,
     'status':'needs_review' if errors or overlaps else 'pass_bounded_checks',
     'room_floors':len(floors),'inventory_count':len(objects),
     'furniture_count':sum(o.get('audit_kind','furniture')=='furniture' for o in objects),'errors':errors,
     'lighting_elevation_checks':lighting,'tabletop_support_checks':tabletop_support,
     'room_lighting_coverage':coverage,
     'conservative_overlap_warnings':overlaps,'objects':records,
     'visual_acceptance':False,'limitations':['Bounding hulls are conservative, not actual triangle intersections',
        'Door swing and route sampling remain separate checks','Ground support uses bounds; tabletop props use minimum mesh vertex against raw support triangles within6mm, excluding modifier deformation']}
a.out.write_text(json.dumps(doc,indent=2));print(json.dumps({'errors':len(errors),'hull_warnings':len(overlaps),'out':str(a.out)}))
