import json
from pathlib import Path
R=Path(__file__).resolve().parents[3];D=R/'data/venue_refs/floor_plans_v3'
critiques={
'industrial_workshop_floor_06':('r3','furnished_r3_entry.blend',[
'Overview and4room images inspected directly: genuine benches/cabinets/grinders are grounded,circulation stays legible and real bench-grinder manufacture is readable.',
'Workshop remains far too sparse and repetitive versus supplied densely outfitted industrial reference. Military-scale machinery,large engine assemblies,crates,cable/tool clutter and substantial mixed work islands are absent. Extra repeated catalog benches would not resolve this.',
'Native windows/blinds,white skirting and lightweight wood benches read domestic; concrete palette and pipework alone do not match aged factory character.',
'Reference central enclosed stair/service structure remains a flat circulation reserve; ground external south entry is inferred,not confirmed by original.',
'0.9m bounded routes and sampled entrance door motion now include actual exterior skins; these checks do not establish workstation operating clearance,pipe penetrations,continuous human motion or photo acceptance.']),
'large_restaurant_floor_07':('r12','furnished_r12_calibrated.blend',[
'Actual R12RGBs show corrected light multiplier restores visible ceramic/table/tile detail; native tableware,chairs and toilets retain functional adult scale.',
'Black vertical boothfronts remain visible in dining/bar images. Actual scene.ray_cast identifies unmaterialed livingroom.exterior closure sheets left across broadened wall openings. R13cuts matching exterior portals; its new views are pending. Prior wall-only route scope was insufficient and is superseded by exterior-inclusive audits.',
'Dining is much sparser and more repetitive than source: absent dense planted separators,pendants,rugs,cutlery,food and service detail. Four private light-stone tables differ from referenced dark timber.',
'Kitchen genuine native products read domestic and sparse; commercial ventilation,steel prep/storage and manufacture detail remain acquisition/work gaps.',
'WC native toilets/basins and approach aisles have functional scale; stall front privacy leaves/hardware,mirrors,dispensers and source surface richness remain incomplete. Northern enclosed extra ceramic region remains ambiguous.',
'Reception genuine desk/computer is supported but reads office reception rather than restaurant checkout. Bounded geometry checks do not certify access or establish source/style/photo acceptance.'])}
for scene,(rev,candidate,findings) in critiques.items():
 d=D/scene;(d/f'visual_critique_{rev}.json').write_text(json.dumps({'candidate':candidate,'actual_findings':findings,'photorealism_accepted':False},indent=2))
for scene,rev,evidence in [
 ('industrial_workshop_floor_06','r3_entry',['actual_triangulated_body_routes_r3_entry.json','actual_all_native_door_sweeps_r3_entry.json','workshop_measured_entry_r3.json']),
 ('large_restaurant_floor_07','r13_portal_skins',['actual_triangulated_body_routes_r13_portal_skins.json','actual_all_native_door_sweeps_r13_portal_skins.json','actual_portal_exterior_skin_fix_r13.json','native_table_prop_contact_rays_r8.json','native_luminaire_inventory_r12.json'])]:
 d=D/scene;prev=max(d.glob('engineering_review_r*.json'),key=lambda p:p.stat().st_mtime);j=json.loads(prev.read_text());seed=48712506 if 'workshop' in scene else 48712507
 j['candidate']=f'out/infinigen_v2/kr_{scene}_{seed}/furnished_{rev}.blend';j['evidence']=[f'out/infinigen_v2/kr_{scene}_{seed}/{e}'for e in evidence]
 msg='Current body-route and sampled door-sweep checks explicitly include actual native .exterior closure meshes alongside .wall,casings and real furniture; previous wall-only scope superseded.'
 if msg not in j['findings']:j['findings'].insert(0,msg)
 if 'restaurant' in scene:j['findings'].append('R13actual blackfront ray diagnosis: matching broadbooth portal cuts applied to BOTH native wall and exterior skins; retained envelope skins get explicit inferred plaster material. Native furniture matrices unchanged; rendered inspection pending.')
 (d/f'engineering_review_{rev}.json').write_text(json.dumps(j,indent=2));(d/'current_geometry_gate.json').write_text(json.dumps(j,indent=2))
