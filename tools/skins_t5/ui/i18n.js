'use strict';
const I18N=(()=>{const x=new XMLHttpRequest();try{x.open('GET','/i18n.json',false);x.send();return JSON.parse(x.responseText);}catch(e){return {lang:'pt',catalog:{},languages:{pt:'Português (Brasil)'}};}})();
const tr=(()=>{
  const exact=new Map(),patterns=[],slot=/\{(\d+)(?::[^}]*)?\}/g;
  for(const [key,value] of Object.entries(I18N.catalog||{})){
    if(key==='_name'||!value||value===key)continue;
    if(!/\{\d+(?::[^}]*)?\}/.test(key)){exact.set(key,value);continue;}
    const parts=key.split(/\{(\d+)(?::[^}]*)?\}/);if(!parts.some((p,i)=>i%2===0&&/[A-Za-zÀ-ÿ]{3}/.test(p)))continue;
    let source='^';const order=[];
    parts.forEach((p,i)=>{if(i%2)order.push(Number(p)),source+='([\\s\\S]*?)';else source+=p.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');});
    patterns.push({re:new RegExp(source+'$'),order,to:value,weight:key.replace(slot,'').length});
  }
  patterns.sort((a,b)=>b.weight-a.weight);
  const t=text=>{
    if(!text||!exact.size&&!patterns.length)return text;
    const m=/^(\s*)([\s\S]*?)(\s*)$/.exec(text),core=m[2];if(!core)return text;
    let out=exact.get(core);
    if(out===undefined)for(const p of patterns){const g=p.re.exec(core);if(!g)continue;const values={};p.order.forEach((n,i)=>values[n]=t(g[i+1]));out=p.to.replace(slot,(_,n)=>values[n]??'');break;}
    if(out===undefined&&core.includes(' · ')){const parts=core.split(' · '),done=parts.map(t);if(done.some((x,i)=>x!==parts[i]))out=done.join(' · ');}
    return out===undefined?text:m[1]+out+m[3];
  };
  return t;
})();
(()=>{
  if(I18N.lang==='pt'||!I18N.catalog)return;
  const attrs=['title','placeholder','aria-label'];
  const node=n=>{
    if(n.nodeType===3){const v=n.nodeValue,t=tr(v);if(t!==v)n.nodeValue=t;return;}
    if(n.nodeType!==1||n.tagName==='SCRIPT'||n.tagName==='STYLE'||n.tagName==='TEXTAREA')return;
    for(const a of attrs)if(n.hasAttribute(a)){const v=n.getAttribute(a),t=tr(v);if(t!==v)n.setAttribute(a,t);}
    for(const c of n.childNodes)node(c);
  };
  document.documentElement.lang=I18N.lang;
  new MutationObserver(list=>{for(const m of list){if(m.type==='childList')m.addedNodes.forEach(node);else node(m.target);}})
    .observe(document.documentElement,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:attrs});
  document.addEventListener('DOMContentLoaded',()=>{node(document.body);document.title=tr(document.title);});
})();
document.addEventListener('DOMContentLoaded',()=>{
  const select=document.getElementById('language');if(!select)return;
  for(const [code,name] of Object.entries(I18N.languages||{})){const o=document.createElement('option');o.value=code;o.textContent=name;select.append(o);}
  select.value=I18N.lang;
  select.onchange=async()=>{
    const token=document.querySelector('meta[name="studio-token"]').content;
    await fetch('/api/lang',{method:'POST',headers:{'Content-Type':'application/json','X-Studio-Token':token},body:JSON.stringify({lang:select.value})});
    location.reload();
  };
});
