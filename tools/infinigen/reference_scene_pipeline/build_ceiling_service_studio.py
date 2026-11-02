"""Actual ceiling fixture underside screening, separate from the office scene."""
import bpy,json,hashlib,sys
from pathlib import Path
from mathutils import Vector
sys.path.insert(0,str(Path(__file__).parent))
from curated_gltf_materials import import_curated_gltf
R=Path(__file__).resolve().parents[3]
D=R/'data/venue_refs/floor_plans_v3/commercial_office_floor_02/real_ceiling_service_candidates'
out=D/'review_studio.blend';assert not out.exists()
bpy.ops.wm.read_factory_settings(use_empty=True)
views=[];records=[]
for i,e in enumerate(json.loads((D/'asset_manifest.json').read_text())['assets']):
    assert hashlib.sha256((R/e['path']).read_bytes()).hexdigest()==e['copied_sha256']
    new,objects,profile=import_curated_gltf(e,repair_nonpositive_ior=1.5)
    matrices={o.name:o.matrix_world.copy() for o in objects}
    for o in objects:o.parent=None;o.matrix_world=matrices[o.name]
    for o in new:
        if o.type!='MESH':bpy.data.objects.remove(o,do_unlink=True)
    bpy.context.view_layer.update()
    pts=[o.matrix_world@v.co for o in objects for v in o.data.vertices]
    lo=Vector(tuple(min(p[k] for p in pts) for k in range(3)))
    hi=Vector(tuple(max(p[k] for p in pts) for k in range(3)))
    size=hi-lo;center=Vector((i*5,0,2));delta=center-(lo+hi)/2
    for o in objects:o.location+=delta;o['original_asset_id']=e['id']
    span=max(size.x,size.y,size.z)*1.5
    views.append({'name':e['id']+'_underside','location':list(center+Vector((span*.5,-span*.8,-span*.65))),
        'target':list(center),'overview':True,'ortho_scale':span,'render_width':768,'samples':32})
    for j,(offset,power) in enumerate([((-.7,-1,-.8),90),((.5,1,-.5),45)]):
        ld=bpy.data.lights.new(e['id']+'_studio'+str(j),'AREA');ld.energy=power*span*span;ld.size=span*.6
        light=bpy.data.objects.new(ld.name,ld);bpy.context.scene.collection.objects.link(light)
        light.location=center+Vector(offset)*span;light.rotation_euler=(center-light.location).to_track_quat('-Z','Y').to_euler()
    records.append({'id':e['id'],'objects':[o.name for o in objects],'extents_m':list(size),
        'polygons':sum(len(o.data.polygons) for o in objects),'translation_only_m':list(delta),
        'material_profile_contract':profile,'native_geometry_uv_preserved':True})
for mat in bpy.data.materials:
    if mat.use_nodes:
        for node in mat.node_tree.nodes:
            if node.type=='TEX_IMAGE' and node.image:
                assert min(node.image.size)>0;node.image.pack()
w=bpy.data.worlds.new('Neutral_fixture_review');w.use_nodes=True
w.node_tree.nodes.get('Background').inputs['Strength'].default_value=.12;bpy.context.scene.world=w
bpy.ops.wm.save_as_mainfile(filepath=str(out))
(D/'views.json').write_text(json.dumps(views,indent=2))
(D/'scope.json').write_text(json.dumps({'assets':records,'scope':'Two actual source fixture meshes viewed from below; native geometry/UV, profile material import, diagnostic area lights. Not powered-luminaire/photometric/certification or room integration evidence.','photorealism_accepted':False},indent=2))
print('CEILING_SERVICE_STUDIO_SAVED',flush=True)
