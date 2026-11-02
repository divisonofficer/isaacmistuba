"""Keep native curved normals and verified metal scan response in the pilot."""
import bpy,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';ref=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03'
bpy.ops.wm.open_mainfile(filepath=str(base/'surface_pilot_r17.blend'))
removed=[]
for o in bpy.data.objects:
 if o.type!='MESH':continue
 # Do not run a generic bevel/weighted-normal on already curved native assets
 # or a joined transparent enclosure; retain the proven original normals.
 if len(o.data.polygons)>20000 or 'shower' in o.get('program_key',''):
  for modifier in list(o.modifiers):
   if modifier.name in ('realistic_manufactured_edge','surface_weighted_normals'):removed.append([o.name,modifier.name]);o.modifiers.remove(modifier)
# Restore known-good steel scan input, adding only broad low-amplitude variation
# later after isolating geometric normal changes in paired views.
m=bpy.data.materials['ReferencePBR_scanned_brushed_steel'];n=m.node_tree.nodes;l=m.node_tree.links;bs=next(x for x in n if x.type=='BSDF_PRINCIPLED')
original=next(x for x in n if x.bl_idname=='ShaderNodeVectorMath' and x.operation=='NORMALIZE')
l.new(original.outputs[0],bs.inputs['Normal'])
# Keep the pre-enrichment scan roughness map (old Map Range .24..34).
rough=next(x for x in n if x.type=='MAP_RANGE' and abs(x.inputs['To Min'].default_value-.24)<1e-5 and abs(x.inputs['To Max'].default_value-.34)<1e-5);l.new(rough.outputs['Result'],bs.inputs['Roughness'])
out=base/'surface_pilot_r17b.blend';assert not out.exists();bpy.ops.wm.save_as_mainfile(filepath=str(out));(ref/'surface_pilot_r17b.json').write_text(json.dumps({'source':'surface_pilot_r17.blend','removed_modifiers':removed,'steel':'Known-good scanned normal/roughness restored for isolation','visual_acceptance':False},indent=2))
