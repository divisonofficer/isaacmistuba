"""Scene-specific courtyard/deck and material fit-out after native realization."""
import argparse
import json
import math
from pathlib import Path
import sys
import bpy
from mathutils import Vector

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'tools/infinigen'))
from room_planner import proc_assets as pa
from room_planner.proc_home import BalconyChairFactory

ap=argparse.ArgumentParser();ap.add_argument('blend');ap.add_argument('--out',required=True)
a=ap.parse_args();bpy.ops.wm.open_mainfile(filepath=a.blend)
wood=pa._flat('pivot_oak',(0.48,0.30,0.15),.5,wood=True)
stone=pa._flat('pivot_stone',(0.48,0.46,0.42),.65)
dark=pa._flat('pivot_frame',(0.025,0.03,0.03),.45)
carpet=pa._flat('pivot_carpet',(0.43,0.42,0.40),.95)
grass=pa._flat('pivot_grass',(0.16,0.23,0.07),.95)
plaster=pa._flat('pivot_plaster',(0.78,0.75,0.69),.8)
floor=bpy.data.objects['living-room_0/1.floor']
fz=max((floor.matrix_world@Vector(c)).z for c in floor.bound_box)
added=[]

def box(name,loc,size,mat,roof=False):
 bpy.ops.mesh.primitive_cube_add(size=1,location=loc)
 o=bpy.context.object;o.name='Pivot'+name+'Factory(48712501).spawn_asset('+str(len(added))+')';o.dimensions=size
 bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
 o.data.materials.append(mat);o['pivot_owned']=True;o['pivot_roof']=roof;added.append(o.name)
 return o

for o in bpy.data.objects:
 if (o.name.startswith('bedroom_') and o.name.endswith('.floor')) or o.name in ('living-room_0/0.floor','office_0/0.floor'):
  o.data.materials.clear();o.data.materials.append(carpet)
 if o.name=='garage_0/0.floor':
  o.data.materials.clear();o.data.materials.append(stone)
 # Keep common floor tile layout in the lighting pass; finish bedrooms here.

def deck(x0,y0,x1,y1,prefix):
 n=math.ceil((y1-y0)/.16)
 for i in range(n):
  y=y0+(i+.5)*(y1-y0)/n
  box(prefix+'Plank',((x0+x1)/2,y,fz-.025),(x1-x0,(y1-y0)/n-.004,.05),wood)
 for x in [x0,x0+(x1-x0)/4,x0+(x1-x0)/2,x0+3*(x1-x0)/4,x1]:
  box(prefix+'Post',(x,y1-.08,fz+1.4),(.12,.12,2.8),dark)
 box(prefix+'Roof',((x0+x1)/2,(y0+y1)/2,fz+2.86),(x1-x0+.2,y1-y0+.2,.12),wood,True)

deck(8,17,20.5,21,'MainDeck')
deck(24,14.5,26.5,17,'EntryDeck')
box('CourtyardLawn',(12.25,6.5,fz-.06),(8.5,5,.1),grass)
box('CourtyardPath',(15.9,6.5,fz-.025),(1.1,5,.06),stone)
box('CourtyardPath',(12.25,8.6,fz-.025),(8.5,.8,.06),stone)

# A six-seat timber table, and chairs from the same native procedural library
# as the production room realizer. Each set remains a real 3D object.
box('DeckDiningTop',(12.8,19,fz+.75),(2.2,1.0,.07),wood)
for x in (11.9,13.7):
 for y in (18.65,19.35):box('DeckDiningLeg',(x,y,fz+.36),(.09,.09,.72),wood)
BalconyChairFactory.TEAL=(.35,.35,.32)
for i,(x,y,yaw) in enumerate([(12,18.1,math.pi/2),(12.8,18.1,math.pi/2),(13.6,18.1,math.pi/2),
                            (12,19.9,-math.pi/2),(12.8,19.9,-math.pi/2),(13.6,19.9,-math.pi/2),
                            (18.5,19.7,-math.pi/2),(19.5,19.7,-math.pi/2)]):
 o=BalconyChairFactory(48712501+i).spawn_asset(i);o.location=(x,y,fz);o.rotation_euler.z=yaw
 o['pivot_owned']=True;added.append(o.name)

box('FireplaceSurround',(20.23,13.6,fz+1.3),(.20,1.7,2.6),plaster)
box('FireplaceRecess',(20.115,13.6,fz+.85),(.035,1.3,.55),dark)
ember=pa._flat('pivot_ember',(0.32,.08,.015),.5)
bs=ember.node_tree.nodes['Principled BSDF'];bs.inputs['Emission Color'].default_value=(1,.25,.03,1)
bs.inputs['Emission Strength'].default_value=2
box('FireplaceEmber',(20.087,13.6,fz+.64),(.02,1.15,.05),ember)

# Existing generated Infinigen plants are reused as real geometry. A mature
# shade tree matching the reference is still a separate landscape refinement.
plants=sorted((ROOT/'data/plant_library').glob('plant_*.blend'))
for i,(x,y) in enumerate([(9,4.6),(9,5.8),(9,7.1),(15.2,4.7),(15.2,7.5)]):
 with bpy.data.libraries.load(str(plants[i%len(plants)]),link=False) as (src,dst):
  dst.objects=[n for n in src.objects if n=='ir_plant']
 for o in dst.objects:
  if o:
   bpy.context.scene.collection.objects.link(o);o.name=f'PivotGardenPlantFactory({i}).spawn_asset({i})';o.location=(x,y,fz)
   o['pivot_owned']=True;added.append(o.name)
bpy.context.scene['pivot_scene_id']='pivot_courtyard_house_01'
bpy.context.scene['pivot_dimensions_estimated']=True
bpy.ops.wm.save_as_mainfile(filepath=a.out)
Path(a.out).with_suffix('.fitout.json').write_text(json.dumps({'floor_z':fz,'added':added,
 'known_remaining':['mature shade tree','deck glazing/door comparison','garage external door verification']},indent=2))
print('PIVOT_FITOUT',len(added),flush=True)
