"""Four actual fresh vanity-style/mirror controls against measured entry/front regions."""
import bpy,json,sys,hashlib,math
from pathlib import Path
from shapely.geometry import box,Polygon
root=Path('/jarvis/project/robomituba');sys.path[:0]=[str(root/'tools/infinigen'),str(Path(__file__).parent)]
from room_planner import proc_home as ph
from wetroom_layout_helpers import place_bottom_wall_vanity,place_sidewall_wc
from wc_layout_checks import bounds,footprint
base=root/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';ref=root/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';src=base/'scene_candidate_r72.blend';routes=json.loads((ref/'wetroom_routes_r72.json').read_text())
with bpy.data.libraries.load(str(src),link=False) as (a,b):b.objects=[n for n in a.objects if n.startswith('Residential03_101_ensuite_wc_')]
assert len(b.objects)==1;prototype=b.objects[0];bpy.context.collection.objects.link(prototype);rows=[]
for unit in [101,102]:
 for oak in [False,True]:
  x0=0 if unit==101 else 19.5;polygon=[[x0,0],[x0+2,0],[x0+2,3],[x0,3]];factory=ph.HomeVanityFactory(73100+unit+int(oak));factory.oak=oak;vanity=factory.spawn_asset(73000+unit+int(oak));vanity.name=f'FreshVanity_{unit}_{oak}';vanity.scale.y=1 if unit==101 else -1;place_bottom_wall_vanity(vanity,polygon,unit)
  wc=prototype.copy();wc.data=prototype.data.copy();bpy.context.collection.objects.link(wc);wc.parent=None;wc.location=(0,0,0);wc.rotation_euler=(0,0,0);wc.scale=prototype.scale.copy();wc.scale.y=abs(wc.scale.y)*(1 if unit==101 else -1);bpy.context.view_layer.update();lo,hi=bounds(wc);wc.location.z-=lo.z;place_sidewall_wc(wc,polygon,unit)
  shower=ph.ShowerEnclosureFactory(73400+unit).spawn_asset(73400+unit);shower.location=(1.38 if unit==101 else 20.12,2.38,0);shower.rotation_euler.z=math.pi if unit==101 else 0;shower.scale.y=1 if unit==101 else -1;bpy.context.view_layer.update();lo,hi=bounds(wc);fw=1 if unit==101 else -1;tip=hi.x if fw==1 else lo.x;front=box(tip if fw==1 else tip-.65,(lo.y+hi.y)/2-.38,tip+.65 if fw==1 else tip,(lo.y+hi.y)/2+.38)
  opening=next(x for x in routes['records'] if x['room']==f'{unit}_ensuite')['opening_candidates'][0];low,high=[y-12 for y in opening['inner_y']];wall=x0+2 if unit==101 else x0;approach=box(wall-.8,low-.3,wall+.02,high+.3) if unit==101 else box(wall-.02,low-.3,wall+.8,high+.3);overlaps=[front.intersection(footprint(q)).area for q in [vanity,shower]];entry=footprint(wc).intersection(approach).area;inside=Polygon(polygon).buffer(1e-6).covers(front);assert entry<1e-7 and inside and max(overlaps)<1e-7,(unit,oak,entry,inside,overlaps);rows.append({'unit':unit,'fresh_factory_oak':oak,'vanity_bounds':[list(v) for v in bounds(vanity)],'wc_bounds':[list(v) for v in bounds(wc)],'entry_overlap_m2':entry,'front_fixture_overlaps_m2':overlaps,'front_inside_room':inside,'pass':True})
 for o in [vanity,wc,shower]:bpy.data.objects.remove(o,do_unlink=True)
p=ref/'initial_wetroom_layout_factory_validation.json';p.write_text(json.dumps({'source_native_wc_template':str(src),'source_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),'helper_sha256':hashlib.sha256(Path(__file__).with_name('wetroom_layout_helpers.py').read_bytes()).hexdigest(),'initial_fitter_sha256':hashlib.sha256(Path(__file__).with_name('fit_residential.py').read_bytes()).hexdigest(),'fresh_factory_controls':rows,'initial_historical_fitter_executed':False,'scope':'Actual fresh white/oak vanity factories andnative WC template,mirrored2 units,measured entry/front bounds. Not full-source orphoto certification. Existing initial r1 snapshot wasnot overwritten.'},indent=2));print('Fresh factory controls passed',len(rows),flush=True)
