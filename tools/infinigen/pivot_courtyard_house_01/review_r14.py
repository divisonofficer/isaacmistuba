"""Complete bathroom programme, reference stone finishes, final camera defects."""
import bpy,json,sys,math
from pathlib import Path
from mathutils import Vector
import shapely
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'tools/infinigen'))
from room_planner import proc_assets as pa
from room_planner.proc_home import HomeVanityFactory,ShowerEnclosureFactory,RecessedSpotFactory
pa.SURFACE_DETAIL=False
base=ROOT/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01';run=ROOT/'out/infinigen_v2/kr_pivotHouse_48712501/full';fixes=[]
def remove(o):
 for q in reversed([o,*o.children_recursive]):bpy.data.objects.remove(q,do_unlink=True)
def bounds(o):
 pts=[o.matrix_world@Vector(v) for v in o.bound_box]
 return [(min(v[i] for v in pts),max(v[i] for v in pts)) for i in range(3)]
def align(o,x,y,z):
 bpy.context.view_layer.update();b=bounds(o);o.location+=Vector((x-(b[0][0]+b[0][1])/2,y-(b[1][0]+b[1][1])/2,z-b[2][0]))
def mat(name,col,rough=.7,metal=0):
 m=bpy.data.materials.new(name);m.use_nodes=True;bs=m.node_tree.nodes.get('Principled BSDF');bs.inputs['Base Color'].default_value=(*col,1);bs.inputs['Roughness'].default_value=rough;bs.inputs['Metallic'].default_value=metal;return m
stone=mat('pivot_r14_limestone',(.43,.40,.35),.65);nt=stone.node_tree;bs=nt.nodes.get('Principled BSDF');noise=nt.nodes.new('ShaderNodeTexNoise');noise.inputs['Scale'].default_value=32;ramp=nt.nodes.new('ShaderNodeValToRGB');ramp.color_ramp.elements[0].color=(.37,.35,.31,1);ramp.color_ramp.elements[1].color=(.49,.46,.41,1);nt.links.new(noise.outputs['Fac'],ramp.inputs['Fac']);nt.links.new(ramp.outputs[0],bs.inputs['Base Color'])
ceramic=mat('pivot_r14_ceramic',(.82,.82,.78),.24);dark=mat('pivot_r14_dark_case',(.018,.02,.023),.6);steel=mat('pivot_r14_brushed_hardware',(.48,.50,.52),.3,1)
# A full bath + separate shower + vanity can fit without changing the source
# 2.5m-square room: bath south, shower north-east, vanity west, door north-west.
tub=next(o for o in bpy.data.objects if o.get('ir_room')=='bathroom_0/0' and 'BathtubFactory' in o.name)
tub.rotation_euler.z=0;bpy.context.view_layer.update();longx=tub.dimensions.x>tub.dimensions.y
if longx:tub.scale.x*=1.70/tub.dimensions.x;tub.scale.y*=.75/tub.dimensions.y
else:tub.scale.x*=.75/tub.dimensions.x;tub.scale.y*=1.70/tub.dimensions.y;tub.rotation_euler.z=math.pi/2
align(tub,4.75,12.05,.14754)
for o in list(bpy.data.objects):
 if (o.get('ir_room')=='bathroom_0/0' and any(k in o.name for k in ('Vanity','ShowerEnclosure'))) or 'PivotBathShowerFactory' in o.name:remove(o)
van=HomeVanityFactory(48713401).spawn_asset(1701);van.location=(3.67,12.95,.14754);van['ir_room']='bathroom_0/0'
shower=ShowerEnclosureFactory(48713402).spawn_asset(1702);shower.location=(5.35,13.35,.14754);shower.rotation_euler.z=math.pi;shower['ir_room']='bathroom_0/0'
# A simple wall bath tap/spout, independent of the separate shower.
tap=pa._prims('PivotBathTapFactory(1703).spawn_asset(1703)',[(steel,[('cyl',(4.75,11.80,1.02),(.022,.022,.22),(math.pi/2,0,0)),('cyl',(4.45,11.72,1.01),(.032,.032,.035),(math.pi/2,0,0)),('cyl',(4.57,11.72,1.01),(.032,.032,.035),(math.pi/2,0,0))])]);tap['ir_room']='bathroom_0/0'
fixes.append({'issue':'shared bathroom reference has separate bath and glass shower, previous bath-shower combination insufficient','action':'full programme laid out within original room: 1.7m tub at south, 0.95m shower northeast, vanity west; doorway unchanged'})
# Wainscot tile modules, with actual openings excluded. Do not block doors or
# residential windows: only lower courses beneath window sill are continued.
doc=json.loads((base/'floor_plan.json').read_text());ports=[];windows=[]
for kind in ('doors','opens','entrance'):
 ports.extend(eval(v['shape']) for v in doc[kind].values())
windows=[eval(v['shape']) for v in doc['windows'].values()]
tile_count=0
for rid,rec in doc['rooms'].items():
 if not rid.startswith('bathroom_'):continue
 x0,y0,x1,y1=eval(rec['shape']).bounds
 for side,constant,a0,a1,vertical in [('west',x0,y0+.15,y1-.15,True),('east',x1,y0+.15,y1-.15,True),('south',y0,x0+.15,x1-.15,False),('north',y1,x0+.15,x1-.15,False)]:
  n=max(1,math.ceil((a1-a0)/.55))
  for col in range(n):
   lo=a0+(a1-a0)*col/n;hi=a0+(a1-a0)*(col+1)/n
   wallseg=shapely.LineString([(constant,lo),(constant,hi)] if vertical else [(lo,constant),(hi,constant)])
   if any(wallseg.intersection(p.buffer(.035)).length>.03 for p in ports):continue
   for row in range(2):
    if row==1 and any(wallseg.intersection(w.buffer(.02)).length>.03 for w in windows):continue
    cz=.14754+(row+.5)*.51
    if vertical:loc=(constant+(.153 if side=='west' else -.153),(lo+hi)/2,cz);size=(.008,hi-lo-.006,.504)
    else:loc=((lo+hi)/2,constant+(.153 if side=='south' else -.153),cz);size=(hi-lo-.006,.008,.504)
    o=pa._prims(f'PivotBathTileFactory({1800+tile_count}).spawn_asset({1800+tile_count})',[(stone,[('box',loc,size,(0,0,0))])]);o['ir_room']=rid;tile_count+=1
 floor=bpy.data.objects.get(rid+'.floor')
 if floor:floor.data=floor.data.copy();floor.data.materials.clear();floor.data.materials.append(stone)
fixes.append({'issue':'bathrooms lack reference stone/tile contrast','action':'limestone lower wall tiles and floors, skip authored doorway spans and upper window-sill courses','tiles':tile_count})
# A compact hand basin in the WC southeast corner, clear of the toilet.
x,y,z=5.75,14.32,.80
basinparts=[('box',(x,y,z-.06),(.18,.34,.025),(0,0,0)),('box',(x-.085,y,z),(.018,.34,.12),(0,0,0)),('box',(x+.085,y,z),(.018,.34,.12),(0,0,0)),('box',(x,y-.16,z),(.18,.018,.12),(0,0,0)),('box',(x,y+.16,z),(.18,.018,.12),(0,0,0))]
basin=pa._prims('PivotCornerWashbasinFactory(1901).spawn_asset(1901)',[(ceramic,basinparts),(steel,[('cyl',(5.82,14.32,.94),(.01,.01,.17),(0,0,0)),('cyl',(5.79,14.32,1.02),(.01,.01,.08),(0,math.pi/2,0))])]);basin['ir_room']='bathroom_0/1'
mirror=mat('pivot_r14_mirror',(.8,.82,.84),.02,1)
pa._prims('PivotCornerWcMirrorFactory(1902).spawn_asset(1902)',[(mirror,[('box',(5.837,14.32,1.32),(.008,.33,.46),(0,0,0))])])
lamp=bpy.data.objects.get('pivot_wc_ceiling')
if lamp:lamp.data.energy=23
# Remove scan/noise from all monitor surfaces; both front and back can be seen.
for o in bpy.data.objects:
 if 'PivotCleanMonitorFactory' in o.name:
  for slot in o.material_slots:slot.material=dark
# Suppress the older decorative living pendant geometry, keeping its light
# source while native recessed spots provide the visible ceiling fixtures.
hidden=[]
for o in bpy.data.objects:
 if o.type!='MESH' or any(k in o.name for k in ('RecessedSpot','LinearPendant')):continue
 b=bounds(o)
 if b[2][0]>2.1 and b[2][1]<3.1 and max(b[0][1]-b[0][0],b[1][1]-b[1][0])<1.6 and 15.6<(b[0][0]+b[0][1])/2<20.4 and 11.6<(b[1][0]+b[1][1])/2<16.9:
  o.hide_render=True;hidden.append(o.name)
fixes.append({'issue':'bare WC, monitor texture reappears in new view, old living pendant conflicts with recessed ref','action':'compact corner WC hand basin/mirror, moderated WC light, flat clean display both sides, hide old pendant geometry','hidden_fixture_meshes':hidden})
views=json.loads((run/'review_views_r13.json').read_text())
for v in views:
 if v['name']=='bedroom_0-2_wide1':v.update(location=[2.9,11.95,1.65],target=[1.0,13.3,1.0],hfov=85)
 if v['name']=='bathroom_0-0_wide1':v.update(location=[4.45,13.62,1.65],target=[4.8,12.55,1.0],hfov=95)
(run/'review_views_r14.json').write_text(json.dumps(views,indent=2))
bpy.context.view_layer.update()
# Verify that bath, vanity, shower have disjoint XY footprints, and stay inside.
items={'tub':bounds(tub),'vanity':bounds(van),'shower':bounds(shower)}
for k,b in items.items():assert b[0][0]>3.63 and b[0][1]<5.87 and b[1][0]>11.63 and b[1][1]<13.87,(k,b)
for i,(k,b) in enumerate(items.items()):
 for k2,c in list(items.items())[i+1:]:
  overlap=max(0,min(b[0][1],c[0][1])-max(b[0][0],c[0][0]))*max(0,min(b[1][1],c[1][1])-max(b[1][0],c[1][0]));assert overlap<1e-5,(k,k2,overlap)
invalid=[o.name for o in bpy.data.objects if o.type=='MESH' and any(not math.isfinite(v) or abs(v)>100 for v in o.dimensions)];assert not invalid,invalid
bpy.context.scene['pivot_revision']='r14_bathroom_completion';bpy.ops.wm.save_as_mainfile(filepath=str(run/'scene_review_r14.blend'))
(base/'revision_r14.json').write_text(json.dumps({'fixes':fixes,'invalid_mesh_extents':invalid,'shared_bath_fixtures':items,'camera_changes':['bedroom_0-2_wide1','bathroom_0-0_wide1'],'camera_count':len(views),'limitations':['Generated style references may differ from source plan in opening positions; source-plan topology is retained','Absolute dimensions estimated','Procedural furniture approximates photographic references']},indent=2));print('PIVOT_R14_COMPLETE',flush=True)
