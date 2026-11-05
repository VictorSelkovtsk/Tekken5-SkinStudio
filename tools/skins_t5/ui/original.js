'use strict';
let t5Textures={},clipData=null,clipFrame=null,clipStart=0,clipOffset=0,clipBase=null,clipKey='';
const baseLibrary=library,baseMaterials=materials,baseMods=mods,baseOpenMod=openMod,baseShowPreview=showPreview,baseEditUI=editUI;
function isT5(){return preview?.kind==='t5';}
function t5UI(){
  const on=isT5();
  $('.slot-options').classList.toggle('hidden',on);$('#slotInfo').classList.toggle('hidden',on);$('#t5Note').classList.toggle('hidden',!on);
  $('[data-tab="rig"]').classList.toggle('hidden',on);$('[data-tab="blender"]').classList.toggle('hidden',on);
  $('#character').disabled=on;$('#base').disabled=on;$('#applyMaterials').classList.toggle('hidden',on);
  if(on)$('#convert').firstChild.textContent=editing?'Salvar alterações no mod ':'Salvar texturas como mod ';
  const active=$('.tabs .active')?.dataset.tab;if(on&&(active==='rig'||active==='blender'))$('[data-tab="install"]').click();
}
editUI=function(){baseEditUI();t5UI();};
library=function(){
  if(kind!=='t5')return baseLibrary();
  const text=$('#search').value.toLowerCase(),root=$('#library');root.replaceChildren();
  for(const c of state.characters)for(const s of c.slots){
    const label=c.name+' · '+s.label;if(!label.toLowerCase().includes(text))continue;
    const card=document.createElement('button');card.className='skin-card'+(currentPath==='t5:'+s.index?' active':'');
    const thumb=document.createElement('div');thumb.className='thumb';thumb.textContent='T5';
    const name=document.createElement('span');name.textContent=label;card.append(thumb,name);
    card.onclick=action(()=>loadOriginal(s.index));root.append(card);
  }
};
async function loadOriginal(base,textures={}){
  $('#job').textContent='Lendo a roupa original…';t5Textures={...textures};
  const data=await api('t5/costume',{base_index:base,textures:t5Textures});
  editing=null;materialConfig={};mapping={};blenderProject=null;currentPath='t5:'+base;
  if(data.character!==null){$('#character').value=String(data.character);bases();$('#base').value=String(base);}
  showPreview(data,true);$('#modName').value='Texturas · '+data.name;editUI();library();
  $('#job').textContent='Roupa original carregada. Troque texturas na aba Materiais ou toque uma animação do jogo.';
}
async function reloadOriginal(){
  const data=await api('t5/costume',{base_index:preview.base_index,textures:t5Textures});
  showPreview(data,false);
}
showPreview=function(data,reset=false){
  stopClip();baseShowPreview(data,reset);t5UI();loadBanks().catch(e=>toast(e.message));
};
materials=function(){
  if(!isT5())return baseMaterials();
  const root=$('#materialList');root.replaceChildren();
  const note=document.createElement('p');note.className='muted';
  note.textContent='Escolha a imagem nova de cada textura. A prévia já mostra como ela fica no PS2: no tamanho original e reduzida à paleta da textura (16 ou 256 cores).';
  root.append(note);
  for(const m of preview.materials){
    const row=document.createElement('div');row.className='t5-row';const img=new Image();if(m.url)img.src=m.url;
    const info=document.createElement('div');const name=document.createElement('strong');name.textContent=m.name;
    const detail=document.createElement('small');const n=m.native||{};
    detail.textContent=(n.colors?n.colors+' cores':'cor direta')+(t5Textures[m.key]?' · trocada':'');if(t5Textures[m.key])detail.className='changed';
    info.append(name,detail);
    const buttons=document.createElement('div');
    const pick=document.createElement('button');pick.textContent='Trocar textura…';
    pick.onclick=action(async()=>{const file=await api('pick',{kind:'texture'});if(!file.path)return;t5Textures[m.key]=file.path;await reloadOriginal();});
    buttons.append(pick);
    if(t5Textures[m.key]){const undo=document.createElement('button');undo.textContent='Original';undo.onclick=action(async()=>{delete t5Textures[m.key];await reloadOriginal();});buttons.append(undo);}
    row.append(img,info,buttons);root.append(row);
  }
};
openMod=async function(m){
  if(m.kind!=='textures'){await baseOpenMod(m);t5UI();return;}
  $('#job').textContent='Abrindo o mod para edição…';
  const data=await api('mod/open',{id:m.id});editing=data.mod;t5Textures={...(data.textures||{})};currentPath='t5:'+data.base_index;
  $('#character').value=String(data.mod.character);bases();$('#base').value=String(data.base_index);
  showPreview(data,true);$('#modName').value=data.mod.name;editUI();library();
  $('#job').textContent=`Editando “${data.mod.name}”. Troque as texturas e clique em Salvar alterações no mod.`;
};
mods=function(){
  baseMods();
  for(const m of state.config.mods){
    if(m.kind!=='textures')continue;
    const card=$(`.mod-card[data-id="${m.id}"]`);if(!card)continue;
    const c=state.characters.find(c=>c.id===m.character),slot=c?.slots.find(s=>s.index===m.base_index)?.label||'roupa';
    card.querySelector('small').textContent=`${c?.name||m.character} · Texturas da roupa ${slot} · ${m.report.textures} ${m.report.textures===1?'textura':'texturas'} · ${bytes(m.report.bytes)}`;
  }
};
$('#convert').onclick=action(async()=>{
  if(!isT5())return jobStart('convert',{...request(),mode:$('input[name=mode]:checked').value,name:$('#modName').value,edit:editing?.id});
  const job=await api('t5/save',{name:$('#modName').value,textures:t5Textures,edit:editing?.id});
  await poll(job);
  const final=await api('job');
  if(final.state==='done'&&final.result?.kind==='textures'){const updated=!!final.result.updated;editing=null;editUI();mods();$('#job').textContent=updated?'Mod de texturas atualizado. Gere uma nova ISO para levar ao jogo.':'Mod de texturas criado. Ele já está ativo; gere a ISO para testar.';}
});
$('#search').oninput=()=>library();
async function loadBanks(){
  const base=isT5()?preview.base_index:Number($('#base').value);
  if(!Number.isFinite(base)||(clipBase===base&&$('#clipList').options.length>1))return;
  clipBase=base;clipData=null;clipKey='';stopClip();$('#playClip').disabled=true;$('#clipInfo').textContent='';
  const list=$('#clipList');list.replaceChildren(option('','Animações do jogo…'));
  for(const b of await api('anim/banks',{base_index:base})){
    const group=document.createElement('optgroup');group.label=`${b.name} (${b.clips.length})`;
    b.clips.forEach((frames,i)=>group.append(option(b.bank+':'+i,`#${String(i).padStart(3,'0')} · ${(frames/60).toFixed(2)} s`)));
    list.append(group);
  }
}
function transformsAt(frame){
  const n=clipData.bones,out=new Array(n);
  for(let i=0;i<n;i++){const o=(frame*n+i)*12;out[i]={rotation:clipData.arr.subarray(o,o+9),translation:clipData.arr.subarray(o+9,o+12)};}
  return out;
}
renderer.skinWith=function(t){
  if(!preview||!this.gl)return;const bones=preview.target_bones;
  for(const m of this.meshes){m.walkPositions??=new Float32Array(m.original.length);m.walkNormals??=new Float32Array(m.original.length);skinMesh(m,t,m.walkPositions,m.walkNormals);this.upload(m,m.walkPositions,m.walkNormals);}
  this.posed=bones.map((b,i)=>{const r=t[i].rotation,p=b.position;return [0,1,2].map(k=>r[k*3]*p[0]+r[k*3+1]*p[1]+r[k*3+2]*p[2]+t[i].translation[k]);});
  this.render();
};
async function fetchClip(){
  const value=$('#clipList').value;if(!value)return false;
  const key=value+':'+clipBase+':'+$('#rootMotion').checked;if(clipData&&clipKey===key)return true;
  const [bank,clip]=value.split(':').map(Number);$('#clipInfo').textContent='carregando…';
  const r=await api('anim/clip',{base_index:clipBase,bank,clip,root:$('#rootMotion').checked});
  const raw=Uint8Array.from(atob(r.data),c=>c.charCodeAt(0));
  clipData={frames:r.frames,bones:r.bones,arr:new Float32Array(raw.buffer)};clipKey=key;clipOffset=0;
  if(clipData.bones!==preview.target_bones.length)throw Error('Esqueleto diferente da roupa base');
  return true;
}
function playClip(){
  if(walkFrame!==null)$('#walk').click();stopFace();
  $('#playClip').textContent='⏸ Pausar';clipStart=performance.now()-clipOffset/60*1000;
  const tick=now=>{
    if(document.hidden||!clipData){stopClip();return;}
    clipOffset=Math.floor((now-clipStart)/1000*60)%clipData.frames;
    renderer.skinWith(transformsAt(clipOffset));$('#clipInfo').textContent=`quadro ${clipOffset+1}/${clipData.frames}`;
    clipFrame=requestAnimationFrame(tick);
  };
  clipFrame=requestAnimationFrame(tick);
}
function stopClip(){if(clipFrame!==null){cancelAnimationFrame(clipFrame);clipFrame=null;}$('#playClip').textContent='▶ Tocar';}
$('#clipList').onchange=action(async()=>{stopClip();clipData=null;$('#playClip').disabled=!$('#clipList').value;if(await fetchClip())playClip();});
$('#playClip').onclick=action(async()=>{if(clipFrame!==null){stopClip();return;}if(await fetchClip())playClip();});
$('#rootMotion').onchange=action(async()=>{if(!$('#clipList').value)return;const playing=clipFrame!==null;stopClip();if(await fetchClip()&&playing)playClip();});
$('#walk').addEventListener('click',()=>stopClip(),true);
$('#base').addEventListener('change',()=>{if(!isT5())loadBanks().catch(e=>toast(e.message));});
const basePose=renderer.pose.bind(renderer);renderer.pose=function(){stopClip();basePose();};
