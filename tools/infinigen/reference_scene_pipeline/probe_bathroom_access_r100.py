"""Inventory all eight actual WCs and door geometry before user-requested access repair."""
import bpy,json,hashlib,sys
from pathlib import Path
from mathutils import Vector
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(Path(__file__).parent));from wc_layout_checks import bounds,seat_measurement,evaluated_geometry
D=R/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';B=R/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';out=D/'bathroom_access_r100_baseline_probe.json';assert not out.exists();results=[]
for revision in [22,97]:
 S=B/f'scene_candidate_r{revision}.blend';h=hashlib.sha256(S.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(S));wcs=[];doors=[];fixtures=[]
 for o in bpy.context.scene.objects:
  key=str(o.get('program_key',''))
  if o.type!='MESH':continue
  if key.endswith('_wc'):
   lo,hi=bounds(o);wcs.append({'object':o.name,'key':key,'bbox_m':[list(lo),list(hi)],'bbox_size_m':list(hi-lo),'seat':seat_measurement(o),'scale':list(o.scale),'matrix':[list(v) for v in o.matrix_world],'raw_vertices':len(o.data.vertices),'faces':len(o.data.polygons),'properties':{k:v for k,v in o.items() if isinstance(v,(str,int,float,bool))}})
  if 'DoorFactory' in o.name:
   ev,me,pts=evaluated_geometry(o);attrs=[{'name':a.name,'domain':a.domain,'type':a.data_type} for a in me.attributes];frame=me.attributes.get('door_frame');fp=[p for p,a in zip(pts,frame.data) if a.value>.5] if frame and frame.domain=='POINT' else []
   relevant=[]
   if fp:
    lo=[min(p[k] for p in fp) for k in range(3)];hi=[max(p[k] for p in fp) for k in range(3)];relevant=[lo,hi]
   doors.append({'object':o.name,'key':key,'frame_bbox_m':relevant,'attributes':attrs,'matrix':[list(v) for v in o.matrix_world],'modifiers':[{'name':m.name,'type':m.type,'group':m.node_group.name if m.type=='NODES' and m.node_group else None,'properties':{k:v for k,v in m.items() if isinstance(v,(str,int,float,bool))}} for m in o.modifiers]});ev.to_mesh_clear()
  if any(key.startswith(f'{unit}_{room}_') for unit in [101,102] for room in ['bathroom1','bathroom2','ensuite','laundry_wc']) and not key.endswith('_wc') and o.get('audit_kind')=='furniture':
   lo,hi=bounds(o);fixtures.append({'object':o.name,'key':key,'bbox_m':[list(lo),list(hi)]})
 assert hashlib.sha256(S.read_bytes()).hexdigest()==h;results.append({'revision':revision,'source':str(S),'source_sha256':h,'wcs':wcs,'doors':doors,'fixtures':fixtures})
out.write_text(json.dumps({'results':results,'scope':'Actual evaluated geometry inventory;not clearance approval.'},indent=2))
