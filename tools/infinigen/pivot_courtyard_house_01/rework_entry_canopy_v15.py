"""Close porch roof/wall gap, ground canopy posts, articulate masonry, add low planted edge."""
import bpy,math,json,sys,random
from pathlib import Path
from mathutils import Vector
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(R/'tools/infinigen'))
from room_planner import proc_assets as pa
B=R/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01';F=R/'out/infinigen_v2/kr_pivotHouse_48712501/full';changes=[]
roof=next(o for o in bpy.data.objects if o.name.startswith('PivotEntryDeckRoofFactory'));roof.location.z-=.1455513;roof.hide_render=False;roof.data.materials.clear();roof.data.materials.append(bpy.data.materials['pivot_plaster'])
for o in bpy.data.objects:
 if o.name.startswith('PivotEntryDeckPostFactory'):
  ratio=(2.8-.1455512)/2.8;o.scale.z*=ratio;o.location.z-=.1455512/2
 if o.name.startswith(('PivotEntryV4_downlight_trim','entry_v4_warm_downlight')):o.location.z-=.1455513
# Warm porch timber: subtle elongated grain, no high-contrast wave pattern.
wood=bpy.data.materials['pivot_r16_residential_oak'].copy();wood.name='entry_v15_warm_deck_oak'
for n in wood.node_tree.nodes:
 if n.type=='VALTORGB':n.color_ramp.elements[0].color=(.20,.12,.055,1);n.color_ramp.elements[1].color=(.31,.205,.11,1)
for o in bpy.data.objects:
 if o.name.startswith('PivotEntryDeckPlankFactory'):
  for s in o.material_slots:s.material=wood
stone=bpy.data.materials['entry_v11_limestone'];soil=bpy.data.materials['courtyard_v3_soil']
def box(c,s):return ('box',c,s,(0,0,0))
def create(n,groups):
 o=pa._prims('PivotEntryV15_'+n,groups);o['ir_room']='entry_deck';return o
# Physical stone course joints on the pier face provide readable masonry detail.
create('stone_pier_courses',[(stone,[box((24.23,14.68,.14555+(i+.5)*.44),(.045,.38,.432)) for i in range(6)])])
create('south_planting_bed',[(soil,[box((25.8,14.25,.15),(1.25,.30,.10))])])
source=bpy.data.objects['PivotLeafyV9_low_shrub_0'];members=[source,*source.children_recursive]
for i,x in enumerate([25.35,25.72,26.10]):
 mapping={}
 for old in members:
  o=old.copy();bpy.context.scene.collection.objects.link(o);mapping[old]=o
 for old,o in mapping.items():o.parent=mapping.get(old.parent);o.matrix_parent_inverse=old.matrix_parent_inverse.copy();o.matrix_basis=old.matrix_basis.copy()
 root=mapping[source];root.name='PivotEntryV15_low_shrub_'+str(i);root.location=(x,14.25,-.08);root.rotation_euler.z=i*1.7;root.scale*=.70;root['ir_room']='entry_deck'
# Native grass tufts add a visibly different low leaf form along the outer bed.
from mathutils import Vector
src=next(o for o in bpy.data.objects if o.name.startswith('PivotBorderV6_FarGrass_'))
for i,x in enumerate([25.48,25.90,26.28]):
 o=src.copy();bpy.context.scene.collection.objects.link(o);o.name='PivotEntryV15_grass_'+str(i);o.parent=None;o.location=(x,14.33,0);bpy.context.view_layer.update();pts=[o.matrix_world@Vector(v) for v in o.bound_box];o.location.z=.20-min(p.z for p in pts);o['ir_room']='entry_deck'
bpy.context.view_layer.update();bpy.context.scene['pivot_revision']='quality_rework_v15';bpy.context.scene['pivot_candidate_status']='work in progress, reference acceptance and regression audit pending';bpy.ops.wm.save_as_mainfile(filepath=str(F/'scene_rework_entry_v15.blend'))
(B/'entry_canopy_stage_v15.json').write_text(json.dumps({'status':'geometry_saved_visual_review_pending','changes':['Canopy underside lowered from 2.94555m to 2.80m to close sky gap above main wall','Canopy posts shortened while retaining floor contact','Warm restrained timber deck material','Actual stone pier courses and open joints','Low shrubs and native grasses south of deck, outside central entry passage'],'remaining':['Original entry camera reference comparison','Roof/light/pier collision and post grounding audit','Path clearance and full affected room regressions']},indent=2)+'\n');print('PIVOT_ENTRY_V15_SAVED',flush=True)
