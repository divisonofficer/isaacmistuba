"""Locate self-overlap introduction before any cloth step; no scene save."""
from pathlib import Path
import json,bpy
from mathutils.bvhtree import BVHTree
stages=[]
def record_stage(label,o):
 me=o.data;polys=[list(f.vertices) for f in me.polygons];points=[v.co.copy() for v in me.vertices];tree=BVHTree.FromPolygons(points,polys);sets=[set(f) for f in polys];coords=[{tuple(round(float(x),7) for x in points[k]) for k in f} for f in polys];pairs=[(i,j) for i,j in tree.overlap(tree) if j>i and not sets[i]&sets[j] and not coords[i]&coords[j]]
 samples=[]
 for i,j in pairs[:12]:samples.append({'faces':[i,j],'centres':[[float(c) for c in me.polygons[k].center] for k in [i,j]]})
 stages.append({'stage':label,'candidate_nonadjacent_overlap_pairs':len(pairs),'samples':samples});print('INITIAL_STAGE',label,len(pairs),flush=True)
p=Path(__file__).with_name('garment_mass_corrected_pilot03.py');code=p.read_text().split('# Require actual initial wire clearance')[0].replace('garment_mass_corrected_pilot03','garment_initial_stage_control')
code=code.replace('bm.to_mesh(f.data);bm.free();fresh.append(f)','bm.to_mesh(f.data);bm.free();fresh.append(f);record_stage("fresh_neck_cut",f)')
code=code.replace('upper_pairs=sorted','record_stage("before_shoulder_fit",proto)\n upper_pairs=sorted')
code=code.replace('proto.data.transform(proto.matrix_world);','record_stage("after_shoulder_fit",proto)\n proto.data.transform(proto.matrix_world);')
code=code.replace("proto['contact_pin_proof_json']=json.dumps(pin_proof)","record_stage('after_contact_pins',proto)\n proto['contact_pin_proof_json']=json.dumps(pin_proof)")
exec(compile(code,str(p),'exec'))
(ref/'garment_initial_stage_control.json').write_text(json.dumps({'stages':stages,'scope':'BVH candidate nonadjacent overlaps only; no signed depth or cloth solve; not visual acceptance'},indent=2))
