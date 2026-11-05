import numpy as np

TAG_FACE={7:85,8:96,9:105,10:85,11:87,12:89,13:90,14:91,
          15:94,16:103,17:93,18:102,19:101,20:110,21:100,22:109,
          23:99,24:108,25:98,26:107,27:97,28:106}
NAMES={85:'mandíbula',86:'lábio inferior E',87:'canto da boca E',
       88:'lábio inferior D',89:'canto da boca D',90:'língua',91:'ponta da língua',
       92:'lábio superior central',93:'nariz E',94:'bochecha E',95:'bochecha alta E',
       96:'lábio superior E',97:'pálpebra inferior E',98:'pálpebra superior E',
       99:'sobrancelha externa E',100:'olho E',101:'sobrancelha interna E',
       102:'nariz D',103:'bochecha D',104:'bochecha alta D',105:'lábio superior D',
       106:'pálpebra inferior D',107:'pálpebra superior D',108:'sobrancelha externa D',
       109:'olho D',110:'sobrancelha interna D'}

def native_face(bones):
    return (len(bones)>110 and bones[85]['parent']==6 and
            all(bones[i]['parent']==85 for i in (86,87,88,89,90)) and
            bones[91]['parent']==90 and all(bones[i]['parent']==6 for i in range(92,111)))

def tag_face(source,target,settings):
    bones=source['bones']
    return (source['kind']=='taghd' and settings.get('facial',True) and native_face(target)
            and len(bones)>=98 and bones[29]['parent']==2 and bones[7]['parent']==6
            and bones[10]['parent']==7 and bones[21]['parent']==6)

def split_lower_lip(meshes,mapping,source,target,source_id=10):
    if mapping[source_id]!=85:return
    left,right=len(source['bones']),len(source['bones'])+1
    mapping[left]=86;mapping[right]=88
    points=[m['positions'][(m['indices']==source_id).any(1)] for m in meshes]
    points=np.concatenate([p for p in points if len(p)]) if any(len(p) for p in points) else None
    if points is None:return
    center=(points[:,0].min()+points[:,0].max())*.5
    width=max((points[:,0].max()-points[:,0].min())*.25,1e-5)
    for mesh in meshes:
        for v in np.flatnonzero(((mesh['indices']==source_id)&(mesh['weights']>0)).any(1)):
            blend=float(np.clip(.5+(mesh['positions'][v,0]-center)/(2*width),0,1));merged={}
            for bone,weight in zip(mesh['indices'][v],mesh['weights'][v]):
                if weight<=0:continue
                pairs=((left,weight*(1-blend)),(right,weight*blend)) if bone==source_id else ((int(bone),weight),)
                for index,value in pairs:
                    if value>0:merged[index]=merged.get(index,0)+value
            if len(merged)>4:
                merged={}
                for bone,weight in zip(mesh['indices'][v],mesh['weights'][v]):
                    if weight<=0:continue
                    index=(left if blend<.5 else right) if bone==source_id else int(bone)
                    merged[index]=merged.get(index,0)+weight
            values=sorted(merged.items(),key=lambda item:-item[1]);total=sum(w for _,w in values)
            mesh['indices'][v]=[i for i,_ in values]+[0]*(4-len(values))
            mesh['weights'][v]=[w/total for _,w in values]+[0]*(4-len(values))
