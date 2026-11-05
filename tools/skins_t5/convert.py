from collections import OrderedDict
from pathlib import Path
import copy
import math
import struct
from tools.stages.container import pack
from tools.mod.port_t4_julia_t5 import bone_map, model, container, texture_picture, crop_texture
from .sources import worlds
import numpy as np
from PIL import Image, ImageOps
from .facial import TAG_FACE,tag_face,split_lower_lip,native_face
from .rig import describe
from .xps_mapping import suggest as suggest_xps

FIELDS = ('positions', 'normals', 'uv0', 'weights', 'indices')


def tag_accessory_anchors(source):
    if source['kind'] != 'taghd': return {}
    anchors = {i:6 for i in range(7,min(29,len(source['bones'])))}
    if len(source['bones']) >= 98:
        anchors.update({3:2,4:2,30:29,32:31,33:31,35:34,36:34,37:34,
                        55:54,57:56,58:56,60:59,61:59,62:59,
                        80:81,82:81,83:81,85:84,86:84,
                        89:90,91:90,92:90,94:93,95:93})
    for i in range(98, len(source['bones'])):
        parent = source['bones'][i]['parent']
        while parent >= 98: parent = source['bones'][parent]['parent']
        if parent >= 0: anchors[i] = parent
    return anchors


def material_key(mesh):
    return str(mesh.get('material_id',mesh.get('tex0', mesh['texture'] or mesh['name'])))
BODY = {1: 'pelvis', 2: 'spine lower', 3: 'spine middle', 5: 'chest', 6: 'head / neck',
        7: 'left collar', 8: 'left upper arm', 9: 'left forearm', 10: 'left hand',
        11: 'right collar', 12: 'right upper arm', 13: 'right forearm', 14: 'right hand',
        15: 'left thigh', 16: 'left knee', 17: 'left ankle', 21: 'left toe',
        18: 'right thigh', 19: 'right knee', 20: 'right ankle', 22: 'right toe'}


def skeleton(package):
    raw = pack(package)[3]
    _, n, _, po, to, ro, _ = struct.unpack_from('<HHf4I', raw)
    if not 1 <= n <= 255: raise ValueError('Esqueleto T5 incompatível')
    result=[dict(name='%03d · %s' % (i, BODY.get(i, 'helper / acessório')),
                 parent=struct.unpack_from('<i',raw,po+i*4)[0],
                 translation=struct.unpack_from('<3f',raw,to+i*12),
                 rotation=struct.unpack_from('<3f',raw,ro+i*12)) for i in range(n)]
    return describe(result,package)


def alignment(source, target, settings):
    scale = float(settings.get('scale', 1000 if source['kind'] == 'xps' else 1))
    if not math.isfinite(scale) or not .00001 <= scale <= 100000:
        raise ValueError('Escala inválida')
    angle = math.radians(float(settings.get('yaw', 0)))
    if not math.isfinite(angle): raise ValueError('Rotação inválida')
    cs, sn = math.cos(angle), math.sin(angle)
    matrix = np.array([[cs,0,sn],[0,1,0],[-sn,0,cs]])
    offset = np.asarray(settings.get('offset', [0,1127,0] if source['kind'] in ('t4','taghd') else [0,0,0]), float)
    if offset.shape != (3,) or not np.isfinite(offset).all(): raise ValueError('Posição inválida')
    return scale, matrix, offset


def suggested_mapping(source, target, settings):
    sw, tw = worlds(source['bones']), worlds(target)
    scale, rotation, offset = alignment(source, target, settings)
    sp = sw[:,:3,3] @ rotation.T * scale + offset
    tp = tw[:,:3,3]
    mapping = {i: int(np.linalg.norm(tp-p,axis=1).argmin()) for i,p in enumerate(sp)}
    if source['kind'] == 't5edit':
        if sw.shape!=tw.shape or not np.allclose(sw,tw,atol=.001):
            raise ValueError('Esta edição pertence a outro esqueleto T5. Selecione a roupa base usada na exportação.')
        mapping={i:i for i in range(len(sw))}
    if source['kind'] == 't4':
        mapping.update({i:j for i,j in bone_map().items() if i < len(sw) and j < len(tw) and i < 111})
        if len(sw) == 123 and len(tw) == 132:
            mapping.update(bone_map())
    if source['kind'] == 'taghd' and len(sw) >= 98 and source['bones'][29]['parent'] == 2:
        mapping.update({0:1,1:2,2:3,5:5,6:6,29:7,30:7,31:8,32:8,33:8,
                        34:9,35:9,36:9,37:9,38:10,54:11,55:11,56:12,57:12,58:12,
                        59:13,60:13,61:13,62:13,63:14,79:4,80:15,81:15,82:15,83:15,
                        84:16,85:16,86:16,87:17,88:21,89:18,90:18,91:18,92:18,
                        93:19,94:19,95:19,96:20,97:22})
        mapping.update({i:55+i-39 for i in range(39,54)})
        mapping.update({i:70+i-64 for i in range(64,79)})
        for i, parent in tag_accessory_anchors(source).items(): mapping[i] = mapping[parent]
        if tag_face(source,target,settings):mapping.update(TAG_FACE)
    if source['kind'] == 'xps':
        mapping,_=suggest_xps(source,target,sp,tp,settings)
    mapping.update({int(i):int(j) for i,j in settings.get('mapping',{}).items()})
    if set(mapping) != set(range(len(sw))) or any(not 0 <= j < len(tw) for j in mapping.values()):
        raise ValueError('Remapeamento contém osso inexistente')
    return mapping


def prepared(source, target, settings):
    mapping = suggested_mapping(source, target, settings)
    scale, rotation, offset = alignment(source, target, settings)
    sw, tw = worlds(source['bones']), worlds(target)
    sw[:,:3,3] = sw[:,:3,3] @ rotation.T * scale + offset
    sw[:,:3,:3] = rotation @ sw[:,:3,:3]
    transforms = np.asarray([tw[mapping[i]] @ np.linalg.inv(m) for i,m in enumerate(sw)])
    if source['kind'] in ('taghd','xps'):
        transforms[:,:3,:3] = np.eye(3)
        transforms[:,:3,3] = tw[[mapping[i] for i in range(len(sw))],:3,3]-sw[:,:3,3]
    explicit = {int(i) for i in settings.get('mapping', {})}
    for i, parent in tag_accessory_anchors(source).items():
        if 7<=i<=28 or i not in explicit or mapping[i] == mapping[parent]:
            transforms[i] = transforms[parent]
    enabled = settings.get('materials', {})
    meshes = []
    for index, mesh in enumerate(source['meshes']):
        material = enabled.get(material_key(mesh), {})
        if not material.get('enabled',True): continue
        m = {k:v.copy() for k,v in mesh.items() if isinstance(v,np.ndarray)}
        m.update({k:v for k,v in mesh.items() if not isinstance(v,np.ndarray)})
        pos = m['positions'] @ rotation.T * scale + offset
        normals = m['normals'] @ rotation.T
        if settings.get('retarget', source['kind'] not in ('t4','t5edit','xps')):
            ids = m['indices']; ws = m['weights']
            matrices = transforms[ids]
            pos = (np.einsum('nvij,nj->nvi',matrices[:,:,:3,:3],pos) + matrices[:,:,:3,3])
            pos = np.einsum('nvi,nv->ni',pos,ws)
            normals = np.einsum('nvij,nj,nv->ni',matrices[:,:,:3,:3],normals,ws)
        normals /= np.maximum(np.linalg.norm(normals,axis=1,keepdims=True),1e-12)
        m['positions'],m['normals'] = pos.astype(np.float32),normals.astype(np.float32)
        m['material_key'] = material_key(mesh)
        meshes.append(m)
    if not meshes: raise ValueError('Ative ao menos um material')
    if tag_face(source,target,settings):split_lower_lip(meshes,mapping,source,target)
    if source['kind']=='xps' and native_face(target):
        from .xps_mapping import normalized
        for i,b in enumerate(source['bones']):
            if normalized(b['name']) in ('head lip lower middle','head lip lower center') and i not in explicit:
                split_lower_lip(meshes,mapping,source,target,source_id=i)
                break
    return meshes,mapping


def strips(mesh):
    n = len(mesh['positions']); f = mesh['faces']
    expected = np.asarray([(i-2,i-1,i) if i%2==0 else (i-1,i-2,i) for i in range(2,n)])
    native = f.shape == expected.shape and (np.array_equal(f,expected) or np.array_equal(f,expected[:,[1,0,2]]))
    if native and n <= 40:
        draw = {k:mesh[k].copy() for k in FIELDS}
        if not np.array_equal(f,expected):
            draw = {k:np.concatenate([v[:1],v]) for k,v in draw.items()}
        if len(draw['positions']) <= 40:
            yield draw; return
    yield from indexed_strips(mesh)


def indexed_strips(mesh):
    f=mesh['faces'];lookup={};canonical=[]
    for i in range(len(mesh['positions'])):
        key=tuple(tuple(np.round(mesh[k][i],5)) for k in FIELDS)
        canonical.append(lookup.setdefault(key,len(lookup)))
    triangles=np.array(canonical,np.int32)[f];edges={}
    for i,(a,b,c) in enumerate(triangles):
        for edge in ((a,b),(b,c),(c,a)):edges.setdefault(edge,[]).append(i)
    remaining=set(range(len(f)))
    for first in range(len(f)):
        if first not in remaining:continue
        best=None
        for shift in range(3):
            vertices=list(np.roll(f[first],-shift));ids=list(np.roll(triangles[first],-shift));used={first}
            while len(vertices)<40:
                a,b=ids[-2:]
                edge=(b,a) if len(vertices)%2 else (a,b)
                candidate=next((j for j in edges.get(edge,[]) if j in remaining and j not in used),None)
                if candidate is None:break
                tri=list(triangles[candidate]);at=next(k for k in range(3) if (tri[k],tri[(k+1)%3])==edge)
                ids.append(tri[(at+2)%3]);vertices.append(int(f[candidate,(at+2)%3]));used.add(candidate)
            if best is None or len(used)>len(best[1]):best=(vertices,used)
        vertices,used=best;remaining.difference_update(used)
        yield {k:mesh[k][vertices].copy() for k in FIELDS}


def material_state(nud):
    offset = 32
    for _ in range(struct.unpack_from('<H',nud,10)[0]):
        count = struct.unpack_from('<H',nud,offset+4)[0]
        if count:
            gs, mat = struct.unpack_from('<II',nud,offset+28)
            material = bytearray(nud[mat:mat+48]); state = nud[gs:gs+48]
            if len(material) != 48 or len(state) != 48: raise ValueError('Estado material nativo truncado')
            return bytes(material),state
        offset += 24+count*40
    raise ValueError('Roupa base sem material')


MAX_PACKAGE = 1621680
MAX_PICTURE = 512*256
MIN_SIDE = 64
PICTURE_OVERHEAD = 1104


def align16(n):
    return -(-n//16)*16


def mb(n):
    return ('%.2f MB'%(n/1048576)).replace('.',',')


def package_bytes(sizes, fixed, bank):
    return fixed+align16(bank+sum(PICTURE_OVERHEAD+w*h for w,h in sizes))


def half(size):
    return (max(1,size[0]//2),max(1,size[1]//2))


def capped(size, side=None):
    size=tuple(size)
    while size[0]*size[1]>MAX_PICTURE or (side and max(size)>side):size=half(size)
    return size


def fitted_sizes(sizes, fixed, bank):
    result=[capped(size) for size in sizes]
    while package_bytes(result,fixed,bank)>MAX_PACKAGE:
        shrinkable=[i for i,(w,h) in enumerate(result) if max(w,h)//2>=MIN_SIDE and min(w,h)//2>=8]
        if not shrinkable:break
        i=max(shrinkable,key=lambda i:result[i][0]*result[i][1]);result[i]=half(result[i])
    return result


def convert(source, package, settings, output):
    target = skeleton(package); meshes,mapping = prepared(source,target,settings)
    parts = list(pack(package)); groups = OrderedDict()
    bykey = OrderedDict()
    for mesh in meshes: bykey.setdefault(mesh['material_key'],[]).append(mesh)
    if len(bykey) > 128: raise ValueError('Máximo de 128 materiais por skin')
    texbank = bytearray(parts[1]); count = struct.unpack_from('<H',texbank,6)[0]
    cursor, gids = 16, []
    for _ in range(count):
        size = struct.unpack_from('<I',texbank,cursor)[0]
        header = struct.unpack_from('<H',texbank,cursor+12)[0]
        if size < header or cursor+size > len(texbank): raise ValueError('TIM2 inválido')
        loc = texbank.find(b'GIDX',cursor,cursor+header)
        if loc >= 0: gids.append(struct.unpack_from('<I',texbank,loc+8)[0])
        cursor += size
    nextid = max(gids,default=0x10500000)+1
    texture_ids = {}; stats = []; images = []
    for number,(key,items) in enumerate(bykey.items()):
        config = settings.get('materials',{}).get(key,{})
        file = Path(config.get('texture') or items[0]['texture'])
        if not file.is_file(): raise ValueError('Textura ausente: '+str(file))
        im = crop_texture(file,items) if source['kind'] in ('t4','taghd','t5edit') and not config.get('texture') else Image.open(file).convert('RGBA')
        if im.width > 1024 or im.height > 1024: im.thumbnail((1024,1024))
        w,h = [1 << (max(1,v)-1).bit_length() for v in im.size]
        if (w,h) != im.size: im = im.resize((w,h),Image.Resampling.LANCZOS)
        color = config.get('color','#ffffff').lstrip('#')
        if len(color) != 6: raise ValueError('Cor de material inválida')
        rgba = np.asarray(im).copy()
        rgba[:,:,:3] = np.rint(rgba[:,:,:3].astype(float)*np.array([int(color[i:i+2],16) for i in (0,2,4)])/255).astype(np.uint8)
        if config.get('alpha',items[0].get('alpha','texture' if source['kind']=='xps' else 'opaque')) == 'opaque': rgba[:,:,3] = 255
        texture_ids[key] = nextid+number
        images.append(Image.fromarray(rgba))
        draws = []
        for mesh in items:
            for draw in strips(mesh):
                active = {mapping[int(i)] for i in draw['indices'][draw['weights']>0]}
                if len(active)>10:
                    for end in range(2,len(draw['positions'])):
                        face=[end-2,end-1,end] if end%2==0 else [end-1,end-2,end]
                        triangle={k:draw[k][face].copy() for k in FIELDS}
                        used={mapping[int(i)] for i in triangle['indices'][triangle['weights']>0]}
                        if len(used)>10:raise ValueError('Um triângulo usa mais de 10 ossos T5; revise seus pesos no Blender.')
                        draws.append(triangle)
                    continue
                draws.append(draw)
        groups[key] = draws
        stats.append({'key':key,'texture':str(file),'source_size':im.size,'triangles':sum(len(x['faces']) for x in items)})
    struct.pack_into('<H',texbank,6,count+len(bykey))
    native, packets = model(groups,texture_ids,parts[2],mapping=mapping,translation=(0,0,0),material_state=material_state(parts[2]))
    warnings=list(source['warnings'])
    if packets>400:
        warnings.append('Skin com %d pacotes VU (as roupas originais usam até 290); confira o desempenho no jogo.'%packets)
    parts[2] = native
    header = bytearray(parts[0]); struct.pack_into('<I',header,4,max(0x30000,packets*768)); parts[0]=bytes(header)
    fixed = align16(4+8*len(parts))+sum(align16(len(p)) for i,p in enumerate(parts) if i!=1)
    sizes = fitted_sizes([im.size for im in images],fixed,len(texbank))
    smallest = package_bytes(sizes,fixed,len(texbank))
    if smallest > MAX_PACKAGE:
        def cut(total):return min(99,math.ceil(100*(total-MAX_PACKAGE)/len(native)))
        sharp = package_bytes([capped(im.size,256) for im in images],fixed,len(texbank))
        raise ValueError('A skin não cabe na memória do jogo (limite: %s, o tamanho da maior roupa original). O modelo ocupa %s. '
                         'Reduza no Blender (Decimate) cerca de %d%% dos triângulos para manter texturas de até 256 px, ou no mínimo %d%% '
                         'com texturas bem reduzidas, e converta de novo.'%(mb(MAX_PACKAGE),mb(len(native)),cut(sharp),cut(smallest)))
    reduced = 0
    for (key,_),image,size,stat in zip(bykey.items(),images,sizes,stats):
        if image.size != size: image = image.resize(size,Image.Resampling.LANCZOS);reduced += 1
        texbank.extend(texture_picture(image,texture_ids[key]));stat['size'] = size
    parts[1] = bytes(texbank)
    result = container(parts)
    if len(result) > MAX_PACKAGE: raise ValueError('Pacote final excede o orçamento de memória calculado')
    if reduced:
        warnings.append('Texturas reduzidas para caber na memória do PS2: %d de %d. Pacote final: %s de %s.'
                        %(reduced,len(images),mb(len(result)),mb(MAX_PACKAGE)))
    output = Path(output); output.parent.mkdir(parents=True,exist_ok=True); output.write_bytes(result)
    return {'asset':str(output),'bytes':len(result),'memory_budget':MAX_PACKAGE,'packets':packets,'triangles':sum(len(x['faces']) for x in meshes),
            'source':source['path'],'mapping':mapping,'materials':stats,'warnings':warnings,
            'target_bones':len(target),'retarget_revision':4,'status':'converted; game validation required'}
