"""Bounded node/input/image signature for exact declared optical ablations."""
import hashlib,json
def optical_signature(material,ignore_principled_inputs=()):
    rows=[]
    for node in material.node_tree.nodes:
        inputs=[]
        for socket in node.inputs:
            if node.type=='BSDF_PRINCIPLED' and socket.name in ignore_principled_inputs:continue
            if not hasattr(socket,'default_value'):continue
            value=socket.default_value
            if not isinstance(value,(str,int,float,bool,type(None))):
                try:value=list(value)
                except TypeError:value=str(value)
            inputs.append((socket.name,value))
        row={'name':node.name,'type':node.bl_idname,'inputs':inputs,
             'attributes':{key:getattr(node,key) for key in ['operation','uv_map','space'] if hasattr(node,key)}}
        if node.type=='TEX_IMAGE' and node.image:
            im=node.image;assert im.packed_file,im.name
            row['image']={'packed_sha256':hashlib.sha256(bytes(im.packed_file.data)).hexdigest(),
                          'colorspace':im.colorspace_settings.name,'size':list(im.size)}
        rows.append(row)
    links=sorted((x.from_node.name,x.from_socket.name,x.to_node.name,x.to_socket.name) for x in material.node_tree.links)
    return hashlib.sha256(json.dumps({'nodes':sorted(rows,key=lambda r:r['name']),'links':links},sort_keys=True).encode()).hexdigest()
