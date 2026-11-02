"""Bounded static lower-edge compression,explicitly not a physical solve."""
import bpy,sys,json,numpy as np,bmesh
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(Path(__file__).parent))
from pillow_shape_refinement import self_overlap
ref=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';out=ref/'contact_compression_pillow_studio';assert not out.exists();out.mkdir()
src=ref/'moderate_panel_pillow_studio/smooth_pressure.blend';bpy.ops.wm.open_mainfile(filepath=str(src));o=bpy.data.objects['Isolated_pillow'];mesh=o.data.copy();o.data=mesh
a=np.asarray([list(v.co) for v in mesh.vertices]);before=a.copy();low=a[:,2].min();L=.065;alpha=.15;mask=a[:,2]<low+L;t=(a[mask,2]-low)/L
# Strictly positive derivative(alpha..):no flatten-to-zero singularity;C1 identity atband top.
a[mask,2]=low+L*(alpha*t+(1-alpha)*t**5*(5-4*t));mesh.vertices.foreach_set('co',a.astype(np.float32).ravel());mesh.update()
overlaps=self_overlap(mesh);assert not overlaps,overlaps[:4]
bpy.ops.wm.save_as_mainfile(filepath=str(out/'compressed.blend'))
views=json.loads((ref/'moderate_panel_pillow_studio/views.json').read_text());(out/'views.json').write_text(json.dumps(views,indent=2))
profiles={}
for name,arr in [('before',before),('after',a)]:
 lo,hi=arr[:,1].min(),arr[:,1].max();edges=np.linspace(lo,hi,17);profiles[name]=[float(arr[(arr[:,1]>=l)&(arr[:,1]<=h),2].min()-low) for l,h in zip(edges[:-1],edges[1:])]
(out/'provenance.json').write_text(json.dumps({'source':str(src),'method':'Static monotone C1 vertical compression inlower65mm,minimum derivative.15;no new physics solve','maximum_vertical_displacement_m':float((before[:,2]-a[:,2]).max()),'upper_vertices_unchanged':bool(np.array_equal(before[~mask],a[~mask])),'self_overlap_pairs':len(overlaps),'relative_bottom_profile_m':profiles,'photorealism_accepted':False,'accepted_for_room_trial':False,'requires':'Actual neutral comparison andindependent review;then actualbed support/geometry/image gates before room acceptance'},indent=2));print('SAVED',out,flush=True)
