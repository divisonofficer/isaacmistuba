import bpy,json
from pathlib import Path
root=Path(__file__).resolve().parents[3];src=root/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full/scene_candidate_r79.blend';bpy.ops.wm.read_factory_settings(use_empty=True)
with bpy.data.libraries.load(str(src),link=False) as (a,b):b.worlds=['World']
w=b.worlds[0];rows=[]
for n in w.node_tree.nodes:
 if n.type=='TEX_SKY':rows.append({'name':n.name,'sky_type':n.sky_type,'sun_disc':n.sun_disc,'sun_elevation':n.sun_elevation,'sun_rotation':n.sun_rotation,'sun_size':n.sun_size,'sun_intensity':n.sun_intensity})
(root/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03/sky_source_r79_probe.json').write_text(json.dumps({'source':str(src),'world':w.name,'sky_nodes':rows,'scope':'Actual saved world parameters only;ray direction/window visibility not yetvalidated.'},indent=2)+'\n');print('RESIDENTIAL_SKY_SOURCE_PROBE_COMPLETE',rows,flush=True)
