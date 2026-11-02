"""Read-only active-surface lobe inventory; role hints flag review, never approval."""
import bpy,json,hashlib,argparse,sys,re
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--blend',required=True,type=Path);p.add_argument('--out',required=True,type=Path)
a=p.parse_args(sys.argv[sys.argv.index('--')+1:]);assert not a.out.exists()
sha=hashlib.sha256(a.blend.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(a.blend))
bound={}
for obj in bpy.context.scene.objects:
    if obj.hide_render or obj.type not in ['MESH','CURVE']:continue
    for mat in obj.data.materials:
        if mat:bound.setdefault(mat,[]).append(obj.name)
rows=[]
for mat,objects in bound.items():
    if not mat.use_nodes:continue
    outputs=[n for n in mat.node_tree.nodes if n.type=='OUTPUT_MATERIAL' and n.is_active_output]
    seen=set();todo=[link.from_node for n in outputs for link in n.inputs['Surface'].links]
    while todo:
        node=todo.pop()
        if node in seen:continue
        seen.add(node);todo.extend(link.from_node for inp in node.inputs for link in inp.links)
    hint=bool(re.search('fabric|textile|cloth|upholster|carpet|duvet|pillow|cushion',mat.name,re.I)) or mat.get('reference_pbr_kind')=='textile'
    lobes=[]
    for node in seen:
        if node.type!='BSDF_PRINCIPLED':continue
        values={}
        for name in ['Metallic','Roughness','IOR','Specular IOR Level','Coat Weight','Coat Roughness','Sheen Weight','Sheen Roughness']:
            socket=node.inputs[name]
            values[name]={'constant':float(socket.default_value) if not socket.is_linked else None,
                          'linked_sources':[{'node':link.from_node.name,'socket':link.from_socket.name} for link in socket.links]}
        lobes.append({'node':node.name,'inputs':values})
    flag=hint and any(n['inputs']['Coat Weight']['constant'] is not None and n['inputs']['Coat Weight']['constant']>.05 for n in lobes)
    rows.append({'material':mat.name,'bound_objects':sorted(set(objects)),'textile_hint_provisional':hint,
                 'positive_constant_coat_on_hinted_textile_review':flag,'reachable_principled':lobes})
assert hashlib.sha256(a.blend.read_bytes()).hexdigest()==sha
a.out.write_text(json.dumps({'source':str(a.blend),'source_sha256':sha,'source_unchanged':True,
    'bound_node_material_count':len(rows),'hinted_textile_review_flags':sum(row['positive_constant_coat_on_hinted_textile_review'] for row in rows),
    'materials':rows,'photorealism_accepted':False,
    'scope':'All materials bound to scene MESH/CURVE objects with hide_render false, upstream active Surface graphs. Collection/ray visibility, effective linked values and nested node groups not resolved. Textile hints from names/tag are provisional, not exhaustive material classification. Positive coat flags require role/source/RGB review, not automatic stripping or a realism verdict.'},indent=2))
print('BOUND_MATERIAL_LOBES',len(rows),sum(row['positive_constant_coat_on_hinted_textile_review'] for row in rows),flush=True)
