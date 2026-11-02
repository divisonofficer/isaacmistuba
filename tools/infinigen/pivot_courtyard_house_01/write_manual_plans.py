"""This session's explicit furnishing decisions; no planning/revision API."""
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[3]
REF=ROOT/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01'
F=ROOT/'out/infinigen_v2/kr_pivotHouse_48712501/full'
sys.path.insert(0,str(ROOT/'tools/infinigen'))
from room_planner import catalog

def wall(room, side):
 walls=room['walls']
 key=(lambda w:(w['p0'][0]+w['p1'][0])/2) if side in ('west','east') else (lambda w:(w['p0'][1]+w['p1'][1])/2)
 return (min if side in ('west','south') else max)(walls,key=key)['id']

def item(id,cat,relation='against_wall',**kw):
 return dict(id=id,category=cat,relation=relation,**kw)

def make(room,key):
 W=lambda s:wall(room,s)
 A=lambda id,cat,side,**kw:item(id,cat,wall=W(side),**kw)
 f=[];small=[]
 if key in ('bed1','bed2','bed3','bed4','guest_bed'):
  side={'bed4':'west','bed3':'east','bed2':'south','bed1':'west','guest_bed':'east'}[key]
  f=[A('bed','bed',side),item('bedside','nightstand','beside',target='bed',side='both'),
     item('bed_rug','rug','under',target='bed')]
  if key in ('bed4','bed3','bed2'):f.append(A('robe','oak_wardrobe','south' if key!='bed2' else 'east'))
 elif key in ('rumpus','living'):
  f=[A('sofa','sofa','south'),item('coffee','coffee_table','in_front_of',target='sofa',gap_m=.45),
     item('rug','rug','under',target='coffee'),A('armchair','armchair','west'),
     A('media','media_wall','east' if key=='living' else 'west')]
 elif key=='dining':
  f=[A('island','kitchen_island','south'),item('table','dining_table','near_window'),
     item('chairs','dining_chair','around',target='table',count=6)]
 elif key=='kitchen':
  f=[A('kitchen','home_kitchen_run','south')]
 elif key=='pantry':
  f=[A('pantry','pantry_run','north')]
 elif key=='laundry':
  f=[A('laundry','laundry_run','north')]
 elif key=='study':
  f=[A('desk1','office_desk','south'),item('chair1','desk_chair','in_front_of',target='desk1',gap_m=.15),
     A('desk2','office_desk','west'),item('chair2','desk_chair','in_front_of',target='desk2',gap_m=.15)]
 elif key=='wir':
  f=[A('wardrobe','open_wardrobe','east')]
 elif key=='bathroom':
  f=[A('tub','bathtub','east'),A('basin','vanity','west'),A('shower','shower_glass','south')]
 elif key=='ensuite':
  f=[A('tub','bathtub','north'),A('vanity','oak_vanity_long','east'),A('shower','shower_glass','south')]
 elif key=='guest_bath':
  f=[A('shower','shower_glass','east'),A('toilet','wc','north'),A('basin','vanity','south')]
 elif key in ('wc','pdr','ensuite_wc'):
  f=[A('toilet','wc','north' if key=='wc' else 'east')]
  if key=='pdr':f.append(A('basin','wash_basin','west'))
 elif key=='garage':
  f=[A('rack','storage_rack','east')]
 elif key=='guest_living':
  f=[A('kitchenette','home_kitchen_run','north'),A('sofa','sofa','south'),
     item('coffee','coffee_table','in_front_of',target='sofa',gap_m=.4),
     item('meal_table','break_table','corner'),item('meal_chairs','break_chair','around',target='meal_table',count=2)]
 # Hallways deliberately keep their entire width for circulation. Guest robe
 # is a fitted niche handled by the scene-local architecture pass.
 for it in f:
  assert it['category'] in catalog.FURNITURE,it
  assert it['relation'] in catalog.RELATIONS,it
 return dict(occupant='family household and occasional guests',
  narrative='quiet daytime; architecture and furnishing reference reconstruction',
  tidiness=.9,fixed=True,furniture=f,lived_in=small,
  notes=f'Directly authored by this Codex session from source.png + {key}_v1.png; preserve doors and circulation; report any dropped item. No API revisions.')

if __name__=='__main__':
 doc=json.loads((F/'rooms.json').read_text())
 mapping=json.loads((REF/'room_mapping.json').read_text())
 byid={v['room_id']:k for k,v in mapping.items()}
 kit=json.loads((REF/'kit.json').read_text())
 out=dict(scene=doc['scene'],model='manual-current-session',prompt_version='pivot-manual-v1',seed=48712501,
          venue=None,style=None,style_spec=kit,room_venues={},rooms={})
 for room in doc['rooms']:
  key=byid[room['id']]
  if key=='study':
   room={**room,'type':'home-study','source_semantic_type':room['type']}
  out['rooms'][room['id']]={'room':room,'plan':make(room,key)}
 (F/'plans.json').write_text(json.dumps(out,indent=2))
 summary={rid:[i['category'] for i in entry['plan']['furniture']] for rid,entry in out['rooms'].items()}
 (REF/'manual_furnishing_plan.json').write_text(json.dumps(summary,indent=2))
 print(json.dumps({'rooms':len(out['rooms']),'requested_furniture':sum(map(len,summary.values())),'plans':str(F/'plans.json')},indent=2))
