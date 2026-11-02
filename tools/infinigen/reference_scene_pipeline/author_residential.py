"""Two mirrored three-bedroom units; source right-hand labelled panel governs.

The provided composite is itself illustrative. Dimensions and bathroom naming
are explicit reconstruction assumptions, never surveyed facts.
"""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
REF=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03'

def main():
    mapping={};plan={k:{} for k in ['rooms','doors','opens','interiors','windows','entrance']}
    def shape(points):return 'shapely.Polygon('+repr(points)+')'
    def room(key,semantic,pts):
        rid=f'{semantic}_0/{sum(v["room_id"].startswith(semantic+"_0/") for v in mapping.values())}'
        mapping[key]={'room_id':rid,'polygon_m':pts};plan['rooms'][rid]={'shape':shape(pts)}
    def rect(key,semantic,b):
        x0,y0,x1,y1=b;room(key,semantic,[(x0,y0),(x1,y0),(x1,y1),(x0,y1)])
    for unit in (101,102):
        mirror=lambda p: (21.5-p[0],p[1]) if unit==102 else p
        definitions=[('master','bedroom',[(5,14),(9,14),(9,18),(5,18)]),
          ('balcony','balcony',[(0,15),(5,15),(5,18),(0,18)]),
          ('dressing','closet',[(2,12),(5,12),(5,15),(2,15)]),
          ('ensuite','bathroom',[(0,12),(2,12),(2,15),(0,15)]),
          ('bedroom2','bedroom',[(0,9.5),(5,9.5),(5,12),(0,12)]),
          ('bathroom1','bathroom',[(5,12),(7,12),(7,14),(5,14)]),
          ('private_hall','hallway',[(5,9.5),(9,9.5),(9,14),(7,14),(7,12),(5,12)]),
          ('living','living-room',[(0,6),(7,6),(7,9.5),(0,9.5)]),
          ('living_entry','hallway',[(7,6),(9,6),(9,9.5),(7,9.5)]),
          ('kitchen_dining','kitchen',[(3,3),(9,3),(9,6),(3,6)]),
          ('bathroom2','bathroom',[(0,3),(3,3),(3,6),(0,6)]),
          ('bedroom3','bedroom',[(0,0),(5,0),(5,3),(0,3)]),
          ('laundry_wc','bathroom',[(5,0),(7,0),(7,3),(5,3)]),
          ('foyer','hallway',[(7,0),(9,0),(9,3),(7,3)])]
        for key,semantic,pts in definitions:
            ps=[mirror(p) for p in pts];room(f'{unit}_{key}',semantic,list(reversed(ps)) if unit==102 else ps)
        def opening(group,key,pts,**kw):
            plan[group][f'{unit}_{key}']={'shape':f'shapely.LineString({[mirror(p) for p in pts]!r})',**kw}
        for key,pts in [
          ('master_hall',[(7.5,14),(8.5,14)]),
          ('master_dressing',[(5,14.06),(5,14.94)]),
          ('ensuite_dressing',[(2,12.7),(2,13.7)]),
          ('bed2_hall',[(5,10.2),(5,11.2)]),
          ('bath1_hall',[(7,12.5),(7,13.5)]),
          ('bath2_kitchen',[(3,3.9),(3,4.9)]),
          ('bed3_kitchen',[(3.6,3),(4.6,3)]),
          ('laundry_foyer',[(7,.8),(7,1.8)]),
          ('master_balcony',[(5,16),(5,17.3)]),
          ('unit_main',[(9,.6),(9,1.6)]),
          ('unit_landing',[(9,7),(9,8.2)])]:opening('doors',key,pts)
        for key,pts in [('living_hall',[(5.2,9.5),(6.7,9.5)]),
             ('living_entry',[(7,6.4),(7,9.1)]),('entry_kitchen',[(7.3,6),(8.7,6)]),
             ('foyer_kitchen',[(7.3,3),(8.7,3)])]:opening('opens',key,pts)
        for key,pts in [('living',[(0,6.5),(0,9)]),('bed2',[(0,10),(0,11.5)]),
             ('bed3',[(.5,0),(4.4,0)]),('master',[(5.5,18),(8.5,18)]),
             ('balcony',[(.2,18),(4.8,18)]),('kitchen',[(3.3,6),(6.7,6)])]:
            # Kitchen's north boundary is internal to living: open connection,
            # not an exterior window or an extra invented room.
            opening('opens' if key=='kitchen' else 'windows',key,pts,**({} if key=='kitchen' else {'is_panoramic':key in ('living','balcony')}))
    rect('shared_entrance','hallway',(9,0,12.5,2))
    rect('elevator','utility',(9,2,12.5,5))
    rect('shared_landing','hallway',(9,5,12.5,11))
    rect('stairs','staircase-room',(9,11,12.5,18))
    # A real path must bypass the lift shaft. The shared external side passage
    # is represented by a continuous corridor along its east side, not through
    # elevator geometry: split the elevator zone and adjoining landing explicitly.
    elev=mapping['elevator']['room_id'];plan['rooms'][elev]['shape']='shapely.box(9,2,11,5)'
    mapping['elevator']['polygon_m']=[(9,2),(11,2),(11,5),(9,5)]
    rect('lift_bypass','hallway',(11,2,12.5,5))
    def core(group,key,pts):plan[group][key]={'shape':f'shapely.LineString({pts!r})'}
    core('entrance','building_entry',[(9.7,0),(11.8,0)])
    core('opens','entry_bypass',[(11.1,2),(12.4,2)])
    core('opens','bypass_landing',[(11.1,5),(12.4,5)])
    core('doors','elevator_door',[(11,3),(11,4)])
    core('opens','stair_landing',[(9.7,11),(11.8,11)])
    from collections import Counter
    contract={'scene_id':'dual_unit_residential_floor_03','revision':'layout_v1',
       'required_room_count':len(mapping),'required_semantic_counts':dict(Counter(v['room_id'].split('_0/')[0] for v in mapping.values())),
       'minimum_door_width_m':.85,'minimum_room_area_m2':3,
       'source_uncertainties':['Illustrative composite has inconsistent bathroom labels across panels',
          'Bathroom and laundry/WC allocations are reconstruction assumptions',
          'Estimated metric dimensions; shared lift bypass introduced to ensure real access',
          'Balconies are glazed; native shell to be refined into actual balcony enclosure'],
       'required_views':['overview','shared_corridor','stairs','elevator','101_living','101_kitchen','101_master','101_bedroom2','101_bedroom3','101_bathroom','101_balcony','102_living','102_kitchen','102_master','102_bedroom2','102_bedroom3','102_bathroom','102_balcony'],
       'visual_acceptance':False}
    for filename,data in [('floor_plan.json',plan),('room_mapping.json',mapping),('scene_contract.json',contract)]:
        (REF/filename).write_text(json.dumps(data,indent=2)+'\n')
    print(json.dumps({'reference':str(REF),'rooms':len(mapping),'semantic_counts':contract['required_semantic_counts']}))

if __name__=='__main__':main()
