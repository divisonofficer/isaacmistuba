"""Reference correction planning only. Never edits canonical plans or Blender scenes.

Footprints below are clearance envelopes, not substitute renderable products.
Native basin/door geometry, wall construction and saved-source checks remain required.
"""
import copy
import hashlib
import json
from pathlib import Path

from shapely.geometry import LineString, Polygon, box
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[3]
D = ROOT / 'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03'


def main():
    original = {name: (D / name).read_bytes() for name in
                ('floor_plan.json', 'room_mapping.json')}
    plan = json.loads(original['floor_plan.json'])
    mapping = json.loads(original['room_mapping.json'])
    proposed_plan, proposed_mapping = copy.deepcopy(plan), copy.deepcopy(mapping)
    results = []
    # 230 mm total reserved wall thickness follows current shell planning.
    # Pocket door avoids trapping the narrow room behind a transverse open leaf.
    toilet = box(8.45 - .379654 / 2, 9.365 - .680532,
                 8.45 + .379654 / 2, 9.365)
    # Native imported Plieger product measured in the saved studio; no resize.
    basin = box(8.87 - .44987910985946655, 7.635,
                8.87, 7.635 + .23987740278244019)
    wc_inner = box(8.015, 7.615, 8.885, 9.385)
    lower_hall = box(7.115, 6.115, 8.885, 7.385)
    side_hall = box(7.115, 7.385, 7.785, 9.385)
    wc_threshold = box(7.785, 7.85, 8.015, 8.65)
    unit_threshold = box(8.885, 6.25, 9.115, 7.35)
    landing = box(9.115, 5.115, 12.385, 10.885)
    free = unary_union([wc_inner, lower_hall, side_hall, wc_threshold,
                        unit_threshold, landing])
    route = LineString([(9.4, 6.8), (7.45, 6.8), (7.45, 8.25),
                        (8.45, 8.25), (8.45, 8.365)])
    route_envelope = route.buffer(.3, resolution=32)
    # Complete open unit entrance leaf: hinge at south jamb, opens west.
    main_leaf_open = box(7.785, 6.2325, 8.885, 6.2675)
    side = min(8.45 - 8.015, 8.885 - 8.45)
    route_outside = route_envelope.difference(free).area
    collisions = {name: route_envelope.intersection(geom).area for name, geom in
                  [('toilet', toilet), ('basin', basin), ('open_entrance_leaf', main_leaf_open)]}
    assert side >= .4 and route_outside < 1e-9
    assert all(area < 1e-9 for area in collisions.values())
    for unit in (101, 102):
        def mirrored(points):
            return [[21.5-x if unit == 102 else x, y] for x, y in points]
        def line(points):
            return {'shape': 'shapely.LineString(' + repr(mirrored(points)) + ')'}
        room_id = 'bathroom_0/' + str(8 if unit == 101 else 9)
        hall_id = mapping[f'{unit}_living_entry']['room_id']
        wc_points = mirrored([(7.9, 7.5), (9, 7.5), (9, 9.5), (7.9, 9.5)])
        hall_points = mirrored([(7, 6), (9, 6), (9, 7.5), (7.9, 7.5),
                                (7.9, 9.5), (7, 9.5)])
        proposed_mapping[f'{unit}_core_wc'] = {'room_id': room_id, 'polygon_m': wc_points}
        proposed_mapping[f'{unit}_living_entry']['polygon_m'] = hall_points
        for rid, points in [(room_id, wc_points), (hall_id, hall_points)]:
            proposed_plan['rooms'][rid] = {'shape': 'shapely.Polygon(' + repr(points) + ')'}
        proposed_plan['doors'][f'{unit}_unit_landing'] = line([(9, 6.25), (9, 7.35)])
        proposed_plan['doors'][f'{unit}_core_wc'] = dict(
            line([(7.9, 7.85), (7.9, 8.65)]),
            proposed_mechanism='native_pocket_sliding_product_required',
            pocket_interval_y_m=[8.65, 9.45])
        # Existing broad living opening remains alongside the narrow hall;
        # it is not a boundary of the newly proposed WC.
        assert Polygon(wc_points).intersection(Polygon(hall_points)).area < 1e-9
        assert abs(Polygon(wc_points).area + Polygon(hall_points).area - 7) < 1e-8
        results.append({'unit': unit, 'toilet_bbox_xy_m': mirrored(list(toilet.exterior.coords)),
                        'basin_reserved_envelope_xy_m': mirrored(list(basin.exterior.coords)),
                        'route_centres_m': mirrored(list(route.coords)),
                        'route_width_m': .6, 'route_outside_free_area_m2': route_outside,
                        'route_collision_areas_m2': collisions,
                        'min_bowl_centre_side_clearance_m': side,
                        'narrow_hall_clear_width_m': .67,
                        'wc_clear_door_width_m': .8,
                        'door_sweep_note': 'WC sliding door has no swing; entrance checked fully open only, not whole moving sweep.'})
    out = D / 'core_wc104_planning'
    out.mkdir(exist_ok=True)
    for name, value in [('floor_plan_proposed.json', proposed_plan),
                        ('room_mapping_proposed.json', proposed_mapping)]:
        (out / name).write_text(json.dumps(value, indent=2) + '\n')
    report = {'status': 'TWO_DIMENSIONAL_PLANNING_PASS_NOT_SCENE_ACCEPTANCE',
              'source_revision': 103, 'blender_candidate_created': False,
              'existing_bathroom_count': 8, 'proposed_bathroom_count': 10,
              'original_plan_sha256': hashlib.sha256(original['floor_plan.json']).hexdigest(),
              'results': results,
              'basin_native_product_trial': {
                  'id': 'HSSD_05dfa289f4a5be6a1be7f0882a4d929060242b5d',
                  'dimensions_blender_xyz_m': [.44987910985946655,
                                                .23987740278244019,
                                                .2123512625694275],
                  'saved_native_geometry_uv_audit': 'saved_source_audit.json',
                  'visual_status': 'provisional; drain and wall fixing not yet verified'},
              'remaining': ['Resolve actual native pocket door and compact basin products; do not replace them with envelopes.',
                            'Check floor-to-ceiling wall/casing geometry and pocket housing, plumbing and electrical placement.',
                            'Check relocated entrance hinge, sweep and common corridor with native source mesh.',
                            'Update required rooms and native WC access gate from eight to ten only with implemented source.',
                            'Saved-source physical audit and overview/matched living/hall renders required.'],
              'photorealism_accepted': False, 'dataset_promoted': False}
    (out / 'planning_audit.json').write_text(json.dumps(report, indent=2) + '\n')
    for name, data in original.items():
        assert (D / name).read_bytes() == data
    print(json.dumps({'report': str(out / 'planning_audit.json'), 'units': 2,
                      'canonical_plans_unchanged': True, 'candidate_created': False}))


if __name__ == '__main__':
    main()
