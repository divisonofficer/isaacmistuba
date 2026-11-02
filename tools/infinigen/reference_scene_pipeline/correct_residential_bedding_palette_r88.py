"""Room-level bedding palette correction, retain geometry/maps and source87 lights."""
import bpy,json,hashlib
from pathlib import Path
R=Path(__file__).resolve().parents[3];D=R/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';B=R/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';S=B/'scene_candidate_r87.blend';O=B/'scene_candidate_r88.blend';assert not O.exists();sha=hashlib.sha256(S.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(S));meta=json.loads((D/'realism_refinement_r87.json').read_text());rows=[]
palette={'101_bedroom2':{'duvet':(.26,.30,.19),'accent':(.18,.23,.12)},'102_bedroom2':{'duvet':(.52,.32,.36),'accent':(.32,.16,.21)},'101_bedroom3':{'duvet':(.40,.38,.44),'accent':(.24,.22,.29)},'102_bedroom3':{'duvet':(.48,.30,.37),'accent':(.30,.15,.23)},'102_master':{'duvet':(.48,.31,.30),'accent':(.29,.16,.18)}}
def fingerprint(o):
 d={'matrix':[list(r) for r in o.matrix_world],'vertices':[list(v.co) for v in o.data.vertices],'polygons':[list(f.vertices) for f in o.data.polygons],'uv':[[list(x.uv) for x in l.data] for l in o.data.uv_layers]} if o.type=='MESH' else {'matrix':[list(r) for r in o.matrix_world],'type':o.type}
 return hashlib.sha256(json.dumps(d).encode()).hexdigest()
def tint(o,index,rgb,role):
 old=o.data.materials[index];m=old.copy();m.name='Res03_r88_'+o.get('program_key',o.name)+'_'+role;bs=next(n for n in m.node_tree.nodes if n.type=='BSDF_PRINCIPLED');base=bs.inputs['Base Color'];oldrgb=list(base.default_value);ratio=[rgb[i]/max(oldrgb[i],.01) for i in range(3)];node=m.node_tree.nodes.new('ShaderNodeMixRGB');node.name='ReferencePaletteMultiply';node.label='Preserve source pattern; room-specific palette';node.blend_type='MULTIPLY';node.inputs[0].default_value=1;node.use_clamp=False;node.inputs[2].default_value=(*ratio,1)
 if base.is_linked:
  link=base.links[0];source=link.from_socket;m.node_tree.links.remove(link);m.node_tree.links.new(source,node.inputs[1])
 else:node.inputs[1].default_value=oldrgb
 m.node_tree.links.new(node.outputs[0],base);base.default_value=(*rgb,1);o.data.materials[index]=m;rows.append({'object':o.name,'program_key':o.get('program_key'),'slot':index,'role':role,'source_material':old.name,'material':m.name,'target_linear_rgb':rgb,'multiply_rgb':ratio,'source_pattern_preserved':True,'scope':'Appearance tint retaining source base pattern and roughness/normal;target is authored palette,not measured reference colour.'})
for o in list(bpy.context.scene.objects):
 if o.type not in ['MESH','CURVE']:continue
 key=o.get('program_key','');room=next((k for k in palette if key.startswith(k+'_bed')),None);native_unit=key[:3] if '_native_bed_pillow' in key and 'teal' in key else None
 if room:
  roles=[]
  for i,m in enumerate(o.data.materials):
   if not m:continue
   faces=sum(p.material_index==i for p in o.data.polygons) if o.type=='MESH' else 1
   if not faces:continue
   if key.endswith('_draped_duvet') and m.name.startswith('ir_sfb_white'):roles.append((i,palette[room]['duvet'],'full_duvet'))
   elif m.name.startswith('ir_sfb_throw') and (key.endswith('_physical_throw') or key.endswith('_draped_duvet')):roles.append((i,palette[room]['accent'],'throw'))
   elif key==room+'_bed' and m.name.startswith('ir_sfb_petrol'):roles.append((i,palette[room]['accent'],'accent_pillow'))
 elif native_unit in ['101','102']:
  roles=[(i,palette[native_unit+'_bedroom2']['accent'],'native_accent_pillow') for i,m in enumerate(o.data.materials) if m]
 else:continue
 if roles:
  before=fingerprint(o);o.data=o.data.copy()
  for args in roles:tint(o,*args)
  assert before==fingerprint(o),o.name
assert len(rows)>=14,len(rows)
assert all(any(x['program_key']==room+'_bed_draped_duvet' and x['role']=='full_duvet' for x in rows) for room in palette)
bpy.ops.wm.save_as_mainfile(filepath=str(O));assert hashlib.sha256(S.read_bytes()).hexdigest()==sha
meta.update(source=str(S),source_sha256=sha,candidate=str(O),candidate_sha256=hashlib.sha256(O.read_bytes()).hexdigest(),retained_revision=87,change='Room-level palette:full-colour duvets on five original beds,101bed3 grey/lavender,102bed3mauve-pink,102rose accents and101olive accents. Source87 native101master bed left unchanged pending semantic texture-role verification.',colour_changes=rows,palette=palette,photorealism_accepted=False,requires='Saved contracts andsame-camera bedrooms3 plus102master/bedroom2 reference review;cloth geometry andfurnishing unresolved.');(D/'realism_refinement_r88.json').write_text(json.dumps(meta,indent=2)+'\n');print('BEDDING_PALETTE_R88_SAVED',len(rows),flush=True)
