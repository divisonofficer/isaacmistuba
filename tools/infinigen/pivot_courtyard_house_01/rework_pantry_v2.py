"""CPU-only pantry furnishing stage; visual acceptance remains pending rendering."""
import bpy, math, random, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'tools/infinigen'))
from room_planner import proc_assets as pa
pa.SURFACE_DETAIL=False
BASE=ROOT/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01'
RUN=ROOT/'out/infinigen_v2/kr_pivotHouse_48712501/full'
rng=random.Random(48712522)
def mat(name,color,rough=.6):
 m=bpy.data.materials.new(name);m.use_nodes=True;p=m.node_tree.nodes.get('Principled BSDF');p.inputs['Base Color'].default_value=(*color,1);p.inputs['Roughness'].default_value=rough;return m
def obj(name,groups):
 o=pa._prims('PivotPantryV2_'+name,groups);o['ir_room']='utility_0/1';o['ir_quality_stage']='pantry_v2';return o
def cyl(x,y,z,r,h):return ('cyl',(x,y,z),(r,r,h),(0,0,0))
def box(x,y,z,dx,dy,dz):return ('box',(x,y,z),(dx,dy,dz),(0,0,0))
oak=pa._flat('pantry_v2_oak',(.42,.29,.17),.52,wood=True)
ceramic=mat('pantry_v2_ivory_ceramic',(.78,.75,.67),.29)
glass=mat('pantry_v2_clear_glass',(.97,.99,.98),.08);p=glass.node_tree.nodes['Principled BSDF'];p.inputs['Transmission Weight'].default_value=1;p.inputs['IOR'].default_value=1.46
rice=mat('pantry_v2_rice',(.70,.56,.34));lentil=mat('pantry_v2_red_lentils',(.46,.16,.055));pasta=mat('pantry_v2_pasta',(.73,.47,.14));green=mat('pantry_v2_leaf',(.075,.20,.045));terracotta=mat('pantry_v2_terracotta',(.40,.16,.075));weave=mat('pantry_v2_woven_fibre',(.38,.27,.14))
for o in list(bpy.data.objects):
 if o.name.startswith('PivotPantryJarFactory'):
  bpy.data.objects.remove(o,do_unlink=True)
# Closed lathed shell with inner wall and bottom; no solid glass cylinders.
def jar(name,x,y,bottom,r,h):
 profile=[(0,bottom),(r,bottom),(r,bottom+h-.025),(r*.89,bottom+h),(r*.80,bottom+h),(r*.80,bottom+.012),(0,bottom+.012)]
 verts=[];n=64
 for rad,z in profile:
  verts.extend((x+rad*math.cos(2*math.pi*k/n),y+rad*math.sin(2*math.pi*k/n),z) for k in range(n))
 faces=[]
 for j in range(len(profile)-1):
  for k in range(n):faces.append((j*n+k,j*n+(k+1)%n,(j+1)*n+(k+1)%n,(j+1)*n+k))
 me=bpy.data.meshes.new(name);me.from_pydata(verts,[],faces);me.materials.append(glass)
 o=bpy.data.objects.new('PivotPantryV2_'+name,me);bpy.context.scene.collection.objects.link(o);o['ir_room']='utility_0/1'
 for f in me.polygons:f.use_smooth=True
 obj(name+'_lid',[(oak,[cyl(x,y,bottom+h+.009,r*.95,.018)])])
 return bottom+.014
shelf_tops=[1.61504,2.11504]
for i,(x,h,material) in enumerate([(18.48,.24,rice),(18.76,.29,lentil),(19.05,.27,pasta)]):
 z=jar('food_jar_'+str(i),x,9.31,shelf_tops[0],.085,h)
 grains=[]
 for k in range(150):
  angle=rng.uniform(0,math.tau);rr=.065*math.sqrt(rng.random());zz=z+rng.uniform(.007,h*.73)
  grains.append(('lsph',(x+rr*math.cos(angle),9.31+rr*math.sin(angle),zz),(.009,.006,.012 if material==rice else .007),(0,0,rng.random()*math.tau)))
 obj('contents_'+str(i),[(material,grains)])
# Stacked dishes sit directly on shelf; rim rings have actual recesses.
for j,x in enumerate([19.43,19.88]):
 for k in range(5):
  z=shelf_tops[0]+.008+k*.017
  obj('plate_%d_%d'%(j,k),[(ceramic,[cyl(x,9.31,z,.105,.014),('cyl',(x,9.31,z+.010),(.105,.097,.009),(0,0,0))])])
# Two woven open baskets on the previously empty upper shelf.
for j,x in enumerate([18.60,19.12]):
 z=shelf_tops[1];parts=[box(x,9.30,z+.008,.34,.23,.016)]
 for k in range(15):
  xx=x-.16+k*.32/14
  parts +=[box(xx,y,z+.09,.009,.012,.18) for y in [9.19,9.41]]
 for k in range(10):
  zz=z+.018+k*.017
  parts +=[box(x,y,zz,.34,.007,.006) for y in [9.185,9.415]]
 for xx in [x-.17,x+.17]:parts.append(box(xx,9.30,z+.09,.014,.23,.18))
 obj('woven_basket_'+str(j),[(weave,parts)])
# Herb pots on upper shelf and counter, deliberately outside central aisle.
for j,(x,y,z) in enumerate([(19.85,9.30,shelf_tops[1]),(20.06,9.43,1.05504)]):
 obj('herb_pot_'+str(j),[(terracotta,[('cyl',(x,y,z+.06),(.055,.075,.12),(0,0,0))])])
 leaves=[];stems=[]
 for k in range(18):
  a=rng.uniform(0,math.tau);rr=rng.uniform(.025,.11);zz=z+.16+rng.uniform(0,.15)
  leaves.append(('sph',(x+rr*math.cos(a),y+rr*math.sin(a),zz),(.035,.014,.008),(rng.random(),rng.random(),a)))
  stems.append(('cyl',(x+rr*.45*math.cos(a),y+rr*.45*math.sin(a),z+.16),(.002,.001,.14),(rr*math.sin(a)*3,rr*math.cos(a)*3,0)))
 obj('herb_leaves_'+str(j),[(green,leaves+stems)])
# Upright recipe books and a supported cutting board on worktop.
colors=[mat('pantry_v2_book_sage',(.20,.30,.22)),mat('pantry_v2_book_cream',(.65,.58,.43)),mat('pantry_v2_book_rust',(.42,.18,.10))]
for i,m in enumerate(colors):obj('cookbook_'+str(i),[(m,[box(18.45+i*.047,9.31,1.05504+.115,.04,.16,.23)])])
obj('cutting_board',[(oak,[box(19.14,9.42,1.06504,.40,.24,.02)])])
bpy.context.view_layer.update()
assert all(math.isfinite(v) for o in bpy.data.objects if o.name.startswith('PivotPantryV2_') for v in o.dimensions)
out=RUN/'scene_rework_pantry_v2.blend';bpy.ops.wm.save_as_mainfile(filepath=str(out))
(BASE/'pantry_rework_v2.json').write_text(json.dumps({'status':'geometry_stage_visual_review_pending','scene':str(out),'changes':['hollow transparent jars and visible grains','stacked dishes','woven upper shelf baskets','herb pots','recipe books and cutting board'],'render_evidence':None,'acceptance':'not yet assessed'},indent=2)+'\n')
print('PIVOT_PANTRY_V2_SAVED',flush=True)
