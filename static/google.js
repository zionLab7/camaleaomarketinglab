function googleConnectionState(connected){
 document.querySelector('#googleKeyState').textContent=connected?'Credencial validada e criptografada no servidor.':'Nenhuma credencial salva. A coleta do site e a leitura das APIs são conexões diferentes.';
}
async function googleRender(){
 const box=document.querySelector('#googleMetrics');box.replaceChildren();
 try{
  const data=await api('/api/google/metrics');
  for(const [key,title] of [['ga4','Google Analytics'],['search_console','Search Console']]){
   const part=node('div','');part.append(node('h4','',title));const d=data[key];
   if(!d){part.append(node('p','','Ainda não há uma consulta concluída da API.'));box.append(part);continue;}
   part.append(node('p','',`Período: ${d.start_date} a ${d.end_date} · Consultado em ${new Date(d.captured_at).toLocaleString('pt-BR')}`));
   if(key==='ga4')part.append(node('p','',`Sessões: ${d.totals.sessions??'—'} · Visualizações: ${d.totals.screenPageViews??'—'} · Sessões engajadas: ${d.totals.engagedSessions??'—'}`));
   else part.append(node('small','',d.limitation));
   const table=node('table','');table.style.width='100%';const head=node('tr','');
   for(const h of key==='ga4'?['Página','Visualizações']:['Página','Cliques','Impressões'])head.append(node('th','',h));table.append(head);
   for(const row of d.pages){const tr=node('tr','');for(const value of key==='ga4'?[row.path,row.views]:[row.url,row.clicks,row.impressions]){const td=node('td','',value);td.style.padding='8px';td.style.overflowWrap='anywhere';tr.append(td);}table.append(tr);}
   part.append(table);
   if(key==='ga4'&&d.events?.length){
    part.append(node('h4','','Interações medidas com consentimento'));
    const events=node('table','');events.style.width='100%';const header=node('tr','');
    for(const text of ['Evento','Ocorrências','Usuários no evento'])header.append(node('th','',text));events.append(header);
    for(const event of d.events){const row=node('tr','');for(const value of [event.name,event.count,event.users])row.append(node('td','',value));events.append(row);}
    part.append(events,node('small','','Ocorrências não equivalem a pessoas. Usuários de eventos diferentes podem ser os mesmos; não some essa coluna. Pagamento e qualificação são confirmados na planilha.'));
   }
   box.append(part);
  }
 }catch(e){box.append(node('p','','Não foi possível consultar as métricas. '+e.message));}
}
document.addEventListener('DOMContentLoaded',()=>{
 document.querySelector('#googleSettings').addEventListener('submit',async e=>{
  e.preventDefault();const form=e.target,button=form.querySelector('button'),status=document.querySelector('#googleSaveState');
  const file=form.elements.credential.files[0];if(!file)return;
  if(file.size>16000){status.textContent='Arquivo maior que o esperado para uma conta de serviço.';return;}
  button.disabled=true;status.textContent='Validando as três conexões...';
  try{const credential=await file.text();await api('/api/settings/google',{method:'POST',body:JSON.stringify({credential})});form.reset();status.textContent='Conexão validada e salva. A sincronização será iniciada pela rotina do servidor.';await refresh();}
  catch(err){status.textContent=err.message;}
  finally{button.disabled=false;}
 });
});
