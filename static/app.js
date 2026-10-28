const $ = (selector) => document.querySelector(selector);
const state = { csrf: null, data: null, view: 'overview', filter: 'all' };
const labels = {brand:'MARCA E AGENTES', overview:'VISÃO GERAL', radar:'RADAR', studio:'ESTÚDIO', approvals:'APROVAÇÕES', analytics:'RESULTADOS', integrations:'CONEXÕES', audit:'REGISTRO', campaigns:'CAMPANHAS',library:'BIBLIOTECA CML',team:'EQUIPE IA',learnings:'APRENDIZADOS',calendar:'CALENDÁRIO EDITORIAL',leads:'LEADS E VENDAS' };
const statusLabels = {draft:'Rascunho', review:'Em aprovação', approved:'Aprovado', rejected:'Rejeitado', published:'Publicado'};
const typeLabels = {post:'POST',carousel:'CARROSSEL', blog:'BLOG / SEO', reel:'VÍDEO', idea:'IDEIA'};

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = String(text);
  return element;
}
function empty(parent, title, detail) {
  parent.replaceChildren();
  const card = node('div','empty-state');
  card.append(node('div','empty-glyph','✦'), node('strong','',title), node('p','',detail));
  parent.append(card);
}
function date(text) { return new Date(text).toLocaleDateString('pt-BR', {day:'2-digit', month:'short'}); }
function money(value) { return new Intl.NumberFormat('pt-BR',{style:'currency',currency:window.cmlBrand?.currency||'BRL',maximumFractionDigits:0}).format(value||0); }
function safeUrl(value) { try { const u=new URL(value); return ['https:','http:'].includes(u.protocol) ? u.href : null; } catch { return null; } }
function toast(message, error=false) { const t=$('#toast'); t.textContent=message; t.classList.toggle('error',error); t.classList.add('visible'); clearTimeout(toast.timer); toast.timer=setTimeout(()=>t.classList.remove('visible'),4000); }
async function api(path, options={}) {
  const response = await fetch(path, {credentials:'same-origin',...options, headers:{'Content-Type':'application/json',...(state.csrf?{'X-CSRF-Token':state.csrf}:{}),...options.headers}});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Falha na operação');
  return data;
}
async function refresh() { state.data=await api('/api/dashboard'); if(!window.cmlBrand&&typeof brandLoad==='function') await brandLoad(); render(); }
function showView(view) {
  state.view=view;history.replaceState(null,'','#'+view);
  document.querySelectorAll('.view').forEach(e=>e.classList.toggle('active',e.id===`view-${view}`));
  document.querySelectorAll('.nav-item').forEach(e=>e.classList.toggle('active',e.dataset.view===view));
  $('#crumb').textContent=labels[view];
  if(view==='brand') brandLoad();
  if(view==='leads') leadsRender();
  if(view==='analytics') googleRender();
  window.scrollTo({top:0,behavior:'smooth'});
}
function render() {
  const d=state.data, s=d.summary;
  $('#metricLeads').textContent=s.leads; $('#metricEnrollments').textContent=s.enrollments;
  $('#metricConversion').textContent=`${s.conversion}%`; $('#metricReview').textContent=s.review;
  $('#aLeads').textContent=s.leads; $('#aEnrollments').textContent=s.enrollments;
  $('#aConversion').textContent=`${s.conversion}%`; $('#aRevenue').textContent=money(s.revenue);
  $('#linkedStrip').textContent=`◎ ${s.linked_enrollments} venda(s) vinculada(s) a um lead pelo ID pseudônimo · ${money(s.linked_revenue)} de receita vinculada. Os demais valores são registros brutos.`;
  const ig=d.instagram_insights, val=ig?.values||{};
  $('#igReach').textContent=val.reach??'—';$('#igViews').textContent=val.views??'—';$('#igInteractions').textContent=val.total_interactions??'—';
  $('#instagramInsightsState').textContent=ig?`28 dias: ${ig.start} a ${ig.end} (UTC). Atualizado ${new Date(ig.captured_at).toLocaleString('pt-BR')}. A Meta pode atrasar até 48h; dado ausente aparece como —.`:'Aguardando autorização da conta Instagram e permissão de insights.';
  $('#approvalBadge').textContent=s.review; $('#approvalBadge').hidden=s.review===0;
  chart($('#overviewChart'),d.series); chart($('#analyticsChart'),d.series);
  attention(); radar(); content(); approvals(); analytics(); integrations(); audit(); creativeRender(); editorialRender();
  $('#radarRunState').textContent=d.operations?.radar?.status==='ok' ? 'Atualizado' : d.operations?.radar?.status==='error' ? 'Atenção' : 'Aguardando';
  const editorial=[d.operations?.editorial_post,d.operations?.editorial_blog].filter(Boolean);
  $('#editorialRunState').textContent=editorial.some(j=>j.status==='error')?'Atenção':editorial.length===2?'Ativo':'Aguardando';
  $('#publishRunState').textContent=s.approved?`${s.approved} na fila`:'Após aprovação';
}
function chart(container, series) {
  container.replaceChildren();
  const width=680,height=210,pad=24,max=Math.max(4,...series.map(x=>x.leads),...series.map(x=>x.enrollments));
  const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
  svg.setAttribute('viewBox',`0 0 ${width} ${height}`); svg.setAttribute('role','img'); svg.setAttribute('aria-label','Leads e vendas dos últimos 14 dias');
  for(let i=0;i<4;i++){const line=document.createElementNS(svg.namespaceURI,'line');const y=pad+i*(height-pad*2)/3;line.setAttribute('x1',pad);line.setAttribute('x2',width-pad);line.setAttribute('y1',y);line.setAttribute('y2',y);line.setAttribute('class','gridline');svg.append(line);}
  const points=(key)=>series.map((r,i)=>[pad+i*(width-pad*2)/(series.length-1),height-pad-r[key]/max*(height-pad*2)]);
  [['leads','line-leads'],['enrollments','line-enrollments']].forEach(([key,cls])=>{
    const p=points(key), path=document.createElementNS(svg.namespaceURI,'polyline');path.setAttribute('points',p.map(q=>q.join(',')).join(' '));path.setAttribute('class',cls);svg.append(path);
    p.forEach((q,i)=>{if(series[i][key]){const dot=document.createElementNS(svg.namespaceURI,'circle');dot.setAttribute('cx',q[0]);dot.setAttribute('cy',q[1]);dot.setAttribute('r','4');dot.setAttribute('class',`${cls}-dot`);svg.append(dot);}});
  });
  container.append(svg);
  const axis=node('div','chart-axis');[series[0],series[4],series[8],series[13]].forEach(x=>axis.append(node('span','',date(x.date+'T12:00:00'))));container.append(axis);
  if(series.every(x=>x.leads===0&&x.enrollments===0))container.append(node('p','chart-empty','Registre o primeiro resultado para acompanhar a evolução.'));
}
function attention() {
  const target=$('#attentionList');target.replaceChildren();
  const items=state.data.content.filter(x=>x.status==='review').slice(0,3);
  if(!items.length){empty(target,'Tudo em dia','Nenhum conteúdo aguarda sua decisão.');return;}
  items.forEach(item=>{const row=node('div','attention-row');const icon=node('span','attention-icon',item.kind==='blog'?'▤':item.kind==='reel'?'▶':'✦');const body=node('div');body.append(node('strong','',item.title),node('small','',`${typeLabels[item.kind]} · ${item.channel}`));row.append(icon,body,node('span','attention-arrow','↗'));target.append(row);});
}
function radarCard(item, compact=false) {
  const card=node('article',compact?'radar-row':'radar-card');
  const top=node('div','radar-top');top.append(node('span','radar-score',String(item.score).padStart(2,'0')),node('span','eyebrow',item.category.toUpperCase()));
  const title=node(compact?'strong':'h3','',item.title);
  const foot=node('div','radar-foot');foot.append(node('span','',item.source),node('span','',date(item.seen_at)));
  card.append(top,title,foot);
  const href=safeUrl(item.url);if(href){const link=node('a','card-link','Ver fonte ↗');link.href=href;link.target='_blank';link.rel='noopener noreferrer';card.append(link);}
  return card;
}
function radar(){
  const list=$('#radarList'),small=$('#overviewRadar');list.replaceChildren();small.replaceChildren();
  const items=state.data.radar;
  if(!items.length){empty(list,'O radar está pronto','Configure feeds públicos e execute a rotina para encontrar as primeiras pautas.');empty(small,'Sem sinais ainda','O radar mostrará temas relevantes aqui.');return;}
  items.forEach(x=>list.append(radarCard(x)));
  items.slice(0,3).forEach(x=>small.append(radarCard(x,true)));
}
function content(){
  const list=$('#contentGrid');list.replaceChildren();const items=state.data.content.filter(x=>state.filter==='all'||x.kind===state.filter);
  if(!items.length){empty(list,'A pauta começa aqui','Crie o primeiro rascunho ou transforme um sinal do radar em conteúdo.');return;}
  items.forEach(item=>{
    const card=node('article','content-card');const top=node('div','content-top');top.append(node('span','eyebrow',typeLabels[item.kind]),node('span',`status status-${item.status}`,statusLabels[item.status]));
    card.append(top,node('h3','',item.title),node('p','',item.summary||'Sem resumo. Abra o conteúdo exportado para revisar o texto completo.'));
    const meta=node('div','content-meta');meta.append(node('span','',item.channel),node('span','',item.scheduled_at&&item.status!=='published'?`Programado: ${new Date(item.scheduled_at).toLocaleString('pt-BR',{timeZone:'America/Sao_Paulo',day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'})}`:`Atualizado ${date(item.updated_at)}`));card.append(meta);
    if(item.kind==='blog'){const seo=node('div','seo-line');seo.append(node('span','',`SEO ${item.seo_score}/100`));const track=node('div','seo-track');const fill=node('i');fill.style.width=`${item.seo_score}%`;track.append(fill);seo.append(track);card.append(seo);}
    const actions=node('div','card-actions');const exportBtn=node('button','text-link','Exportar JSON ↗');exportBtn.onclick=()=>exportContent(item.id);actions.append(exportBtn);
    if(['post','carousel','reel'].includes(item.kind)){appendCreativeMedia(card,item);if(!['approved','published'].includes(item.status)){const render=node('button','text-link','Criar nova versão com a equipe');render.onclick=()=>renderVideo(item.id);actions.append(render);}}
    if(['draft','rejected'].includes(item.status)){const edit=node('button','text-link','Editar');edit.onclick=()=>editContent(item);actions.append(edit);}
    if(item.status==='draft'){const submit=node('button','mini-button','Enviar para aprovação');submit.onclick=()=>transition(item.id,'submit');actions.append(submit);}
    if(item.status==='approved'){const reopen=node('button','text-link','Reabrir rascunho');reopen.onclick=()=>transition(item.id,'reopen');actions.append(reopen);}
    card.append(actions);list.append(card);
  });
}
function approvals(){creativeApprovals();}
function analytics(){const src=$('#sourcesList'),ev=$('#eventsList');src.replaceChildren();ev.replaceChildren();if(!state.data.sources.length)empty(src,'Atribuição sem dados','Registre leads com origem para ver quais canais trazem contatos.');else{const max=Math.max(...state.data.sources.map(x=>x.leads));state.data.sources.forEach(x=>{const row=node('div','source-row');const label=node('div','source-label');label.append(node('strong','',x.source),node('span','',x.leads));const bar=node('div','source-bar');const fill=node('i');fill.style.width=`${x.leads/max*100}%`;bar.append(fill);row.append(label,bar);src.append(row);});}
  if(!state.data.events.length)empty(ev,'Sem eventos registrados','Os leads e vendas aparecerão nesta linha do tempo.');else state.data.events.forEach(x=>{const row=node('div','event-row');row.append(node('span',`event-type ${x.event_type}`,x.event_type==='lead'?'LEAD':'MATRÍCULA'),node('strong','',x.source),node('span','',x.campaign||'—'),node('span','',x.event_type==='enrollment'?money(x.value):'—'),node('time','',date(x.occurred_at)));ev.append(row);});}
function integrations(){const list=$('#integrationGrid');list.replaceChildren();const icons=['◎','▤','◈','⌕','✉'];state.data.integrations.forEach((x,i)=>{const card=node('article','integration-card');card.append(node('span','integration-icon',icons[i]),node('span','eyebrow','INTEGRAÇÃO'),node('h3','',x.name),node('p','',x.detail));const foot=node('div','integration-foot');foot.append(node('span',x.status==='connected'?'connected-dot':'pending-dot',x.status==='connected'?'● Conectado':'● Pendente'),node('span','','↗'));card.append(foot);list.append(card);});
  const settings=state.data.settings;
  googleConnectionState(settings.google_key_set);
  $('#openaiKeyState').textContent=settings.openai_key_set?'Chave salva no servidor (valor oculto).':'Nenhuma chave salva.';
  $('#instagramTokenState').textContent=settings.instagram_token_set?'Token salvo no servidor (valor oculto).'+(settings.instagram_token_expires_at?` Validade: ${new Date(settings.instagram_token_expires_at).toLocaleDateString('pt-BR')}.`:' Validade ainda não informada pela Meta.'):'Nenhum token salvo.';
  if(!$('#openaiSettings').contains(document.activeElement)){$('#openaiSettings').elements.mode.value=settings.openai_mode;$('#openaiSettings').elements.model.value=settings.openai_model;}
  if(!$('#instagramSettings').contains(document.activeElement)){$('#instagramSettings').elements.user_id.value=settings.instagram_user_id;$('#instagramSettings').elements.enabled.checked=settings.instagram_enabled;$('#instagramSettings').elements.auto_refresh.checked=settings.instagram_auto_refresh;}
}
function audit(){const list=$('#auditList');list.replaceChildren();$('#auditState').textContent=state.data.audit_valid?'✓ Cadeia íntegra':'⚠ Verificação falhou';$('#auditState').classList.toggle('bad',!state.data.audit_valid);state.data.audit.forEach(x=>{const row=node('div','audit-row');row.append(node('span','audit-number',String(x.id).padStart(3,'0')),node('strong','',x.action),node('span','',x.entity),node('span','',x.detail),node('time','',date(x.at)));list.append(row);});}
async function transition(id,action,reason=''){try{await api(`/api/content/${id}/${action}`,{method:'POST',body:JSON.stringify({reason})});await refresh();toast(({approve:'Conteúdo aprovado.',reject:'Conteúdo rejeitado.',submit:'Enviado para aprovação.',reopen:'Rascunho reaberto.'})[action]);}catch(e){toast(e.message,true);}}
async function exportContent(id){try{const data=await api(`/api/content/${id}/export`);const blob=new Blob([JSON.stringify(data,null,2)],{type:'application/json'});const a=node('a');a.href=URL.createObjectURL(blob);a.download=`cml-conteudo-${id}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);}catch(e){toast(e.message,true);}}
async function renderVideo(id){try{await api(`/api/content/${id}/render`,{method:'POST',body:'{}'});await refresh();toast('Nova versão enviada à equipe. Acompanhe as etapas em Equipe IA.');}catch(e){toast(e.message,true);}}
async function saveOpenai(form,clear=false){const fields=Object.fromEntries(new FormData(form));try{await api('/api/settings/openai',{method:'POST',body:JSON.stringify({mode:clear?'subscription':fields.mode,model:fields.model||'gpt-5-mini',key:clear?'':fields.key||'',clear})});form.elements.key.value='';await refresh();toast(clear?'Chave removida.':'Configuração OpenAI salva.');}catch(e){toast(e.message,true);}}
async function saveInstagram(form,clear=false){const fields=Object.fromEntries(new FormData(form));try{await api('/api/settings/instagram',{method:'POST',body:JSON.stringify({user_id:clear?'':fields.user_id||'',token:clear?'':fields.token||'',enabled:!clear&&form.elements.enabled.checked,auto_refresh:!clear&&form.elements.auto_refresh.checked,clear})});form.elements.token.value='';await refresh();toast(clear?'Instagram desconectado.':'Configuração Instagram salva.');}catch(e){toast(e.message,true);}}
function openDialog(id){document.getElementById(id).showModal();}
function openReview(item){$('#reviewTitle').textContent=item.title;$('#reviewSummary').textContent=item.summary||'';$('#reviewBody').textContent=item.body||'Sem texto.';$('#reviewMedia').replaceChildren();appendCreativeMedia($('#reviewMedia'),item);const source=$('#reviewSource');source.replaceChildren();const href=safeUrl(item.source_url);if(href){const link=node('a','text-link','Ver fonte oficial ↗');link.href=href;link.target='_blank';link.rel='noopener noreferrer';source.append(link);}openDialog('reviewDialog');}
function editContent(item){const form=$('#contentForm');form.dataset.editId=item.id;$('#contentDialogTitle').textContent='Editar conteúdo';for(const key of ['kind','channel','title','summary','body','source_url'])form.elements[key].value=item[key]||'';openDialog('contentDialog');}
async function submitForm(form,path){const data=Object.fromEntries(new FormData(form));try{const target=path==='/api/content'&&form.dataset.editId?`/api/content/${form.dataset.editId}/update`:path;await api(target,{method:'POST',body:JSON.stringify(data)});form.closest('dialog').close();form.reset();delete form.dataset.editId;await refresh();toast('Registrado com sucesso.');}catch(e){toast(e.message,true);}}
function wire(){
  wireCreative();
  document.querySelectorAll('.nav-item').forEach(x=>x.onclick=()=>showView(x.dataset.view));
  document.querySelectorAll('[data-goto]').forEach(x=>x.onclick=()=>showView(x.dataset.goto));
  document.querySelectorAll('[data-close]').forEach(x=>x.onclick=()=>document.getElementById(x.dataset.close).close());
  document.querySelectorAll('.filter').forEach(x=>x.onclick=()=>{state.filter=x.dataset.filter;document.querySelectorAll('.filter').forEach(y=>y.classList.toggle('active',y===x));content();});
  $('#heroCreate').onclick=$('#newContent').onclick=()=>{delete $('#contentForm').dataset.editId;$('#contentForm').reset();$('#contentDialogTitle').textContent='Novo conteúdo';openDialog('contentDialog');};
  $('#heroCreate').onclick=()=>openDialog('creativeDialog');
  $('#newEvent').onclick=()=>openDialog('eventDialog');
  $('#contentForm').onsubmit=e=>{e.preventDefault();submitForm(e.target,'/api/content');};
  $('#eventForm').onsubmit=e=>{e.preventDefault();submitForm(e.target,'/api/events');};
  $('#openaiSettings').onsubmit=e=>{e.preventDefault();saveOpenai(e.target);};
  $('#instagramSettings').onsubmit=e=>{e.preventDefault();saveInstagram(e.target);};
  $('#clearOpenaiKey').onclick=()=>saveOpenai($('#openaiSettings'),true);
  $('#clearInstagramToken').onclick=()=>saveInstagram($('#instagramSettings'),true);
  $('#refreshRadar').onclick=async()=>{const b=$('#refreshRadar');b.disabled=true;b.textContent='Atualizando…';try{const result=await api('/api/jobs/radar',{method:'POST',body:'{}'});await refresh();toast(result.detail||'Radar atualizado.');}catch(e){toast(e.message,true);}finally{b.disabled=false;b.textContent='Atualizar radar ↗';}};
  $('#logout').onclick=async()=>{try{await api('/api/logout',{method:'POST'});}finally{state.csrf=null;state.data=null;$('#shell').hidden=true;$('#login').hidden=false;}};
  $('#loginForm').onsubmit=async e=>{e.preventDefault();const fields=Object.fromEntries(new FormData(e.target));try{const session=await api('/api/login',{method:'POST',body:JSON.stringify(fields)});state.csrf=session.csrf;$('#login').hidden=true;$('#shell').hidden=false;await refresh();e.target.reset();}catch(err){$('#loginError').textContent=err.message;}};
  $('#today').textContent=new Date().toLocaleDateString('pt-BR',{day:'2-digit',month:'long',year:'numeric'}).toUpperCase();
}
async function boot(){wire();try{const session=await api('/api/session');if(session.user){state.csrf=session.csrf;$('#shell').hidden=false;await refresh();const view=location.hash.slice(1);if(labels[view])showView(view);}else $('#login').hidden=false;}catch(e){$('#login').hidden=false;toast('Servidor indisponível. Tente novamente.',true);}setInterval(()=>{if(state.csrf&&!document.hidden)refresh().catch(()=>{});},60000);}
boot();
