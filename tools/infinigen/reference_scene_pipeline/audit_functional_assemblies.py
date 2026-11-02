"""Saved-source assembly gates for confirmed failure modes; not whole-scene collision/navigation QA."""
import argparse, hashlib, json
from pathlib import Path
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

p = argparse.ArgumentParser()
p.add_argument('--blend', type=Path, required=True)
p.add_argument('--out', type=Path, required=True)
a = p.parse_args()
bpy.ops.wm.open_mainfile(filepath=str(a.blend.resolve()))
bpy.context.view_layer.update()
deps = bpy.context.evaluated_depsgraph_get()
records, errors = [], []

def components(o):
    adjacency = {v.index: set() for v in o.data.vertices}
    for e in o.data.edges:
        i, j = e.vertices
        adjacency[i].add(j)
        adjacency[j].add(i)
    unseen = set(adjacency)
    result = []
    while unseen:
        queue = [unseen.pop()]
        ids = set(queue)
        while queue:
            for i in adjacency[queue.pop()]:
                if i in unseen:
                    unseen.remove(i)
                    ids.add(i)
                    queue.append(i)
        points = [o.data.vertices[i].co for i in ids]
        result.append((ids, [min(v[k] for v in points) for k in range(3)],
                       [max(v[k] for v in points) for k in range(3)]))
    return result

def tree(o, parent, material=None):
    ev = o.evaluated_get(deps)
    mesh = ev.to_mesh()
    transform = parent.matrix_world.inverted() @ o.matrix_world
    points = [transform @ v.co for v in mesh.vertices]
    faces = [tuple(f.vertices) for f in mesh.polygons
             if material is None or (mesh.materials and mesh.materials[f.material_index]
                                     and mesh.materials[f.material_index].name == material)]
    ev.to_mesh_clear()
    return BVHTree.FromPolygons(points, faces)

def record(row):
    records.append(row)
    if not row['pass']:
        errors.append(row)

for parent in list(bpy.data.objects):
    if parent.type != 'MESH':
        continue
    key = str(parent.get('program_key', ''))
    if 'OfficeDeskFactory' in parent.name and key.startswith('private_') and key.endswith('_desk'):
        bases = [c for c in components(parent)
                 if all(abs(c[2][k] - c[1][k] - d) < 1e-5
                        for k, d in enumerate((.18, .22, .012)))]
        if len(bases) != 1:
            record({'object': parent.name, 'kind': 'private_monitor_support',
                    'pass': False, 'reason': 'expected one measured native stand base', 'count': len(bases)})
            continue
        ids, low, high = bases[0]
        x, y = (low[0] + high[0]) / 2, (low[1] + high[1]) / 2
        # Exclude display stand: ray from above its bottom through real desk surfaces.
        points = [v.co.copy() for v in parent.data.vertices]
        faces = [tuple(f.vertices) for f in parent.data.polygons
                 if not any(i in ids for i in f.vertices)
                 and min(parent.data.vertices[i].co.z for i in f.vertices) < .78
                 and max(parent.data.vertices[i].co.z for i in f.vertices) <= .78]
        support = BVHTree.FromPolygons(points, faces)
        hit, normal, index, distance = support.ray_cast(Vector((x, y, low[2] + .002)), Vector((0, 0, -1)), .2)
        gap = low[2] - hit.z if hit else None
        record({'object': parent.name, 'kind': 'private_monitor_support', 'gap_m': gap,
                'pass': gap is not None and -.0001 <= gap <= .001})
    if 'HomeKitchenRunFactory' not in parent.name or not key.endswith('_kitchen_run'):
        continue
    children = [o for o in bpy.data.objects if o.parent == parent and o.type == 'MESH']
    bowls = [o for o in children if o.name.startswith('FormedSink_')]
    if not bowls:
        records.append({'object': parent.name, 'kind': 'formed_sink_fit', 'status': 'not_applicable',
                        'note': 'No formed-sink assembly; native bowl integrity is not certified by this gate.'})
        continue
    if len(bowls) != 1:
        record({'object': parent.name, 'kind': 'formed_sink_fit', 'pass': False, 'reason': 'ambiguous formed bowl'})
        continue
    bowl = bowls[0]
    counters = [o for o in children if o.name.startswith('CutCounter_')]
    counter_tree = tree(counters[0], parent) if len(counters) == 1 else tree(parent, parent, 'ir_kit_top')
    overlaps = len(tree(bowl, parent).overlap(counter_tree))
    # Exact current family envelope, measured independently of new cutout mesh.
    # Samples outside the sink aperture must retain countertop height.
    sy = (min(v.co.y for v in bowl.data.vertices) + max(v.co.y for v in bowl.data.vertices)) / 2
    probes = []
    for x, y in [(x, sy + dy) for x in (.04, .62) for dy in (-.25, 0, .25)] + [(.32, y) for y in (-.45, .6, 1.1)]:
        hit, normal, index, distance = counter_tree.ray_cast(Vector((x, y, .96)), Vector((0, 0, -1)), .2)
        probes.append({'xy': [x, y], 'hit_z': hit.z if hit else None,
                       'pass': hit is not None and abs(hit.z - .8975) < 1e-4})
    record({'object': parent.name, 'kind': 'formed_sink_fit', 'triangle_overlaps': overlaps,
            'counter_preservation_rays': probes, 'pass': overlaps == 0 and all(x['pass'] for x in probes)})

report = {'source': str(a.blend.resolve()), 'source_sha256': hashlib.sha256(a.blend.read_bytes()).hexdigest(),
          'records': records, 'errors': errors, 'photorealism_accepted': False,
          'auditor_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          'scope': 'Native private monitor base support and current-family formed sink/counter fit plus nine counter-preservation rays. Other asset families, continuous room collisions, door/navigation clearance and visual realism remain unverified.'}
a.out.write_text(json.dumps(report, indent=2))
print(json.dumps({'records': len(records), 'errors': len(errors), 'out': str(a.out)}), flush=True)
if errors:
    raise SystemExit(1)
