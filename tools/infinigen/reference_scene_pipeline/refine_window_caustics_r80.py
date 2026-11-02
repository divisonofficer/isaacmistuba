"""Source79 optical trial: retain real dielectric glass; enable caustic transport and test southwest Sun."""
import bpy,json,hashlib,math
from pathlib import Path
root=Path(__file__).resolve().parents[3];ref=root/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';base=root/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';src=base/'scene_candidate_r79.blend';dst=base/'scene_candidate_r80.blend';assert not dst.exists()
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
evidence=ref/'living_window_caustics_probe_r79/results.json';e=json.loads(evidence.read_text());before=sha(src);assert before==e['source_sha256'] and e['source_unchanged'];assert e['sun_disc_deltas']['caustics']>.1
for row in e['rows']:assert sha(Path(row['path']))==row['sha256']
bpy.ops.wm.open_mainfile(filepath=str(src));scene=bpy.context.scene;world=scene.world;output=next(n for n in world.node_tree.nodes if n.type=='OUTPUT_WORLD' and n.is_active_output);bg=output.inputs['Surface'].links[0].from_node;sky=bg.inputs['Color'].links[0].from_node;assert sky.type=='TEX_SKY' and sky.sky_type=='NISHITA';prior_rotation=sky.sun_rotation;sky.sun_rotation=math.pi/2-math.radians(195);prior_world=world.cycles.is_caustics_light;world.cycles.is_caustics_light=True;casters=[];receivers=[]
for o in scene.objects:
 if o.type!='MESH' or o.hide_render:continue
 dielectric=any(m and m.use_nodes and any(n.type=='BSDF_GLASS' or (n.type=='BSDF_PRINCIPLED' and n.inputs['Transmission Weight'].default_value>.5) for n in m.node_tree.nodes) for m in o.data.materials)
 if dielectric:
  casters.append({'object':o.name,'previous':o.cycles.is_caustics_caster});o.cycles.is_caustics_caster=True
 else:
  receivers.append({'object':o.name,'previous':o.cycles.is_caustics_receiver});o.cycles.is_caustics_receiver=True
assert any(x['object']=='Residential03_r3_101_living_glass' for x in casters);assert sha(src)==before;bpy.ops.wm.save_as_mainfile(filepath=str(dst))
meta={'source':str(src),'source_sha256':before,'candidate':str(dst),'candidate_sha256':sha(dst),'evidence':str(evidence),'evidence_sha256':sha(evidence),'previous_sun_rotation':prior_rotation,'sun_rotation':sky.sun_rotation,'previous_world_caustics':prior_world,'world_caustics':True,'dielectric_casters':casters,'opaque_receivers':receivers,'change':'Only Nishita Sun azimuth and actual World/caster/receiver caustic transport flags. Preserve glass/material graphs, geometry, fixture power/CCT, sky elevation/size/intensity/background strength and exposure. No glass hidden, no camera-specific shaders.','retained_revision':77,'photorealism_accepted':False,'scope':'Source79 lighting remains held pending same-camera six-view RGB and independent review. Global lighting trial requires both-unit regressions. No promotion/full-suite/nav certification.'};(ref/'realism_refinement_r80.json').write_text(json.dumps(meta,indent=2)+'\n');print('WINDOW_CAUSTICS_R80_SAVED',flush=True)
