import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import numpy as np
from .container import pack
from .ps2gs import Memory

REPO = Path(__file__).resolve().parents[2]
ELF_SHA = 'b63a0683c83dfd48dabc899372d5eb0207726296bc6620a99b41c14bf3509ea3'


class Archive:
    def __init__(self, iso):
        self.path = Path(iso)
        with self.path.open('rb') as f:
            f.seek(16*2048)
            pvd = f.read(2048)
            if pvd[:7] != b'\x01CD001\x01':
                raise ValueError('Expected ISO9660')
            self.files = {}
            def directory(record, prefix=''):
                sector, size = struct.unpack_from('<I', record, 2)[0], struct.unpack_from('<I', record, 10)[0]
                f.seek(sector*2048)
                data = f.read(size)
                offset = 0
                while offset < len(data):
                    n = data[offset]
                    if not n:
                        offset = (offset//2048+1)*2048
                        continue
                    row = data[offset:offset+n]
                    offset += n
                    name = row[33:33+row[32]]
                    if name in (b'\0', b'\1'):
                        continue
                    name = prefix+'/'+name.decode('ascii').split(';')[0]
                    if row[25]&2:
                        directory(row, name)
                    else:
                        self.files[name] = (struct.unpack_from('<I',row,2)[0]*2048,
                                            struct.unpack_from('<I',row,10)[0])
            directory(pvd[156:190])
            offset, size = self.files['/SLUS_203.28']
            f.seek(offset)
            elf = f.read(size)
        if hashlib.sha256(elf).hexdigest() != ELF_SHA:
            raise ValueError('Unsupported Tekken 4 executable fingerprint')
        self.entries = list(struct.iter_unpack('<3I2h',elf[0x194380:0x194380+1122*16]))
        self.base, self.size = self.files['/TEKKEN/DATA.BIN']
        for i,(sector,size,checksum,ident,key) in enumerate(self.entries):
            if ident != i or key not in (-1,i):
                raise ValueError('Invalid resource identifier/key')
            if size != 0xffffffff and sector*2048+size > self.size:
                raise ValueError('Resource outside archive')

    def read(self, identifier):
        sector, size, checksum, ident, key = self.entries[identifier]
        if size in (0,0xffffffff):
            return b''
        with self.path.open('rb') as f:
            f.seek(self.base+sector*2048)
            data = bytearray(f.read(size))
        if len(data) != size:
            raise ValueError('Truncated resource')
        if key >= 0:
            words = np.frombuffer(data,'<u4',min(size//4,1024))
            words[:] = np.uint32(key-1)-words
        if int(np.frombuffer(data,'<u4',size//4).sum())&0xffffffff != checksum:
            raise ValueError('Resource checksum mismatch: '+str(identifier))
        return bytes(data)


def faces(positions, normals, primitive=4):
    n = len(positions)
    if primitive == 4:
        indices = [(i-2,i-1,i) if i%2==0 else (i-1,i-2,i) for i in range(2,n)]
    elif primitive == 3:
        indices = [(i,i+1,i+2) for i in range(0,n-2,3)]
    elif primitive == 5:
        indices = [(0,i-1,i) for i in range(2,n)]
    else:
        raise ValueError('Unsupported native primitive '+str(primitive))
    result = []
    for a,b,c in indices:
        normal = np.cross(positions[b]-positions[a],positions[c]-positions[a])
        if np.linalg.norm(normal)<1e-8:
            continue
        if np.dot(normal,normals[[a,b,c]].sum(0))<0:
            b,c = c,b
        result.append((a,b,c))
    return np.asarray(result,np.int32).reshape(-1,3)


def stage_draws(data, start=0, end=None):
    end = len(data) if end is None else end
    result = []
    off=start;tex0=None
    while off+28<end:
        cmd=data[off:off+4]
        if cmd[1:]==b'\xc0\x06\x6c':
            gs=data[off+4:off+100]
            tag,desc=struct.unpack_from('<2Q',gs)
            if tag!=0x4000000000000001 or desc&0xffff!=0xe68e:
                off+=4;continue
            tex0=struct.unpack_from('<Q',gs,48)[0]
            gif=struct.unpack_from('<Q',gs,80)[0]
            color=off+104
        elif cmd[1:]==b'\xc0\x01\x6c':
            gif,desc=struct.unpack_from('<2Q',data,off+4)
            if desc&0xfff!=0x412 or (gif>>60)&15!=3:
                off+=4;continue
            if tex0 is None:raise ValueError('Stage draw without material state')
            color=off+24
        else:
            off+=4;continue
        n, primitive = gif&32767, (gif>>47)&7
        if not 3<=n<=85:
            raise ValueError('Unsupported stage packet vertex count')
        if data[color-4:color] != b'\x04\x01\x00\x01' or data[color+2:color+4] != bytes([n,0x6e]):
            raise ValueError('Stage color stream mismatch')
        xyz = color+4+n*4+4
        if data[xyz-4:xyz] != b'\x04\x03\x00\x01' or data[xyz+2:xyz+4] != bytes([n*3,0x68]):
            raise ValueError('Stage interleaved stream mismatch')
        if xyz+4+n*36>end:
            raise ValueError('Truncated stage vertices')
        values = np.frombuffer(data,'<f4',n*9,xyz+4).reshape(n,9).copy()
        if not np.isfinite(values).all():
            raise ValueError('Nonfinite stage vertices')
        positions,normals = values[:,6:9],values[:,3:6]
        result.append({'tex0':tex0, 'offset':off,
                       'positions':positions, 'normals':normals, 'uv0':values[:,:2],
                       'colors':np.frombuffer(data,np.uint8,n*4,color+4).reshape(n,4).astype(np.float32)/128.,
                       'faces':faces(positions,normals,primitive)})
        off=xyz+4+n*36
    return result


def character_palettes(data, start, bone_count):
    mappings = {}
    chunk = start
    while chunk + 16 <= len(data):
        count, size, zero, zero2 = struct.unpack_from('<4I', data, chunk)
        tail = chunk + size
        end = tail + count * 16
        if not 0 < count < 10000 or size < 16 or zero or zero2 or end > len(data):
            raise ValueError('Invalid CHRTK4 DMA chunk')
        palette = []
        expected = None
        for offset in range(tail, end, 16):
            tag, address, kind, vif = struct.unpack_from('<4I', data, offset)
            if kind == 0x10000000:
                palette = []
                expected = address
            elif kind == 1:
                if tag != 0x30000004 or vif != 0x6c044000 or address >= bone_count:
                    raise ValueError('Invalid CHRTK4 matrix reference')
                palette.append(address)
            elif kind == 2:
                pool = chunk + address + 8
                if expected != len(palette) or pool < chunk + 16 or pool + 4 > tail:
                    raise ValueError('Invalid CHRTK4 pool palette')
                if data[pool:pool+2] != b'\x5e\x40' or data[pool+3] != 0x68:
                    raise ValueError('CHRTK4 DMA reference is not a vertex pool')
                if pool in mappings and mappings[pool] != palette:
                    raise ValueError('Conflicting CHRTK4 pool palettes')
                mappings[pool] = palette[:]
            elif kind != 4:
                raise ValueError('Unknown CHRTK4 DMA reference kind')
        chunk = end
    if chunk != len(data):
        raise ValueError('Truncated CHRTK4 DMA chunks')
    return mappings


def character_pose_helpers(bones):
    result = []
    for control in range(1, min(22, len(bones))):
        target = bones[control]
        for helper in range(27, min(55, len(bones))):
            source = bones[helper]
            if (source['parent'] == target['parent']
                    and np.linalg.norm(np.subtract(source['translation'], target['translation'])) < .3
                    and np.linalg.norm(np.subtract(source['rotation'], target['rotation'])) < .005):
                result.append({'bone':helper,'control':control})
    return result


def character_draws(data):
    if data[:16] != b'CHRTK4 \0  0.003\0':
        raise ValueError('Unsupported CHRTK4 version')
    nmain, nextra = struct.unpack_from('<2I',data,100)
    start = struct.unpack_from('<I',data,112)[0]+16
    bones = []
    for i in range(nmain+nextra):
        off = 0xe0+i*32
        parent = struct.unpack_from('<i',data,off)[0]
        values = struct.unpack_from('<6f',data,off+4)
        if parent>=nmain+nextra or parent==i or parent< -1 or not np.isfinite(values).all():
            raise ValueError('Invalid native skeleton')
        bones.append({'parent':parent,'translation':list(values[:3]),'rotation':list(values[3:])})
    for i in range(len(bones)):
        seen=set();parent=i
        while parent>=0:
            if parent in seen:raise ValueError('Cyclic native skeleton')
            seen.add(parent);parent=bones[parent]['parent']
    if 0xe0+32*len(bones)!=start-16:
        raise ValueError('CHRTK4 skeleton/geometry bounds mismatch')
    palettes = character_palettes(data, start, len(bones))
    used_pools = set()
    result = []
    pool = None
    tex0 = None
    off = start
    while off+4<len(data):
        cmd = data[off:off+4]
        if cmd[:2]==b'\x5e\x40' and cmd[3]==0x68:
            n = cmd[2] or 256
            p = off+4
            positions = np.frombuffer(data,'<f4',n*3,p).reshape(n,3).copy()
            streams = []
            p += n*12
            for address,stride,code,dtype,width in [(0x5f,16,0x6c,'<f4',4),(0x60,16,0x6c,'<f4',4),(0x61,8,0x6d,'<u2',4)]:
                if data[p:p+4]!=b'\x04\x01\0\x01' or data[p+4:p+8]!=bytes([address,0x40,cmd[2],code]):
                    raise ValueError('CHRTK4 pool stream mismatch at '+hex(p))
                p += 8
                streams.append(np.frombuffer(data,dtype,n*width,p).reshape(n,width).copy())
                p += n*stride
            normals,weights,indices = streams
            if not np.isfinite(positions).all() or not np.isfinite(normals).all() or not np.isfinite(weights).all():
                raise ValueError('Nonfinite character pool')
            if off not in palettes:
                raise ValueError('CHRTK4 vertex pool has no DMA palette')
            palette = palettes[off]
            active = weights > 0
            if (weights < 0).any() or not np.allclose(weights.sum(1),1,atol=.002):
                raise ValueError('Invalid character weights')
            if (indices[active] < 1).any() or (indices[active] > len(palette)).any():
                raise ValueError('Character matrix slot outside local palette')
            mapped = np.zeros_like(indices)
            mapped[active] = np.asarray(palette, np.uint16)[indices[active]-1]
            indices = mapped
            used_pools.add(off)
            pool = positions,normals[:,:3],weights,indices
            off = p
            continue
        if cmd[1:]==b'\xc0\x05\x6c':
            gs = data[off+4:off+84]
            tag,desc = struct.unpack_from('<2Q',gs)
            if tag!=0x4000000000000001 or desc&0xffff!=0xe68e:
                off += 4
                continue
            if pool is None:
                raise ValueError('Draw without vertex pool')
            tex0 = struct.unpack_from('<Q',gs,48)[0]
            off += 84
            continue
        if cmd[1:]==b'\xc0\x01\x6c' and off+24<len(data):
            gif,desc = struct.unpack_from('<2Q',data,off+4)
            if desc&0xfff!=0x412 or (gif>>60)&15!=3:
                off += 4
                continue
            if pool is None or tex0 is None:
                raise ValueError('Character draw without state/pool')
            n,primitive = gif&32767,(gif>>47)&7
            uv = off+24
            if not 3<=n<=255 or data[uv:uv+4]!=bytes([cmd[0]+1,0xc0,n,0x6c]):
                raise ValueError('CHRTK4 indexed UV layout mismatch')
            if uv+4+n*16>len(data):
                raise ValueError('Truncated character draw')
            texcoords = np.frombuffer(data,'<f4',n*4,uv+4).reshape(n,4)
            refs = np.frombuffer(data,'<u4',n*4,uv+4).reshape(n,4)[:,2]
            if (refs>=len(pool[0])).any():
                raise ValueError('Character index outside vertex pool')
            pos,normals,weights,indices = [a[refs] for a in pool]
            result.append({'tex0':tex0,'offset':off,'positions':pos,
                           'normals':normals,'uv0':texcoords[:,:2].copy(),'weights':weights,'indices':indices,
                           'faces':faces(pos,normals,primitive)})
            off = uv+4+n*16
            continue
        off += 4
    if not result:
        raise ValueError('No character draw packets')
    if used_pools != set(palettes):
        raise ValueError('CHRTK4 DMA/geometry pool coverage mismatch')
    if sum(len(p['faces']) for p in result)!=struct.unpack_from('<I',data,120)[0]:
        raise ValueError('Native character triangle count mismatch')
    if sum(len(p['positions']) for p in result)!=struct.unpack_from('<I',data,132)[0]:
        raise ValueError('Native character draw vertex count mismatch')
    return result,bones


def stage_model(data):
    n=struct.unpack_from('<I',data,124)[0]
    start,table=struct.unpack_from('<2I',data,128)
    if not 0<n<20000 or start+160*n>table or table+4*n>len(data):
        raise ValueError('Invalid MAPTK4 object table')
    offsets=list(struct.unpack_from('<%dI'%n,data,table))
    if any(o and (o<start+160*n or o>table or o%16) for o in offsets):
        raise ValueError('Invalid MAPTK4 geometry offset')
    bounds=sorted(set(o for o in offsets+[table] if o));ends=dict(zip(bounds,bounds[1:]))
    cache={};result=[]
    for i,off in enumerate(offsets):
        if not off or off==table:continue
        if off not in cache:cache[off]=stage_draws(data,off,ends[off])
        matrix=np.frombuffer(data,'<f4',16,start+i*160+16).reshape(4,4)
        if not np.isfinite(matrix).all():raise ValueError('Nonfinite stage object matrix')
        linear=matrix[:3,:3]
        if abs(np.linalg.det(linear))<1e-10:continue
        for draw in cache[off]:
            transformed=dict(draw)
            transformed['positions']=draw['positions']@linear+matrix[3,:3]
            normal=draw['normals']@np.linalg.inv(linear).T
            transformed['normals']=normal/np.maximum(np.linalg.norm(normal,axis=1,keepdims=True),1e-12)
            transformed['object']=i
            if np.linalg.det(linear)<0:transformed['faces']=draw['faces'][:,[0,2,1]]
            result.append(transformed)
    return result


class Export:
    def __init__(self, iso, root):
        self.archive=Archive(iso)
        self.root=Path(root).resolve()
        self.assets=self.root/'assets'
        self.assets.mkdir(parents=True,exist_ok=True)

    def meshes(self, model, bank, prefix, group, character=False):
        draws,bones=character_draws(model) if character else (stage_model(model),None)
        if not draws:raise ValueError('No geometry: '+prefix)
        memory=Memory().load_ngi(bank)
        grouped=defaultdict(list)
        for draw in draws:grouped[(draw.get('object',0),draw['tex0'])].append(draw)
        meshes=[];textures={}
        for (obj,tex0),parts in grouped.items():
            key=prefix+'_%016x'%tex0
            if key not in textures:
                image=memory.texture(tex0)
                png=self.assets/(key+'.png');image.save(png)
                textures[key]={'file':str(png),'faces':[str(png)],'width':image.width,
                               'height':image.height,'has_alpha':image.getextrema()[3][0]<255}
            meshkey=key if character else key+'_object_%04d'%obj
            values={};counts=np.cumsum([0]+[len(p['positions']) for p in parts])
            values['faces']=np.concatenate([p['faces']+counts[i] for i,p in enumerate(parts)])
            for name in ('positions','normals','uv0'):
                values[name]=np.concatenate([p[name] for p in parts])
            if character:
                values['bone_indices']=np.concatenate([p['indices'] for p in parts])
                values['bone_weights']=np.concatenate([p['weights'] for p in parts])
            else:values['colors']=np.concatenate([p['colors'] for p in parts])
            path=self.assets/(meshkey+'.mesh.npz');np.savez_compressed(path,**values)
            meshes.append({'id':meshkey,'name':prefix+' object '+str(obj)+' material '+('%016x'%tex0),'file':str(path),
                           'textures':[key],'group':group,'kind':'character' if character else 'stage',
                           'vertices':len(values['positions']),'triangles':len(values['faces']),
                           'vertex_color_modulate':not character,'native_draw_count':len(parts)})
        return meshes,textures,bones

    def prepare(self, identifier, part=None):
        raw=self.archive.read(identifier);parts=pack(raw)
        character=part is not None
        name=('Character_%04d_%d'%(identifier,part)) if character else ('Stage_%02d'%((identifier-995)//4))
        folder=self.root/name;folder.mkdir(exist_ok=True)
        (folder/'native_package.bin').write_bytes(raw)
        meshes=[];textures={};static_skins=[];metadata={}
        if character:
            model,bank=parts[part+3],parts[part]
            added,tex,bones=self.meshes(model,bank,name,0,True)
            meshes.extend(added);textures.update(tex)
            bone={'count':len(bones),'parents':[b['parent'] for b in bones],
                  'translations':[b['translation'] for b in bones],'rotations':[b['rotation'] for b in bones]}
            static_skins.append({'name':name+' skeleton','bone':bone,'meshes':[m['id'] for m in meshes],
                                 'pose_helper_links':character_pose_helpers(bones)})
            camera={'location':[3,-4,1.5],'target':[0,0,0],'lens':40}
            limits=['Modelo CHRTK4, UVs e texturas GS; esqueleto e pesos nativos em pose de repouso.',
                    'Índices de skin resolvidos pelas paletas DMA locais de cada pool de vértices.',
                    'Helpers coincidentes seguem a rotação da articulação no Blender; isso aproxima o comportamento procedural do motor.',
                    'Animações de golpes e simulação de cabelo/roupa não convertidas.',
                    'Nomes provisórios usam o ID do recurso e da variante; não representam personagens adicionais.']
        else:
            banks,models=pack(parts[7]),pack(parts[8])
            for group,(model,bank) in enumerate(zip(models,banks)):
                if not model:continue
                if not model.startswith(b'MAPTK4 \0  0.015\0'):raise ValueError('Unsupported stage model')
                added,tex,_=self.meshes(model,bank,name+'_G'+str(group),group)
                meshes.extend(added);textures.update(tex)
                n=struct.unpack_from('<I',model,124)[0]
                offset=struct.unpack_from('<I',model,128)[0]
                table=struct.unpack_from('<I',model,132)[0]
                if offset+160*n>len(model) or table+4*n>len(model):raise ValueError('Invalid native object table')
                metadata[str(group)]={'object_count':n,'records_offset':offset,'geometry_index_offset':table,
                                      'geometry_offsets':list(struct.unpack_from('<%dI'%n,model,table))}
            camera={'location':[30,-50,35],'target':[0,0,1],'lens':28}
            limits=['Geometria MAPTK4, matrizes e instâncias dos objetos, UVs, cores de vértice e atlas GS nativos em repouso.',
                    'Pacotes principais de cenário preservados por grupo; modelos auxiliares, colisores e animações não montados.',
                    'Partículas, iluminação e shaders do motor não são reproduzidos.']
        manifest={'version':2,'source':'Tekken 4 PS2 USA','stage':identifier,'name':name,'blender':'2.79b',
                  'scale':.001,'meshes':meshes,'textures':textures,'skins':[],'static_skins':static_skins,
                  'crowd_models':[],'actors':[],'alo_graphs':[],'errors':[],'hidden_groups':[],
                  'two_sided_preview':True,'preview_camera':camera,'limits':limits,
                  'native_resource':identifier,'native_model_part':part,'native_object_metadata':metadata,
                  'skin_weight_mapping':'CHRTK4_DMA_palette_v2' if character else None,
                  'resources':[{'iso':str(self.archive.path),'catalog_id':identifier,'sha256':hashlib.sha256(raw).hexdigest()}]}
        path=folder/'scene.json';path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
        print('PREPARED',name,len(meshes),'materials',flush=True)
        return path

    def convert(self,path):
        with (path.parent/'blender_export.log').open('w',encoding='utf8') as log:
            result=subprocess.run([str(REPO/'out/tools/blender279/blender-2.79b-windows64/blender.exe'),
                  '--background','--factory-startup','--threads','4','--python-exit-code','1',
                  '--python',str(REPO/'tools/stages/blender279_scene.py'),'--',str(path)],
                  stdout=log,stderr=subprocess.STDOUT)
        if result.returncode:raise ValueError('Blender failed; see '+str(path.parent/'blender_export.log'))
        report=json.loads((path.parent/'export_report.json').read_text(encoding='utf8'))
        if report['errors']:raise ValueError('Blender conversion issues: '+str(report['errors']))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--iso',required=True)
    parser.add_argument('--out',required=True)
    parser.add_argument('--resource',type=int)
    parser.add_argument('--part',type=int)
    parser.add_argument('--all',action='store_true')
    parser.add_argument('--resume',action='store_true')
    parser.add_argument('--prepare-only',action='store_true')
    args=parser.parse_args()
    export=Export(args.iso,args.out)
    if args.resource is not None:
        path=export.prepare(args.resource,args.part)
        if not args.prepare_only:export.convert(path)
        return
    if not args.all:
        print('Validated catalogue:',len(export.archive.entries),'resources');return
    requests=[(i,None) for i in range(995,1060,4)]
    seen=set();duplicates=[]
    for ident in range(294,890):
        row=export.archive.entries[ident]
        if not 16<=row[1]<16000000:continue
        raw=export.archive.read(ident)
        try:parts=pack(raw)
        except ValueError:continue
        if len(parts)!=17:continue
        for part in range(3):
            if not parts[part+3].startswith(b'CHRTK4'):continue
            key=hashlib.sha256(parts[part]+parts[part+3]).hexdigest()
            if key in seen:duplicates.append({'resource':ident,'part':part,'sha256':key});continue
            seen.add(key);requests.append((ident,part))
    scenes=[];failures=[]
    for ident,part in requests:
        name=('Character_%04d_%d'%(ident,part)) if part is not None else ('Stage_%02d'%((ident-995)//4))
        path=export.root/name/'scene.json'
        try:
            if not args.resume or not path.is_file():path=export.prepare(ident,part)
            if not args.prepare_only and not (args.resume and list(path.parent.glob('*.blend'))):export.convert(path)
            scenes.append(str(path))
        except Exception as exc:
            failures.append({'resource':ident,'part':part,'reason':str(exc)});print('FAILED',ident,part,str(exc),flush=True)
    (export.root/'export_index.json').write_text(json.dumps({'scenes':scenes,'failures':failures,'duplicates':duplicates},indent=2),encoding='utf8')
    print('FINISHED',len(scenes),'scenes',len(failures),'failures',flush=True)
    if failures:raise SystemExit(1)


if __name__=='__main__':main()
