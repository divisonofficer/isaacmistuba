"""Reference-driven local surface pass, preserving v26 architecture and routes."""
import bpy, json
from pathlib import Path

R = Path(__file__).resolve().parents[3]
B = R / 'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01'
F = R / 'out/infinigen_v2/kr_pivotHouse_48712501/full'
changes = []

def surface(name, colors, scale, fine_scale, distance, roughness):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    bs = nt.nodes['Principled BSDF']
    bs.inputs['Roughness'].default_value = roughness
    tc = nt.nodes.new('ShaderNodeTexCoord')
    noise = nt.nodes.new('ShaderNodeTexNoise')
    noise.inputs['Scale'].default_value = scale
    noise.inputs['Detail'].default_value = 4
    nt.links.new(tc.outputs['Object'], noise.inputs['Vector'])
    ramp = nt.nodes.new('ShaderNodeValToRGB')
    for e, color in zip(ramp.color_ramp.elements, colors):
        e.color = (*color, 1)
    nt.links.new(noise.outputs['Fac'], ramp.inputs[0])
    nt.links.new(ramp.outputs['Color'], bs.inputs['Base Color'])
    fine = nt.nodes.new('ShaderNodeTexNoise')
    fine.inputs['Scale'].default_value = fine_scale
    fine.inputs['Detail'].default_value = 2
    nt.links.new(tc.outputs['Object'], fine.inputs['Vector'])
    bump = nt.nodes.new('ShaderNodeBump')
    bump.inputs['Strength'].default_value = .28
    bump.inputs['Distance'].default_value = distance
    nt.links.new(fine.outputs['Fac'], bump.inputs['Height'])
    nt.links.new(bump.outputs['Normal'], bs.inputs['Normal'])
    return m

floor = bpy.data.objects['garage_0/0.floor']
floor.data.materials.clear()
floor.data.materials.append(surface('garage_v27_honed_concrete',
    ((.24,.245,.24),(.40,.395,.375)), 2.6, 160, .0025, .43))
changes.append('Garage floor: object-coordinate mottling, fine concrete pores and subdued reflection')

pier = bpy.data.objects['PivotEntryV4_stone_pier']
pier.data.materials.clear()
pier.data.materials.append(surface('entry_v27_limestone',
    ((.27,.245,.20),(.49,.455,.385)), 5.5, 80, .004, .72))
changes.append('Entry stone: local limestone contrast and fine relief; existing physical joints retained')

# Isolate each leaf slot before tinting: shared engine materials elsewhere stay intact.
meta = json.loads((B / 'leafy_stage_v9.json').read_text())
palettes = [( .36,.48,.22,1),(.42,.48,.32,1),(.23,.37,.16,1)]
leaf_slots = 0
for i, row in enumerate(meta['plants']):
    if row['root'].startswith('PivotLeafyV9_planter'):
        continue
    root = bpy.data.objects[row['root']]
    for o in root.children_recursive:
        if o.type != 'MESH' or len(o.data.polygons) < 500:
            continue
        # Native canopy objects are distinguished from skeletal edges and woody trunks.
        if not any(k in o.name.lower() for k in ('leaf','foliage','canopy')):
            continue
        for slot in o.material_slots:
            if not slot.material or not slot.material.use_nodes:
                continue
            m = slot.material.copy()
            m.name = 'courtyard_v27_leaf_palette_%02d' % leaf_slots
            slot.link = 'OBJECT'
            slot.material = m
            nt = m.node_tree
            for bs in [n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED']:
                socket = bs.inputs['Base Color']
                old = socket.links[0].from_socket if socket.is_linked else None
                mix = nt.nodes.new('ShaderNodeMixRGB')
                mix.blend_type = 'MIX'
                mix.inputs[0].default_value = .25
                if old:
                    nt.links.new(old, mix.inputs[1])
                else:
                    mix.inputs[1].default_value = socket.default_value
                mix.inputs[2].default_value = palettes[i % len(palettes)]
                nt.links.new(mix.outputs[0], socket)
            leaf_slots += 1
changes.append({'isolated_native_canopy_material_slots': leaf_slots})

# Existing low flowers were too small to read from the frozen courtyard camera.
# Enlarge blossoms only, keeping stem roots, soil and walk paths unchanged.
flowers = bpy.data.objects['PivotCourtyardV18_low_flowering_border']
from mathutils import Vector
adj = [[] for _ in flowers.data.vertices]
for e in flowers.data.edges:
    a,b = e.vertices
    adj[a].append(b); adj[b].append(a)
seen = set(); enlarged = 0
petal_mats = {i for i,m in enumerate(flowers.data.materials) if m and 'cream_petals' in m.name}
petal_vertices = {v for p in flowers.data.polygons if p.material_index in petal_mats for v in p.vertices}
for start in sorted(petal_vertices):
    if start in seen: continue
    stack=[start]; seen.add(start); group=[]
    while stack:
        v=stack.pop(); group.append(v)
        for w in adj[v]:
            if w not in seen: seen.add(w); stack.append(w)
    center=sum((flowers.data.vertices[j].co for j in group),Vector())/len(group)
    for j in group:
        flowers.data.vertices[j].co=center+(flowers.data.vertices[j].co-center)*1.7
    enlarged += 1
changes.append({'low_border_petals_enlarged': enlarged, 'factor': 1.7})
bpy.context.view_layer.update()
bpy.context.scene['pivot_revision']='quality_rework_v27_surface_candidate'
out=F/'scene_rework_integrated_v27.blend'
bpy.ops.wm.save_as_mainfile(filepath=str(out))
(B/'surface_refinement_v27.json').write_text(json.dumps({
    'status':'saved_visual_review_pending', 'source_scene':str(F/'scene_rework_integrated_v26.blend'),
    'candidate_scene':str(out), 'changes':changes,
    'remaining':['Original-camera renders and direct comparison','Distinct plant forms and tool details still require assessment','Full-scene final consistency and registration']
},ensure_ascii=False,indent=2)+'\n')
print('PIVOT_SURFACE_V27_SAVED',json.dumps(changes),flush=True)
