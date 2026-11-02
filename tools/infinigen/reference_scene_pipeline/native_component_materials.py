"""Assign native door-body material without destroying tagged hardware or glazing."""
def assign_door_body_preserving_hardware(obj, body_material):
    mesh = obj.data
    attr = mesh.attributes.get('handle')
    if attr is None or attr.domain not in ('FACE', 'POINT'):
        raise ValueError(f'{obj.name}: native handle mask missing or unsupported; refusing blanket slot replacement')
    if attr.domain == 'FACE':
        handles = {p.index for p, value in zip(mesh.polygons, attr.data) if value.value > .5}
    else:
        values = [value.value for value in attr.data]
        mixed = [p.index for p in mesh.polygons if any(values[i] > .5 for i in p.vertices)
                 and not all(values[i] > .5 for i in p.vertices)]
        if mixed:
            raise ValueError(f'{obj.name}: {len(mixed)} ambiguous native handle faces')
        handles = {p.index for p in mesh.polygons if all(values[i] > .5 for i in p.vertices)}
    if not handles:
        raise ValueError(f'{obj.name}: empty native hardware selection')
    protected = {p.index: p.material_index for p in mesh.polygons if p.index in handles
                 or (mesh.materials[p.material_index] and 'glass' in mesh.materials[p.material_index].name.lower())}
    slot = len(mesh.materials)
    mesh.materials.append(body_material)
    changed = 0
    for p in mesh.polygons:
        if p.index not in protected:
            p.material_index = slot
            changed += 1
    assert all(mesh.polygons[i].material_index == previous for i, previous in protected.items())
    return {'object': obj.name, 'mask_domain': attr.domain, 'preserved_handle_faces': len(handles),
            'preserved_hardware_and_glass_faces': len(protected), 'body_faces_assigned': changed}
