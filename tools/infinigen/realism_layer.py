"""Opt-in, non-destructive Blender realism layer with shading-free material GT.

Run with Blender --background --python realism_layer.py -- --blend IN --out OUT
--steps bevel,joint,variation,grime,glass,hdri, or with a Python containing bpy.
Optional step patches adds larger, dataset-visible intrinsic material variation.
Owners may set object['realism_skip']=True, object['realism_tile_size']=[x,y],
material['realism_skip']=True, or material['realism_roughness_base']=float.
Never changes the input file. No vegetation, layout, or clear-coat pass.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import sys

try:
    import bpy
    from mathutils import Matrix, Vector
    from mathutils.bvhtree import BVHTree
except ImportError:
    bpy = None

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_HDRI = ROOT / 'data/venue_refs/floor_plans_v3/environment_assets/greenwich_park_03_4k.hdr'
SUNNY_HDRI = ROOT / 'data/venue_refs/floor_plans_v3/environment_assets/greenwich_park_4k.hdr'
ORDER = ('joint', 'bevel', 'variation', 'grime', 'patches', 'glass', 'hdri')
DEFAULT_STEPS = tuple(s for s in ORDER if s != 'patches')
PREFIX = 'RL/'


@dataclass
class Settings:
    bevel_m: float = .0015
    joint_depth_m: float = .008
    joint_width_m: float = .006
    tile_x_m: float = .5
    tile_y_m: float = .5
    max_tiles: int = 12000
    glass_thickness_m: float = .008
    glass_roughness: float = .035
    macro_roughness: float = .08
    object_roughness: float = .025
    micro_roughness: float = .03
    albedo_variation: float = .025
    grime_strength: float = .20
    mask_resolution: int = 128
    ao_distance_m: float = .35
    hdri: str = ''  # Auto: sunny capture with a retained sun, cloudy otherwise.
    sun: str = 'keep'
    patch_albedo: float = .08
    patch_roughness: float = .15
    patches_outdoors: bool = False
    hdri_strength: float = .35
    exterior_ev: float = 1.5
    hdri_rotation_deg: float = 0.
    triangle_limit: int = 5_000_000


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def bounds(obj):
    pts = [obj.matrix_world @ Vector(v) for v in obj.bound_box]
    return tuple(min(v[k] for v in pts) for k in range(3)), tuple(max(v[k] for v in pts) for k in range(3))


def node(nt, kind, label):
    n = nt.nodes.new(kind)
    n.name = PREFIX + label
    n.label = label
    return n


def mathnode(nt, op, a, b=0., label='math'):
    n = node(nt, 'ShaderNodeMath', label)
    n.operation = op
    for i, x in enumerate((a, b)):
        if isinstance(x, (int, float)):
            n.inputs[i].default_value = x
        else:
            nt.links.new(x, n.inputs[i])
    return n.outputs[0]


def ramp(nt, value, low, high, label):
    n = node(nt, 'ShaderNodeMapRange', label)
    nt.links.new(value, n.inputs['Value'])
    n.inputs['To Min'].default_value = low
    n.inputs['To Max'].default_value = high
    n.clamp = True
    return n.outputs[0]


def noise(nt, pos, scale, label):
    n = node(nt, 'ShaderNodeTexNoise', label)
    n.inputs['Scale'].default_value = scale
    n.inputs['Detail'].default_value = 3.
    nt.links.new(pos, n.inputs['Vector'])
    return n.outputs['Fac']


def source(nt, socket, label):
    if socket.is_linked:
        return socket.links[0].from_socket
    if socket.type == 'RGBA':
        n = node(nt, 'ShaderNodeRGB', label)
        n.outputs[0].default_value = socket.default_value
    else:
        n = node(nt, 'ShaderNodeValue', label)
        n.outputs[0].default_value = socket.default_value
    return n.outputs[0]


def principled(mat):
    return [n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'] if mat.use_nodes else []


def glass_material(mat):
    return ('glass' in mat.name.lower() and 'fiberglass' not in mat.name.lower()) or any(
        not b.inputs['Transmission Weight'].is_linked and b.inputs['Transmission Weight'].default_value > .5
        for b in principled(mat))


def eligible(mat):
    if not mat or mat.get('realism_skip') or glass_material(mat):
        return False
    if any(k in mat.name.lower() for k in ('leaf', 'foliage', 'grass', 'bark', 'fabric', 'cloth', 'skin', 'water', 'screen', 'emiss', 'sky', 'photo', 'mirror')):
        return False
    bs = principled(mat)
    return bool(bs) and all(not b.inputs['Alpha'].is_linked and b.inputs['Alpha'].default_value >= .999
                            and not b.inputs['Emission Strength'].is_linked
                            and b.inputs['Emission Strength'].default_value <= .001 for b in bs)


def cube_mesh(name, dimensions):
    sx, sy, sz = dimensions
    vs = [(x*sx/2, y*sy/2, z*sz/2) for x,y,z in
          [(-1,-1,-1),(-1,-1,1),(-1,1,-1),(-1,1,1),(1,-1,-1),(1,-1,1),(1,1,-1),(1,1,1)]]
    me = bpy.data.meshes.new(name)
    me.from_pydata(vs, [], [(0,2,6,4),(1,5,7,3),(0,4,5,1),(2,3,7,6),(0,1,3,2),(4,6,7,5)])
    me.update()
    return me


def cuboid(scene, name, lo, hi, mat=None, mesh_cache=None):
    dims = tuple(round(hi[k]-lo[k], 7) for k in range(3))
    key = (dims, mat.name if mat else '')
    me = mesh_cache.get(key) if mesh_cache is not None else None
    if me is None:
        me = cube_mesh(name, dims)
        if mat:
            me.materials.append(mat)
        if mesh_cache is not None:
            mesh_cache[key] = me
    o = bpy.data.objects.new(name, me)
    scene.collection.objects.link(o)
    o.location = tuple((lo[k]+hi[k])/2 for k in range(3))
    return o


def axis_box(obj):
    if obj.type != 'MESH' or len(obj.data.vertices) != 8 or len(obj.data.polygons) != 6:
        return False
    m = obj.matrix_world.to_3x3()
    return all(sum(abs(m[i][j]) > 1e-5 for i in range(3)) == 1 for j in range(3))


def joint(scene, cfg, report):
    made = []
    cache = {}
    for obj in list(scene.objects):
        if obj.get('realism_skip') or obj.hide_render or not axis_box(obj):
            continue
        if not any(k in obj.name.lower() for k in ('paving', 'paver', 'floor_tile', 'floor tile')):
            continue
        lo, hi = bounds(obj)
        if hi[2]-lo[2] > .20 or min(hi[0]-lo[0], hi[1]-lo[1]) < .15:
            continue
        if len(obj.data.materials) != 1 or not eligible(obj.data.materials[0]):
            continue
        mat = obj.data.materials[0]
        brick = next((n for n in mat.node_tree.nodes if n.type == 'TEX_BRICK'), None)
        size = obj.get('realism_tile_size')
        tx, ty = tuple(size) if size else (cfg.tile_x_m, cfg.tile_y_m)
        gap, offset, frequency = cfg.joint_width_m, 0., 2
        if brick and not size:
            scale = brick.inputs['Scale'].default_value
            tx = brick.inputs['Brick Width'].default_value / max(scale, 1e-8)
            ty = brick.inputs['Row Height'].default_value / max(scale, 1e-8)
            gap = max(gap, 2*brick.inputs['Mortar Size'].default_value/max(scale, 1e-8))
            offset, frequency = brick.offset, max(1, brick.offset_frequency)
            if any(abs(obj.matrix_world[i][j] - (1 if i == j else 0)) > 1e-5 for i in range(4) for j in range(4)):
                report['skipped'].append([obj.name, 'Shader brick transform is not identity; set realism_tile_size explicitly.'])
                continue
        if min(tx, ty) <= gap*2:
            report['skipped'].append([obj.name, 'Tile dimensions too small for joint width.'])
            continue
        nx, ny = math.ceil((hi[0]-lo[0])/tx)+2, math.ceil((hi[1]-lo[1])/ty)+2
        if nx*ny > cfg.max_tiles:
            report['skipped'].append([obj.name, 'Physical grid exceeds max_tiles.'])
            continue
        # Preserve old Object-coordinate material mapping on the new instances.
        tilemat = mat.copy()
        tilemat.name = PREFIX + mat.name + '/physical tiles'
        anchor = bpy.data.objects.new(PREFIX+'texture space/'+obj.name, None)
        scene.collection.objects.link(anchor)
        anchor.matrix_world = obj.matrix_world.copy()
        for n in tilemat.node_tree.nodes:
            if n.type == 'TEX_COORD' and n.object is None:
                n.object = anchor
        # A coplanar background floor must be recessed too, otherwise it fills every joint.
        for base in list(scene.objects):
            if base is obj or base.hide_render or not axis_box(base):
                continue
            blo, bhi = bounds(base)
            if (all(blo[k] <= lo[k]+1e-5 and bhi[k] >= hi[k]-1e-5 for k in (0,1))
                    and abs(bhi[2]-hi[2]) < .002 and blo[2] < hi[2]-.005):
                cut = cuboid(scene, PREFIX+'temporary bedding recess',
                             (lo[0], lo[1], hi[2]-cfg.joint_depth_m), (hi[0], hi[1], hi[2]+.01))
                mod = base.modifiers.new(PREFIX+'bedding recess', 'BOOLEAN')
                mod.operation, mod.solver, mod.object = 'DIFFERENCE', 'EXACT', cut
                bpy.context.view_layer.objects.active = base
                bpy.ops.object.modifier_apply(modifier=mod.name)
                bpy.data.objects.remove(cut, do_unlink=True)
                report['recessed_bases'].append(base.name)
        # Flat source becomes a recessed bedding layer; top height of tile lands is unchanged.
        bed = bpy.data.materials.new(PREFIX+'rough mortar')
        bed.use_nodes = True
        b = principled(bed)[0]
        b.inputs['Base Color'].default_value = (.22,.23,.21,1)
        b.inputs['Roughness'].default_value = .82
        bed['realism_joint'] = True
        cuboid(scene, PREFIX+'bedding/'+obj.name,
                (lo[0],lo[1],hi[2]-cfg.joint_depth_m-.01), (hi[0],hi[1],hi[2]-cfg.joint_depth_m), bed)
        count = 0
        for j in range(math.floor(lo[1]/ty), math.ceil(hi[1]/ty)):
            shift = offset*tx if j % frequency == 0 else 0.
            for i in range(math.floor((lo[0]-shift)/tx), math.ceil((hi[0]-shift)/tx)):
                x0,x1 = max(lo[0],i*tx+shift+gap/2), min(hi[0],(i+1)*tx+shift-gap/2)
                y0,y1 = max(lo[1],j*ty+gap/2), min(hi[1],(j+1)*ty-gap/2)
                if x1-x0 < gap or y1-y0 < gap:
                    continue
                o = cuboid(scene, PREFIX+f'tile/{obj.name}/{i}/{j}',
                            (x0,y0,hi[2]-max(.025,cfg.joint_depth_m+.01)), (x1,y1,hi[2]), tilemat, cache)
                o['realism_tile'] = True
                o['realism_ground_z'] = hi[2]
                count += 1
        obj.hide_render = True
        obj.hide_set(True)
        obj['realism_replaced_by_tiles'] = count
        made.append(dict(source=obj.name, tiles=count, tile_size=[tx,ty], gap_m=gap, depth_m=cfg.joint_depth_m,
                         top_z=hi[2], bounds=[lo,hi]))
    report['physical_grids'] = made


def bevel(scene, cfg, report):
    count = 0
    for o in scene.objects:
        if o.type != 'MESH' or o.hide_render or o.get('realism_skip') or len(o.data.polygons) > 20000:
            continue
        if not o.data.materials or not all(eligible(m) for m in o.data.materials):
            continue
        if any(m.type == 'BEVEL' for m in o.modifiers):
            continue
        dims = o.dimensions
        if min(dims) < .001:
            continue
        m = o.modifiers.new(PREFIX+'physical edge bevel', 'BEVEL')
        m.width = min(cfg.bevel_m, min(dims)*.18)/max(abs(v) for v in o.scale)
        m.segments, m.limit_method = 2, 'ANGLE'
        m.angle_limit, m.use_clamp_overlap = math.radians(25), True
        count += 1
    report['bevel_objects'] = count


def variation(scene, cfg, report):
    count = 0
    for mat in bpy.data.materials:
        if not eligible(mat) or mat.get('rl_variation'):
            continue
        nt = mat.node_tree
        pos = node(nt, 'ShaderNodeNewGeometry', 'world position').outputs['Position']
        rnd = node(nt, 'ShaderNodeObjectInfo', 'per-object jitter').outputs['Random']
        macro = noise(nt, pos, 1.1, 'metre-scale roughness')
        micro = noise(nt, pos, 170., 'micro roughness')
        wear = ramp(nt, noise(nt, pos, .65, 'worn patches'), .0, 1., 'wear coverage')
        wear = mathnode(nt, 'MINIMUM', mathnode(nt, 'MAXIMUM',
                           mathnode(nt, 'MULTIPLY', mathnode(nt, 'SUBTRACT', wear, .50), 5.), 0.), 1., 'wear threshold')
        delta = mathnode(nt, 'ADD', ramp(nt, macro, -cfg.macro_roughness, cfg.macro_roughness, 'macro +/-0.08'),
                         ramp(nt, rnd, -cfg.object_roughness, cfg.object_roughness, 'object roughness jitter'))
        delta = mathnode(nt, 'ADD', delta, ramp(nt, micro, -cfg.micro_roughness, cfg.micro_roughness, 'micro +/-0.03'))
        delta = mathnode(nt, 'SUBTRACT', delta, mathnode(nt, 'MULTIPLY', wear, .12, 'worn areas smoother'))
        tint = mathnode(nt, 'ADD', ramp(nt, macro, -.012, .012, 'macro albedo value'), ramp(nt, rnd, -.010, .010, 'object albedo value'))
        tint = mathnode(nt, 'ADD', tint, ramp(nt, micro, -.003, .003, 'micro albedo value'))
        tint = mathnode(nt, 'MULTIPLY', tint, cfg.albedo_variation/.025, 'value variation amplitude')
        tint = mathnode(nt, 'ADD', tint, 1., 'shading-free reflectance multiplier')
        for b in principled(mat):
            old = source(nt, b.inputs['Roughness'], 'authored roughness')
            if 'realism_roughness_base' in mat:
                old = float(mat['realism_roughness_base'])
            expr = mathnode(nt, 'ADD', old, delta, 'spatial roughness')
            clamp = node(nt, 'ShaderNodeClamp', 'physical roughness range')
            clamp.inputs['Min'].default_value, clamp.inputs['Max'].default_value = .04,.96
            nt.links.new(expr, clamp.inputs['Value'])
            nt.links.new(clamp.outputs[0], b.inputs['Roughness'])
            if mat.get('realism_joint'):
                nt.links.new(mathnode(nt, 'MAXIMUM', clamp.outputs[0], .82, 'rougher mortar'), b.inputs['Roughness'])
            old = source(nt, b.inputs['Base Color'], 'authored reflectance')
            mix = node(nt, 'ShaderNodeMixRGB', 'intrinsic value variation, no illumination')
            mix.blend_type = 'MULTIPLY'
            mix.inputs[0].default_value = 1.
            nt.links.new(old, mix.inputs[1]); nt.links.new(tint, mix.inputs[2]); nt.links.new(mix.outputs[0], b.inputs['Base Color'])
        mat['rl_variation'] = True
        count += 1
    report['variation_materials'] = count


def geometry_contact_map(scene, cfg, report):
    """Geometry-only ambient visibility field; never RGB lighting/AO shading baked into albedo."""
    tiles = [o for o in scene.objects if o.get('realism_tile') and not o.hide_render]
    candidates = tiles or [o for o in scene.objects if o.type == 'MESH' and not o.hide_render and
                           any(k in o.name.lower() for k in ('floor','paving','paver'))]
    if not candidates:
        return None
    boxes = [bounds(o) for o in candidates]
    lo = [min(a[k] for a,b in boxes) for k in range(3)]
    hi = [max(b[k] for a,b in boxes) for k in range(3)]
    z = sorted(bounds(o)[1][2] for o in candidates)[len(candidates)//2]
    verts, faces = [], []
    deps = bpy.context.evaluated_depsgraph_get()
    for o in scene.objects:
        if o.type != 'MESH' or o.hide_render or o.get('realism_skip'):
            continue
        if any(k in o.name.lower() for k in ('leaf','tree','hedge','grass','foliage')):
            continue
        a,b = bounds(o)
        if b[2] < z+.025 or a[2] > z+cfg.ao_distance_m or any(b[k] < lo[k]-cfg.ao_distance_m or a[k] > hi[k]+cfg.ao_distance_m for k in (0,1)):
            continue
        eo = o.evaluated_get(deps); me = eo.to_mesh(); me.calc_loop_triangles()
        start = len(verts)
        verts.extend(o.matrix_world @ v.co for v in me.vertices)
        faces.extend(tuple(start+i for i in t.vertices) for t in me.loop_triangles)
        eo.to_mesh_clear()
    if not faces:
        report['contact_map'] = {'note':'No nearby contact geometry; edge/skirting masks remain active.'}
        return None
    bvh = BVHTree.FromPolygons(verts, faces, all_triangles=True)
    res = cfg.mask_resolution
    # Fixed geometry-space rays, independent of camera, lighting, exposure and HDRI.
    directions = [Vector((math.cos(i*math.tau/12)*.94, math.sin(i*math.tau/12)*.94, .34)).normalized() for i in range(12)]
    pixels = []
    for j in range(res):
        y = lo[1]+(j+.5)*(hi[1]-lo[1])/res
        for i in range(res):
            x = lo[0]+(i+.5)*(hi[0]-lo[0])/res
            origin = Vector((x,y,z+.01))
            hits = sum(bvh.ray_cast(origin,d,cfg.ao_distance_m)[0] is not None for d in directions)
            # This is deposition propensity, not illumination or an ambient darkening multiplier.
            value = hits/len(directions)
            pixels.extend((value,value,value,1.))
    im = bpy.data.images.new(PREFIX+'geometry contact deposition',width=res,height=res,float_buffer=True)
    im.colorspace_settings.name = 'Non-Color'
    im.pixels.foreach_set(pixels); im.pack()
    report['contact_map'] = dict(bounds=[lo,hi],ground_z=z,resolution=res,rays=12,distance_m=cfg.ao_distance_m,
                                 method='Static geometry visibility -> stochastic dirt coverage; no illumination bake')
    return im, lo, hi, z


def curvature_attributes(scene):
    """Light-independent concavity on original mesh topology, shared safely by instances."""
    seen = set()
    for o in scene.objects:
        if o.type != 'MESH' or o.hide_render or o.data in seen or len(o.data.polygons)>20000:
            continue
        seen.add(o.data)
        me = o.data; me.update()
        adjacency = {}
        for p in me.polygons:
            for e in p.edge_keys:
                adjacency.setdefault(tuple(sorted(e)),[]).append(p)
        values = [0.]*len(me.vertices)
        for (a,b), ps in adjacency.items():
            if len(ps)!=2:
                continue
            p,q = ps
            # Concave folds collect material; convex rims are represented by edge-distance masks.
            diff = q.center-p.center
            concave = max(0., min(1., p.normal.dot(diff)/max(diff.length,1e-8)))
            angle = 1-max(-1., min(1.,p.normal.dot(q.normal)))
            v = concave*angle
            values[a],values[b] = max(values[a],v),max(values[b],v)
        attr = me.attributes.get('rl_concavity') or me.attributes.new('rl_concavity','FLOAT','POINT')
        attr.data.foreach_set('value',values)


def grime(scene, cfg, report):
    field = geometry_contact_map(scene,cfg,report)
    curvature_attributes(scene)
    count = 0
    for mat in bpy.data.materials:
        if not eligible(mat) or mat.get('rl_grime'):
            continue
        if not any(k in mat.name.lower() for k in ('stone','pav','tile','concrete','wall','plaster','mortar','coping','floor','paint')):
            continue
        nt = mat.node_tree
        geo = node(nt,'ShaderNodeNewGeometry','geometry for dirt deposition')
        pos = geo.outputs['Position']
        sep = node(nt,'ShaderNodeSeparateXYZ','world height'); nt.links.new(pos,sep.inputs[0])
        ground_z = field[3] if field else 0.
        height = mathnode(nt,'ABSOLUTE', mathnode(nt,'SUBTRACT',sep.outputs['Z'],ground_z))
        height_band = mathnode(nt,'SUBTRACT',1., mathnode(nt,'MINIMUM',mathnode(nt,'DIVIDE',height,.22),1.),'ground proximity band')
        norm = node(nt,'ShaderNodeSeparateXYZ','surface orientation');nt.links.new(geo.outputs['True Normal'],norm.inputs[0])
        vertical = mathnode(nt,'SUBTRACT',1.,mathnode(nt,'ABSOLUTE',norm.outputs['Z']))
        skirt = mathnode(nt,'MULTIPLY',height_band,vertical,'vertical skirting deposition')
        tc = node(nt,'ShaderNodeTexCoord','object edge coordinates')
        xyz = node(nt,'ShaderNodeSeparateXYZ','local bounds'); nt.links.new(tc.outputs['Generated'],xyz.inputs[0])
        edge = None
        for axis in ('X','Y'):
            v = xyz.outputs[axis]
            dist = mathnode(nt,'MINIMUM',v,mathnode(nt,'SUBTRACT',1.,v))
            e = mathnode(nt,'SUBTRACT',1.,mathnode(nt,'MINIMUM',mathnode(nt,'MULTIPLY',dist,35.),1.))
            edge = e if edge is None else mathnode(nt,'MAXIMUM',edge,e)
        attr = node(nt,'ShaderNodeAttribute','static concavity'); attr.attribute_name='rl_concavity'
        propensity = mathnode(nt,'MAXIMUM',mathnode(nt,'MULTIPLY',edge,.45),attr.outputs['Fac'])
        propensity = mathnode(nt,'MAXIMUM',propensity,mathnode(nt,'MULTIPLY',skirt,.38))
        if field:
            im,lo,hi,z = field
            mapping = node(nt,'ShaderNodeVectorMath','world contact map offset'); mapping.operation='SUBTRACT'
            nt.links.new(pos,mapping.inputs[0]); mapping.inputs[1].default_value=(lo[0],lo[1],z)
            scale = node(nt,'ShaderNodeVectorMath','world contact map scale'); scale.operation='MULTIPLY'
            nt.links.new(mapping.outputs[0],scale.inputs[0]); scale.inputs[1].default_value=(1/max(hi[0]-lo[0],.01),1/max(hi[1]-lo[1],.01),0)
            image = node(nt,'ShaderNodeTexImage','geometry-only deposition field'); image.image=im; image.extension='CLIP'
            nt.links.new(scale.outputs[0],image.inputs['Vector'])
            contact = mathnode(nt,'MULTIPLY',image.outputs['Color'],height_band)
            propensity=mathnode(nt,'MAXIMUM',propensity,contact)
        # Geometry influences WHERE soil is deposited; it never multiplies reflectance as AO shadow.
        speckle=noise(nt,pos,24.,'material soil islands')
        threshold=mathnode(nt,'SUBTRACT',.78,mathnode(nt,'MULTIPLY',propensity,.58))
        coverage=mathnode(nt,'GREATER_THAN',speckle,threshold,'binary material soil coverage')
        coverage=mathnode(nt,'MULTIPLY',coverage, cfg.grime_strength,'soil surface fraction')
        for b in principled(mat):
            old=source(nt,b.inputs['Base Color'],'clean intrinsic reflectance')
            mix=node(nt,'ShaderNodeMixRGB','clean / deposited soil material mixture'); mix.blend_type='MIX'
            nt.links.new(coverage,mix.inputs[0]); nt.links.new(old,mix.inputs[1]); mix.inputs[2].default_value=(.105,.092,.068,1)
            nt.links.new(mix.outputs[0],b.inputs['Base Color'])
            old=source(nt,b.inputs['Roughness'],'clean roughness before soil')
            r=mathnode(nt,'ADD',mathnode(nt,'MULTIPLY',old,mathnode(nt,'SUBTRACT',1.,coverage)),mathnode(nt,'MULTIPLY',coverage,.82),'soil roughness mixture')
            nt.links.new(r,b.inputs['Roughness'])
        # A separate material AOV exposes the semantic coverage, not a beauty/AO bake.
        out=node(nt,'ShaderNodeOutputAOV','dirt coverage GT'); out.aov_name='rl_grime_coverage'; nt.links.new(coverage,out.inputs['Value'])
        mat['rl_grime']=True
        count+=1
    report['grime_materials']=count


def patches(scene, cfg, report):
    """Optional metre-scale weathering of intrinsic materials, independent of light."""
    count = 0
    for mat in bpy.data.materials:
        if not eligible(mat) or mat.get('rl_patches'):
            continue
        if not (mat.get('realism_patches') or mat.get('realism_joint') or any(
                k in mat.name.lower() for k in ('stone','pav','tile','concrete','wall',
                'plaster','mortar','coping','floor','paint','wood','timber','brick'))):
            continue
        nt=mat.node_tree
        pos=node(nt,'ShaderNodeNewGeometry','patch world metres').outputs['Position']
        coarse=noise(nt,pos,.55,'0.5–3 m wet dry and faded zones')
        # Contrast the field so the requested amplitude reads at 512 px.
        signed=mathnode(nt,'MULTIPLY',mathnode(nt,'SUBTRACT',coarse,.5),20.,'patch contrast')
        clamp=node(nt,'ShaderNodeClamp','bounded signed patches')
        clamp.inputs['Min'].default_value=-1.;clamp.inputs['Max'].default_value=1.
        nt.links.new(signed,clamp.inputs['Value']);signed=clamp.outputs[0]
        value=mathnode(nt,'ADD',1.,mathnode(nt,'MULTIPLY',signed,cfg.patch_albedo),'intrinsic patch value')
        rough=mathnode(nt,'MULTIPLY',signed,cfg.patch_roughness,'wet smoother dry rougher')
        moss=None
        if cfg.patches_outdoors and mat.get('realism_joint'):
            moss=ramp(nt,noise(nt,pos,.8,'joint moss colonies'),0.,1.,'moss distribution')
        for b in principled(mat):
            mix=node(nt,'ShaderNodeMixRGB','patch intrinsic reflectance');mix.blend_type='MULTIPLY';mix.inputs[0].default_value=1.
            nt.links.new(source(nt,b.inputs['Base Color'],'before patches'),mix.inputs[1]);nt.links.new(value,mix.inputs[2])
            col=mix.outputs[0]
            if moss is not None:
                tint=node(nt,'ShaderNodeMixRGB','outdoor joint moss tint');tint.blend_type='MULTIPLY'
                nt.links.new(moss,tint.inputs[0]);nt.links.new(col,tint.inputs[1]);tint.inputs[2].default_value=(.94,1.015,.92,1)
                col=tint.outputs[0]
            nt.links.new(col,b.inputs['Base Color'])
            lim=node(nt,'ShaderNodeClamp','patch roughness physical limits');lim.inputs['Min'].default_value=.04;lim.inputs['Max'].default_value=.96
            nt.links.new(mathnode(nt,'ADD',source(nt,b.inputs['Roughness'],'before patch roughness'),rough),lim.inputs['Value'])
            nt.links.new(lim.outputs[0],b.inputs['Roughness'])
        aov=node(nt,'ShaderNodeOutputAOV','signed patches GT');aov.aov_name='rl_patch_field'
        nt.links.new(mathnode(nt,'MULTIPLY',mathnode(nt,'ADD',signed,1.),.5),aov.inputs['Value'])
        mat['rl_patches']=True;count+=1
    report['patches']={'materials':count,'characteristic_patch_metres':[.5,3.],
        'albedo_amplitude':cfg.patch_albedo,'roughness_amplitude':cfg.patch_roughness,
        'outdoor_joint_moss':cfg.patches_outdoors,'lighting_independent':True}


def glass(scene,cfg,report):
    mats=[m for m in bpy.data.materials if glass_material(m) and not m.get('realism_skip')]
    for m in mats:
        nt=m.node_tree
        for b in principled(m):
            for key,value in [('Base Color',(.96,.98,.99,1)),('Metallic',0.),('Transmission Weight',1.),('IOR',1.46),('Roughness',cfg.glass_roughness),('Coat Weight',0.),('Emission Strength',0.)]:
                for link in list(b.inputs[key].links):nt.links.remove(link)
                b.inputs[key].default_value=value
            # Principled's dielectric Fresnel is physical; no camera-angle tint/emission trick.
        m['rl_glass']=True
    kept,thickened,skipped=[],[],[]
    for o in scene.objects:
        if o.type!='MESH' or o.hide_render or not any(m in mats for m in o.data.materials):continue
        edges={}
        for p in o.data.polygons:
            for e in p.edge_keys:edges[tuple(sorted(e))]=edges.get(tuple(sorted(e)),0)+1
        closed=bool(edges) and all(n==2 for n in edges.values())
        if closed and min(o.dimensions)>=.001:
            kept.append({'object':o.name,'min_extent_m':min(o.dimensions)})
        elif all(m in mats for m in o.data.materials):
            if not any(m.type=='SOLIDIFY' for m in o.modifiers):
                q=o.modifiers.new(PREFIX+'real glass thickness','SOLIDIFY');q.thickness=cfg.glass_thickness_m/max(abs(v) for v in o.scale);q.offset=0.;q.use_even_offset=True
                thickened.append(o.name)
        else:skipped.append([o.name,'Mixed glass/opaque open mesh: isolate panes before adding thickness.'])
    report['glass']={'materials':[m.name for m in mats],'existing_closed_panes':kept,'solidified':thickened,'skipped':skipped,'ior':1.46,'roughness':cfg.glass_roughness}


def hdri_peak_direction(image):
    """Brightest upper-hemisphere texel, in Blender environment coordinates."""
    import numpy as np
    w,h=image.size
    px=np.empty(w*h*4,dtype=np.float32);image.pixels.foreach_get(px)
    rgb=px.reshape(h,w,4)[h//2:,:,:3]
    lum=rgb @ np.array([.2126,.7152,.0722],dtype=np.float32)
    y,x=np.unravel_index(int(np.argmax(lum)),lum.shape);y+=h//2
    az=math.pi-2*math.pi*(x+.5)/w;el=math.pi*((y+.5)/h-.5)
    return Vector((math.cos(el)*math.cos(az),math.cos(el)*math.sin(az),math.sin(el)))


def hdri(scene,cfg,report):
    suns=[o for o in scene.objects if o.type=='LIGHT' and o.data.type=='SUN']
    active=[o for o in suns if o.data.energy>0 and not o.hide_render]
    path=Path(cfg.hdri or (SUNNY_HDRI if cfg.sun=='keep' and active else DEFAULT_HDRI)).resolve()
    if not path.is_file() or path.suffix.lower() not in ('.hdr','.exr'):
        raise ValueError('A real local .hdr/.exr environment is required: '+str(path))
    if not 1. <= cfg.exterior_ev <= 2.:
        raise ValueError('exterior_ev must be within the requested 1–2 stop offset.')
    world=bpy.data.worlds.new(PREFIX+'captured environment');world.use_nodes=True;scene.world=world;nt=world.node_tree;nt.nodes.clear()
    env=node(nt,'ShaderNodeTexEnvironment','captured HDRI');env.image=bpy.data.images.load(str(path),check_existing=True);env.image.pack()
    # An unlinked Environment Vector uses Blender's world-ray direction.
    # World Texture Coordinate Normal reverses that direction (sky/ground swap).
    rotation=math.radians(cfg.hdri_rotation_deg);alignment=None
    if cfg.sun=='keep' and active:
        lamp=max(active,key=lambda o:o.data.energy)
        direction=(lamp.matrix_world.to_quaternion() @ Vector((0,0,1))).normalized()
        peak=hdri_peak_direction(env.image)
        rotation+=math.atan2(peak.y,peak.x)-math.atan2(direction.y,direction.x)
        alignment={'sun':lamp.name,'sun_direction_to_source':list(direction),
            'capture_peak_direction':list(peak),'yaw_radians':rotation,
            'elevation_difference_deg':math.degrees(math.asin(peak.z)-math.asin(direction.z)),
            'note':'Azimuth aligned; horizon stays level. Retained lamp energy/angle unchanged; check elevation mismatch and summed direct illumination.'}
    env.texture_mapping.rotation[2]=rotation
    bg=node(nt,'ShaderNodeBackground','single physical exterior exposure');bg.inputs['Strength'].default_value=cfg.hdri_strength*2**cfg.exterior_ev;nt.links.new(env.outputs[0],bg.inputs['Color'])
    out=node(nt,'ShaderNodeOutputWorld','world');nt.links.new(bg.outputs[0],out.inputs['Surface'])
    lamps=[{'name':o.name,'energy':o.data.energy,'angle':o.data.angle} for o in suns]
    if cfg.sun=='remove':
        for o in suns:o.data.energy=0.
    report['hdri']={'path':str(path),'sha256':sha256(path),'base_strength':cfg.hdri_strength,'exterior_ev':cfg.exterior_ev,'strength':bg.inputs['Strength'].default_value,'sun_mode':cfg.sun,'original_suns':lamps,'alignment':alignment,'camera_reflection_lighting_same_environment':True,'note':'EV is the physical environment multiplier relative to base strength, not a guaranteed measured room contrast. Calibrate each owner interior.'}


def triangle_counts(scene):
    deps=bpy.context.evaluated_depsgraph_get();total=0;unique=0;seen=set()
    for o in scene.objects:
        if o.type not in ('MESH','CURVE','FONT') or o.hide_render:continue
        eo=o.evaluated_get(deps);me=eo.to_mesh();me.calc_loop_triangles();n=len(me.loop_triangles);total+=n
        # Object modifier settings enter the key; linked repeated geometry is counted once.
        key=(o.data.as_pointer(),tuple((m.type,m.name) for m in o.modifiers))
        if key not in seen:unique+=n;seen.add(key)
        eo.to_mesh_clear()
    return {'evaluated_triangles':total,'unique_geometry_triangles':unique}


def apply(scene,steps,settings=None):
    cfg=settings or Settings()
    if cfg.sun not in ('keep','remove'):raise ValueError('sun must be keep or remove')
    if not .06<=cfg.patch_albedo<=.10:raise ValueError('patch_albedo must be within 0.06–0.10')
    if not 0<=cfg.patch_roughness<=.15:raise ValueError('patch_roughness must be within 0–0.15')
    # Builders may call the API immediately after assigning object transforms.
    # Flush them before bounds-based joints and the static contact field.
    bpy.context.view_layer.update()
    requested=set(steps)
    if requested-set(ORDER):raise ValueError('Unknown steps: '+','.join(sorted(requested-set(ORDER))))
    done=set(json.loads(scene.get('rl_completed_steps','[]')))
    report={'settings':asdict(cfg),'steps':[],'skipped':[],'recessed_bases':[]}
    for step in ORDER:
        if step not in requested or step in done:continue
        bpy.context.view_layer.update()
        globals()[step](scene,cfg,report);report['steps'].append(step);done.add(step)
    # The shared layer never introduces/preserves clear coat on its output.
    coats=0
    for m in bpy.data.materials:
        if not m.use_nodes:continue
        for b in principled(m):
            sock=b.inputs['Coat Weight']
            if sock.is_linked or sock.default_value:
                for link in list(sock.links):m.node_tree.links.remove(link)
                sock.default_value=0.;coats+=1
    report['clear_coat_removed']=coats
    scene['rl_completed_steps']=json.dumps([s for s in ORDER if s in done])
    bpy.context.view_layer.update();report.update(triangle_counts(scene))
    if report['unique_geometry_triangles']>cfg.triangle_limit:raise ValueError('Unique triangle budget exceeded')
    return report


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--blend',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--steps',default=','.join(DEFAULT_STEPS));p.add_argument('--hdri',default='');p.add_argument('--exterior-ev',type=float,default=1.5)
    p.add_argument('--sun',choices=['keep','remove'],default='keep')
    p.add_argument('--patch-albedo',type=float,default=.08);p.add_argument('--patch-roughness',type=float,default=.15)
    p.add_argument('--patches-outdoors',action='store_true')
    p.add_argument('--hdri-strength',type=float,default=.35);p.add_argument('--joint-width',type=float,default=.006);p.add_argument('--joint-depth',type=float,default=.008)
    p.add_argument('--tile-size',type=float,nargs=2,default=[.5,.5]);p.add_argument('--triangle-limit',type=int,default=5_000_000);p.add_argument('--overwrite',action='store_true')
    a=p.parse_args(argv)
    if bpy is None:p.error('Run with Blender or a Python environment containing bpy.')
    src,dest=a.blend.resolve(),a.out.resolve()
    if src==dest or (dest.exists() and src.samefile(dest)):p.error('Input and output must be different files.')
    if any(k in dest.name.lower() for k in ('_passed','frozen')):p.error('Refusing to write a promoted/frozen output filename.')
    if dest.exists() and not a.overwrite:p.error('Output exists; choose a new file or explicitly --overwrite.')
    before=sha256(src);bpy.ops.wm.open_mainfile(filepath=str(src));cfg=Settings(hdri=a.hdri,sun=a.sun,patch_albedo=a.patch_albedo,patch_roughness=a.patch_roughness,patches_outdoors=a.patches_outdoors,exterior_ev=a.exterior_ev,hdri_strength=a.hdri_strength,joint_width_m=a.joint_width,joint_depth_m=a.joint_depth,tile_x_m=a.tile_size[0],tile_y_m=a.tile_size[1],triangle_limit=a.triangle_limit)
    r=apply(bpy.context.scene,[s for s in a.steps.split(',') if s],cfg);dest.parent.mkdir(parents=True,exist_ok=True)
    bpy.context.preferences.filepaths.save_version=0;bpy.ops.wm.save_as_mainfile(filepath=str(dest),compress=True)
    assert sha256(src)==before,'Source changed during layer application'
    r.update(source=str(src),source_sha256=before,source_unchanged=True,output=str(dest),output_sha256=sha256(dest))
    dest.with_suffix('.realism.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r,indent=2))


if __name__=='__main__':
    args=sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else sys.argv[1:]
    main(args)
