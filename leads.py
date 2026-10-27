"""Private lead ledger; attribution and confirmed outcomes share a stable ID."""
from __future__ import annotations
import base64,hashlib,json,math,os,re
from datetime import date,datetime,timezone
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

STATES={'Novo','Em atendimento','Qualificado','Não qualificado','Convertido','Perdido'}

def create_schema(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS leads(
      lead_ref TEXT PRIMARY KEY, received_at TEXT NOT NULL, updated_at TEXT NOT NULL,
      contact_encrypted TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Novo',
      first_source TEXT NOT NULL, last_source TEXT NOT NULL, campaign TEXT NOT NULL DEFAULT '',
      content_ref TEXT NOT NULL DEFAULT '', landing_path TEXT NOT NULL DEFAULT '/',
      consent TEXT NOT NULL DEFAULT 'rejected', qualified_at TEXT, paid_at TEXT,
      paid_value REAL, loss_reason TEXT NOT NULL DEFAULT '', notes_encrypted TEXT NOT NULL DEFAULT '',
      status_hash TEXT NOT NULL DEFAULT '', sheet_synced_at TEXT);
      CREATE TABLE IF NOT EXISTS lead_changes(id INTEGER PRIMARY KEY, lead_ref TEXT NOT NULL REFERENCES leads(lead_ref),
      at TEXT NOT NULL, old_status TEXT NOT NULL, new_status TEXT NOT NULL, snapshot_hash TEXT NOT NULL);
      CREATE UNIQUE INDEX IF NOT EXISTS idx_lead_snapshot ON lead_changes(lead_ref,snapshot_hash);
      CREATE TABLE IF NOT EXISTS lead_receipts(external_id TEXT PRIMARY KEY,lead_ref TEXT NOT NULL REFERENCES leads(lead_ref),payload_hash TEXT NOT NULL);
      CREATE INDEX IF NOT EXISTS idx_leads_received ON leads(received_at);''')

def cipher():
    master=os.getenv('CML_APP_SECRET','')
    if len(master)<32:raise RuntimeError('Segredo privado não configurado')
    return AESGCM(hashlib.sha256(b'cml-marketing-os:leads:v1:'+master.encode()).digest())

def encrypt(ref,value):
    nonce=os.urandom(12)
    return base64.urlsafe_b64encode(nonce+cipher().encrypt(nonce,json.dumps(value,ensure_ascii=False).encode(),ref.encode())).decode()

def decrypt(ref,value):
    if not value:return {}
    raw=base64.urlsafe_b64decode(value)
    return json.loads(cipher().decrypt(raw[:12],raw[12:],ref.encode()))

def label(value,limit=100):
    value=str(value or '').strip()[:limit]
    return value if re.fullmatch(r'[\w ./:\-]*',value) and not re.search(r'\d{8,}',value) else ''

def reference(value):
    value=str(value or '')
    if not re.fullmatch(r'[a-zA-Z0-9:_-]{8,120}',value):raise ValueError('ID de lead inválido')
    return value

def ingest(db,data):
    from app import audit,now
    ref=reference(data.get('lead_ref'))
    external=reference(data.get('external_id'))
    payload_hash=hashlib.sha256(json.dumps(data,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    receipt=db.execute('SELECT lead_ref,payload_hash FROM lead_receipts WHERE external_id=?',(external,)).fetchone()
    if receipt:
        if receipt['payload_hash']!=payload_hash:raise ValueError('Evento já recebido com conteúdo diferente')
        return {'lead_ref':receipt['lead_ref'],'duplicate':True}
    previous=db.execute('SELECT lead_ref FROM leads WHERE lead_ref=?',(ref,)).fetchone()
    if previous:
        db.execute('INSERT INTO lead_receipts VALUES(?,?,?)',(external,ref,payload_hash))
        return {'lead_ref':ref,'duplicate':True}
    contact={k:str(data.get(k) or '').strip()[:limit] for k,limit in [('name',160),('phone',40),('email',254),('unit',40),('category',40)]}
    if not contact['name'] or not 10<=len(re.sub(r'\D','',contact['phone']))<=13:
        raise ValueError('Nome e telefone de contato são obrigatórios')
    accepted=data.get('analytics_consent')=='accepted'
    first=data.get('attribution_first') if accepted else {}
    last=data.get('attribution_last') if accepted else {}
    first=first if isinstance(first,dict) else {};last=last if isinstance(last,dict) else {}
    path=str(first.get('landing_path') or data.get('landing_path') or '/')[:300]
    path=path if re.fullmatch(r'/[a-zA-Z0-9_./-]*',path) and not re.search(r'\d{8,}',path) else '/'
    source=label(first.get('source')) or ('direct' if accepted else 'Sem consentimento de medição')
    at=now()
    db.execute('''INSERT INTO leads(lead_ref,received_at,updated_at,contact_encrypted,first_source,last_source,campaign,content_ref,landing_path,consent)
      VALUES(?,?,?,?,?,?,?,?,?,?)''',(ref,at,at,encrypt(ref,contact),source,label(last.get('source')) or source,
       label(last.get('utm_campaign') or first.get('utm_campaign')),label(data.get('assisted_content')) if accepted else '',path,'accepted' if accepted else 'rejected'))
    db.execute('INSERT INTO lead_receipts VALUES(?,?,?)',(external,ref,payload_hash))
    db.execute("INSERT INTO events(event_type,source,campaign,lead_ref,value,occurred_at) VALUES('lead',?,?,?,?,?)",(source,label(last.get('utm_campaign')),ref,0,at))
    audit(db,'n8n','lead.received','lead:'+ref,'Novo contato digital registrado; dados privados criptografados')
    return {'lead_ref':ref,'duplicate':False}

def update_status(db,data):
    from app import audit,now
    ref=reference(data.get('lead_ref'));status=data.get('status')
    if status not in STATES:raise ValueError('Status inválido')
    row=db.execute('SELECT * FROM leads WHERE lead_ref=?',(ref,)).fetchone()
    if not row:raise ValueError('Lead não encontrado; contatos antigos não são importados')
    paid=data.get('paid_at') or None
    qualified=data.get('qualified_at') or row['qualified_at']
    for value in [paid,qualified]:
        if value:date.fromisoformat(str(value))
    amount=data.get('paid_value')
    amount=None if amount in (None,'') else float(amount)
    if amount is not None and (not math.isfinite(amount) or not 0<=amount<=1_000_000):raise ValueError('Valor pago inválido')
    if status=='Convertido' and not paid:raise ValueError('Venda exige data do pagamento confirmado')
    if status=='Qualificado' and not qualified:qualified=now()[:10]
    if paid and status!='Convertido':raise ValueError('Data de pagamento exige status Convertido; revise a planilha')
    reason=str(data.get('loss_reason') or '').strip()[:200]
    if status=='Perdido' and not reason:raise ValueError('Informe o motivo da perda')
    notes=str(data.get('notes') or '').strip()[:2000]
    snapshot={'status':status,'paid_at':paid,'qualified_at':qualified,'paid_value':amount,'loss_reason':reason,'notes':notes}
    digest=hashlib.sha256(json.dumps(snapshot,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    if row['status_hash']==digest:return {'lead_ref':ref,'duplicate':True}
    at=now()
    # A correction to a payment revises the existing result instead of counting a second enrollment.
    db.execute("DELETE FROM events WHERE event_type='enrollment' AND lead_ref=?",(ref,))
    if status=='Convertido':
        db.execute("INSERT INTO events(event_type,source,campaign,lead_ref,value,occurred_at) VALUES('enrollment',?,?,?,?,?)",(row['first_source'],row['campaign'],ref,amount or 0,paid+'T12:00:00-03:00'))
    db.execute('''UPDATE leads SET status=?,updated_at=?,qualified_at=?,paid_at=?,paid_value=?,loss_reason=?,notes_encrypted=?,status_hash=? WHERE lead_ref=?''',
      (status,at,qualified,paid,amount,encrypt(ref,{'reason':reason}),encrypt(ref,{'notes':notes}),digest,ref))
    db.execute('INSERT OR IGNORE INTO lead_changes(lead_ref,at,old_status,new_status,snapshot_hash) VALUES(?,?,?,?,?)',(ref,at,row['status'],status,digest))
    audit(db,'sheet','lead.status','lead:'+ref,row['status']+' → '+status)
    return {'lead_ref':ref,'duplicate':False}

def overview(db):
    rows=[]
    for row in db.execute('SELECT * FROM leads ORDER BY received_at DESC LIMIT 300'):
        item=dict(row);item.update(decrypt(item['lead_ref'],item.pop('contact_encrypted')))
        item.update(decrypt(item['lead_ref'],item.pop('notes_encrypted')))
        item['loss_reason']=decrypt(item['lead_ref'],item['loss_reason']).get('reason','') if item['loss_reason'] else ''
        item.pop('status_hash',None);rows.append(item)
    return {'leads':rows,'total':db.execute('SELECT count(*) FROM leads').fetchone()[0],
      'stages':{status:db.execute('SELECT count(*) FROM leads WHERE status=?',(status,)).fetchone()[0] for status in STATES},
      'sheet_url':'https://docs.google.com/spreadsheets/d/example-id/edit'}
