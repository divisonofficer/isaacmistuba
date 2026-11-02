"""Isolate subtle metal roughness variation after preserving enclosure normals."""
from pathlib import Path
import json
import bpy
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';ref=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03'
bpy.ops.wm.open_mainfile(filepath=str(base/'surface_pilot_r17b.blend'))
m=bpy.data.materials['ReferencePBR_scanned_brushed_steel'];bs=next(n for n in m.node_tree.nodes if n.type=='BSDF_PRINCIPLED');rough=next(n for n in reversed(list(m.node_tree.nodes)) if n.bl_idname=='ShaderNodeMath' and n.operation=='MINIMUM');m.node_tree.links.new(rough.outputs[0],bs.inputs['Roughness'])
counts_before={'materials':len(bpy.data.materials),'images':len(bpy.data.images)};bpy.data.orphans_purge(do_recursive=True)
out=base/'surface_pilot_r17c.blend';assert not out.exists();bpy.ops.wm.save_as_mainfile(filepath=str(out));(ref/'surface_pilot_r17c.json').write_text(json.dumps({'source':'surface_pilot_r17b.blend','change':'Restore three-scale low-amplitude metal roughness while retaining native enclosure normals','counts_before':counts_before,'counts_after':{'materials':len(bpy.data.materials),'images':len(bpy.data.images)},'visual_acceptance':False},indent=2))
