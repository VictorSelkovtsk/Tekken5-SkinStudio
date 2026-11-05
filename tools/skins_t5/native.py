from pathlib import Path
import json,struct
import numpy as np
from PIL import Image
from tools.stages.container import pack,mif
from .convert import skeleton


def pictures(bank):
    if bank[:4]!=b'TIM2':raise ValueError('Banco TIM2 inválido')
    offset=16
    for _ in range(struct.unpack_from('<H',bank,6)[0]):
        total,clut,pixels,header,colors,fmt,mips,ct,it,w,h=struct.unpack_from('<IIIHHBBBBHH',bank,offset)
        if total<header+clut+pixels or offset+total>len(bank):raise ValueError('TIM2 truncado')
        loc=bank.find(b'GIDX',offset,offset+header)
        if loc>=0:
            yield struct.unpack_from('<I',bank,loc+8)[0],dict(offset=offset,header=header,pixels=pixels,
                colors=colors,ct=ct,it=it,width=w,height=h,format=fmt)
        offset+=total


def texture(bank,p):
    offset=p['offset']+p['header'];w,h=p['width'],p['height']
    raw=np.frombuffer(bank,np.uint8,p['pixels'],offset)
    if p['it'] in (4,5):
        channels={1:2,2:3,3:4}.get(p['ct']&63)
        if channels not in (3,4):raise ValueError('Paleta TIM2 não suportada')
        palette=np.full((p['colors'],4),255,np.uint8)
        palette[:,:channels]=np.frombuffer(bank,np.uint8,p['colors']*channels,offset+p['pixels']).reshape(-1,channels)
        if channels==4:palette[:,3]=np.minimum(255,palette[:,3].astype(np.uint16)*255//128)
        if p['colors']==256 and not p['format']&1:
            order=np.arange(256);palette=palette[(order&~24)|((order&8)<<1)|((order&16)>>1)]
        ids=raw if p['it']==5 else np.column_stack((raw&15,raw>>4)).ravel()
        image=palette[ids[:w*h]].reshape(h,w,4)
    elif p['it'] in (2,3):
        channels=3 if p['it']==2 else 4
        image=np.full((h,w,4),255,np.uint8);image[:,:,:channels]=raw[:w*h*channels].reshape(h,w,channels)
        if channels==4:image[:,:,3]=np.minimum(255,image[:,:,3].astype(np.uint16)*255//128)
    else:raise ValueError('Formato TIM2 não suportado: '+str(p['it']))
    return Image.fromarray(image)


def packet_meshes(packet,palette):
    at=0;cl=wl=1;values={};adc=[]
    def finish():
        if not values:return None
        if not all(k in values for k in (1,4,204,205)):raise ValueError('Streams nativos incompletos')
        pos,uv,weights,encoded=[values[k] for k in (1,4,204,205)]
        norm=values.get(2,np.zeros_like(pos))
        n=len(pos)
        if pos.shape!=(n,3) or norm.shape!=(n,3) or uv.shape!=(n,2) or weights.shape!=(n,4) or encoded.shape!=(n,4):
            raise ValueError('Formato de vértice nativo não suportado')
        active=weights>0;slots=encoded.astype(np.int32)//7
        if (encoded[active]%7).any() or (slots[active]>=len(palette)).any():raise ValueError('Paleta nativa inválida')
        ids=np.zeros_like(slots);ids[active]=np.asarray(palette)[slots[active]]
        if (ids[active]==255).any() or not np.allclose(weights.sum(1),1,atol=.003):raise ValueError('Pesos nativos inválidos')
        cut=np.zeros(n,bool);cut[:2]=True
        for begin,count in adc:cut[max(0,begin):min(n,begin+count)]=True
        faces=[]
        for i in range(2,n):
            if not cut[i] and np.linalg.norm(np.cross(pos[i-1]-pos[i-2],pos[i]-pos[i-2]))>1e-8:
                face=[i-2,i-1,i] if i%2==0 else [i-1,i-2,i]
                if np.dot(np.cross(pos[face[1]]-pos[face[0]],pos[face[2]]-pos[face[0]]),norm[face].sum(0))<0:face[0],face[1]=face[1],face[0]
                faces.append(face)
        if 2 not in values:
            for face in faces:
                normal=np.cross(pos[face[1]]-pos[face[0]],pos[face[2]]-pos[face[0]])
                for vertex in face:norm[vertex]+=normal
            lengths=np.linalg.norm(norm,axis=1)
            norm[lengths>0]/=lengths[lengths>0,None]
            norm[lengths==0]=[0,1,0]
        return dict(positions=pos,normals=norm,uv0=uv,weights=weights,indices=ids,faces=np.asarray(faces,np.int32).reshape(-1,3))
    while at+4<=len(packet):
        word=struct.unpack_from('<I',packet,at)[0];at+=4;cmd=(word>>24)&127
        if cmd==1:cl=word&255;wl=(word>>8)&255 or 256
        elif 0x60<=cmd<=0x7f:
            count=(word>>16)&255 or 256;dims=((cmd>>2)&3)+1;bits=(32,16,8,5)[cmd&3];addr=word&1023
            consumed=count if wl<=cl else count//wl*cl+min(count%wl,cl)
            if bits==5:raise ValueError('VIF V4-5 não suportado')
            size=consumed*dims*bits//8
            if at+size>len(packet):raise ValueError('VIF truncado')
            if consumed and addr in (1,2,4,204,205):
                values[addr]=np.frombuffer(packet,{32:'<f4',16:'<u2',8:'u1'}[bits],consumed*dims,at).reshape(consumed,dims).copy()
            elif cmd==0x70 and not consumed:adc.append(((addr-1)//5,(count+4)//5))
            at+=(size+3)//4*4
        elif cmd==0x20:at+=4
        elif cmd in (0x30,0x31):at+=16
        elif cmd in (0x14,0x15,0x17):
            mesh=finish()
            if mesh is not None:yield mesh
            values={};adc=[]
        elif cmd not in (0,2,3,4,5,6,7,0x10,0x11,0x13):raise ValueError('Comando VIF não suportado: %02x'%cmd)
    if values:
        mesh=finish()
        if mesh is not None:yield mesh


def export_reference(package,folder):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    parts=pack(package);nud=parts[2];count=struct.unpack_from('<H',nud,10)[0]
    names=mif(parts[4],count);textures=dict(pictures(parts[1]));images={};meshes=[];off=32
    for obj in range(count):
        name=names[obj][0];draws=struct.unpack_from('<H',nud,off+4)[0]
        for j in range(draws):
            sub=off+24+40*j;tid,gs,mat,flags,start=struct.unpack_from('<5I',nud,sub)
            size=struct.unpack_from('<H',nud,sub+20)[0]*16
            if start+size>len(nud):raise ValueError('Pacote NUDP truncado')
            if tid not in images:
                path=folder/('t5_%08x.png'%tid);texture(parts[1],textures[tid]).save(path);images[tid]=str(path)
            for mesh in packet_meshes(nud[start:start+size],list(nud[sub+30:sub+40])):
                if not len(mesh['faces']):continue
                mesh={k:v.tolist() for k,v in mesh.items()}
                mesh.update(name='T5 %03d · %s'%(obj,name),texture=images[tid],alpha='texture',object_id=obj,flags=flags)
                meshes.append(mesh)
        off+=24+40*draws
    merged={}
    for mesh in meshes:
        key=(mesh['object_id'],mesh['texture'],mesh['flags'])
        target=merged.setdefault(key,dict(name=mesh['name'],texture=mesh['texture'],alpha=mesh['alpha'],object_id=mesh['object_id'],
            flags=mesh['flags'],positions=[],normals=[],uv0=[],weights=[],indices=[],faces=[]))
        offset=len(target['positions'])
        target['faces'].extend([[i+offset for i in face] for face in mesh['faces']])
        for field in ('positions','normals','uv0','weights','indices'):target[field].extend(mesh[field])
    meshes=list(merged.values())
    body_ids={m['object_id'] for m in meshes if names[m['object_id']][0].upper().startswith('MODEL')}
    if not body_ids and meshes:
        counts={}
        for mesh in meshes:counts[mesh['object_id']]=counts.get(mesh['object_id'],0)+len(mesh['faces'])
        body_ids={max(counts,key=counts.get)}
    for mesh in meshes:mesh['base_body']=mesh['object_id'] in body_ids
    data=dict(version=2,bones=skeleton(package),meshes=meshes)
    path=folder/'base_t5.json';path.write_text(json.dumps(data,ensure_ascii=False),encoding='utf8')
    return str(path)


if __name__=='__main__':
    import argparse
    from .game import Archive
    parser=argparse.ArgumentParser();parser.add_argument('--config',required=True);parser.add_argument('--base',type=int,required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args()
    if not 0<=args.base<79:raise ValueError('Base T5 inválida')
    config=json.loads(Path(args.config).read_text(encoding='utf8'))
    print(export_reference(Archive(config['iso']).read(240+11*args.base),args.output))
