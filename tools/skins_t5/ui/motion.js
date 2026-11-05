const DEG=Math.PI/180;
function rotation(axis,angle){
  const c=Math.cos(angle),s=Math.sin(angle);
  if(axis==='x')return [1,0,0,0,c,-s,0,s,c];
  if(axis==='y')return [c,0,s,0,1,0,-s,0,c];
  return [c,-s,0,s,c,0,0,0,1];
}
function axisRotation(axis,angle){
  const [x,y,z]=axis,c=Math.cos(angle),s=Math.sin(angle),t=1-c;
  return [c+x*x*t,x*y*t-z*s,x*z*t+y*s,y*x*t+z*s,c+y*y*t,y*z*t-x*s,z*x*t-y*s,z*y*t+x*s,c+z*z*t];
}
function multiply(a,b){
  const r=new Array(9);
  for(let i=0;i<3;i++)for(let j=0;j<3;j++)r[i*3+j]=a[i*3]*b[j]+a[i*3+1]*b[3+j]+a[i*3+2]*b[6+j];
  return r;
}
function apply(m,v){return [m[0]*v[0]+m[1]*v[1]+m[2]*v[2],m[3]*v[0]+m[4]*v[1]+m[5]*v[2],m[6]*v[0]+m[7]*v[1]+m[8]*v[2]];}
function walkJoints(bones,phase,swing){
  const joints={},side=(arm,hand)=>Math.sign(bones[hand].position[0]-bones[arm].position[0])||1;
  const set=(id,matrix,offset)=>{if(bones[id])joints[id]={rotation:matrix,offset:offset||[0,0,0]};};
  set(1,rotation('y',5*DEG*Math.sin(phase)),[12*Math.sin(phase),27*Math.cos(2*phase)-27,0]);
  set(3,rotation('y',-8*DEG*Math.sin(phase)));
  for(const [thigh,knee,ankle,offset] of [[15,16,17,0],[18,19,20,Math.PI]]){
    const s=phase+offset,hip=-22*DEG*Math.sin(s),bend=(6+50*Math.max(0,Math.cos(s))**1.5)*DEG;
    set(thigh,rotation('x',hip));set(knee,rotation('x',bend));set(ankle,rotation('x',-.6*(hip+bend)));
  }
  for(const [arm,forearm,hand,offset] of [[8,9,10,0],[12,13,14,Math.PI]]){
    if(!bones[hand])continue;const sign=-side(arm,hand);
    set(arm,multiply(rotation('x',22*DEG*Math.sin(phase+offset)),rotation('z',sign*72*DEG)));
    set(forearm,rotation('y',sign*(18+8*Math.sin(phase+offset))*DEG));
  }
  if(swing){
    const next=new Map();
    for(const b of bones)if(b.physics&&bones[b.parent]?.physics&&!next.has(b.parent))next.set(b.parent,b.id);
    for(const b of bones){
      if(!b.physics)continue;let depth=0;
      for(let p=b.parent;p>=0&&bones[p]?.physics;p=bones[p].parent)depth++;
      const limit=Math.max(...b.physics.limits.map(Math.abs)),amount=Math.min(limit||12,18)*DEG;
      let matrix=multiply(rotation('x',amount*Math.sin(2*phase-.7*(depth+1))),rotation('z',.4*amount*Math.sin(phase-.7*depth)));
      let end=b.id;while(depth===0&&next.has(end))end=next.get(end);
      if(end!==b.id){
        const d=[0,1,2].map(i=>bones[end].position[i]-b.position[i]),length=Math.hypot(...d),axis=[d[2],0,-d[0]],size=Math.hypot(...axis);
        const angle=Math.min(.9*Math.acos(Math.max(-1,Math.min(1,-d[1]/length))),limit?limit*DEG:Math.PI);
        if(size>1e-6)matrix=multiply(matrix,axisRotation(axis.map(x=>x/size),angle));
      }
      set(b.id,matrix);
    }
  }
  return joints;
}
function poseTransforms(bones,joints){
  const result=new Array(bones.length);
  const solve=id=>{
    if(result[id])return result[id];
    const joint=joints[id],p=bones[id].position;let local={rotation:[1,0,0,0,1,0,0,0,1],translation:[0,0,0]};
    if(joint){const r=apply(joint.rotation,p);local={rotation:joint.rotation,translation:[0,1,2].map(i=>p[i]-r[i]+joint.offset[i])};}
    const parent=bones[id].parent;
    if(parent<0||parent===id||!bones[parent])return result[id]=local;
    result[id]=null;const up=solve(parent);if(!up)return result[id]=local;
    const t=apply(up.rotation,local.translation);
    return result[id]={rotation:multiply(up.rotation,local.rotation),translation:[t[0]+up.translation[0],t[1]+up.translation[1],t[2]+up.translation[2]]};
  };
  for(let i=0;i<bones.length;i++)solve(i);
  return result;
}
function skinMesh(mesh,transforms,positions,normals){
  const p=mesh.original,n=mesh.restNormals;
  for(let v=0;v<p.length/3;v++){
    let x=0,y=0,z=0,nx=0,ny=0,nz=0,total=0;
    for(let k=0;k<4;k++){
      const w=mesh.weights[v*4+k],m=w&&transforms[mesh.indices[v*4+k]];if(!m)continue;
      const r=m.rotation,a=p[v*3],b=p[v*3+1],c=p[v*3+2],d=n[v*3],e=n[v*3+1],f=n[v*3+2];
      x+=w*(r[0]*a+r[1]*b+r[2]*c+m.translation[0]);y+=w*(r[3]*a+r[4]*b+r[5]*c+m.translation[1]);z+=w*(r[6]*a+r[7]*b+r[8]*c+m.translation[2]);
      nx+=w*(r[0]*d+r[1]*e+r[2]*f);ny+=w*(r[3]*d+r[4]*e+r[5]*f);nz+=w*(r[6]*d+r[7]*e+r[8]*f);total+=w;
    }
    if(total>0){positions[v*3]=x/total;positions[v*3+1]=y/total;positions[v*3+2]=z/total;normals[v*3]=nx;normals[v*3+1]=ny;normals[v*3+2]=nz;}
    else for(let i=0;i<3;i++){positions[v*3+i]=p[v*3+i];normals[v*3+i]=n[v*3+i];}
  }
}
function boneColor(id){
  const h=(id*137.508)%360/60,s=.62,l=id%2?.5:.62,c=(1-Math.abs(2*l-1))*s,x=c*(1-Math.abs(h%2-1)),m=l-c/2;
  const [r,g,b]=h<1?[c,x,0]:h<2?[x,c,0]:h<3?[0,c,x]:h<4?[0,x,c]:h<5?[x,0,c]:[c,0,x];
  return [r+m,g+m,b+m];
}
if(typeof module!=='undefined')module.exports={walkJoints,poseTransforms,skinMesh,boneColor,rotation,axisRotation};
