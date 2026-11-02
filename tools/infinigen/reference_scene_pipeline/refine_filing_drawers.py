"""Real folded cabinet shell and separated drawer fronts within original outer bounds."""
import bpy,json,hashlib
from pathlib import Path
from material_detail import material
from surface_realism import enrich
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';ref=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';source=base/'scene_review_r23_packed.blend';out=base/'scene_candidate_r24.blend';assert not out.exists();before=hashlib.sha256(source.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(source));records=[]
def coating(name,rgb):
 m,n,l,bs,tc,geo=material(name,rgb,.42);enrich(m,'paint');mapped=n.new('ShaderNodeMapRange');mapped.inputs['From Min'].default_value=.60;mapped.inputs['From Max'].default_value=.74;mapped.inputs['To Min'].default_value=.36;mapped.inputs['To Max'].default_value=.50;l.new(bs.inputs['Roughness'].links[0].from_socket,mapped.inputs['Value']);l.new(mapped.outputs[0],bs.inputs['Roughness']);return m
pullmat=coating('FineR5_filer_black_pulls',(.025,.026,.027))
for key in ('support_west_storage','support_east_storage'):
 o=next(o for o in bpy.data.objects if o.get('program_key')==key);oldpoints=[o.matrix_world@__import__('mathutils').Vector(c) for c in o.bound_box];oldbounds=[(min(v[i] for v in oldpoints),max(v[i] for v in oldpoints)) for i in range(3)];oldmat=o.data.materials[0];bs=next(n for n in oldmat.node_tree.nodes if n.type=='BSDF_PRINCIPLED');rgb=tuple(bs.inputs['Base Color'].default_value[:3]);body=coating('FineR5_'+key+'_powder_coated_steel',rgb);parts=[];H=.77;W=.9;D=.48;xc=-.01;t=.002
 parts += [(0,(xc,0,H-t/2),(D,W,t)),(0,(xc,0,t/2),(D,W,t)),(0,(-.25+t/2,0,H/2),(t,W,H))]
 for side in (-1,1):
  parts.append((0,(xc,side*(W/2-t/2),H/2),(D,t,H)));parts.append((0,(.223,side*.445,H/2),(.014,.010,H)))
 parts.append((0,(.223,0,.765),(.014,.9,.010)));parts.append((1,(.215,0,.025),(.030,.88,.05)))
 for row,(z0,z1) in enumerate(((.05,.41),(.41,.758))):
  parts.append((0,(.226,0,(z0+z1)/2),(.012,.874,z1-z0-.003)))
  handlez=.05+(row+.75)*.36
  for side in (-1,1):parts.append((1,(.243,side*(.405/2-.018),handlez),(.022,.018,.018)))
  parts.append((1,(.258,0,handlez),(.012,.405,.020)))
 vertices=[];faces=[];indices=[];pattern=[(-1,-1,-1),(1,-1,-1),(1,1,-1),(-1,1,-1),(-1,-1,1),(1,-1,1),(1,1,1),(-1,1,1)];cube_faces=[(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)]
 for index,center,size in parts:
  offset=len(vertices);vertices.extend([tuple(center[i]+signs[i]*size[i]/2 for i in range(3)) for signs in pattern]);faces.extend([tuple(offset+i for i in face) for face in cube_faces]);indices.extend([index]*6)
 mesh=bpy.data.meshes.new('FineR5_folded_filing_assembly');mesh.from_pydata(vertices,[],faces);mesh.materials.append(body);mesh.materials.append(pullmat)
 for f,index in zip(mesh.polygons,indices):f.material_index=index
 o.data=mesh
 for m in o.modifiers:
  if m.type=='BEVEL':m.width=.0007;m.segments=3;m.use_clamp_overlap=True
 o['fine_drawer_front_count']=2;o['fine_reveal_width_m']=.003;o['fine_carcass_wall_thickness_m']=.002
 bpy.context.view_layer.update();newpoints=[o.matrix_world@__import__('mathutils').Vector(c) for c in o.bound_box];newbounds=[(min(v[i] for v in newpoints),max(v[i] for v in newpoints)) for i in range(3)];drift=max(abs(a-b) for pair1,pair2 in zip(oldbounds,newbounds) for a,b in zip(pair1,pair2));assert drift<.001,(key,drift)
 records.append({'object':o.name,'drawer_fronts':2,'actual_reveal_gap_m':.003,'shell_wall_thickness_m':.002,'grip_clearance_m':.020,'outer_bounds_max_change_m':drift})
bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(source.read_bytes()).hexdigest()==before;(ref/'realism_refinement_r24.json').write_text(json.dumps({'source':str(source),'candidate':str(out),'reason':'Strict manufacturing review found lateral filing cabinets represented by a solid cuboid plus pulls and a black gap strip.','change':'Hollow folded steel shell, independent fronts with actual3mm reveals, supported open pull grips, dielectric powder coat; original footprint/top support preserved.','cabinets':records,'photorealism_accepted':False},indent=2));print(json.dumps({'saved':str(out),'cabinets':records}),flush=True)
