import json,hashlib,collections
from pathlib import Path
from preflight import audit
R=Path(__file__).resolve().parents[3]
def author(scene,seed):
 d=R/'data/venue_refs/floor_plans_v3'/scene;p={k:{} for k in ['rooms','doors','opens','interiors','windows','entrance']};m={}
 def room(k,s,poly):
  rid=f'{s}_0/{sum(v["room_id"].startswith(s+"_0/") for v in m.values())}';m[k]={'room_id':rid,'polygon_m':poly};p['rooms'][rid]={'shape':f'shapely.Polygon({poly!r})'}
 def rect(k,s,x,y,X,Y):room(k,s,[(x,y),(X,y),(X,Y),(x,Y)])
 def op(g,k,a,b):p[g][k]={'shape':f'shapely.LineString({[a,b]!r})'}
 if seed==48712506:
  rect('west_main_workshop','utility',0,7,7,17);rect('central_main_workshop','utility',7,9,12,17);rect('east_main_workshop','utility',12,7,18,17)
  rect('southwest_machine_bay','utility',0,0,7,7);rect('southcentral_machine_bay','utility',7,0,12,6);rect('southeast_machine_bay','utility',12,0,18,7)
  room('entry_service_core','hallway',[(7,6),(12,6),(12,9),(7,9)])
  for k,a,b in [('west_core',(7,7.3),(7,8.7)),('east_core',(12,7.3),(12,8.7)),('central_core',(8.5,9),(10.5,9)),('south_core',(8.5,6),(10.5,6)),('west_south',(4.8,7),(6.4,7)),('east_south',(12.6,7),(14.2,7))]:op('opens',k,a,b)
  op('entrance','south_entry',(8.5,0),(10.5,0))
  for k,a,b in [('west',(0,10),(0,13)),('east',(18,10),(18,13)),('northwest',(2,17),(5,17)),('northcentral',(8,17),(11,17)),('northeast',(14,17),(17,17)),('southwest',(2,0),(5,0)),('southeast',(14,0),(17,0))]:op('windows',k,a,b)
  entry='southcentral_machine_bay';height=3.6;views=['overview','west_main_workshop','central_main_workshop','east_main_workshop','southwest_machine_bay','southcentral_machine_bay','southeast_machine_bay'];unc=['Reference has no dimension labels;18 x17 m envelope estimated from benches and machinery; +/-25% dimensional uncertainty','Heavy machinery, crates, exposed pipework and specialist tooling require genuine product mesh acquisition; no primitive substitutions permitted','Central stair/service feature is represented as ground-floor circulation reserve pending elevation evidence']
 else:
  rect('kitchen','kitchen',0,8,6,18)
  room('dining_bar_circulation','living-room',[(0,3),(2,3),(2,4),(7,4),(7,0),(12,0),(12,5),(22,5),(22,12),(19,12),(19,15),(6,15),(6,8),(0,8)])
  rect('private_south','dining-room',2,0,7,4);rect('accessible_wc','bathroom',0,0,2,3)
  rect('south_wc','bathroom',17,0,22,5);rect('reception','office',12,0,17,5)
  rect('north_wc','bathroom',19,12,22,18)
  for i in range(4):rect('private_north_'+str(i),'dining-room',6+i*3.25,15,9.25+i*3.25,18)
  for k,a,b in [('kitchen',(6,9),(6,10.4)),('private_south',(7,1.5),(7,2.7)),('accessible_wc',(.5,3),(1.5,3)),('reception',(12,1.5),(12,3)),('south_wc',(17,2),(17,3.2)),('north_wc',(19,13),(19,14.2))]:op('doors',k,a,b)
  for i in range(4):op('opens','private_north_'+str(i),(7+i*3.25,15),(8.2+i*3.25,15))
  op('entrance','main',(13.3,0),(15.1,0));op('opens','reception_dining',(13,5),(15,5))
  # An exterior vestibule notch beside the accessible toilet is excluded, as in source.
  entry='reception';height=3.2;views=['overview','dining_bar_circulation','kitchen','private_south','private_north_0','north_wc','south_wc'];unc=['Reference has no dimension labels;22 x18 m envelope inferred from full-size tables/chairs; +/-25% dimensional uncertainty','Kitchen commercial appliances and bar equipment need genuine product meshes; no primitive substitutions','Restroom cubicles remain fixture-installation subdivision task; preserve adult toilet scale and door clearance']
 c={'scene_id':scene,'seed':seed,'revision':'reference_metric_r0','source':'source.png','source_sha256':hashlib.sha256((d/'source.png').read_bytes()).hexdigest(),'dimension_authority':'Inferred visual scale, not surveyed; explicit +/-25% uncertainty','required_room_count':len(m),'required_semantic_counts':dict(collections.Counter(v['room_id'].split('_0/')[0] for v in m.values())),'minimum_door_width_m':.9,'minimum_room_area_m2':3,'entry_room':m[entry]['room_id'],'wall_height_m':height,'wall_thickness_m':.22,'source_uncertainties':unc,'required_views':views,'photorealism_accepted':False,'dataset_promoted':False}
 for n,v in [('floor_plan.json',p),('room_mapping.json',m),('scene_contract.json',c)]:
  assert not (d/n).exists();(d/n).write_text(json.dumps(v,indent=2)+'\n')
 a=audit(d);(d/'preflight_layout.json').write_text(json.dumps(a,indent=2));assert a['status']=='pass',a
 print(scene,a['status'],flush=True)
for s,z in [('industrial_workshop_floor_06',48712506),('large_restaurant_floor_07',48712507)]:author(s,z)
