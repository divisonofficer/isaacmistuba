"""First strict realism pass: real garment surfaces and an assembled coffee appliance."""
import argparse,bpy,bmesh,math,random,json,hashlib
from pathlib import Path
from mathutils import Vector
from material_detail import material,noise,bump,range_value
from surface_realism import enrich
ROOT=Path(__file__).resolve().parents[3];p=argparse.ArgumentParser();p.add_argument('--scene',choices=['office','residential'],required=True);a=p.parse_args();office=a.scene=='office';scene='commercial_office_floor_02' if office else 'dual_unit_residential_floor_03';seed=48712502 if office else 48712503;old=18 if office else 22;revision=19 if office else 23;base=ROOT/'out/infinigen_v2'/f'kr_{scene}_{seed}/full';ref=ROOT/'data/venue_refs/floor_plans_v3'/scene;source=base/f'scene_review_r{old}_packed.blend';out=base/f'scene_candidate_r{revision}.blend';assert not out.exists();digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();before=digest(source);bpy.ops.wm.open_mainfile(filepath=str(source));created=[];changes=[]
def find(key):return next(o for o in bpy.data.objects if o.get('program_key')==key)
def mark(o,key,kind='detail'):
 o['reference_scene_owner']=scene;o['program_key']=key;o['audit_kind']=kind;o['realism_refinement_round']=1;created.append(o.name);return o
def cube(key,loc,size,mat,bevel=.001):
 bpy.ops.mesh.primitive_cube_add(size=1,location=loc);o=bpy.context.object;o.name='FineR1_'+key;o.dimensions=size;bpy.ops.object.transform_apply(location=False,rotation=False,scale=True);o.data.materials.append(mat)
 if bevel:
  mod=o.modifiers.new('manufactured_edge_radius','BEVEL');mod.width=bevel;mod.segments=3;mod=o.modifiers.new('face_weighted_normals','WEIGHTED_NORMAL')
 return mark(o,key,'fixture')
def mesh(key,vertices,faces,mat):
 data=bpy.data.meshes.new(key);data.from_pydata(vertices,[],faces);data.materials.append(mat);o=bpy.data.objects.new('FineR1_'+key,data);bpy.context.scene.collection.objects.link(o)
 for f in data.polygons:f.use_smooth=True
 return mark(o,key)
def wire(key,points,radius,mat,parent=None):
 data=bpy.data.curves.new(key,'CURVE');data.dimensions='3D';data.resolution_u=2;data.bevel_depth=radius;data.bevel_resolution=3;spline=data.splines.new('POLY');spline.points.add(len(points)-1)
 for dst,co in zip(spline.points,points):dst.co=(*co,1)
 o=bpy.data.objects.new('FineR1_'+key,data);bpy.context.scene.collection.objects.link(o);data.materials.append(mat);o.parent=parent;return mark(o,key)
def surface(name,color,rough,kind):
 m,n,l,bs,tc,geo=material(name,color,rough,1 if kind=='bare_metal' else 0)
 if kind=='textile':
  tex=noise(n,l,geo.outputs['Position'],1050);l.new(bump(n,l,tex,.00011,.22),bs.inputs['Normal']);bs.inputs['Sheen Weight'].default_value=.2
 enrich(m,kind);return m
if office:
 oldmachine=find('coffee_machine');center=oldmachine.location.copy();fz=center.z-1.08;steel=find('coffee_machine_carafe').data.materials[0];bpy.data.objects.remove(oldmachine,do_unlink=True)
 paint=surface('FineR1_powder_coated_machine',(.028,.033,.038),.34,'paint');bs=next(n for n in paint.node_tree.nodes if n.type=='BSDF_PRINCIPLED');rough=bs.inputs['Roughness'];ramp=paint.node_tree.nodes.new('ShaderNodeMapRange');ramp.inputs['From Min'].default_value=.55;ramp.inputs['From Max'].default_value=.8;ramp.inputs['To Min'].default_value=.28;ramp.inputs['To Max'].default_value=.42;paint.node_tree.links.new(rough.links[0].from_socket,ramp.inputs['Value']);paint.node_tree.links.new(ramp.outputs[0],rough)
 dark=surface('FineR1_rubber_controls',(.012,.013,.014),.67,'paint');x,y=center.x,center.y;z0=fz+.92
 # Hollow service bay and real drip tray, replacing a solid cuboid.
 cube('coffee_machine',(x+.09,y,z0+.155),(.12,.40,.31),paint,.003)
 for side in (-1,1):cube('machine_side',(x-.025,y+side*.19,z0+.155),(.27,.025,.31),paint,.003)
 cube('machine_upper',(x-.03,y,z0+.275),(.29,.40,.065),paint,.003)
 cube('machine_driptray',(x-.11,y,z0+.015),(.27,.38,.025),steel,.002)
 for j in range(9):cube('machine_drain_slot',(x-.11,y-.15+j*.0375,z0+.029),(.20,.004,.002),dark,.0005)
 cube('machine_control_panel',(x-.18,y,z0+.27),(.007,.32,.041),steel,.001)
 for j in (-1,0,1):
  bpy.ops.mesh.primitive_cylinder_add(vertices=40,radius=.009,depth=.008,location=(x-.188,y+j*.06,z0+.27),rotation=(0,math.pi/2,0));o=bpy.context.object;o.data.materials.append(dark);mark(o,'machine_button','fixture')
 wire('machine_spout',[(x-.11,y,z0+.24),(x-.11,y,z0+.19),(x-.15,y,z0+.18)],.009,steel)
 wire('machine_steam_wand',[(x-.05,y-.15,z0+.23),(x-.15,y-.15,z0+.15),(x-.18,y-.13,z0+.08)],.004,steel)
 # Old generic steel cylinder was a placeholder, now use a hollow metal vessel.
 carafe=find('coffee_machine_carafe');oldmat=carafe.data.materials[0];bpy.data.objects.remove(carafe,do_unlink=True);verts=[];faces=[];N=64;cx=x-.13;cy=y;bottom=z0+.031
 for radius,z in ((.045,bottom),(.047,bottom+.10),(.0445,bottom+.10),(.0425,bottom+.003)):
  verts.extend([(cx+radius*math.cos(2*math.pi*i/N),cy+radius*math.sin(2*math.pi*i/N),z) for i in range(N)])
 for ring in range(3):
  for i in range(N):faces.append((ring*N+i,ring*N+(i+1)%N,(ring+1)*N+(i+1)%N,(ring+1)*N+i))
 faces.append(tuple(reversed(range(N))));faces.append(tuple(3*N+i for i in range(N)));mesh('coffee_machine_carafe',verts,faces,oldmat)
 wire('machine_pitcher_handle',[(cx,cy+.045,bottom+.085),(cx,cy+.075,bottom+.08),(cx,cy+.075,bottom+.025),(cx,cy+.045,bottom+.02)],.004,oldmat)
 # Mounted under-cabinet practical provides a real narrow reflection source.
 upper=find('coffee_upper');lower=min((upper.matrix_world@Vector(c)).z for c in upper.bound_box)
 lamp=bpy.data.lights.new('FineR1_under_cabinet','AREA');lamp.energy=9;lamp.shape='RECTANGLE';lamp.size=3.25;lamp.size_y=.035;obj=bpy.data.objects.new(lamp.name,lamp);bpy.context.scene.collection.objects.link(obj);obj.location=(14.42,5.15,lower-.012);obj.rotation_euler.z=math.pi/2;obj['reference_scene_owner']=scene;mark(obj,'under_cabinet_practical','lighting')
 changes.append({'replaced':'coffee_machine 8 vertices / 6 faces','new':'hollow machine housing, distinct control panel/buttons, spout/wand, slotted drip tray, hollow pitcher and actual handle','edge_radius_m':.001,'practical_watts':9})
else:
 palette=[surface('FineR1_garment_'+str(i),c,.78,'textile') for i,c in enumerate([(.55,.53,.48),(.20,.26,.30),(.75,.73,.68),(.32,.34,.31),(.48,.44,.39)])]
 metal=surface('FineR1_closet_brushed_rail',(.5,.51,.53),.3,'bare_metal')
 for unit in (101,102):
  wardrobe=find(str(unit)+'_dressing');bm=bmesh.new();bm.from_mesh(wardrobe.data);remove=[f for f in bm.faces if f.material_index==1 or f.material_index>=3];bmesh.ops.delete(bm,geom=remove,context='FACES');bm.to_mesh(wardrobe.data);bm.free();wardrobe.data.update();rng=random.Random(unit+2500)
  # Preserve the original oak shell/shelves/LED and matrix, replace primitive clothing.
  for tier,railz in enumerate((1.8,1.05)):
   rail=wire(f'{unit}_real_hanging_rail_{tier}',[(.28,-1.14,railz),(.28,.25,railz)],.014,metal,wardrobe)
   for g in range(6):
    yc=-1.04+g*.22;angle=rng.uniform(-.26,.26);length=rng.uniform(.57,.64) if tier==0 else rng.uniform(.57,.66);mat=palette[(g+tier+unit)%len(palette)];phase=rng.uniform(0,6);verts=[];faces=[];rings=36;sides=48
    def transform(x,y,z):return (.28+math.cos(angle)*x-math.sin(angle)*y,yc+math.sin(angle)*x+math.cos(angle)*y,z)
    for j in range(rings):
     t=j/(rings-1);width=.055+(.13*min(t/.14,1))*(1-.10*t);thickness=.020+.014*math.sin(math.pi*t)**.5;z=railz-.055-t*length
     for k in range(sides):
      theta=2*math.pi*k/sides;fold=.0055*math.sin(6*theta+phase+1.8*t)*math.sin(math.pi*t)**.6
      x=width*math.cos(theta);y=(thickness+fold)*math.sin(theta);zz=z-.006*math.sin(theta*3+phase)*t*t;verts.append(transform(x,y,zz))
    for j in range(rings-1):
     for k in range(sides):faces.append((j*sides+k,j*sides+(k+1)%sides,(j+1)*sides+(k+1)%sides,(j+1)*sides+k))
    garment=mesh(f'{unit}_hanging_garment_{tier}_{g}',verts,faces,mat);garment.parent=wardrobe;sol=garment.modifiers.new('sewn_fabric_thickness','SOLIDIFY');sol.thickness=.0012;sol.offset=0
    for side in (-1,1):
     # Short curved sleeves give each shirt a non-rectangular silhouette.
     sv=[];sf=[]
     for j in range(12):
      t=j/11;cx=side*(.16+.055*t);cz=railz-.12-.19*t;radius=.035-.01*t
      for k in range(24):
       q=2*math.pi*k/24;sv.append(transform(cx+radius*math.cos(q),radius*.7*math.sin(q),cz))
     for j in range(11):
      for k in range(24):sf.append((j*24+k,j*24+(k+1)%24,(j+1)*24+(k+1)%24,(j+1)*24+k))
     sleeve=mesh(f'{unit}_sleeve_{tier}_{g}_{side}',sv,sf,mat);sleeve.parent=wardrobe;sm=sleeve.modifiers.new('cuff_fabric_thickness','SOLIDIFY');sm.thickness=.0012
    hanger=[transform(-.18,0,railz-.13),transform(0,0,railz-.055),transform(.18,0,railz-.13),transform(-.18,0,railz-.13)];wire(f'{unit}_hanger_{tier}_{g}',hanger,.0022,metal,wardrobe)
    hook=[(.28+.019*math.cos(q),yc,railz+.019*math.sin(q)) for q in [i*math.pi*1.5/24 for i in range(25)]];hook.append((.28,yc,railz-.055));wire(f'{unit}_hook_{tier}_{g}',hook,.0022,metal,wardrobe)
    hem=[verts[(rings-1)*sides+k] for k in range(sides)]+[verts[(rings-1)*sides]];wire(f'{unit}_hem_{tier}_{g}',hem,.0008,mat,wardrobe)
  for shelfz in (.45,.9,1.35,1.8):
   for stack in range(2):
    o=cube(f'{unit}_folded_knit',(.28,.53+stack*.31,shelfz+.035),(.38,.27,.065),palette[(stack+unit)%len(palette)],.012);o.parent=wardrobe
  changes.append({'wardrobe':wardrobe.name,'primitive_faces_removed':len(remove),'new_garments':12,'cloth_shell_thickness_m':.0012,'detail':'smooth nonplanar folded bodies, short sleeves, sewn hems, real wire hangers/hooks, folded knits; existing shell retained'})
bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(out));assert digest(source)==before
(ref/f'realism_refinement_r{revision}.json').write_text(json.dumps({'source':str(source),'source_sha256':before,'candidate':str(out),'source_unchanged':True,'changes':changes,'created_objects':created,'visual_realism_accepted':False,'requires':['paired same-camera renders','direct material/mesh review','door/furnishing/support regression']},indent=2));print(json.dumps({'saved':str(out),'new_objects':len(created)}),flush=True)
