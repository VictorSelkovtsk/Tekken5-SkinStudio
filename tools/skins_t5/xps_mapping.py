import re
import numpy as np
from .facial import native_face
from .rig import finger_profile,hair_chains

def normalized(name):
    return re.sub(r'\s+',' ',re.sub(r'[_:.\-]+',' ',name.lower())).strip()

def suggest(source,target,sp,tp,settings):
    bones=source['bones'];names=[normalized(b['name']) for b in bones];mapping={};audit={}
    face=native_face(target);fingers=finger_profile(target)
    def setbone(i,j,reason,confidence='alta'):
        if j>=len(target):return
        mapping[i]=j;audit[i]=dict(reason=reason,confidence=confidence)
    def pair(i,left,right):
        if max(left,right)>=len(target):return min(left,right)
        d=np.linalg.norm(tp[[left,right]]-sp[i],axis=1)
        if abs(d[0]-d[1])<1e-4:return right if 'right' in names[i].split() else left
        return (left,right)[int(d.argmin())]
    central={'root ground':0,'root':0,'root hips':1,'hips':1,'pelvis':1,'spine lower':2,'spine middle':3,
             'spine upper':5,'chest':5,'neck':5,'head neck lower':5,'head':6,'head neck upper':6}
    limb=[(r'shoulder 1|collar|clavicle',7,11),(r'shoulder 2|upper arm|upperarm',8,12),
          (r'elbow|forearm|lower arm',9,13),(r'wrist|hand',10,14),(r'thigh|upper leg',15,18),
          (r'knee|calf|lower leg',16,19),(r'ankle|foot',17,20),(r'toes|toe',21,22)]
    for i,n in enumerate(names):
        if n in central:setbone(i,central[n],'Nome anatômico');continue
        if not re.search(r'finger|thumb|index|middle|ring|pinky|little|weapon',n):
            for pattern,l,r in limb:
                if re.search(r'\b('+pattern+r')\b',n):
                    setbone(i,pair(i,l,r),'Articulação e lado espacial');break
        if i in mapping:continue
        if face and n.startswith('head '):
            j=None
            if 'jaw' in n:j=85
            elif 'tongue' in n:j=91 if re.search(r'\b2\b|tip',n) else 90
            elif 'lip' in n:
                if 'corner' in n:j=pair(i,87,89)
                elif 'lower' in n:j=85 if 'middle' in n or 'center' in n else pair(i,86,88)
                elif 'upper' in n:j=92 if 'middle' in n or 'center' in n else pair(i,96,105)
            elif 'eyelid' in n:j=pair(i,97,106) if 'lower' in n else pair(i,98,107)
            elif 'eyeball' in n or re.search(r'\beye\b',n):j=pair(i,100,109)
            elif 'eyebrow' in n:j=pair(i,101,110) if re.search(r'\b1\b|inner',n) else pair(i,99,108)
            elif 'cheek' in n:j=pair(i,94,103)
            elif 'nose' in n:
                if 'left' in n or 'right' in n:j=pair(i,93,102)
                else:setbone(i,6,'Nariz central sem equivalente direto: acompanha a cabeça','revisar');continue
            if j is not None:setbone(i,j,'Controle facial por nome e lado espacial');continue
        if 'breast' in n or 'bust' in n:setbone(i,5,'Sem dinâmica equivalente confirmada: acompanha o peito','revisar')
    def ancestor(i):
        seen={i};p=bones[i]['parent']
        while 0<=p<len(bones) and p not in seen:
            if p in mapping:return p
            seen.add(p);p=bones[p]['parent']
        return None
    for i,n in enumerate(names):
        match=re.search(r'finger\s*([1-5])\s*([abc])\b',n)
        named=re.search(r'\b(thumb|index|middle|ring|pinky|little)\s*(?:finger\s*)?([123])\b',n)
        if match:finger=int(match[1])-1;segment='abc'.index(match[2])
        elif named:finger={'thumb':0,'index':1,'middle':2,'ring':3,'pinky':4,'little':4}[named[1]];segment=int(named[2])-1
        else:continue
        p=ancestor(i)
        while p is not None and mapping[p] not in (10,14):p=ancestor(p)
        hand=mapping[p] if p is not None else pair(i,10,14)
        if fingers:setbone(i,(55 if hand==10 else 70)+finger*3+segment,'Dedo/falange pelo nome; lado herdado da mão')
        else:setbone(i,hand,'Destino sem perfil de dedos reconhecido: acompanha a mão','revisar')
    pending=set(range(len(bones)))-mapping.keys()
    while pending:
        progressed=False
        for i in sorted(pending):
            p=bones[i]['parent']
            if p in pending:continue
            if p in mapping:setbone(i,mapping[p],'Acompanha o ancestral '+bones[p]['name'],'revisar')
            else:
                ids=[j for j in range(min(23,len(target))) if j not in (0,4)] or [0]
                setbone(i,ids[int(np.linalg.norm(tp[ids]-sp[i],axis=1).argmin())],'Proximidade restrita ao corpo; nome não reconhecido','revisar')
            pending.remove(i);progressed=True
        if not progressed:
            for i in pending:setbone(i,0,'Hierarquia não reconhecida','revisar')
            break
    if settings.get('reuse_hair',False):
        candidates=hair_chains(target)
        roots=[i for i,n in enumerate(names) if 'ponytail' in n and (bones[i]['parent']<0 or 'ponytail' not in names[bones[i]['parent']])]
        for root in roots:
            chain=[root]
            while True:
                children=[i for i,b in enumerate(bones) if b['parent']==chain[-1] and 'ponytail' in names[i]]
                if len(children)!=1:break
                chain.append(children[0])
            if not candidates:continue
            dst=min(candidates,key=lambda c:np.linalg.norm(tp[c[0]]-sp[root]))
            for order,i in enumerate(chain):
                at=int(np.floor(order*len(dst)/len(chain)))
                setbone(i,dst[min(at,len(dst)-1)],'Cadeia auxiliar atrás da cabeça; ordem preservada, física a validar','revisar')
    for i,j in settings.get('mapping',{}).items():
        i,j=int(i),int(j)
        if 0<=i<len(bones):mapping[i]=j;audit[i]=dict(reason='Associação manual',confidence='manual')
    return mapping,audit
