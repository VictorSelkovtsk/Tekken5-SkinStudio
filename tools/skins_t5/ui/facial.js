function facialPositions(mesh,bones,mode,amount){
  const output=mesh.original.slice(),jaw=bones[85].position;
  const angle=amount*Math.PI/10,c=Math.cos(angle),s=Math.sin(angle);
  const eyeSpan=Math.abs(bones[100].position[0]-bones[109].position[0]);
  const size=Math.max(10,eyeSpan);
  for(let v=0;v<output.length/3;v++){
    const p=Array.from(mesh.original.slice(v*3,v*3+3)),delta=[0,0,0];
    for(let k=0;k<4;k++){
      const id=mesh.indices[v*4+k],weight=mesh.weights[v*4+k];
      if(!weight)continue;
      if(mode==='mouth'&&id>=85&&id<=91){
        const y=p[1]-jaw[1],z=p[2]-jaw[2];
        delta[1]+=weight*(y*c-z*s-y);delta[2]+=weight*(y*s+z*c-z);
      }else if(mode==='blink'){
        if(id===98||id===107)delta[1]-=weight*amount*size*.20;
        if(id===97||id===106)delta[1]+=weight*amount*size*.065;
      }else if(mode==='brow'&&[99,101,108,110].includes(id)){
        delta[1]+=weight*amount*size*.12;
      }
    }
    for(let axis=0;axis<3;axis++)output[v*3+axis]+=delta[axis];
  }
  return output;
}
if(typeof module!=='undefined')module.exports={facialPositions};
