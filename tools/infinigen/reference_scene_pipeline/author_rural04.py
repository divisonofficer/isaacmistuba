"""Initial SI reconstruction of user cottage reference, not surveyed dimensions.
Native indoor shell excludes the open porch/garden, authored as exterior zones.
Roof-hidden space is explicitly unassigned, not an invented functional room.
"""
import collections,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];D=ROOT/'data/venue_refs/floor_plans_v3/rural_stone_cottage_04';sys.path.insert(0,str(Path(__file__).parent))
from preflight import audit

def main():
 assert (D/'source.png').exists()
 for name in ['floor_plan.json','room_mapping.json','scene_contract.json']:assert not (D/name).exists(),'Preserve previous authored plan'
 mapping={};plan={k:{} for k in ['rooms','doors','opens','interiors','windows','entrance']}
 def room(key,semantic,points,**extra):
  rid=f'{semantic}_0/{sum(x["room_id"].startswith(semantic+"_0/") for x in mapping.values())}';mapping[key]={'room_id':rid,'polygon_m':points,**extra};plan['rooms'][rid]={'shape':f'shapely.Polygon({points!r})'}
 def rect(key,semantic,x0,y0,x1,y1,**extra):room(key,semantic,[(x0,y0),(x1,y0),(x1,y1),(x0,y1)],**extra)
 rect('living_kitchen','living-room',3.4,2.4,10.4,11.4)
 rect('bedroom','bedroom',0,7.2,3.4,11.4)
 rect('storage_west','closet',0,2.4,3.4,7.2)
 rect('study','office',2.1,11.4,7.2,15.4)
 rect('storage_north','closet',7.2,11.4,9.4,15.4)
 rect('aux_kitchen','kitchen',10.4,2.4,13.6,8.8)
 room('roof_occluded_unassigned','utility',[(10.4,8.8),(13.6,8.8),(13.6,15.4),(9.4,15.4),(9.4,11.4),(10.4,11.4)],provisional=True,source_note='Roof hides interior;function unknown. Empty reserved volume only.')
 def opening(group,key,points,**extra):plan[group][key]={'shape':f'shapely.LineString({points!r})',**extra}
 for key,points in [('bedroom',[(3.4,8.1),(3.4,9.2)]),('storage_west',[(3.4,4.0),(3.4,5.0)]),('study',[(4.1,11.4),(5.2,11.4)]),('storage_north',[(7.7,11.4),(8.7,11.4)]),('aux_kitchen',[(10.4,4),(10.4,5.2)])]:opening('doors',key,points)
 opening('opens','roof_unknown_provisional_access',[(10.4,9.2),(10.4,10.3)],provisional=True)
 opening('entrance','porch_entry',[(5.2,2.4),(6.4,2.4)])
 opening('entrance','bedroom_garden',[(0,8.3),(0,9.5)],source_note='French garden door inferred from supplied bedroom view')
 for key,points in [('living_south_west',[(3.8,2.4),(4.8,2.4)]),('living_south_east',[(7.0,2.4),(9.4,2.4)]),('bedroom_north',[(.4,11.4),(1.7,11.4)]),('study_north',[(2.8,15.4),(6.4,15.4)]),('aux_east',[(13.6,3.4),(13.6,5.6)])]:opening('windows',key,points)
 counts=dict(collections.Counter(x['room_id'].split('_0/')[0] for x in mapping.values()))
 contract={'scene_id':'rural_stone_cottage_04','revision':'plan_r0','seed':48712504,'source':'source.png','source_sha256':hashlib.sha256((D/'source.png').read_bytes()).hexdigest(),'dimension_authority':'Estimated from reference and real adult furniture sizes;not surveyed','required_room_count':len(mapping),'required_semantic_counts':counts,'minimum_door_width_m':.9,'minimum_room_area_m2':3,'entry_room':mapping['living_kitchen']['room_id'],'wall_height_m':2.9,'wall_thickness_m':.45,'exterior_zones':{'open_porch':[[0,0],[10.4,0],[10.4,2.4],[0,2.4]],'garden_envelope':[[-4,-4],[18,-4],[18,19],[-4,19]]},'source_uncertainties':['Roof-occluded zone modelled as an empty unassigned reserve;not a verified extra functional room','Porch/garden and pitched slate roof/timber framing are later exterior construction stages','Door/window sizes and heights are provisional;native saved-mesh fit audits required','No bathroom invented where the supplied reference shows none'],'required_views':['overview','living_kitchen','bedroom','study','aux_kitchen','storage_west','storage_north','porch','garden_context'],'photorealism_accepted':False,'dataset_promoted':False}
 for name,data in [('floor_plan.json',plan),('room_mapping.json',mapping),('scene_contract.json',contract)]: (D/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
 checked=audit(D);(D/'preflight_layout.json').write_text(json.dumps(checked,indent=2)+'\n');assert checked['status']=='pass',checked['failures']
 print('RURAL04_PLAN_PREFLIGHT_PASS',len(mapping),'indoor zones;open porch/garden separate',flush=True)

if __name__=='__main__':main()
