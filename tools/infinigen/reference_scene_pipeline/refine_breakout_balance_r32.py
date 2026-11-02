"""Balance cloth detail and provide actual countertop supports beneath the drop-in sink rim."""
import bpy,json,hashlib,math
from pathlib import Path
from mathutils import Vector
from material_detail import noise,bump
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';ref=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';src=base/'scene_candidate_r31.blend';out=base/'scene_candidate_r32.blend';assert not out.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src));m=bpy.data.materials['BreakoutR30_fine_blue_upholstery'];n=m.node_tree.nodes;l=m.node_tree.links;bs=next(x for x in n if x.type=='BSDF_PRINCIPLED');geo=next(x for x in n if x.type=='NEW_GEOMETRY');old=bs.inputs['Normal'].links[0].from_socket
for node in n:
 if node.type=='VECT_MATH' and node.operation=='SCALE' and not node.inputs[3].is_linked and abs(node.inputs[3].default_value-.1)<1e-5:node.inputs[3].default_value=.25
 if node.type=='MAP_RANGE' and abs(node.inputs['To Min'].default_value-.70)<1e-5:node.inputs['To Min'].default_value=.78;node.inputs['To Max'].default_value=.88
micro=noise(n,l,geo.outputs['Position'],650);l.new(bump(n,l,micro,.00006,.35,old),bs.inputs['Normal']);bs.inputs['Sheen Weight'].default_value=.25;bs.inputs['Specular IOR Level'].default_value=.18
floor=bpy.data.objects['kitchen_0/0.floor'];fz=max((floor.matrix_world@Vector(c)).z for c in floor.bound_box);top=fz+.9175;mat=next(o for o in bpy.data.objects if o.get('program_key')=='coffee_worktop').data.materials[0]
# Existing full-depth gap must have front/back stone rails; an unsupported rim over a full-width hole is not a sink cutout.
for key,x in [('sink_front_stone_support',13.985),('sink_back_stone_support',14.565)]:
 p=[(-1,-1,-1),(1,-1,-1),(1,1,-1),(-1,1,-1),(-1,-1,1),(1,-1,1),(1,1,1),(-1,1,1)];faces=[(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)];mesh=bpy.data.meshes.new(key);mesh.from_pydata([(a*.055,b*.30,c*.0175) for a,b,c in p],[],faces);mesh.materials.append(mat);o=bpy.data.objects.new('BreakoutR32_'+key,mesh);bpy.context.scene.collection.objects.link(o);o.location=(x,4.65,top-.0175);o['reference_scene_owner']='commercial_office_floor_02';o['program_key']=key;o['audit_kind']='fixture';bev=o.modifiers.new('Counter_edge','BEVEL');bev.width=.0007;bev.segments=3;o.modifiers.new('Planar_counter_normals','WEIGHTED_NORMAL')
sink=next(o for o in bpy.data.objects if o.get('program_key')=='sink_formed_bowl');N=128
for k in range(N):
 t=math.tau*k/N;c=math.cos(t);s=math.sin(t);sink.data.vertices[3*N+k].co=(14.275+.225*math.copysign(abs(c)**.4,c),4.65+.260*math.copysign(abs(s)**.4,s),top)
sink.data.update();bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha;(ref/'realism_refinement_r32.json').write_text(json.dumps({'source':str(src),'candidate':str(out),'source_sha256':sha,'findings':['r29 fabric over-amplified; r31 overcorrected and looks vinyl-like','r31 chair closeup exposes unsupported gap below the new sink front lip'],'changes':['cloth normal amplitude .25,60micron fibre bump,roughness .78-.88 and reduced specular','actual stone support rails complete a real sink cutout;3mm metal mounting lip sits on stone','outer underside rim made planar at actual counter top'], 'photorealism_accepted':False,'requires':'new closeup images;direct drop-in rim support rays;do not assume latest is best'},indent=2));print('SAVED',out)
