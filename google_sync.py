"""Scoped Google metrics and one private lead spreadsheet; no Drive-wide reads."""
from __future__ import annotations
import json,re
from datetime import date,datetime,timedelta,timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo
from pathlib import Path

from brand import TrackingConfig
CONFIG=TrackingConfig()
SCOPES=['https://www.googleapis.com/auth/analytics.readonly','https://www.googleapis.com/auth/webmasters.readonly','https://www.googleapis.com/auth/spreadsheets']
HEADERS=['Recebido em','Nome','Telefone','Unidade','Categoria','Status','Qualificado em','Pago em','Valor pago (R$)','Motivo da perda','Observações','ID do lead','Origem inicial','Origem recente','Campanha','Artigo de apoio','Página de entrada','Consentimento']

def create_schema(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS google_snapshots(source TEXT NOT NULL,start_date TEXT NOT NULL,end_date TEXT NOT NULL,captured_at TEXT NOT NULL,data_json TEXT NOT NULL,PRIMARY KEY(source,start_date,end_date));''')

def validate_info(info):
    if not isinstance(info,dict) or info.get('type')!='service_account' or info.get('token_uri')!='https://oauth2.googleapis.com/token' or not re.fullmatch(r'[a-z0-9_-]+@[a-z0-9-]+\.iam\.gserviceaccount\.com',info.get('client_email','')):
        raise ValueError('Arquivo de conta de serviço Google inválido')
    return info

class Client:
    def __init__(self,info):
        from google.oauth2.service_account import Credentials
        from google.auth.transport.requests import AuthorizedSession
        self.session=AuthorizedSession(Credentials.from_service_account_info(validate_info(info),scopes=SCOPES))
    def request(self,method,url,payload=None):
        # All callers build endpoints from constants and configured, validated IDs.
        response=self.session.request(method,url,json=payload,timeout=30)
        if not response.ok:raise RuntimeError('Google recusou a operação (HTTP '+str(response.status_code)+'); verifique a API e a permissão da conta de serviço')
        return response.json()

def client():
    from app import connect
    from secret_store import get_secret
    with connect() as db:value=get_secret(db,'google_service_account')
    return Client(json.loads(value)) if value else None

def verify(info):
    api=Client(info);result={}
    if not any(CONFIG[k] for k in ['ga4_property_id','search_console_site','lead_sheet_id']):raise ValueError('Configure ao menos um recurso Google em Marca')
    if CONFIG['ga4_property_id']:
        api.request('POST',f"https://analyticsdata.googleapis.com/v1beta/properties/{CONFIG['ga4_property_id']}:runReport",{'dateRanges':[{'startDate':'yesterday','endDate':'yesterday'}],'metrics':[{'name':'sessions'}]});result['ga4']=True
    if CONFIG['search_console_site']:
        api.request('GET','https://www.googleapis.com/webmasters/v3/sites/'+quote(CONFIG['search_console_site'],safe=''));result['search_console']=True
    if CONFIG['lead_sheet_id']:
        sheet=CONFIG['lead_sheet_id'];api.request('GET',f'https://sheets.googleapis.com/v4/spreadsheets/{sheet}?fields=spreadsheetId')
        cell=quote("'Como usar'!B12",safe='')
        message='Conexão Google verificada pelo servidor. A rotina consulta novos leads e status a cada 5 minutos. Confira o estado da sincronização no painel; não importe contatos antigos.'
        url=f'https://sheets.googleapis.com/v4/spreadsheets/{sheet}/values/{cell}'
        api.request('PUT',url+'?valueInputOption=RAW',{'values':[[message]]})
        if api.request('GET',url).get('values')!=[[message]]:raise RuntimeError('Planilha não confirmou escrita')
        result.update(sheet_read=True,sheet_write=True)
    return result

def serial_date(value):
    if value in ('',None):return None
    if isinstance(value,(int,float)):
        return (date(1899,12,30)+timedelta(days=int(value))).isoformat()
    text=str(value).strip()
    for fmt in ['%Y-%m-%d','%d/%m/%Y','%d/%m/%y']:
        try:return datetime.strptime(text,fmt).date().isoformat()
        except ValueError:pass
    raise ValueError('Data de status inválida na planilha')

def paid_value(value):
    if value in ('',None):return None
    if isinstance(value,(int,float)):return value
    text=str(value).strip().replace('R$','').replace(' ','')
    if ',' in text:text=text.replace('.','').replace(',','.')
    return float(text)

def sync_sheet(api=None):
    from app import connect,now
    from leads import decrypt,update_status
    from jobs import record_job
    api=api or client()
    if not api or not CONFIG['lead_sheet_id']:return
    sheet=CONFIG['lead_sheet_id'];base=f'https://sheets.googleapis.com/v4/spreadsheets/{sheet}/values/'
    # Bound the operational surface. Expand explicitly before reaching capacity.
    response=api.request('GET',base+quote('Leads!A1:R1000',safe='')+'?valueRenderOption=UNFORMATTED_VALUE&dateTimeRenderOption=SERIAL_NUMBER')
    values=response.get('values',[])
    if not values or values[0]!=HEADERS:raise RuntimeError('Cabeçalho da planilha mudou; sincronização interrompida para preservar os dados')
    records={};errors=0
    for index,raw in enumerate(values[1:],2):
        row=(raw+['']*18)[:18];ref=str(row[11])
        if not ref:continue
        if ref in records:raise RuntimeError('ID duplicado na planilha; resolva a duplicidade antes de sincronizar')
        records[ref]=(index,row)
    with connect() as db:pending=[dict(x) for x in db.execute('SELECT * FROM leads ORDER BY received_at,lead_ref')]
    occupied={i for i,row in enumerate(values,1) if any(v not in ('',None) for v in row)}
    next_row=2;created=updated=0
    for lead in pending:
        ref=lead['lead_ref']
        if ref in records:
            _,row=records[ref]
            try:
                payload={'lead_ref':ref,'status':row[5] or 'Novo','qualified_at':serial_date(row[6]),'paid_at':serial_date(row[7]),'paid_value':paid_value(row[8]),'loss_reason':row[9],'notes':row[10]}
                with connect() as db:
                    result=update_status(db,payload)
                    db.execute('UPDATE leads SET sheet_synced_at=? WHERE lead_ref=?',(now(),ref))
                updated+=not result['duplicate']
            except (ValueError,TypeError):errors+=1
            continue
        if lead['sheet_synced_at']:
            # A missing row may have been manually deleted; do not resurrect it.
            errors+=1;continue
        if created>=30:break
        while next_row in occupied:next_row+=1
        if next_row>1000:raise RuntimeError('Planilha atingiu a capacidade configurada; amplie a tabela antes de continuar')
        contact=decrypt(ref,lead['contact_encrypted'])
        unit=contact.get('unit','')
        stamp=datetime.fromisoformat(lead['received_at']).astimezone(ZoneInfo(__import__('brand').get()['timezone']))
        serial=(stamp.replace(tzinfo=None)-datetime(1899,12,30)).total_seconds()/86400
        row=[serial,contact.get('name',''),contact.get('phone',''),unit,contact.get('category',''),lead['status'],'','','','','',ref,lead['first_source'],lead['last_source'],lead['campaign'],lead['content_ref'],lead['landing_path'],lead['consent']]
        # RAW prevents names/notes/phones beginning with '=' from becoming formulas.
        api.request('PUT',base+quote(f'Leads!A{next_row}:R{next_row}',safe='')+'?valueInputOption=RAW',{'values':[row]})
        with connect() as db:db.execute('UPDATE leads SET sheet_synced_at=? WHERE lead_ref=?',(now(),ref))
        occupied.add(next_row);created+=1
    with connect() as db:record_job(db,'google_sheet','error' if errors else 'ok',f'{created} novos contatos sincronizados; {updated} atualizações; {errors} registros precisam de revisão')
    return {'created':created,'updated':updated,'errors':errors}

def collect_metrics(api=None):
    from app import connect,now
    from jobs import record_job
    api=api or client()
    if not api:return
    today=datetime.now(ZoneInfo(__import__('brand').get()['timezone'])).date()
    start=(today-timedelta(days=28)).isoformat();end=(today-timedelta(days=1)).isoformat()
    ga=None
    if CONFIG['ga4_property_id']:
        ga=api.request('POST',f"https://analyticsdata.googleapis.com/v1beta/properties/{CONFIG['ga4_property_id']}:runReport",{
          'dateRanges':[{'startDate':start,'endDate':end}],
          'dimensions':[{'name':x} for x in ['date','pagePath','sessionSourceMedium']],
          'metrics':[{'name':x} for x in ['sessions','screenPageViews','engagedSessions','userEngagementDuration']],
          'limit':10000,'returnPropertyQuota':True,'metricAggregations':['TOTAL']})
        ga['cml_event_report']=api.request('POST',f"https://analyticsdata.googleapis.com/v1beta/properties/{CONFIG['ga4_property_id']}:runReport",{
          'dateRanges':[{'startDate':start,'endDate':end}],
          'dimensions':[{'name':'eventName'}],
          'metrics':[{'name':'eventCount'},{'name':'totalUsers'}],
          'limit':100})
    gsc=None
    if CONFIG['search_console_site']:
        site=quote(CONFIG['search_console_site'],safe='')
        gsc=api.request('POST',f'https://www.googleapis.com/webmasters/v3/sites/{site}/searchAnalytics/query',{
          'startDate':start,'endDate':end,'dimensions':['page','query'],'rowLimit':1000,'dataState':'final','type':'web'})
    with connect() as db:
        create_schema(db)
        for source,data in [('ga4',ga),('search_console',gsc)]:
            if data is None:continue
            db.execute('INSERT OR REPLACE INTO google_snapshots VALUES(?,?,?,?,?)',(source,start,end,now(),json.dumps(data,ensure_ascii=False)))
            record_job(db,source,'ok','Métricas consultadas pela API oficial; período '+start+' a '+end)

def overview(db):
    present=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='google_snapshots'").fetchone()
    result={}
    for source in ['ga4','search_console']:
        row=db.execute('SELECT * FROM google_snapshots WHERE source=? ORDER BY captured_at DESC LIMIT 1',(source,)).fetchone() if present else None
        if not row:result[source]=None;continue
        data=json.loads(row['data_json'])
        item={k:row[k] for k in ['start_date','end_date','captured_at']}
        if source=='ga4':
            names=[x['name'] for x in data.get('metricHeaders',[])]
            item['totals']=dict(zip(names,[float(x['value']) for x in (data.get('totals') or [{}])[0].get('metricValues',[])]))
            pages={}
            for r in data.get('rows',[]):
                path=r['dimensionValues'][1]['value'];values=dict(zip(names,[float(x['value']) for x in r['metricValues']]))
                p=pages.setdefault(path,{'path':path,'views':0,'engagement_seconds':0})
                p['views']+=values.get('screenPageViews',0);p['engagement_seconds']+=values.get('userEngagementDuration',0)
            item['pages']=sorted(pages.values(),key=lambda x:x['views'],reverse=True)[:20]
            item['row_count']=data.get('rowCount',0);item['returned_rows']=len(data.get('rows',[]))
            item['events']=[{'name':r['dimensionValues'][0]['value'],
              'count':int(r['metricValues'][0]['value']),'users':int(r['metricValues'][1]['value'])}
              for r in data.get('cml_event_report',{}).get('rows',[])]
        else:
            pages={}
            for r in data.get('rows',[]):
                url=r.get('keys',[''])[0];p=pages.setdefault(url,{'url':url,'clicks':0,'impressions':0})
                p['clicks']+=r.get('clicks',0);p['impressions']+=r.get('impressions',0)
            item['pages']=sorted(pages.values(),key=lambda x:x['clicks'],reverse=True)[:20]
            item['limitation']='Linhas principais disponibilizadas pelo Search Console; não equivalem ao total completo de pesquisas.'
        result[source]=item
    return result

if __name__=='__main__':
    import sys
    sheet_mode=len(sys.argv)>1 and sys.argv[1]=='sheet'
    try:(sync_sheet if sheet_mode else collect_metrics)()
    except Exception:
        from app import connect
        from jobs import record_job
        with connect() as db:
            for job in (['google_sheet'] if sheet_mode else ['ga4','search_console']):
                record_job(db,job,'error','Não foi possível concluir a sincronização Google. Verifique autorização, cabeçalho e disponibilidade da API; valores privados foram omitidos.')
        raise SystemExit(1)
