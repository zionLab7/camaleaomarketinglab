/* Editorial calendar: dates are assigned before approval; no automatic approval. */
function calendarStamp(value){return new Date(value).toLocaleString('pt-BR',{timeZone:'America/Sao_Paulo',day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'});}
function editorialRender(){
  const data=state.data.calendar;if(!data)return;
  const root=document.querySelector('#editorialCalendar');root.replaceChildren();
  const labels={draft:'Em criação',review:'Aguardando aprovação',approved:'Aprovado',published:'Publicado'};
  const days=new Map();for(const slot of data.slots){if(!days.has(slot.local_date))days.set(slot.local_date,[]);days.get(slot.local_date).push(slot);}
  for(const [day,slots]of days){
    const section=node('section','calendar-day');const heading=node('h2','',new Date(day+'T12:00:00-03:00').toLocaleDateString('pt-BR',{timeZone:'America/Sao_Paulo',weekday:'long',day:'2-digit',month:'short'}));section.append(heading);
    const grid=node('div','calendar-day-grid');
    for(const slot of slots){
      const card=node('article','calendar-piece '+(slot.status||'empty'));
      const top=node('div','calendar-piece-top');top.append(node('span','eyebrow',slot.channel),node('strong','',calendarStamp(slot.scheduled_at).split(', ').pop()));card.append(top);
      card.append(node('h3','',slot.title||'Pauta reservada para a equipe'),node('p','calendar-status',labels[slot.status]||'Falta criar conteúdo'));
      card.append(node('small','',`Horário de teste: ${slot.test_arm} · São Paulo`));
      if(slot.overdue)card.append(node('p','calendar-warning','Horário vencido · aguardando recuperação da fila'));
      if(slot.last_result==='error')card.append(node('p','calendar-warning',slot.error||'Falha de publicação; a fila tentará novamente'));
      if(slot.content_id){const actions=node('div','calendar-actions');
        if(slot.status==='review'){const button=node('button','button ghost','Revisar peça');button.type='button';button.onclick=()=>openReview(state.data.content.find(x=>x.id===slot.content_id));actions.append(button);const approve=node('button','button dark','Aprovar esta versão');approve.type='button';approve.onclick=()=>transition(slot.content_id,'approve');actions.append(approve);}
        if(['draft','review','approved'].includes(slot.status)){const button=node('button','button ghost','Alterar data e hora');button.type='button';button.onclick=()=>calendarEdit(slot);actions.append(button);}
        if(slot.status==='published'&&slot.published_url){const url=safeUrl(slot.published_url);if(url){const link=node('a','button ghost','Ver publicação ↗');link.href=url;link.target='_blank';link.rel='noopener noreferrer';actions.append(link);}}
        card.append(actions);
      }
      grid.append(card);
    }section.append(grid);root.append(section);
  }
  const heartbeat=document.querySelector('#calendarHeartbeat');heartbeat.textContent=data.heartbeats.map(x=>`${x.role==='publisher'?'Publicador':'Equipe'}: última passagem ${calendarStamp(x.at)}`).join(' · ')||'Aguardando a primeira passagem dos executores.';
  const summary=document.querySelector('#calendarExperiments');summary.replaceChildren();
  summary.append(node('h2','','Testes de horário'),node('p','','Comparação por formato após 72 horas. Envios atrasados ficam fora da comparação; menos de três peças por grupo não define um vencedor.'));
  if(!data.experiments.length)summary.append(node('p','creative-source-note','Ainda não há publicações com 72 horas de métricas. A coleta é automática após o envio, sem criar números de demonstração.'));
  for(const group of data.experiments){const line=node('div','calendar-experiment');line.append(node('strong','',`${typeLabels[group.format]||group.format} · ${group.hour}`),node('span','',`${group.samples} peça(s) · alcance médio ${group.reach??'—'} · interações médias ${group.interactions??'—'}`),node('small','',group.conclusion));summary.append(line);}
  summary.append(node('p','creative-source-note',data.blog_metrics));
  const measured=document.querySelector('#calendarMeasurements');measured.replaceChildren();
  for(const row of data.measurements){const card=node('div','calendar-experiment');card.append(node('strong','',row.title+' · '+row.window));card.append(node('p','',Object.entries(row.metrics).map(([k,v])=>`${k}: ${v}`).join(' · ')));if(row.missing.length)card.append(node('small','',`Sem dados da Meta para: ${row.missing.join(', ')}`));measured.append(card);}
}
function calendarEdit(slot){
  const form=document.querySelector('#scheduleForm');form.dataset.contentId=slot.content_id;
  document.querySelector('#scheduleTitle').textContent=slot.title;
  const parts=new Intl.DateTimeFormat('sv-SE',{timeZone:'America/Sao_Paulo',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(slot.scheduled_at));
  form.elements.scheduled_at.value=parts.replace(' ','T');document.querySelector('#scheduleDialog').showModal();
}
document.addEventListener('DOMContentLoaded',()=>{
  document.querySelector('#scheduleForm').addEventListener('submit',async event=>{event.preventDefault();const form=event.currentTarget;try{await api(`/api/content/${form.dataset.contentId}/schedule`,{method:'POST',body:JSON.stringify({scheduled_at:new Date(form.elements.scheduled_at.value+'-03:00').toISOString()})});document.querySelector('#scheduleDialog').close();await refresh();toast('Data e hora atualizadas. A aprovação da peça continua obrigatória.');}catch(error){toast(error.message,true);}});
});
