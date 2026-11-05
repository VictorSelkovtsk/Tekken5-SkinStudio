from pathlib import Path
import hashlib
import numpy as np
from tools.stages.container import pack
from tools.stages.tekken4 import stage_draws
from tools.stages.ps2gs import Memory


def append_cloth(raw,body,cache):
    parts=pack(raw)
    if len(parts)<=13 or not parts[12]:return 0
    data=parts[12]
    if data[:4]!=b'CLT\0' or data[8:14]!=b'TK4002':raise ValueError('Versão CLT T4 não suportada')
    cloth=stage_draws(data)
    if not cloth:raise ValueError('Bloco CLT presente, mas sem geometria legível')
    banks=pack(parts[13]);bank=banks[2] if len(banks)>2 and banks[2] else banks[0]
    memory=Memory().load_ngi(bank)
    folder=Path(cache)/hashlib.sha256(bank).hexdigest()[:24];folder.mkdir(parents=True,exist_ok=True)
    pos=np.concatenate([m['positions'] for m in body]);weights=np.concatenate([m['weights'] for m in body]);ids=np.concatenate([m['indices'] for m in body])
    _,unique=np.unique(np.round(pos,4),axis=0,return_index=True);pos=pos[unique];weights=weights[unique];ids=ids[unique]
    textures={}
    for mesh in cloth:
        mesh['positions']=mesh['positions'].copy()-np.array([0,1127,0],np.float32)
        n=len(mesh['positions']);target_weights=np.zeros((n,4),np.float32);target_ids=np.zeros((n,4),np.int32)
        for v,p in enumerate(mesh['positions']):
            distance=np.sum((pos-p)**2,axis=1);nearest=np.argsort(distance)[:4]
            factor=1/np.maximum(distance[nearest],.01);factor/=factor.sum();combined={}
            for idx,f in zip(nearest,factor):
                for bone,weight in zip(ids[idx],weights[idx]):
                    if weight>0:combined[int(bone)]=combined.get(int(bone),0)+float(f*weight)
            selected=sorted(combined.items(),key=lambda item:-item[1])[:4];total=sum(w for _,w in selected)
            for slot,(bone,weight) in enumerate(selected):target_ids[v,slot]=bone;target_weights[v,slot]=weight/total
        mesh['weights']=target_weights;mesh['indices']=target_ids
        tex0=mesh['tex0']
        if tex0 not in textures:
            path=folder/('%016x.png'%tex0);memory.texture(tex0).save(path,format='PNG');textures[tex0]=str(path)
        mesh.update(texture=textures[tex0],material_id='t4-cloth:'+folder.name+':%016x'%tex0,
                    name='T4 tecido CLT · %016x'%tex0,alpha='texture',cloth=True)
    body.extend(cloth)
    return sum(len(m['faces']) for m in cloth)
