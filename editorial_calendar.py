"""Daily editorial reservations, explicit experiments and measured outcomes."""
from __future__ import annotations
import json
import re
import unicodedata
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo

def settings():
    from brand import get
    b=get()
    return ZoneInfo(b['timezone']),{'Instagram':[tuple(map(int,t.split(':'))) for t in b['instagram_times']], 'Blog':[tuple(map(int,t.split(':'))) for t in b['blog_times']]}

ACTIVE=('draft','review','approved','published')


def create_schema(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS editorial_slots(channel TEXT NOT NULL,local_date TEXT NOT NULL,
      scheduled_at TEXT NOT NULL,test_arm TEXT NOT NULL,content_id INTEGER UNIQUE REFERENCES content(id),
      PRIMARY KEY(channel,local_date));
    CREATE TABLE IF NOT EXISTS media_measurements(content_id INTEGER NOT NULL REFERENCES content(id),
      window TEXT NOT NULL,captured_at TEXT NOT NULL,metrics_json TEXT NOT NULL,missing_json TEXT NOT NULL,
      PRIMARY KEY(content_id,window));
    CREATE TABLE IF NOT EXISTS worker_heartbeats(role TEXT PRIMARY KEY,at TEXT NOT NULL,status TEXT NOT NULL);
    ''')
    if 'published_url' not in {r['name'] for r in db.execute('PRAGMA table_info(content)')}:
        db.execute("ALTER TABLE content ADD COLUMN published_url TEXT NOT NULL DEFAULT ''")


def current_time(current=None):
    return (current or datetime.now(timezone.utc)).astimezone(settings()[0])


def iso(dt):return dt.astimezone(timezone.utc).isoformat(timespec='seconds')


def supported(kind,channel):return (channel=='Instagram' and kind in {'post','carousel','reel'}) or (channel=='Blog' and kind=='blog')


def ensure_horizon(db,current=None,days=21):
    local=current_time(current);today=local.date()
    for channel,times in settings()[1].items():
        for offset in range(days):
            day=today+timedelta(days=offset)
            hour,minute=times[day.toordinal()%len(times)]
            stamp=datetime(day.year,day.month,day.day,hour,minute,tzinfo=settings()[0])
            db.execute('INSERT OR IGNORE INTO editorial_slots(channel,local_date,scheduled_at,test_arm) VALUES(?,?,?,?)',
                       (channel,day.isoformat(),iso(stamp),f'{hour:02}:{minute:02}'))
        if local.hour<23:
            recovery=local+timedelta(minutes=30)
            db.execute('UPDATE editorial_slots SET scheduled_at=?,test_arm=? WHERE channel=? AND local_date=? AND content_id IS NULL AND scheduled_at<=?',
                       (iso(recovery),'Recuperação '+recovery.strftime('%H:%M'),channel,today.isoformat(),iso(local)))


def reserve(db,content_id,current=None):
    row=db.execute('SELECT kind,channel,status,scheduled_at,published_at FROM content WHERE id=?',(content_id,)).fetchone()
    if not row or not supported(row['kind'],row['channel']) or row['status'] not in ACTIVE:return None
    old=db.execute('SELECT scheduled_at FROM editorial_slots WHERE content_id=?',(content_id,)).fetchone()
    if old:return old[0]
    ensure_horizon(db,current)
    local=current_time(current)
    # Preserve explicit dates already approved by the owner during migration.
    existing_stamp=row['scheduled_at'] or (row['published_at'] if row['status']=='published' else None)
    if existing_stamp:
        stamp=datetime.fromisoformat(existing_stamp).astimezone(settings()[0])
        date=stamp.date().isoformat()
        existing=db.execute('SELECT content_id FROM editorial_slots WHERE channel=? AND local_date=?',(row['channel'],date)).fetchone()
        if not existing or existing[0] is None:
            db.execute('INSERT INTO editorial_slots(channel,local_date,scheduled_at,test_arm,content_id) VALUES(?,?,?,?,?) ON CONFLICT(channel,local_date) DO UPDATE SET scheduled_at=excluded.scheduled_at,test_arm=excluded.test_arm,content_id=excluded.content_id',
                       (row['channel'],date,iso(stamp),stamp.strftime('%H:%M'),content_id))
            return iso(stamp)
    slot=db.execute('SELECT * FROM editorial_slots WHERE channel=? AND content_id IS NULL AND scheduled_at>? ORDER BY scheduled_at LIMIT 1',
                    (row['channel'],iso(local+timedelta(minutes=5)))).fetchone()
    if not slot:raise ValueError('Calendário cheio; reprograme uma peça antes de criar outra')
    db.execute('UPDATE editorial_slots SET content_id=? WHERE channel=? AND local_date=?',(content_id,row['channel'],slot['local_date']))
    db.execute('UPDATE content SET scheduled_at=? WHERE id=?',(slot['scheduled_at'],content_id))
    return slot['scheduled_at']


def synchronize(db,current=None):
    ensure_horizon(db,current)
    db.execute("UPDATE editorial_slots SET content_id=NULL WHERE content_id IN (SELECT id FROM content WHERE status='rejected')")
    rows=db.execute("SELECT id FROM content WHERE (channel='Instagram' AND kind IN ('post','carousel','reel') OR channel='Blog' AND kind='blog') AND (status IN ('review','approved','published') OR (status='draft' AND creative_run_id<>'')) ORDER BY CASE status WHEN 'published' THEN 0 WHEN 'approved' THEN 1 ELSE 2 END,COALESCE(scheduled_at,created_at),id").fetchall()
    for row in rows:reserve(db,row['id'],current)


def approve_schedule(db,content_id,current=None):
    stamp=reserve(db,content_id,current)
    if not stamp:return None
    local=current_time(current)
    planned=datetime.fromisoformat(stamp).astimezone(settings()[0])
    if planned.date()<local.date():
        # An expired approval must get an explicit new slot, never a silent bulk send.
        db.execute('UPDATE editorial_slots SET content_id=NULL WHERE content_id=?',(content_id,))
        db.execute('UPDATE content SET scheduled_at=NULL WHERE id=?',(content_id,))
        stamp=reserve(db,content_id,current)
    return stamp


def reschedule(db,content_id,stamp,current=None):
    from app import audit,now
    row=db.execute('SELECT * FROM content WHERE id=?',(content_id,)).fetchone()
    if not row or row['status'] not in {'draft','review','approved'} or not supported(row['kind'],row['channel']):raise ValueError('Esta peça não pode ser reprogramada')
    parsed=datetime.fromisoformat(stamp)
    if parsed.tzinfo is None:raise ValueError('Informe o fuso horário da data')
    parsed=parsed.astimezone(settings()[0])
    if parsed<=current_time(current)+timedelta(minutes=2):raise ValueError('Escolha um horário pelo menos dois minutos à frente')
    outbox=db.execute('SELECT stage FROM instagram_outbox WHERE content_id=?',(content_id,)).fetchone()
    if outbox and outbox[0] in {'publishing','needs_review','published'}:raise ValueError('Concilie a publicação em andamento antes de reprogramar')
    other=db.execute('SELECT content_id FROM editorial_slots WHERE channel=? AND local_date=?',(row['channel'],parsed.date().isoformat())).fetchone()
    if other and other[0] not in {None,content_id}:raise ValueError('Esse canal já tem uma peça reservada neste dia')
    db.execute('UPDATE editorial_slots SET content_id=NULL WHERE content_id=?',(content_id,))
    db.execute('INSERT INTO editorial_slots(channel,local_date,scheduled_at,test_arm,content_id) VALUES(?,?,?,?,?) ON CONFLICT(channel,local_date) DO UPDATE SET scheduled_at=excluded.scheduled_at,test_arm=excluded.test_arm,content_id=excluded.content_id',
               (row['channel'],parsed.date().isoformat(),iso(parsed),parsed.strftime('%H:%M'),content_id))
    db.execute('UPDATE content SET scheduled_at=?,updated_at=? WHERE id=?',(iso(parsed),now(),content_id))
    audit(db,'admin','calendar.reschedule',f'content:{content_id}',iso(parsed))


def clean_caption(text):
    """Remove only the explicit production-note paragraphs requested by the owner."""
    def key(s):return ''.join(c for c in unicodedata.normalize('NFD',s.lower()) if unicodedata.category(c)!='Mn')
    kept=[]
    for paragraph in re.split(r'\n\s*\n',text.strip()):
        normalized=key(paragraph.strip())
        note=bool(re.match(r'^(?:imagem|imagens|fotografias?|ilustracao|ilustracoes|cenas?|conteudo)\b',normalized) and
                  re.search(r'\b(?:ia|inteligencia artificial|ilustrativ\w*)\b',normalized))
        continuation=bool(re.match(r'^(?:nao (?:mostram?|representam?)|trilha instrumental original, sem depoimento)',normalized))
        if not note and not continuation:kept.append(paragraph.strip())
    return '\n\n'.join(kept)


def clean_existing_captions(db):
    from app import audit,now
    from creative_store import content_digest
    changed=[]
    for row in db.execute("SELECT id,body,status FROM content WHERE channel='Instagram' AND status IN ('draft','review','approved')").fetchall():
        caption=clean_caption(row['body'])
        if caption==row['body'] or not caption:continue
        box=db.execute('SELECT stage FROM instagram_outbox WHERE content_id=?',(row['id'],)).fetchone()
        if box and box[0] in {'publishing','needs_review','published'}:continue
        db.execute('UPDATE content SET body=?,updated_at=? WHERE id=?',(caption,now(),row['id']))
        media=db.execute('SELECT spec_json FROM creative_media WHERE content_id=?',(row['id'],)).fetchone()
        if media:
            spec=json.loads(media[0]);spec['caption']=caption
            db.execute('UPDATE creative_media SET spec_json=? WHERE content_id=?',(json.dumps(spec,ensure_ascii=False),row['id']))
            if row['status']=='approved':
                db.execute('UPDATE content SET approved_digest=? WHERE id=?',(content_digest(db,row['id']),row['id']))
        if box:db.execute("UPDATE instagram_outbox SET stage='preparing',container_id='',error='',updated_at=? WHERE content_id=?",(now(),row['id']))
        audit(db,'admin','caption.production_note_removed',f'content:{row["id"]}','Remoção das observações finais conforme solicitação do proprietário; mídia preservada')
        changed.append(row['id'])
    return changed


def overview(db,current=None):
    today=current_time(current).date();start=(today-timedelta(days=2)).isoformat();end=(today+timedelta(days=13)).isoformat()
    slots=[]
    for row in db.execute('''SELECT s.*,c.title,c.kind,c.status,c.published_at,c.published_url,
      (SELECT detail FROM job_runs j WHERE j.job=CASE WHEN s.channel='Blog' THEN 'blog_publish_' ELSE 'instagram_publish_' END||s.content_id ORDER BY id DESC LIMIT 1) error,
      (SELECT status FROM job_runs j WHERE j.job=CASE WHEN s.channel='Blog' THEN 'blog_publish_' ELSE 'instagram_publish_' END||s.content_id ORDER BY id DESC LIMIT 1) last_result
      FROM editorial_slots s LEFT JOIN content c ON c.id=s.content_id WHERE local_date BETWEEN ? AND ? ORDER BY local_date,channel''',(start,end)):
        item=dict(row);item['overdue']=bool(item['status']=='approved' and item['scheduled_at']<iso(current_time(current)))
        slots.append(item)
    measurements=[dict(r) for r in db.execute('SELECT m.*,c.title,c.kind,c.scheduled_at,c.published_at FROM media_measurements m JOIN content c ON c.id=m.content_id ORDER BY captured_at DESC LIMIT 100')]
    for m in measurements:m['metrics']=json.loads(m.pop('metrics_json'));m['missing']=json.loads(m.pop('missing_json'))
    groups={}
    for m in measurements:
        if m['window']!='72h':continue
        if not m['scheduled_at'] or abs((datetime.fromisoformat(m['published_at'])-datetime.fromisoformat(m['scheduled_at'])).total_seconds())>900:continue
        arm=datetime.fromisoformat(m['scheduled_at']).astimezone(settings()[0]).strftime('%H:%M');key=m['kind']+' · '+arm
        g=groups.setdefault(key,{'format':m['kind'],'hour':arm,'samples':0,'reach':[],'interactions':[]})
        g['samples']+=1
        for metric in ['reach','interactions']:
            if metric in m['metrics']:g[metric].append(m['metrics'][metric])
    for g in groups.values():
        for metric in ['reach','interactions']:g[metric]=round(sum(g[metric])/len(g[metric]),1) if g[metric] else None
        g['conclusion']='Amostra inicial; sem vencedor' if g['samples']<3 else 'Comparação descritiva; conteúdo também influencia'
    return {'slots':slots,'experiments':list(groups.values()),'measurements':measurements[:20],
            'heartbeats':[dict(r) for r in db.execute('SELECT * FROM worker_heartbeats')],
            'timezone':__import__('brand').get()['timezone'],'daily_target':{'Instagram':1,'Blog':1},
            'blog_metrics':'GA4/Search Console ainda não conectados; horários são hipóteses, sem resultados inventados.'}
