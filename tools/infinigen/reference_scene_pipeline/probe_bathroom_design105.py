import bpy,json
from pathlib import Path
R=Path(__file__).resolve().parents[3];S=R/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full/scene_candidate_r104_draft.blend';bpy.ops.wm.open_mainfile(filepath=str(S));rows=[]
for o in bpy.context.scene.objects:
 if o.type!='MESH':continue
 key=str(o.get('program_key',''));name=o.name
 fixture=key.startswith('102_') and any(t in key for t in ['vanity','mirror','shelf','cabinet']) and 'dressing' not in key
 tile=name.startswith('Realism_bathroom_0/') and any('_0/'+str(i)+'_' in name for i in range(4,8))
 if not fixture and not tile:continue
 pts=[o.matrix_world@v.co for v in o.data.vertices]
 if not pts:continue
 rows.append({'object':name,'key':key,'fixture':fixture,'bbox_scope':'raw source mesh,not evaluated modifiers','bbox_m':[[min(p[k] for p in pts) for k in range(3)],[max(p[k] for p in pts) for k in range(3)]],'matrix':[list(v) for v in o.matrix_world],'materials':[{'index':i,'name':m.name,'faces':sum(f.material_index==i for f in o.data.polygons)} for i,m in enumerate(o.data.materials) if m],'vertices':len(o.data.vertices),'polygons':len(o.data.polygons)})
D=R/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';(D/'bathroom105_design_inventory.json').write_text(json.dumps(rows,indent=2));print('BATHROOM_DESIGN105_INVENTORY',len(rows),flush=True)
