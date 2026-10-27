"""Aggregate outcomes for agents; never expose a contact or a spreadsheet note."""
from datetime import datetime,timedelta,timezone
import json

def summary(db):
    since=(datetime.now(timezone.utc)-timedelta(days=30)).isoformat(timespec='seconds')
    present=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='leads'").fetchone()
    groups=[]
    if present:
        for row in db.execute('''SELECT first_source AS source,content_ref AS assisted_content,count(*) AS leads,
          sum(qualified_at IS NOT NULL) AS qualified,sum(status='Convertido' AND paid_at IS NOT NULL) AS paid_enrollments,
          sum(CASE WHEN status='Convertido' THEN paid_value ELSE NULL END) AS reported_paid_value
          FROM leads WHERE received_at>=? GROUP BY first_source,content_ref''',(since,)):
            item=dict(row);item['sample']='insuficiente para comparar' if item['leads']<5 else 'observacional'
            groups.append(item)
    media=[]
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='media_measurements'").fetchone():
        for row in db.execute('''SELECT m.content_id,c.title,c.kind,m.window,m.captured_at,m.metrics_json,m.missing_json
          FROM media_measurements m JOIN content c ON c.id=m.content_id WHERE m.window='72h' ORDER BY m.captured_at DESC LIMIT 20'''):
            item=dict(row);item['metrics']=json.loads(item.pop('metrics_json'));item['missing']=json.loads(item.pop('missing_json'));media.append(item)
    from google_sync import overview
    from leads import label
    from urllib.parse import urlsplit
    metrics=overview(db);traffic={}
    ga=metrics.get('ga4');search=metrics.get('search_console')
    if ga:
        traffic['ga4']={'period_start':ga['start_date'],'period_end':ga['end_date'],'totals':ga['totals'],
          'pages':[p for p in ga['pages'][:10] if label(p['path'],300)],'events':ga.get('events',[])}
    if search:
        traffic['search_console']={'period_start':search['start_date'],'period_end':search['end_date'],
          'pages':[{'path':label(urlsplit(p['url']).path,300),'clicks':p['clicks'],'impressions':p['impressions']}
            for p in search['pages'][:10] if label(urlsplit(p['url']).path,300)],'limitation':search['limitation']}
    return {'period_start':since,'commercial_groups':groups,'instagram_72h':media,'site_metrics':traffic,
      'limitations':['Somente novos leads digitais registrados. A planilha de telefone e balcão não participa.',
      'Qualificação exige conversa com continuidade. Venda exige pagamento confirmado pelo responsável.',
      'Conteúdo de apoio é assistência observada na navegação, não prova de causalidade nem de exposição a um post.',
      'Amostras com menos de cinco contatos não definem vencedor. Não transformar correlação em promessa comercial.',
      'Nomes, telefones, e-mails, IDs de lead e notas de atendimento não são fornecidos aos agentes.']}
