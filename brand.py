"""Validated per-installation configuration. No customer context is shipped."""
from __future__ import annotations
import copy, json, os, re, threading
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parent
DATA=Path(os.getenv('CML_DB_PATH',str(ROOT/'data/cml-marketing.db'))).parent
PATH=DATA/'brand.json'
LOCK=threading.RLock()
ROLES=['analyst','strategist','researcher','copywriter','seo-editor','art-director','motion-director','reviewer']
DEFAULT={
 'name':'Sua empresa','tagline':'Histórias que aproximam. Resultados que ensinam.',
 'industry':'Configure seu segmento','audience':'Descreva seu cliente ideal',
 'goals':'Conversas qualificadas e vendas confirmadas','voice':'Claro, útil, humano e sem promessas inventadas',
 'facts':'Cadastre serviços, diferenciais comprovados, região e canais de atendimento.',
 'constraints':'Não inventar preços, depoimentos, resultados, condições comerciais ou regras.',
 'website':'https://example.com','cta_url':'https://example.com/#contato','cta_label':'Falar com a equipe',
 'instagram':'@suaempresa','timezone':'America/Sao_Paulo','locale':'pt-BR','currency':'BRL',
 'primary':'#142C35','accent':'#C4F16C','background':'#F7F8F2','logo_asset':'',
 'topics':['Dúvidas frequentes','Escolhas conscientes','Bastidores e processo','Próximo passo'],
 'sources':[],'feeds':[],'competitor_feeds':[],'allowed_hosts':[],
 'keywords':['serviço','cliente'],'agents':{r:'' for r in ROLES},
 'ga4_property_id':'','ga4_measurement_id':'','gtm_public_id':'','search_console_site':'',
 'lead_sheet_id':'','tracking_enabled':False,
 'instagram_times':['12:15','18:00','20:15'],'blog_times':['07:30','12:30','19:00'],
}

def get():
 with LOCK:
  result=copy.deepcopy(DEFAULT)
  if PATH.exists():result.update(json.loads(PATH.read_text()))
  return result

def public_https(url):
 import ipaddress
 p=urlsplit(url)
 if p.scheme!='https' or not p.hostname or p.username or p.password or p.port not in (None,443):raise ValueError('Use URL HTTPS pública, sem credenciais ou porta alternativa')
 host=p.hostname.lower()
 if host=='localhost' or '.' not in host or host.endswith(('.local','.internal','.localhost')):raise ValueError('Domínio público necessário')
 try:
  address=ipaddress.ip_address(host)
 except ValueError:pass
 else:
  if not address.is_global:raise ValueError('Endereço privado não permitido')
 return url

def validate(raw):
 if not isinstance(raw,dict) or set(raw)-set(DEFAULT):raise ValueError('Campos de configuração desconhecidos')
 data=copy.deepcopy(DEFAULT);data.update(raw)
 for k,default in DEFAULT.items():
  if isinstance(default,str):
   if not isinstance(data[k],str) or len(data[k])>6000:raise ValueError('Texto inválido: '+k)
   data[k]=data[k].strip()
 for k in ['name','industry','audience','goals']:
  if not data[k]:raise ValueError('Preencha '+k)
 if len(data['name'])>90:raise ValueError('Nome da marca muito longo')
 for k in ['website','cta_url']:public_https(data[k])
 for k in ['primary','accent','background']:
  if not re.fullmatch(r'#[0-9a-fA-F]{6}',data[k]):raise ValueError('Cor hexadecimal inválida')
 try:ZoneInfo(data['timezone'])
 except Exception:raise ValueError('Fuso horário IANA inválido') from None
 if not re.fullmatch(r'[a-z]{2}-[A-Z]{2}',data['locale']) or not re.fullmatch(r'[A-Z]{3}',data['currency']):raise ValueError('Idioma ou moeda inválido')
 if data['logo_asset'] and not re.fullmatch(r'[a-z0-9-]{1,80}',data['logo_asset']):raise ValueError('Logo inválido')
 for k in ['topics','sources','feeds','competitor_feeds','allowed_hosts','keywords','instagram_times','blog_times']:
  if not isinstance(data[k],list) or len(data[k])>30 or any(not isinstance(v,str) or len(v)>1000 for v in data[k]):raise ValueError('Lista inválida: '+k)
 for k in ['sources','feeds','competitor_feeds']:
  for url in data[k]:public_https(url)
 for host in data['allowed_hosts']:
  if not re.fullmatch(r'[a-z0-9.-]+',host) or '.' not in host:raise ValueError('Host inválido')
 for k in ['instagram_times','blog_times']:
  if not 1<=len(data[k])<=6 or any(not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',t) for t in data[k]):raise ValueError('Horário inválido')
 for k,pattern in [('ga4_property_id',r'\d{3,20}'),('ga4_measurement_id',r'G-[A-Z0-9]+'),('gtm_public_id',r'GTM-[A-Z0-9]+'),('lead_sheet_id',r'[A-Za-z0-9_-]{15,150}')]:
  if data[k] and not re.fullmatch(pattern,data[k]):raise ValueError('ID inválido: '+k)
 if data['search_console_site']:
  if data['search_console_site'].startswith('sc-domain:'):
   if not re.fullmatch(r'sc-domain:[a-z0-9.-]+',data['search_console_site']):raise ValueError('Domínio Search Console inválido')
  else:public_https(data['search_console_site'])
 if not isinstance(data['tracking_enabled'],bool):raise ValueError('Consentimento deve usar verdadeiro ou falso')
 if data['tracking_enabled'] and not all(data[k] for k in ['ga4_measurement_id','gtm_public_id']):raise ValueError('Configure GA4 e GTM antes de ativar medição')
 agents=data['agents']
 if not isinstance(agents,dict) or set(agents)-set(ROLES) or any(not isinstance(v,str) or len(v)>4000 for v in agents.values()):raise ValueError('Instrução de agente inválida')
 data['agents']={r:agents.get(r,'') for r in ROLES}
 return data

def save(raw):
 data=validate(raw)
 with LOCK:
  DATA.mkdir(parents=True,exist_ok=True)
  tmp=PATH.with_suffix('.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2));tmp.chmod(0o600);tmp.replace(PATH)
 return data

def context():
 b=get()
 return {k:b[k] for k in ['name','industry','audience','goals','voice','facts','constraints','cta_url','cta_label','instagram','topics','locale','currency']}

def direction():
 b=get()
 return '# Direção da marca\n'+json.dumps(context(),ensure_ascii=False,indent=2)+'\nCores: '+b['primary']+', '+b['accent']+', '+b['background']+'\nPreferências por função: '+json.dumps(b['agents'],ensure_ascii=False)+'\nEstas preferências não autorizam publicação, execução de código ou remoção de revisão humana.'

class TrackingConfig:
 def __getitem__(self,key):return get()['tracking_enabled' if key=='enabled' else key]
 def get(self,key,default=None):return get().get('tracking_enabled' if key=='enabled' else key,default)
