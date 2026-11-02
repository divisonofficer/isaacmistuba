"""Small external geometric diagrams from the saved-source audit; no raster edits."""
import json,math,html
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];D=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';W=D/'wc_access103';a=json.load(open(D/'bathroom_access_r103_saved_audit.json'));assert a['pass']
def simplify(points,eps=.002):
 if len(points)<3:return points
 ax,ay=points[0];bx,by=points[-1];den=math.hypot(bx-ax,by-ay);dist=[math.hypot(x-ax,y-ay) if den<1e-12 else abs((bx-ax)*(ay-y)-(ax-x)*(by-ay))/den for x,y in points[1:-1]];best=max(dist,default=0)
 if best<=eps:return [points[0],points[-1]]
 k=dist.index(best)+1;return simplify(points[:k+1],eps)[:-1]+simplify(points[k:],eps)
for r in a['records']:
 p=r['room_inner_polygon_xy_m'];route=r['path_polyline_xy_m'];xs=[x for x,y in p+route];ys=[y for x,y in p+route];x0=min(xs)-.45;x1=max(xs)+.45;y0=min(ys)-.45;y1=max(ys)+.45
 def xy(pts):return ' '.join(f'{x:.4f},{-y:.4f}' for x,y in simplify(pts))
 def polygon(pts,fill,stroke,width=.006,opacity=1):return f'<polygon points="{xy(pts)}" fill="{fill}" stroke="{stroke}" stroke-width="{width}" opacity="{opacity}"/>'
 body=polygon(p,'#fff','#17202a',.018)
 for f in r['fixture_footprints_xy_m']:body+=polygon(f['polygon'],'#d9dde3','#7a8189')
 for f in r['door_sweep_regions_xy_m']:body+=polygon(f,'#f4a340','#d68a23',.005,.28)
 for f in r['fixed_door_footprints_xy_m']:body+=polygon(f,'#555','#555',.003)
 body+=f'<polyline points="{xy(route)}" fill="none" stroke="#269f7b" stroke-width=".6" opacity=".16" stroke-linecap="round" stroke-linejoin="round"/>'
 body+=polygon(r['wc_footprint_xy_m'],'#ba9be1','#6b459b',.012)
 body+=f'<polyline points="{xy(route)}" fill="none" stroke="#168066" stroke-width=".014"/>'
 cx,cy,_=r['bowl_centre_m'];body+=f'<circle cx="{cx}" cy="{-cy}" r=".018" fill="#5b248c"/>'
 svg=f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x0:.4f} {-y1:.4f} {x1-x0:.4f} {y1-y0:.4f}"><title>{html.escape(r["key"])} saved103 local access diagram</title><rect x="{x0}" y="{-y1}" width="{x1-x0}" height="{y1-y0}" fill="#f9fbfd"/>{body}</svg>'
 assert len(svg.encode())<100000;(W/(r['key']+'_access.svg')).write_text(svg)
print('8 saved-source diagrams;display curves simplified2mm,exact audit JSON preserved')
