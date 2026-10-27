/* Creative library, team and version-aware review. No publishing credentials in the browser. */
const creativeStatus={queued:'Na fila',running:'Em criação',review:'Aguardando você',needs_attention:'Precisa de ajuste',failed:'Interrompido'};
const roleName=id=>state.data?.creative?.roles.find(x=>x.id===id)?.name||({render:'Renderização',finished:'Concluído'})[id]||id;

function appendCreativeMedia(parent,item){
  const files=item.creative_media?.files||[];
  if(!files.length)return;
  const wrap=node('div','creative-preview');
  if(item.kind==='reel'){
    const videoFile=files.find(x=>x.name.endsWith('.mp4'));
    if(videoFile){const video=node('video');video.src=videoFile.url;video.controls=true;video.preload='metadata';video.playsInline=true;const cover=files.find(x=>x.name.endsWith('-cover.jpg'));if(cover)video.poster=cover.url;wrap.append(video);}
  }else{
    files.filter(x=>x.name.endsWith('.jpg')).forEach((file,i)=>{
      const link=node('a','creative-slide');link.href=file.url;link.target='_blank';link.rel='noopener';
      const img=node('img');img.src=file.url;img.alt=`${item.title} · página ${i+1}`;img.loading='lazy';link.append(img);wrap.append(link);
    });
  }
  parent.append(wrap);
  const review=item.creative_media?.review;
  if(review){
    const box=node('div','creative-review-notes');
    box.append(node('strong','',review.verdict==='pass'?'Revisão da equipe concluída':'A equipe encontrou ajustes necessários'));
    if(review.summary)box.append(node('p','',review.summary));
    for(const issue of review.issues||[])box.append(node('p','creative-warning',issue));
    if(review.notes)box.append(node('p','',review.notes));
    parent.append(box);
  }
}

function creativeApprovals(){
  const list=$('#approvalList');list.replaceChildren();
  const items=state.data.content.filter(x=>x.status==='review');
  if(!items.length){empty(list,'Nenhuma decisão pendente','A equipe enviará aqui as peças renderizadas e as legendas.');return;}
  for(const item of items){
    const card=node('article','approval-card creative-approval');const copy=node('div');
    copy.append(node('span','eyebrow',`${typeLabels[item.kind]} · ${item.channel}`),node('h3','',item.title),node('p','',item.summary));
    if(item.scheduled_at)copy.append(node('p','calendar-status','Programado: '+calendarStamp(item.scheduled_at)+' · São Paulo'));
    appendCreativeMedia(copy,item);
    const social=['post','carousel','reel'].includes(item.kind)&&item.channel==='Instagram';
    const ready=!social||item.creative_media?.review?.verdict==='pass';
    if(social&&!ready)copy.append(node('p','creative-warning','Peça do fluxo anterior: solicite uma nova versão para aplicar a direção aprovada da marca.'));
    const actions=node('div','approval-actions');
    const text=node('button','text-link','Ver peça e legenda');text.onclick=()=>openReview(item);
    const yes=node('button','button dark','Aprovar esta versão →');yes.disabled=!ready;yes.onclick=()=>transition(item.id,'approve');
    const no=node('button','button ghost','Pedir ajuste');no.onclick=()=>feedbackDialog(item);
    actions.append(text,yes,no);
    if(social){const recreate=node('button','text-link','Solicitar nova versão');recreate.onclick=()=>renderVideo(item.id);actions.append(recreate);}
    card.append(copy,actions);list.append(card);
  }
}

function feedbackDialog(item){
  const form=$('#creativeFeedbackForm');form.dataset.contentId=item.id;$('#creativeFeedbackTitle').textContent=item.title;form.elements.reason.value='';openDialog('creativeFeedbackDialog');
}

function creativeRender(){
  const d=state.data.creative;if(!d)return;
  const roles=$('#creativeTeam');roles.replaceChildren();
  const active=d.runs.find(x=>x.status==='running');
  for(const role of d.roles){
    const card=node('article','team-card');const running=active?.stage===role.id;
    card.append(node('span',running?'status status-review':'eyebrow',running?'Trabalhando agora':'EQUIPE CML'),node('h3','',role.name),node('p','',role.purpose));roles.append(card);
  }
  for(const selector of ['#creativeRuns','#campaignRuns']){
    const list=$(selector);list.replaceChildren();
    if(!d.runs.length){empty(list,'A equipe está pronta','Envie um briefing para criar a próxima peça.');continue;}
    for(const run of d.runs){
      const row=node('article','creative-run');const top=node('div','creative-run-top');
      top.append(node('span','eyebrow',run.kind==='auto'?'FORMATO EDITORIAL':typeLabels[run.kind]),node('span',`status status-${run.status==='review'?'review':run.status==='failed'?'rejected':'draft'}`,creativeStatus[run.status]||run.status));
      row.append(top,node('h3','',run.brief),node('p','',`Etapa: ${roleName(run.stage)||'Aguardando executor'} · ${date(run.created_at)}`));
      if(run.steps.length){const steps=node('div','creative-steps');for(const step of run.steps){const badge=node('span',step.status==='done'?'done':'',`${step.status==='done'?'✓':'◌'} ${roleName(step.stage)}`);steps.append(badge);}row.append(steps);}
      if(run.error)row.append(node('p','creative-warning',run.error));
      const actions=node('div','card-actions');
      if(run.content_id){const piece=state.data.content.find(x=>x.id===run.content_id);if(piece){const open=node('button','text-link','Abrir peça ↗');open.onclick=()=>openReview(piece);actions.append(open);}}
      if(run.status==='needs_attention'&&run.content_id){const redo=node('button','mini-button','Solicitar nova versão');redo.onclick=()=>renderVideo(run.content_id);actions.append(redo);}
      if(run.status==='failed'){const retry=node('button','mini-button','Retomar etapas guardadas');retry.onclick=async()=>{try{await api(`/api/creative/runs/${run.id}/retry`,{method:'POST',body:'{}'});await refresh();toast('Trabalho devolvido à fila.');}catch(e){toast(e.message,true);}};actions.append(retry);}
      row.append(actions);list.append(row);
    }
  }
  const learnings=$('#creativeLearnings');learnings.replaceChildren();
  if(!d.feedback.length)empty(learnings,'A memória começa nas suas decisões','Aprovações e pedidos de ajuste ficarão registrados para orientar as próximas peças.');
  else for(const feedback of d.feedback){const row=node('article','creative-run');row.append(node('span','eyebrow',({approve:'VERSÃO APROVADA',reject:'AJUSTE SOLICITADO',reopen:'VERSÃO REABERTA',submit:'ENVIADO À REVISÃO'})[feedback.action]||feedback.action),node('p','',feedback.note||'Decisão registrada sem comentário adicional.'),node('small','',`Peça ${feedback.content_id} · ${date(feedback.created_at)}`));learnings.append(row);}
  renderLibrary();
}

function renderLibrary(){
  const normalize=x=>x.toLocaleLowerCase('pt-BR').normalize('NFD').replace(/[\u0300-\u036f]/g,'');
  const query=normalize($('#librarySearch').value||'');
  const kind=$('#libraryStyle').value;
  const files=(state.data?.creative?.library||[]).filter(x=>(kind==='all'||x.style===kind)&&normalize([x.title,...x.tags].join(' ')).includes(query));
  $('#libraryCount').textContent=`${files.length} elementos`;
  const list=$('#creativeLibrary');list.replaceChildren();
  if(!files.length){empty(list,'Nenhum elemento encontrado','Tente outro tema ou formato.');return;}
  for(const file of files){
    const card=node('article','library-card');const image=node('img');image.src=file.url;image.alt=file.title;image.loading='lazy';
    const text=node('div','library-copy');text.append(node('span','eyebrow',file.style==='photo'?'IMAGEM DA BIBLIOTECA':'ILUSTRAÇÃO'),node('h3','',file.title),node('p','',file.tags.join(' · ')));
    const open=node('button','text-link','Ver elemento ↗');open.onclick=()=>{const target=$('#libraryPreview');target.replaceChildren();const img=node('img');img.src=file.url;img.alt=file.title;target.append(img,node('h3','',file.title),node('p','',file.usage),node('small','','Origem: '+(file.provenance?.origin||'registrada')+' · ID: '+file.id));openDialog('libraryDialog');};
    text.append(open);card.append(image,text);list.append(card);
  }
}

function wireCreative(){
  $('#librarySearch').oninput=renderLibrary;$('#libraryStyle').onchange=renderLibrary;
  for(const button of document.querySelectorAll('[data-creative-new]'))button.onclick=()=>openDialog('creativeDialog');
  $('#creativeForm').onsubmit=async event=>{
    event.preventDefault();const form=event.target;const button=form.querySelector('[type=submit]');button.disabled=true;
    try{const fields=Object.fromEntries(new FormData(form));await api('/api/creative/runs',{method:'POST',body:JSON.stringify(fields)});form.closest('dialog').close();form.reset();await refresh();showView('team');toast('Briefing enviado à equipe. A peça chegará para sua aprovação.');}catch(e){toast(e.message,true);}finally{button.disabled=false;}
  };
  $('#creativeFeedbackForm').onsubmit=async event=>{
    event.preventDefault();const form=event.target;await transition(Number(form.dataset.contentId),'reject',form.elements.reason.value);form.closest('dialog').close();
  };
}
