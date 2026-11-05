import math,re,struct
import numpy as np
from tools.stages.container import pack,mif
from .sources import worlds
from .facial import NAMES,native_face
from .physics import physics

BODY={0:'raiz',1:'pelve',2:'coluna inferior',3:'coluna média',4:'quadril',5:'peito',6:'cabeça / pescoço',
      7:'clavícula E',8:'braço E',9:'antebraço E',10:'mão E',11:'clavícula D',12:'braço D',13:'antebraço D',14:'mão D',
      15:'coxa E',16:'joelho E',17:'tornozelo E',18:'coxa D',19:'joelho D',20:'tornozelo D',21:'dedos do pé E',22:'dedos do pé D'}
FINGERS=('polegar','indicador','médio','anelar','mínimo')

def finger_profile(bones):
    return len(bones)>84 and all(bones[start+3*f+j]['parent']==(hand if j==0 else start+3*f+j-1)
        for start,hand in ((55,10),(70,14)) for f in range(5) for j in range(3))

def native_usage(package):
    parts=pack(package);nud=parts[2];count=struct.unpack_from('<H',nud,10)[0]
    names=mif(parts[4],count);at=32;usage={}
    for obj in range(count):
        draws=struct.unpack_from('<H',nud,at+4)[0]
        for j in range(draws):
            sub=at+24+40*j
            for bone in nud[sub+30:sub+40]:
                if bone!=255:usage.setdefault(bone,set()).add(names[obj][0])
        at+=24+draws*40
    return {i:sorted(v) for i,v in usage.items()}

def describe(bones,package):
    usage=native_usage(package);positions=worlds(bones)[:,:3,3]
    try:dynamics=physics(package,len(bones))
    except ValueError as error:dynamics=dict(colliders=[],joints={},status='unknown',note=str(error))
    fingers=finger_profile(bones);face=native_face(bones)
    for i,b in enumerate(bones):
        name=BODY.get(i);category='corpo';evidence='Perfil anatômico T5'
        if fingers and 55<=i<=84:
            j=(i-55)%15;name='%s %s · falange %d'%(FINGERS[j//3],'E' if i<70 else 'D',j%3+1);category='dedos'
        elif face and i in NAMES:name=NAMES[i];category='face'
        elif name is None:
            category='auxiliar';parent=b['parent'];seen={i}
            while parent>=0 and parent not in BODY and parent not in seen:
                seen.add(parent);parent=bones[parent]['parent']
            region=BODY.get(parent,'raiz');objects=usage.get(i,[]);joined=' '.join(objects).lower()
            if re.search(r'kami|hair|mitusaki|insage',joined):name='cabelo / adorno de cabelo'
            elif 'ear' in joined:name='adorno da orelha'
            elif 'boots' in joined:name='adorno da bota'
            elif 'nekles' in joined:name='colar'
            elif i>110 and parent==6 and positions[i,2]<positions[6,2]-30:name='cadeia atrás da cabeça'
            else:name='auxiliar de '+region
            evidence='Região inferida por hierarquia/posição e nomes das peças; '+('física não confirmada' if dynamics['status']=='unknown' else 'sem registro de física no bloco MOP')
        b.update(label='%03d · %s'%(i,name),category=category,native_objects=usage.get(i,[]),evidence=evidence,physics=None)
    for i,joint in dynamics['joints'].items():
        colliders=[c['bone'] for c in (dynamics['colliders'][k] for k in joint['colliders']) if c['bone']<len(bones)]
        limits=[round(math.degrees(x)) for x in joint['limits']];names=[]
        for c in colliders:
            if bones[c]['label'][6:] not in names:names.append(bones[c]['label'][6:])
        bones[i]['physics']=dict(stiffness=round(joint['stiffness'],2),damping=round(joint['damping'],3),limits=limits,
                                 radius=round(joint['radius'],2),colliders=sorted(set(colliders)))
        number=lambda x:('%g'%x).replace('.',',')
        angles=('limites %d…%d° e %d…%d°'%(limits[1],limits[0],limits[3],limits[2])) if any(limits) else 'sem limite de ângulo'
        bones[i]['evidence']=' · '.join(['Simulado pelo jogo (bloco MOP do traje)','rigidez '+number(round(joint['stiffness'],2)),
                                         'amortecimento '+number(round(joint['damping'],3)),angles,
                                         'colide com '+', '.join(names) if names else 'sem colisores'])
    return bones

def hair_chains(bones):
    if len(bones)<=111:return []
    points=worlds(bones)[:,:3,3];children={i:[] for i in range(len(bones))}
    for i,b in enumerate(bones):
        if b['parent']>=0:children[b['parent']].append(i)
    result=[]
    for i in range(111,len(bones)):
        if bones[i]['parent']!=6 or points[i,2]>=points[6,2]-30:continue
        chain=[i]
        while len(children[chain[-1]])==1:
            child=children[chain[-1]][0]
            if child<=110:break
            chain.append(child)
        if len(chain)>=3:result.append(chain)
    return result
