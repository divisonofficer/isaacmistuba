import collections,hashlib,json,sys
from pathlib import Path
R=Path(__file__).resolve().parents[3];D=R/'data/venue_refs/floor_plans_v3/shared_dining_residence_05';sys.path.insert(0,str(Path(__file__).parent));from preflight import audit
assert not (D/'floor_plan.json').exists()
p={k:{} for k in ['rooms','doors','opens','interiors','windows','entrance']};m={}
def room(k,s,pts):
 rid=s+'_0/0';m[k]={'room_id':rid,'polygon_m':pts};p['rooms'][rid]={'shape':f'shapely.Polygon({pts!r})'}
room('twin_bedroom','bedroom',[(0,6.2),(6,6.2),(6,10.8),(0,10.8)])
room('shared_dining_kitchen','living-room',[(6,6.2),(6,10.8),(14,10.8),(14,0),(8.7,0),(8.7,5),(6,5)])
room('utility_kitchen_laundry','kitchen',[(0,0),(1.5,0),(1.5,2.7),(3,2.7),(3,0),(8.7,0),(8.7,5),(6,5),(6,6.2),(0,6.2)])
room('compact_wc','bathroom',[(1.5,0),(3,0),(3,2.7),(1.5,2.7)])
def op(g,k,pts):p[g][k]={'shape':f'shapely.LineString({pts!r})'}
op('doors','bedroom_dining',[(6,6.5),(6,7.5)]);op('doors','laundry_dining',[(8.7,3.3),(8.7,4.3)]);op('doors','wc',[(1.7,0),(2.7,0)])
# WC exterior entry visible in source: use entrance, not falsely internal door.
p['doors'].pop('wc');op('entrance','wc_entry',[(1.7,0),(2.7,0)]);op('entrance','main',[(14,4.0),(14,5.2)])
for k,pts in [('bedroom',[(.7,10.8),(4.8,10.8)]),('kitchen',[(7,10.8),(9,10.8)]),('dining_east',[(14,6.2),(14,8.7)]),('utility',[(0,2.9),(0,5.2)]),('dining_south',[(10,0),(12.7,0)])]:op('windows',k,pts)
c={'scene_id':'shared_dining_residence_05','seed':48712505,'revision':'plan_r0','source':'source.png','source_sha256':hashlib.sha256((D/'source.png').read_bytes()).hexdigest(),'dimension_authority':'Image estimate calibrated to 2.0m adult beds and 0.75m tables, not surveyed','required_room_count':4,'required_semantic_counts':dict(collections.Counter(v['room_id'].split('_0/')[0] for v in m.values())),'minimum_door_width_m':.85,'minimum_room_area_m2':3,'entry_room':m['shared_dining_kitchen']['room_id'],'wall_height_m':2.8,'wall_thickness_m':.2,'source_uncertainties':['Metric dimensions estimated; not surveyed','Utility tiled area enclosure ambiguous; treated roofed interior provisionally','WC south entry inferred from outward visible door; main south dining opening assumed glazed','Three dining tables share continuous east room; not invented separate walled rooms','No shower or extra bedroom invented'],'required_views':['overview','shared_dining','twin_bedroom','utility_laundry','compact_wc'],'photorealism_accepted':False,'dataset_promoted':False}
for n,d in [('floor_plan.json',p),('room_mapping.json',m),('scene_contract.json',c)]: (D/n).write_text(json.dumps(d,indent=2)+'\n')
a=audit(D);(D/'preflight_layout.json').write_text(json.dumps(a,indent=2));assert a['status']=='pass',a
print('DINING_PLAN_PASS')
