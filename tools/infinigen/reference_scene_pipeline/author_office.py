"""Session-authored source reconstruction; dimensions are estimates, not surveyed.

No planner API. Creates the native Infinigen predefined-floorplan contract.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
REF = ROOT / 'data/venue_refs/floor_plans_v3/commercial_office_floor_02'


def main():
    rooms, mapping = {}, {}
    def room(key, semantic, points):
        rid = f'{semantic}_0/{sum(v["room_id"].startswith(semantic+"_0/") for v in mapping.values())}'
        rooms[rid] = {'shape': f'shapely.Polygon({points!r})'}
        mapping[key] = {'room_id': rid, 'polygon_m': points}
    def box(key, semantic, x0, y0, x1, y1):
        room(key, semantic, [(x0,y0),(x1,y0),(x1,y1),(x0,y1)])
    # Six cellular offices are visually distinguishable in the supplied image.
    # Their individual labels are too small to transcribe reliably.
    for i in range(6):
        y0, y1 = 3+i*2.5, 5.5+i*2.5
        room(f'private_office_{i+1}', 'office',
             [(.045*y0,y0),(4,y0),(4,y1),(.045*y1,y1)])
    box('conference_a','office',.81,18,6,22)
    box('meeting_b','office',6,18,10,22)
    room('meeting_c','office',[(10,18),(14.56,18),(14.24,22),(10,22)])
    room('open_workplace','office',[(4,3),(10,3),(10,10),(15.2,10),
                                  (14.56,18),(4,18)])
    box('support_west','utility',10,8,12.5,10)
    room('support_east','utility',[(12.5,8),(15.36,8),(15.2,10),(12.5,10)])
    room('breakout_kitchen','kitchen',[(10,0),(16,0),(15.36,8),(10,8)])
    box('reception','hallway',0,0,10,3)
    plan = {'rooms':rooms,'doors':{},'opens':{},'interiors':{},'windows':{},'entrance':{}}
    def opening(group,key,points,**kw):
        plan[group][key]={'shape':f'shapely.LineString({points!r})',**kw}
    for i in range(6):
        y=3+i*2.5+.35
        opening('doors',f'private_{i+1}',[(4,y),(4,y+1)])
    for key,x in [('conference_a',4.3),('meeting_b',7),('meeting_c',11)]:
        opening('doors',key,[(x,18),(x+1,18)])
    opening('doors','support_west',[(10,8.4),(10,9.4)])
    opening('doors','support_east',[(13.3,10),(14.3,10)])
    opening('opens','reception_workplace',[(4.5,3),(9.5,3)])
    opening('opens','breakout_workplace',[(10,4),(10,6.5)])
    opening('opens','breakout_reception',[(10,.5),(10,2.5)])
    opening('entrance','main',[(6,0),(8,0)])
    opening('windows','front_left',[(.5,0),(5.3,0)],is_panoramic=1)
    opening('windows','front_right',[(10.5,0),(15.5,0)],is_panoramic=1)
    for i in range(6):
        ya=3+i*2.5+.4;yb=ya+1.7
        opening('windows',f'office_{i+1}',[(.045*ya,ya),(.045*yb,yb)])
    for key,a,b in [('conference',1.4,5.4),('meeting_b',6.5,9.5),('meeting_c',10.5,13.7)]:
        opening('windows',key,[(a,22),(b,22)])
    for i,(ya,yb) in enumerate([(1,3),(4.3,7),(11,13),(14,16.5)]):
        opening('windows',f'east_{i}',[(16-.08*ya,ya),(16-.08*yb,yb)])
    contract={'scene_id':'commercial_office_floor_02','revision':'layout_v1',
              'source':'source.png','dimension_authority':'estimated; small supplied image',
              'required_room_count':len(mapping),'required_semantic_counts':
              {'office':10,'utility':2,'kitchen':1,'hallway':1},
              'entry_room':mapping['reception']['room_id'],
              'minimum_door_width_m':.85,'minimum_room_area_m2':3,
              'source_uncertainties':['Private-office labels and dimensions unreadable',
                  'Six private cells reconstructed visually; count remains subject to reference review',
                  'Two support-room functions unspecified; no invented bathroom labels'],
              'required_views':['overview','reception','open_workplace_north','open_workplace_south',
                 'conference_a','meeting_b','meeting_c','private_office','support_west','support_east','breakout_kitchen'],
              'visual_acceptance':False}
    for name,data in [('floor_plan.json',plan),('room_mapping.json',mapping),('scene_contract.json',contract)]:
        (REF/name).write_text(json.dumps(data,indent=2)+'\n')
    print(json.dumps({'rooms':len(mapping),'reference':str(REF)}))


if __name__=='__main__':
    main()
