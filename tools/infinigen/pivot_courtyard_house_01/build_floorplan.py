"""Directly authored reconstruction of the supplied plan; dimensions estimated.

Writes a standalone Infinigen PredefinedFloorPlanSolver contract without changing
the shared floorplan registry. Coordinates are metres, +Y is image-up.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
REF = ROOT / 'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01'
ROOMS = {
 'bed4': ('bedroom_0/0', [0,17,3.5,21]),
 'bed3': ('bedroom_0/1', [5,17,8,21]),
 'bed2': ('bedroom_0/2', [0,11.5,3.5,15.5]),
 'bed1': ('bedroom_0/3', [20.5,19,24,23]),
 'guest_bed': ('bedroom_0/4', [20,0,23.5,4]),
 'bathroom': ('bathroom_0/0', [3.5,11.5,6,14]),
 'wc': ('bathroom_0/1', [4.8,14,6,15.5]),
 'ensuite': ('bathroom_0/2', [24,19,26.5,23]),
 'pdr': ('bathroom_0/3', [21.7,13,24,14.5]),
 'guest_bath': ('bathroom_0/4', [18,1.5,20,4]),
 'wir': ('closet_0/0', [20.5,17,25,19]),
 'upper_hall': ('hallway_0/2', [3.5,17,5,21]),
 'bath_hall': ('hallway_0/3', [3.5,14,4.8,15.5]),
 'study_hall': ('hallway_0/4', [20.5,13,21.7,14.5]),
 'ensuite_wc': ('bathroom_0/5', [25,17,26.5,19]),
 'rumpus': ('living-room_0/0', [6,11.5,10.5,17]),
 'dining': ('dining-room_0/0', [10.5,11.5,15.5,17]),
 'living': ('living-room_0/1', [15.5,11.5,20.5,17]),
 'kitchen': ('kitchen_0/0', [10.5,9,16.5,11.5]),
 'laundry': ('utility_0/0', [8,9,10.5,11.5]),
 'pantry': ('utility_0/1', [16.5,9,20.5,11.5]),
 'study': ('office_0/0', [20.5,9,24,13]),
 'entry': ('hallway_0/0', [20.5,14.5,24,17]),
 'bedroom_hall': ('hallway_0/1', [2.5,15.5,6,17]),
 'garage': ('garage_0/0', [16.5,4,22,9]),
 'guest_living': ('living-room_0/2', [13,0,18,4]),
 'guest_robe': ('closet_0/2', [18,1,20,1.5]),
 'guest_hall': ('hallway_0/5', [18,0,20,1]),
}

def shape(bounds):
 return 'shapely.box(' + ','.join(map(str,bounds)) + ')'

def line(points):
 return {'shape': 'shapely.LineString(' + repr(points) + ')'}

def build():
 plan = {'rooms': {name: {'shape':shape(box)} for name,box in ROOMS.values()},
         'doors':{}, 'opens':{}, 'interiors':{}, 'windows':{}, 'entrance':{}}
 # Every connection is authored from the source; the large LDK is open, not
 # separated by doors. Exact original opening widths remain unverified.
 links = [
  ('bed4_hall',[(2.6,17),(3.4,17)]),
  ('bed3_hall',[(5.1,17),(5.9,17)]),
  ('bed2_hall',[(2.6,15.5),(3.4,15.5)]),
  ('bath_hall',[(3.7,14),(4.6,14)]),
  ('wc_hall',[(4.8,14.3),(4.8,15.2)]),
  ('hall_rumpus',[(6,15.7),(6,16.6)]),
  ('laundry_kitchen',[(10.5,9.5),(10.5,10.4)]),
  ('pantry_garage',[(17,9),(17.9,9)]),
  ('study_entry',[(20.7,13),(21.6,13)]),
  ('powder_entry',[(21.7,13.3),(21.7,14.2)]),
  ('entry_wir',[(21,17),(21.9,17)]),
  ('wir_bed1',[(21,19),(21.9,19)]),
  ('bed1_ensuite',[(24,19.4),(24,20.3)]),
  ('ensuite_wc',[(25.3,19),(26.2,19)]),
  ('garage_guest',[(16.7,4),(17.6,4)]),
  ('guest_bath',[(18,2.4),(18,3.3)]),
  ('guest_bed',[(20,0.05),(20,0.95)]),
 ]
 plan['doors'] = {name:line(pts) for name,pts in links}
 plan['opens'] = {name:line(pts) for name,pts in [
  ('rumpus_dining',[(10.5,13),(10.5,15.5)]),
  ('dining_living',[(15.5,11.6),(15.5,16.9)]),
  ('dining_kitchen',[(10.6,11.5),(15.4,11.5)]),
  ('kitchen_pantry',[(16.5,9.4),(16.5,10.9)]),
  ('living_entry',[(20.5,15),(20.5,16.5)]),
  ('upper_hall',[(3.6,17),(4.9,17)]),
  ('bath_hall',[(3.6,15.5),(4.7,15.5)]),
  ('study_hall',[(20.6,14.5),(21.6,14.5)]),
  ('guest_hall',[(18,0.05),(18,0.95)]),
  ('guest_robe',[(20,1.02),(20,1.48)]),
 ]}
 plan['entrance'] = {name:line(pts) for name,pts in [
  ('main_entry',[(24,15),(24,16.2)]),
  ('laundry_courtyard',[(8,9.3),(8,10.3)]),
  ('guest_courtyard',[(13,1.5),(13,2.5)]),
 ]}
 windows = [
  ('bed4',[(0.5,21),(2.9,21)]),('bed3',[(5.3,21),(7.7,21)]),
  ('bed2',[(0,12.2),(0,14.8)]),('bed1',[(21,23),(23.4,23)]),
  ('ensuite',[(24.4,23),(26,23)]),('study',[(24,9.8),(24,12.1)]),
  ('guest_bed',[(20.5,0),(23,0)]),('guest_living',[(13,0.5),(13,1.3)]),
  ('deck_dining',[(11,17),(15,17)]),('deck_living',[(16,17),(20,17)]),
 ]
 plan['windows'] = {name:{**line(pts),'is_panoramic':name.startswith('deck_')} for name,pts in windows}
 return plan

if __name__ == '__main__':
 REF.mkdir(parents=True,exist_ok=True)
 (REF/'floor_plan.json').write_text(json.dumps(build(),indent=2))
 (REF/'room_mapping.json').write_text(json.dumps({k:{'room_id':v[0],'bounds_m':v[1]} for k,v in ROOMS.items()},indent=2))
 (REF/'planning_assumptions.json').write_text(json.dumps({
  'source':'source.png','units':'metres','dimensions':'estimated from screenshot; no surveyed measurements supplied',
  'ceiling_height_m':2.8,'topology_authority':'source.png',
  'exterior_spaces':{'deck':[8,17,20.5,21],'entry_deck':[24,14.5,26.5,17],
                     'private_courtyard':[8,4,16.5,9]},
  'uncertainties':['carport cropped in source','exact garage door position','small ensuite WC and guest robe topology'],
  'pending_corrections':['deck sliding door openings need architectural pass',
                         'linen cupboard is a furniture niche in upper hallway, not a separate room'],
 },indent=2))
 print(REF/'floor_plan.json')
