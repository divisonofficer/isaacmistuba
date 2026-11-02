"""Reviewed neutral honey finish across real cabinet fronts,carcass,fascia andfiller."""
import bpy,json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];D=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';B=ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';pilot=json.load(open(D/'wood_finish105_pilot/neutral_honey_contract.json'));review=json.load(open(D/'wood_finish105_pilot/blind_visual_review.json'));S=Path(pilot['candidate']);O=B/'scene_candidate_r105.blend';assert not O.exists();sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest();assert sha(S)==pilot['candidate_sha256'];bpy.ops.wm.open_mainfile(filepath=str(S));meta=json.load(open(D/'realism_refinement_r104.json'));previous=meta['photographic_veneer'];oldrows={r['object']:r for r in previous['objects']};extras=[o for o in bpy.context.scene.objects if o.type=='MESH' and o.get('program_key') in ['coffee_end_panel','coffee_back_panel','coffee_bottom_panel','coffee_top_fascia','fridge_left_bay_filler']];assert len(extras)==6;mat=bpy.data.materials[previous['material']];prior_bindings={o.name:[m.name if m else None for m in o.data.materials] for o in list(extras)+[bpy.data.objects[n] for n in oldrows]};mat.name='Office02_r105_photographic_sealed_oak';gain=tuple(mat.node_tree.nodes['R104_preserved_linear_gain'].inputs[2].default_value[:3]);assert max(abs(a-b) for a,b in zip(gain,[.30,.25,.17]))<1e-6;rows=[]
for name,r in oldrows.items():
 r=dict(r);r.update(material=mat.name,old_materials=prior_bindings[name],grain_mapping='vertical');rows.append(r)
for o in sorted(extras,key=lambda o:o.name):
 assert len(o.data.materials)==1;o.data=o.data.copy();me=o.data;geom=hashlib.sha256(repr(([tuple(v.co) for v in me.vertices],[tuple(f.vertices) for f in me.polygons])).encode()).hexdigest();active=me.uv_layers.active_index;layer=me.uv_layers.get('R104_veneer_metres') or me.uv_layers.new(name='R104_veneer_metres');phase=int(hashlib.sha256(o.name.encode()).hexdigest()[:6],16)/(16**6);mode='long_y' if o.get('program_key') in ['coffee_top_fascia','coffee_bottom_panel'] else 'vertical'
 for face in me.polygons:
  n=(o.matrix_world.to_3x3().inverted().transposed()@face.normal).normalized()
  for li in face.loop_indices:
   p=o.matrix_world@me.vertices[me.loops[li].vertex_index].co
   if mode=='vertical':uv=(p.z+phase,p.y) if abs(n.x)>.5 else ((p.z+phase,p.x) if abs(n.y)>.5 else (p.y+phase,p.x))
   else:uv=(p.y+phase,p.z) if abs(n.x)>.5 else ((p.x+phase,p.z) if abs(n.y)>.5 else (p.y+phase,p.x))
   layer.data[li].uv=uv
 me.uv_layers.active_index=active;me.materials.clear();me.materials.append(mat)
 for f in me.polygons:f.material_index=0
 rows.append({'object':o.name,'old_materials':prior_bindings[o.name],'geometry_sha256':geom,'uv_layer':'R104_veneer_metres','phase_m':phase,'grain_mapping':mode,'material':mat.name})
assert len(rows)==17;bpy.ops.wm.save_as_mainfile(filepath=str(O));assert sha(S)==pilot['candidate_sha256'];meta.update(source=str(S),source_sha256=pilot['candidate_sha256'],candidate=str(O),candidate_sha256=sha(O),change='Reviewed neutral-honey photo-oak finish extends from11fronts to6actual cabinet carcass/fascia/filler panels with metreUV andmanufacturing grain directions. No table/exterior/lighting/geometry changes. Table replacement is a separate real-product task.',photographic_veneer={**previous,'objects':rows,'material':mat.name,'linear_basecolor_gain':list(gain),'scope':'17existing real cabinet panels,source photographic4Kroughness/GLnormal retained. Authored finish,not measuredBRDF. Native table remains unchanged andis still anopen reference/geometry defect.'},photorealism_accepted=False);(D/'realism_refinement_r105.json').write_text(json.dumps(meta,indent=2));print('SAVED105',sha(O),flush=True)
