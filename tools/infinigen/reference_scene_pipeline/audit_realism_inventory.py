"""Whole-scene material/mesh inventory; quantitative coverage is not photoreal acceptance."""
import bpy,json,argparse,hashlib,collections
from pathlib import Path
from mathutils import Vector
p=argparse.ArgumentParser();p.add_argument('--blend',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();bpy.ops.wm.open_mainfile(filepath=str(a.blend.resolve()));usage=collections.defaultdict(list);meshes=[]
for o in bpy.data.objects:
 if o.hide_render or o.type not in ('MESH','CURVE','SURFACE','FONT','META'):continue
 for m in o.data.materials:
  if m:usage[m.name].append(o.name)
 if o.type!='MESH':continue
 pts=[o.matrix_world@Vector(c) for c in o.bound_box];dims=[max(v[k] for v in pts)-min(v[k] for v in pts) for k in range(3)]
 meshes.append({'object':o.name,'role':o.get('program_key'),'vertices':len(o.data.vertices),'polygons':len(o.data.polygons),'smooth_polygons':sum(f.use_smooth for f in o.data.polygons),'has_bevel':any(m.type=='BEVEL' for m in o.modifiers),'has_solidify':any(m.type=='SOLIDIFY' for m in o.modifiers),'world_dimensions_m':dims,'material_names':[m.name for m in o.data.materials if m]})
materials=[]
for name,objects in usage.items():
 m=bpy.data.materials[name];bs=next((n for n in m.node_tree.nodes if n.type=='BSDF_PRINCIPLED'),None) if m.use_nodes else None
 materials.append({'material':name,'kind':m.get('reference_pbr_kind'),'used_by_renderable_objects':len(objects),'objects':objects,'principled_directly_accessible':bool(bs),'channels':{k:{'linked':bs.inputs[k].is_linked,'default':list(bs.inputs[k].default_value) if k in ('Base Color','Normal') else bs.inputs[k].default_value} for k in ('Base Color','Roughness','Metallic','Normal')} if bs else {},'noise_nodes':sum(n.type=='TEX_NOISE' for n in m.node_tree.nodes) if m.use_nodes else 0,'bump_nodes':sum(n.type=='BUMP' for n in m.node_tree.nodes) if m.use_nodes else 0})
boxes=[m for m in meshes if m['polygons']==6 and not m['has_bevel'] and m['role'] and min(m['world_dimensions_m'])>.01];summary={'renderable_meshes':len(meshes),'assigned_materials_including_curves':len(materials),'unclassified_materials':len([m for m in materials if not m['kind']]),'owned_box_forms_without_bevel':[m['role'] for m in boxes],'kinds':dict(collections.Counter(m['kind'] or 'unclassified' for m in materials))};doc={'source':str(a.blend.resolve()),'source_sha256':hashlib.sha256(a.blend.read_bytes()).hexdigest(),'summary':summary,'materials':materials,'meshes':meshes,'limitations':['Unclassified is a coverage warning, not a visual failure.','Planar/flat-shaded parts may be intentional; shape and material response require image inspection.','A linked roughness/normal channel does not prove realistic amplitude, scale, coordinates, or lighting.'],'photorealism_accepted':False};a.out.write_text(json.dumps(doc,indent=2));print(json.dumps(summary),flush=True)
