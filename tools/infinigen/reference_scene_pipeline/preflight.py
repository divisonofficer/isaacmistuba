"""Validate native predefined plans without eval or expensive Blender rendering.

Checks authored geometry, room counts, opening attachment/width and entry
reachability. This does not certify furniture, render quality or actual meshes.
"""
import argparse
import ast
import hashlib
import json
from collections import Counter
from pathlib import Path

from shapely.geometry import Polygon, LineString, box


def geometry(expression):
    node=ast.parse(expression,mode='eval').body
    if not isinstance(node,ast.Call) or not isinstance(node.func,ast.Attribute):
        raise ValueError('Expected explicit shapely geometry constructor')
    if not isinstance(node.func.value,ast.Name) or node.func.value.id!='shapely' or node.keywords:
        raise ValueError('Unsupported shape expression')
    constructor={'Polygon':Polygon,'LineString':LineString,'box':box}[node.func.attr]
    return constructor(*(ast.literal_eval(a) for a in node.args))


def audit(ref):
    raw=(ref/'floor_plan.json').read_bytes()
    plan=json.loads(raw);contract=json.loads((ref/'scene_contract.json').read_text())
    rooms={k:geometry(v['shape']) for k,v in plan['rooms'].items()}
    failures=[];links=[];graph={k:set() for k in rooms};entries=[]
    for k,r in rooms.items():
        if not r.is_valid or r.area<contract['minimum_room_area_m2']:
            failures.append(f'Invalid or undersized room: {k}')
    keys=list(rooms)
    for i,a in enumerate(keys):
        for b in keys[i+1:]:
            if rooms[a].intersection(rooms[b]).area>1e-5:
                failures.append(f'Overlapping rooms: {a}, {b}')
    counts=dict(Counter(k.split('_0/')[0] for k in rooms))
    if counts!=contract['required_semantic_counts'] or len(rooms)!=contract['required_room_count']:
        failures.append('Required room program does not match')
    for group in ('doors','opens','entrance','windows'):
        for name,obj in plan[group].items():
            line=geometry(obj['shape'])
            attached=[k for k,r in rooms.items() if r.boundary.buffer(1e-5).covers(line)]
            expected=1 if group in ('entrance','windows') else 2
            if len(attached)!=expected:failures.append(f'{group}/{name}: attached {attached}; expected {expected}')
            if group!='windows' and line.length<contract['minimum_door_width_m']:
                failures.append(f'{group}/{name}: opening too narrow')
            if group in ('doors','opens') and len(attached)==2:
                a,b=attached;graph[a].add(b);graph[b].add(a)
            if group=='entrance':entries+=attached
            links.append({'group':group,'id':name,'rooms':attached,'width_m':line.length})
    seen=set(entries);todo=list(entries)
    while todo:
        for nxt in graph[todo.pop()]-seen:seen.add(nxt);todo.append(nxt)
    if seen!=set(rooms):failures.append(f'Unreachable rooms: {sorted(set(rooms)-seen)}')
    return {'status':'pass' if not failures else 'fail','scene_id':contract['scene_id'],
            'floor_plan_sha256':hashlib.sha256(raw).hexdigest(),'room_count':len(rooms),
            'semantic_counts':counts,'reachable_rooms':sorted(seen),'openings':links,
            'failures':failures,'limitations':['Authored plan only; actual mesh checks still required',
            'Furniture clearance, support and visual/reference acceptance not checked']}


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('reference',type=Path);args=ap.parse_args()
    result=audit(args.reference)
    (args.reference/'preflight_layout.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2));raise SystemExit(0 if result['status']=='pass' else 1)
