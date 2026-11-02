"""Opt-in apartment scanned finishes. Hook: apt_realism.apply(stats)."""
import os
import math
import bpy


def _prepare_scan_mean(source, scan):
    """Shader RGB is linear; Blender image.pixels exposes encoded byte RGB."""
    import numpy as np
    from PIL import Image
    path=scan+'/base_color.jpg'
    if path not in _LINEAR_MEANS:
        rgb=np.asarray(Image.open(path).convert('RGB').resize((512,512)),dtype=np.float64)/255
        linear=np.where(rgb<=.04045,rgb/12.92,((rgb+.055)/1.055)**2.4)
        _LINEAR_MEANS[path]=float((linear@np.array([.2126,.7152,.0722])).mean())
    source._PBR_MEAN[path]=_LINEAR_MEANS[path]


_LINEAR_MEANS={}


def apply(stats=None):
    """Refresh scanned wall/floor/textile materials; add physical small bevels."""
    stats = stats if stats is not None else {}
    if os.environ.get('APT_REALISM', '0') != '1':
        return stats
    import apt_shell as source
    counts = {'walls': 0, 'floors': 0, 'fabrics': 0, 'bevels': 0}
    for m in list(bpy.data.materials):
        rgb = m.get('apt_rgb')
        if rgb is None or m.get('apt_realism_v1'):
            continue
        if m.name.startswith('ir_apt_paint_'):
            scan = source.PBR_STRUCT + ('grey_plaster' if sum(rgb[:3])/3 < .3 else 'plastered_wall')
            _prepare_scan_mean(source,scan)
            ok = source._pbr_build(m, scan, rgb[:3], tile=1.0, contrast=.75 if sum(rgb[:3])/3 < .3 else 2.0,
                              rough=.86, normal=.8, var=.04, ao=.12, mottle=.065)
            kind = 'walls'
        elif m.name.startswith('ir_apt_plank_'):
            _prepare_scan_mean(source,source.PBR_STRUCT+'wood_planks_grey')
            ok = source._pbr_build(m, source.PBR_STRUCT+'wood_planks_grey', rgb[:3],
                              tile=1.5, contrast=.8, rough=.57, normal=1.0, var=.04, ao=.15)
            kind = 'floors'
        elif m.name.startswith(source.R2_FABRIC):
            import zlib
            scan=source.FAB_SCANS[zlib.crc32(m.name.encode())%len(source.FAB_SCANS)]
            _prepare_scan_mean(source,scan)
            ok = source._pbr_build(m, scan,
                              rgb[:3], tile=.48, contrast=.35, rough=.92, normal=.85,
                              var=.01, ao=.1, sheen=.35, wrinkle=.35)
            kind = 'fabrics'
        else:
            continue
        if not ok:
            raise FileNotFoundError('Missing PBR maps for '+m.name)
        # Curvature-driven subtle wear; no emission. Preserve the scanned base.
        nt=m.node_tree
        p=next((n for n in nt.nodes if n.type=='BSDF_PRINCIPLED'),None)
        if p and p.inputs['Base Color'].is_linked:
            base=p.inputs['Base Color'].links[0].from_socket
            geom=nt.nodes.new('ShaderNodeNewGeometry')
            ramp=nt.nodes.new('ShaderNodeMapRange')
            ramp.inputs['From Min'].default_value=.35
            ramp.inputs['From Max'].default_value=.65
            ramp.inputs['To Min'].default_value=.985
            ramp.inputs['To Max'].default_value=1.02
            nt.links.new(geom.outputs['Pointiness'],ramp.inputs['Value'])
            mix=nt.nodes.new('ShaderNodeMixRGB');mix.blend_type='MULTIPLY';mix.inputs[0].default_value=1
            nt.links.new(base,mix.inputs[1]);nt.links.new(ramp.outputs[0],mix.inputs[2])
            nt.links.new(mix.outputs[0],p.inputs['Base Color'])
        if kind == 'floors' and p:
            # Metric staggered plank seams, scanned grain and varying roughness.
            tc=nt.nodes.new('ShaderNodeTexCoord')
            brick=nt.nodes.new('ShaderNodeTexBrick')
            brick.inputs['Scale'].default_value=1
            brick.inputs['Mortar Size'].default_value=.0025
            brick.inputs['Mortar Smooth'].default_value=.0015
            brick.inputs['Brick Width'].default_value=1.2
            brick.inputs['Row Height'].default_value=.18
            nt.links.new(tc.outputs['Object'],brick.inputs['Vector'])
            bump=nt.nodes.new('ShaderNodeBump');bump.invert=True
            bump.inputs['Distance'].default_value=.0025
            bump.inputs['Strength'].default_value=.65
            if p.inputs['Normal'].is_linked:
                nt.links.new(p.inputs['Normal'].links[0].from_socket,bump.inputs['Normal'])
            nt.links.new(brick.outputs['Fac'],bump.inputs['Height'])
            bevel=nt.nodes.new('ShaderNodeBevel');bevel.samples=4
            bevel.inputs['Radius'].default_value=.0025
            nt.links.new(bump.outputs['Normal'],bevel.inputs['Normal'])
            nt.links.new(bevel.outputs['Normal'],p.inputs['Normal'])
        m['apt_realism_v1']=True
        counts[kind]+=1
    for o in bpy.data.objects:
        if o.type!='MESH' or len(o.data.polygons)>40000 or o.name.endswith(('.wall','.floor','.ceiling')):
            continue
        structural=o.name.startswith(('Real_','Baseboard','DoorCasing','PanelDoor','apt_Wardrobe','apt_Vanity','apt_Kitchen','apt_Plank','apt_FloorPlank'))
        if structural and not any(x.type=='BEVEL' for x in o.modifiers):
            b=o.modifiers.new('apt_realism_2p5mm','BEVEL');b.width=.0025/max(max(abs(v) for v in o.scale),1e-6);b.segments=3;b.limit_method='ANGLE';b.angle_limit=math.radians(30)
            counts['bevels']+=1
    stats['apt_realism']=counts
    return stats
