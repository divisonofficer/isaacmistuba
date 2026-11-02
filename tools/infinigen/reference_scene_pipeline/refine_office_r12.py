"""Preserve resolved baseline wood scans; improve diagnostic-scale relief."""
import json,sys,shutil
from pathlib import Path
import bpy
from material_detail import paint,carpet,brushed_metal,noise,bump,range_value
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';ref=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02'
bpy.ops.wm.open_mainfile(filepath=str(base/'scene_candidate_r9.blend'))
wall=paint();metal=brushed_metal(ref/'pbr_assets');cp=next(im for im in bpy.data.images if im.name.startswith('cp_'));mat=carpet(cp,ref/'pbr_assets')
# Resolve roller stipple at millimetre scale rather than subpixel smoothness.
n=wall.node_tree.nodes;l=wall.node_tree.links;bs=next(x for x in n if x.type=='BSDF_PRINCIPLED');g=next(x for x in n if x.type=='NEW_GEOMETRY')
roller=noise(n,l,g.outputs['Position'],115,(1,1,1.3));normal=bump(n,l,roller,.00075,.7);l.new(normal,bs.inputs['Normal']);l.new(range_value(n,l,roller,.47,.82),bs.inputs['Roughness'])
n=metal.node_tree.nodes;l=metal.node_tree.links;bs=next(x for x in n if x.type=='BSDF_PRINCIPLED');g=next(x for x in n if x.type=='NEW_GEOMETRY')
f=noise(n,l,g.outputs['Position'],18,(1,12,1));l.new(range_value(n,l,f,.12,.46),bs.inputs['Roughness']);l.new(bump(n,l,f,.00010,.5),bs.inputs['Normal'])
n=mat.node_tree.nodes;l=mat.node_tree.links;bs=next(x for x in n if x.type=='BSDF_PRINCIPLED');g=next(x for x in n if x.type=='NEW_GEOMETRY')
old=bs.inputs['Normal'].links[0].from_socket
pile=noise(n,l,g.outputs['Position'],260,(1,1,.3));l.new(bump(n,l,pile,.0016,.8,old),bs.inputs['Normal'])
changes=[]
for o in bpy.data.objects:
 if o.type!='MESH':continue
 if o.name.endswith('.wall'):o.data.materials.clear();o.data.materials.append(wall);changes.append(o.name)
 elif o.name.endswith('.floor') and o.name.startswith(('office','utility')):o.data.materials.clear();o.data.materials.append(mat);changes.append(o.name)
 else:
  for slot in o.material_slots:
   if slot.material and slot.material.name.startswith(('office02_sink_steel','ir_chrome')):slot.material=metal
  if o.name.startswith('Office02_') and o.get('audit_kind')!='vegetation' and not any(m.type=='BEVEL' for m in o.modifiers):
   if any(s.material and ('oak' in s.material.name or 'steel' in s.material.name or s.material==metal) for s in o.material_slots):
    mod=o.modifiers.new('reference_physical_edge_rounding','BEVEL');mod.width=.0012;mod.segments=3;mod.limit_method='ANGLE'
# Make existing baseline wood dependencies project-local without changing maps.
for image in bpy.data.images:
 if '/texturecan_wood_0054/' in image.filepath:
  source=Path(image.filepath);dest=ref/'pbr_assets/wood_0054'/source.name;dest.parent.mkdir(parents=True,exist_ok=True)
  if not dest.exists():shutil.copy2(source,dest)
  image.filepath=str(dest)
out=base/'scene_candidate_r12.blend';assert not out.exists();bpy.ops.wm.save_as_mainfile(filepath=str(out))
(ref/'material_detail_r12.json').write_text(json.dumps({'source':'scene_candidate_r9.blend','changes':changes,'wood':'Preserved original resolved wood_0054 albedo, roughness and normal; project-local copies','paint':'0.75mm nominal bump distance, 115/m roller noise','carpet':'layered scan normal plus nominal 1.6mm pile bump; no mesh displacement','metal':'directional roughness .12-.46, bare metal metallic1','visual_acceptance':False},indent=2))
