/* Private contacts are rendered only inside the authenticated leads view. */
let leadRows=[];
async function leadsRender(){
  const list=document.querySelector('#leadList');
  try{
    const data=await api('/api/leads');leadRows=data.leads;
    document.querySelector('#leadSheetLink').href=data.sheet_url;
    document.querySelector('#leadStats').textContent=`${data.total} contatos digitais · ${data.stages.Qualificado||0} qualificados na etapa atual · ${data.stages.Convertido||0} vendas pagas`;
    leadsDraw();
  }catch(err){list.replaceChildren();const p=document.createElement('p');p.textContent='Não foi possível carregar os leads. '+err.message;list.append(p);}
}
function leadsDraw(){
  const list=document.querySelector('#leadList');list.replaceChildren();
  const search=document.querySelector('#leadSearch').value.trim().toLocaleLowerCase('pt-BR'),stage=document.querySelector('#leadStage').value;
  const rows=leadRows.filter(r=>(!stage||r.status===stage)&&(!search||[r.name,r.phone,r.lead_ref].some(x=>String(x||'').toLocaleLowerCase('pt-BR').includes(search))));
  if(!rows.length){empty(list,'Nenhum contato nesta seleção',leadRows.length?'Ajuste os filtros.':'Os novos leads aparecerão aqui após a integração do formulário. Não importamos contatos antigos.');return;}
  for(const r of rows){
    const card=node('details','panel');card.style.padding='20px';card.style.marginBottom='12px';
    const summary=node('summary','');summary.style.cursor='pointer';summary.append(node('strong','',r.name+' · '+r.status),node('span','',` — ${r.unit||'Unidade não informada'} · ${new Date(r.received_at).toLocaleString('pt-BR')}`));card.append(summary);
    const grid=node('dl','');
    const fields=[['Telefone',r.phone],['E-mail',r.email],['Categoria',r.category],['Origem inicial',r.first_source],['Origem recente',r.last_source],['Campanha',r.campaign],['Artigo de apoio',r.content_ref],['Página de entrada',r.landing_path],['Qualificado em',r.qualified_at],['Pagamento confirmado em',r.paid_at],['Valor pago',r.paid_value==null?'Não informado':money(r.paid_value)],['Motivo da perda',r.loss_reason],['Observações',r.notes],['ID do lead',r.lead_ref]];
    for(const [label,value] of fields){grid.append(node('dt','',label),node('dd','',value||'Não informado'));}
    card.append(grid);list.append(card);
  }
}
document.addEventListener('DOMContentLoaded',()=>{
 document.querySelector('#leadSearch').addEventListener('input',leadsDraw);
 document.querySelector('#leadStage').addEventListener('change',leadsDraw);
 document.querySelector('#leadRefresh').addEventListener('click',leadsRender);
});
