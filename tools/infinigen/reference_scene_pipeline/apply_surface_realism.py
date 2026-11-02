"""Apply user-requested clean multiscale surfaces to new scene candidates."""
import argparse,json
from pathlib import Path
import bpy
from surface_realism import enrich,glazed_ceramic,tile_material,grout_material
import tile_geometry
ROOT=Path(__file__).resolve().parents[3]
p=argparse.ArgumentParser();p.add_argument('--scene',choices=['office','residential'],required=True);p.add_argument('--pilot-room',default='');a=p.parse_args()
office=a.scene=='office';scene='commercial_office_floor_02' if office else 'dual_unit_residential_floor_03';seed=48712502 if office else 48712503;previous=15 if office else 16;revision=16 if office else 17
base=ROOT/'out/infinigen_v2'/f'kr_{scene}_{seed}'/'full';ref=ROOT/'data/venue_refs/floor_plans_v3'/scene;source=base/f'scene_review_r{previous}_packed.blend';out=base/(f'surface_pilot_r{revision}.blend' if a.pilot_room else f'scene_candidate_r{revision}.blend');assert not out.exists()
bpy.ops.wm.open_mainfile(filepath=str(source))
used={s.material.name for o in bpy.data.objects if o.type=='MESH' for s in o.material_slots if s.material};changes=[];unhandled=[]
for name in sorted(used):
 m=bpy.data.materials[name];kind=m.get('reference_pbr_kind');lower=name.lower()
 if kind in ('paint','carpet','textile','wood','bare_metal','stone'):pass
 elif 'oak' in lower or lower.startswith('shader_wood'):kind='wood'
 elif lower.startswith(('ir_ceramic_white','ir_shower_tray')):kind='glazed_ceramic'
 elif 'glass' in lower:kind='glass'
 elif lower.startswith(('ir_sfb_','ir_sec_fabric','ir_sec_cushion','ir_sec_pillow','ir_wdc_fabric','ir_bal_teal','res03_sheer','res03_lamp_linen')):kind='textile'
 elif lower.startswith(('ir_kit_top','ir_sdt_stone','ir_sct_stone','ir_vanity_top')):kind='stone'
 elif lower=='res03_shared_core_stone':kind='floor_stone'
 else:continue
 result=enrich(m,kind)
 if result:changes.append(result)
 else:unhandled.append({'material':name,'reason':'non-Principled native shader; preserved to avoid changing transparency contracts'})
ceramic=glazed_ceramic();assigned=[]
for o in bpy.data.objects:
 if o.type=='MESH' and o.get('program_key','').endswith('_wc'):
  o.data.materials.clear();o.data.materials.append(ceramic);assigned.append(o.name)
tiles=[]
if not office:
 floor_mat=tile_material('Realism_porcelain_floor',(.24,.23,.205),.43);wall_mat=tile_material('Realism_porcelain_wall',(.30,.28,.25),.42);grout=grout_material('Realism_clean_grout',(.21,.20,.18))
 rooms=[a.pilot_room] if a.pilot_room else [o.name[:-6] for o in bpy.data.objects if o.name.startswith('bathroom') and o.name.endswith('.floor')]
 for room in rooms:tiles.append(tile_geometry.apply(room,scene,floor_mat,wall_mat,grout))
beveled=[]
for o in bpy.data.objects:
 if o.type!='MESH' or o.name.startswith('Realism_'):continue
 structural=o.name.endswith(('.wall','.ceiling','.exterior'))
 hard=any(s.material and s.material.get('reference_pbr_kind') in ('wood','bare_metal','stone','glazed_ceramic','glass') for s in o.material_slots)
 if not structural and not (o.get('reference_scene_owner')==scene and hard):continue
 if o.get('audit_kind') in ('vegetation','soil','floor_covering'):continue
 if len(o.data.polygons)>20000 or 'shower' in o.get('program_key',''):continue
 if not any(mod.type=='BEVEL' for mod in o.modifiers):
  bevel=o.modifiers.new('realistic_manufactured_edge','BEVEL');bevel.width=.0008 if structural else .0012;bevel.segments=3;bevel.limit_method='ANGLE';beveled.append(o.name)
 if not any(mod.type=='WEIGHTED_NORMAL' for mod in o.modifiers):mod=o.modifiers.new('surface_weighted_normals','WEIGHTED_NORMAL');mod.keep_sharp=True
lighting=[]
if not office and not a.pilot_room:
 from bathroom_lighting import apply as apply_bathroom_lighting
 lighting=apply_bathroom_lighting(json.loads((ref/'room_mapping.json').read_text()))
bpy.data.orphans_purge(do_recursive=True)
bpy.ops.wm.save_as_mainfile(filepath=str(out))
record={'source':str(source),'candidate':str(out),'multiscale_materials':changes,'glazed_wc_assignments':assigned,'actual_tile_geometry':tiles,'new_beveled_objects':beveled,'preserved_native_shader_exceptions':unhandled,'lighting':{'new_practical_sources':lighting,'note':'Pilot A/B uses matched diagnostic lights; full wet-room pass mixes downlights, mirror bars and reduced broad ambient.'},'visual_acceptance':False}
(ref/(f'surface_pilot_r{revision}.json' if a.pilot_room else f'material_detail_r{revision}.json')).write_text(json.dumps(record,indent=2));print(json.dumps({'saved':str(out),'materials':len(changes),'wc':len(assigned),'tiles':sum(x['floor_tiles']+x['wall_tiles'] for x in tiles),'beveled':len(beveled)}))
