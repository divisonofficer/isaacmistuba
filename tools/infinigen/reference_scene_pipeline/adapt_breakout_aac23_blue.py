"""Reference-blue upholstery and authored wood response on the actual AAC23 mesh."""
import bpy,json,hashlib,numpy as np
from pathlib import Path
from mathutils import Vector
R=Path(__file__).resolve().parents[3]
D=R/'data/venue_refs/floor_plans_v3/commercial_office_floor_02/real_breakout_chair_candidates'
O=D/'aac23_blue_wood_variant';assert not O.exists();O.mkdir()
source=D/'review_studio.blend'
bpy.ops.wm.open_mainfile(filepath=str(source))
names=json.loads((D/'review_scope.json').read_text())['assets'][0]['objects']
objects=[bpy.data.objects[n] for n in names]
def fingerprint():
    return hashlib.sha256(repr([(o.name,[tuple(v.co) for v in o.data.vertices],
        [tuple(p.vertices) for p in o.data.polygons],[[tuple(x.uv) for x in layer.data] for layer in o.data.uv_layers],
        [list(v) for v in o.matrix_world]) for o in objects]).encode()).hexdigest()
before=fingerprint();changes=[]
for obj in objects:
    for index,old in enumerate(obj.data.materials):
        if not old:continue
        if 'b033c9e6d7b22928943277cb35ce135cc3d54685::000' in old.name:
            mat=old.copy();mat.name='BreakoutAAC23_authored_blue_native_fabric'
            n,l=mat.node_tree.nodes,mat.node_tree.links
            bs=next(x for x in n if x.type=='BSDF_PRINCIPLED')
            upstream=bs.inputs['Base Color'].links[0].from_socket
            todo=[upstream.node];seen=set();images=set()
            while todo:
                node=todo.pop()
                if node in seen:continue
                seen.add(node)
                if node.type=='TEX_IMAGE' and node.image:images.add(node.image)
                todo.extend(link.from_node for inp in node.inputs for link in inp.links)
            assert len(images)==1
            image=next(iter(images));arr=np.empty(len(image.pixels),np.float32);image.pixels.foreach_get(arr)
            mean=arr.reshape(-1,4)[:,:3].mean(axis=0);ratio=[float(v/max(mean[i],.03)) for i,v in enumerate((.105,.175,.235))]
            tint=n.new('ShaderNodeMixRGB');tint.name='Authored_reference_blue_tint';tint.blend_type='MULTIPLY'
            tint.inputs[0].default_value=1;tint.inputs[2].default_value=(*ratio,1)
            l.new(upstream,tint.inputs[1]);l.new(tint.outputs[0],bs.inputs['Base Color'])
            inherited_coat=float(bs.inputs['Coat Weight'].default_value)
            assert not bs.inputs['Coat Weight'].is_linked
            bs.inputs['Coat Weight'].default_value=0
            bs.inputs['IOR'].default_value=1.46;bs.inputs['Sheen Weight'].default_value=.2
            changes.append({'object':obj.name,'slot':index,'role':'native fabric colour/normal preserved, authored blue tint + IOR1.46/sheen0.2; explicit uncoated textile policy',
                'inherited_coat_weight_before':inherited_coat,'authored_coat_weight':0,
                'optical_policy_evidence':'surface_cause_probe/visual_review.json',
                'mean_decoded_base_rgb':mean.tolist(),'multipliers':ratio})
            obj.data.materials[index]=mat
        elif 'b033c9e6d7b22928943277cb35ce135cc3d54685::001' in old.name:
            mat=old.copy();mat.name='BreakoutAAC23_authored_wood_leg_response'
            n,l=mat.node_tree.nodes,mat.node_tree.links;bs=next(x for x in n if x.type=='BSDF_PRINCIPLED')
            for link in list(bs.inputs['Metallic'].links):l.remove(link)
            bs.inputs['Metallic'].default_value=0;bs.inputs['IOR'].default_value=1.5
            if bs.inputs['Roughness'].is_linked:
                socket=bs.inputs['Roughness'].links[0].from_socket
                mapper=n.new('ShaderNodeMapRange');mapper.name='Authored_wood_roughness_035_050'
                mapper.inputs['From Max'].default_value=max(float(bs.inputs['Roughness'].default_value),1e-5)
                mapper.inputs['To Min'].default_value=.35;mapper.inputs['To Max'].default_value=.50
                l.new(socket,mapper.inputs['Value']);l.new(mapper.outputs[0],bs.inputs['Roughness'])
            else:bs.inputs['Roughness'].default_value=.42
            bs.inputs['Coat Weight'].default_value=.1;bs.inputs['Coat Roughness'].default_value=.3
            obj.data.materials[index]=mat
            changes.append({'object':obj.name,'slot':index,'role':'authored nonmetallic wood-leg response; source textured colour/normal retained, metallic response overridden','roughness_range':[.35,.50]})
assert changes and fingerprint()==before
bpy.ops.wm.save_as_mainfile(filepath=str(O/'review_studio.blend'))
view=json.loads((D/'review_views.json').read_text())[0]
rear={**view,'name':'AAC23_blue_rear','location':[-1.8,2.8,1.8]}
(O/'views.json').write_text(json.dumps([{**view,'name':'AAC23_blue_front'},rear],indent=2))
(O/'provenance.json').write_text(json.dumps({'source':str(source),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
    'object_names':names,'geometry_uv_pose_fingerprint_unchanged':before,'changes':changes,
    'photorealism_accepted':False,'scope':'Actual21744-triangle source product, no mesh/UV/pose changes. Authored dye/wood optical response, not native measured BRDF or separately isolated causes. Front/rear appearance and later room acceptance required.'},indent=2))
print('AAC23_BLUE_WOOD_VARIANT_SAVED',len(changes),flush=True)
