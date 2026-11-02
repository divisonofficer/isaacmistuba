"""Measured seat height and bounded toilet/entry checks. No building-code certification."""
import collections
import bpy
from mathutils import Vector
from shapely.geometry import box,Polygon,MultiPoint

def evaluated_geometry(obj):
    bpy.context.view_layer.update()
    ev=obj.evaluated_get(bpy.context.evaluated_depsgraph_get()); mesh=ev.to_mesh()
    return ev,mesh,[ev.matrix_world@v.co for v in mesh.vertices]

def bounds(obj):
    ev,mesh,points=evaluated_geometry(obj)
    lo=Vector([min(v[k] for v in points) for k in range(3)]);hi=Vector([max(v[k] for v in points) for k in range(3)])
    ev.to_mesh_clear();return lo,hi

def seat_measurement(obj):
    ev,mesh,points=evaluated_geometry(obj);floor=min(v.z for v in points);areas=collections.defaultdict(float)
    # Native bowl lip and seat are the dominant near-horizontal upward annuli.
    # Keep both, then select the higher annulus; opened lid is excluded by normal.
    for f in mesh.polygons:
        n=(ev.matrix_world.to_3x3().inverted().transposed()@f.normal).normalized()
        z=sum(points[i].z for i in f.vertices)/len(f.vertices)-floor
        if n.z>.95 and .25<z<.55:
            ps=[points[i] for i in f.vertices];area=sum((ps[i]-ps[0]).cross(ps[i+1]-ps[0]).length/2 for i in range(1,len(ps)-1));areas[round(z,3)]+=area
    ev.to_mesh_clear();assert areas,'No seat annulus measurable'
    largest=max(areas.values());peaks=[(height,area) for height,area in areas.items() if area>=max(.01,.2*largest)]
    assert peaks,'No sufficiently large horizontal seat surface'
    return {'floor_z':floor,'seat_height_m':max(z for z,a in peaks),'dominant_upward_annuli':sorted(peaks)}

def calibrate_seat_height(obj,target=.42,floor_z=None):
    before=seat_measurement(obj);floor_target=before['floor_z'] if floor_z is None else floor_z;factor=target/before['seat_height_m'];assert .8<factor<1.5
    obj.scale.z*=factor;bpy.context.view_layer.update();lo,hi=bounds(obj);obj.location.z+=floor_target-lo.z;bpy.context.view_layer.update();after=seat_measurement(obj)
    assert abs(after['floor_z']-floor_target)<2e-6 and abs(after['seat_height_m']-target)<.002
    return {'before':before,'after':after,'vertical_factor':factor,'horizontal_scale_unchanged':True}

def footprint(obj):
    lo,hi=bounds(obj);return box(lo.x,lo.y,hi.x,hi.y)

def bathroom2_entry_check(obj,room_polygon,unit,doors,fixtures):
    room=Polygon(room_polygon);x0,y0,x1,y1=room.bounds;wall_x=x1 if unit==101 else x0;matches=[]
    for door in doors:
        ev,me,pts=evaluated_geometry(door);attr=me.attributes.get('door_frame')
        if attr and attr.domain=='POINT':
            xy=[(p.x,p.y) for p,a in zip(pts,attr.data) if a.value>.5]
            if len(xy)>=3:
                hull=MultiPoint(xy).convex_hull
                if hull.geom_type=='Polygon':
                    a,b,c,d=hull.bounds
                    if abs((a+c)/2-wall_x)<.12 and min(d,y1)-max(b,y0)>.5:matches.append((door.name,(b,d)))
        ev.to_mesh_clear()
    assert len(matches)==1,('Ambiguous bathroom2 doorway',unit,matches)
    name,(low,high)=matches[0]
    # Conservative design approach zone: 0.8m into room plus0.3m beside jambs.
    # This catches a WC crowded next to the entry even without surface collision.
    approach=box(wall_x-.8,low-.3,wall_x+.02,high+.3) if unit==101 else box(wall_x-.02,low-.3,wall_x+.8,high+.3)
    body=footprint(obj);lo,hi=bounds(obj);cx=(lo.x+hi.x)/2
    forward=obj.matrix_world.to_3x3()@Vector((1,0,0));forward.z=0;forward.normalize();lateral=Vector((-forward.y,forward.x,0));corners=[Vector((x,y,0)) for x,y in list(body.exterior.coords)[:-1]];tip=max(v.dot(forward) for v in corners);side=(min(v.dot(lateral) for v in corners)+max(v.dot(lateral) for v in corners))/2;front=Polygon([(forward*a+lateral*c).xy[:] for a,c in [(tip,side-.38),(tip+.65,side-.38),(tip+.65,side+.38),(tip,side+.38)]])
    obstacles=[{'object':f.name,'overlap_m2':front.intersection(footprint(f)).area} for f in fixtures]
    return {'door':name,'door_opening_y_bounds':[low,high],'wc_footprint_xy':list(body.exterior.coords),'entry_approach_overlap_m2':body.intersection(approach).area,'entry_approach_definition':'0.8m inward,0.3m jamb-side extension; project design gate,not a legal standard','front_clearance_box_xy':list(front.exterior.coords),'front_clearance_inside_room':room.buffer(1e-6).covers(front),'front_fixture_overlaps':obstacles,'pass':body.intersection(approach).area<1e-7 and room.buffer(1e-6).covers(front) and all(x['overlap_m2']<1e-7 for x in obstacles),'scope':'Two mirrored bathroom2 rooms only. Conservative evaluated bounds; not full door-angle sweep or all-room navigation.'}

def place_bathroom2_wc(obj,room_polygon):
    import math
    obj.rotation_euler.z=math.pi/2
    bpy.context.view_layer.update();lo,hi=bounds(obj)
    x0=min(p[0] for p in room_polygon);x1=max(p[0] for p in room_polygon);y0=min(p[1] for p in room_polygon)
    obj.location.x+=(x0+x1)/2-(lo.x+hi.x)/2
    obj.location.y+=y0+.12-lo.y
    bpy.context.view_layer.update()
