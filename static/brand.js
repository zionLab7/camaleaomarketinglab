const brandLists=['topics','sources','feeds','competitor_feeds','allowed_hosts','keywords','instagram_times','blog_times'];
async function brandLoad(){
 try{
 const b=await api('/api/brand');window.cmlBrand=b;const f=document.querySelector('#brandForm');
 for(const [k,v] of Object.entries(b)){
  const input=f.elements[k];if(!input)continue;
  if(input.type==='checkbox')input.checked=v;else input.value=Array.isArray(v)?v.join('\n'):v;
 }
 for(const [role,value] of Object.entries(b.agents))f.elements['agent_'+role].value=value;
 document.querySelectorAll('[data-brand-name]').forEach(el=>el.textContent=b.name);
 document.documentElement.style.setProperty('--brand-primary',b.primary);document.documentElement.style.setProperty('--brand-accent',b.accent);document.documentElement.style.setProperty('--brand-background',b.background);document.documentElement.style.setProperty('--navy',b.primary);document.documentElement.style.setProperty('--lime',b.accent);
 document.title=b.name+' · Camaleão Marketing Lab';
 }catch(e){if(state.csrf)document.querySelector('#brandState').textContent=e.message;}
}
document.addEventListener('DOMContentLoaded',()=>{
 document.querySelector('#brandForm').addEventListener('submit',async e=>{
 e.preventDefault();const data={...window.cmlBrand,agents:{...window.cmlBrand.agents}},f=e.target,status=document.querySelector('#brandState');
 for(const input of f.elements){if(!input.name)continue;const key=input.name;if(key.startsWith('agent_'))data.agents[key.slice(6)]=input.value;else data[key]=input.type==='checkbox'?input.checked:brandLists.includes(key)?input.value.split('\n').map(x=>x.trim()).filter(Boolean):input.value;}
 try{await api('/api/brand',{method:'POST',body:JSON.stringify(data)});await brandLoad();await refresh();status.textContent='Marca e agentes salvos. Novas peças usarão essa direção.';}catch(err){status.textContent=err.message;}
 });
 document.querySelector('#libraryUpload').addEventListener('submit',async e=>{
 e.preventDefault();const f=e.target,file=f.elements.file.files[0],status=document.querySelector('#uploadState');
 if(!file||file.size>4_000_000){status.textContent='Selecione imagem de até 4 MB.';return;}
 const reader=new FileReader();reader.onload=async()=>{try{const result=await api('/api/library/upload',{method:'POST',body:JSON.stringify({data:reader.result.split(',')[1],title:f.elements.title.value,illustrative:f.elements.illustrative.checked,ai_generated:f.elements.ai_generated.checked,rights_confirmed:f.elements.rights.checked})});status.textContent='Elemento salvo. ID: '+result.id;await refresh();}catch(err){status.textContent=err.message;}};reader.readAsDataURL(file);
 });
});
