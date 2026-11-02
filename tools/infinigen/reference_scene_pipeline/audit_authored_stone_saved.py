"""Bounded saved tile/texture contract; no visual or global scene acceptance."""
import bpy,sys,json,hashlib
from pathlib import Path
R=Path(__file__).resolve().parents[3];D=R/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03'
a=sys.argv[sys.argv.index('--')+1:];assert len(a) in [2,3]
S=Path(a[0]);out=Path(a[1]);revision=int(a[2]) if len(a)==3 else 97;meta=json.loads((D/f'realism_refinement_r{revision}.json').read_text());sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest();assert sha(S)==meta['candidate_sha256']
bpy.ops.wm.open_mainfile(filepath=str(S));errors=[]
for row in meta['surfaces']:
 o=bpy.data.objects[row['object']];m=o.data
 geom=hashlib.sha256(repr(([tuple(v.co) for v in m.vertices],[tuple(f.vertices) for f in m.polygons])).encode()).hexdigest()
 if geom!=row['geometry_sha256']:errors.append(o.name+':geometry')
 if len(m.materials)!=1 or m.materials[0].name!=row['new_material'] or any(f.material_index for f in m.polygons):errors.append(o.name+':binding')
 if not m.uv_layers.get('R93_StoneMetres'):errors.append(o.name+':uv_missing')
 else:
  layer=m.uv_layers['R93_StoneMetres']
  for f in m.polygons:
   normal=(o.matrix_world.to_3x3().inverted().transposed()@f.normal).normalized()
   for li in f.loop_indices:
    p=o.matrix_world@m.vertices[m.loops[li].vertex_index].co;want=(p.x,p.y) if abs(normal.z)>.5 else ((p.y,p.z) if abs(normal.x)>.5 else (p.x,p.z))
    if max(abs(x-y) for x,y in zip(want,layer.data[li].uv))>1e-5:errors.append(o.name+':metric_uv');break
 mat=m.materials[0];n=mat.node_tree.nodes;tex=n['R97_synthetic_albedo'];image=tex.image
 expected=R/'assets/opticalnav_curated/authored_stone_20261026/warm_greige_stone_basecolor_v1.png'
 if not image.packed_file or hashlib.sha256(bytes(image.packed_file.data)).hexdigest()!=sha(expected):errors.append(o.name+':packed_image')
 bs=next(x for x in n if x.type=='BSDF_PRINCIPLED')
 if bs.inputs['Base Color'].links[0].from_node.name!='R93_tile_colour_variation':errors.append(o.name+':base_colour')
 if n['R93_tile_colour_variation'].inputs[1].links[0].from_node!=tex:errors.append(o.name+':image_not_active')
 if bs.inputs['Normal'].links[0].from_node.name!='R93_micro_relief_80um':errors.append(o.name+':micro_normal')
 if abs(n['R93_micro_relief_80um'].inputs['Distance'].default_value-.00008)>1e-8:errors.append(o.name+':micro_scale')
 if not bs.inputs['Roughness'].is_linked:errors.append(o.name+':roughness')
 if abs(bs.inputs['Metallic'].default_value)>1e-6:errors.append(o.name+':metal')
assert len(meta['surfaces'])==131
out.write_text(json.dumps({'source':str(S),'source_sha256':sha(S),'tile_count':131,'errors':errors,'pass':not errors,'photorealism_accepted':False,'scope':'Saved131tile geometry/binding/metricUV, packed albedo SHA and active BaseColor/roughness/micro-normal. Not full collision/nav/lighting/reference certification.'},indent=2));assert not errors,errors
