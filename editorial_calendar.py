"""Configurable daily editorial reservations and publication pacing."""
from __future__ import annotations
import json,re,unicodedata
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
def settings():
    from brand import get
    b=get()
    return ZoneInfo(b['timezone']),{'Instagram':[tuple(map(int,t.split(':'))) for t in b['instagram_times']], 'Blog':[tuple(map(int,t.split(':'))) for t in b['blog_times']]}

ACTIVE=('draft','review','approved','published')


def policy(db):
    from secret_store import setting
    raw=setting(db,'publication_policy','')
    return json.loads(raw) if raw else {c:{'daily':1,'gap_minutes':60} for c in settings()[1]}


def save_policy(db,data):
    from app import audit
    from secret_store import put_setting
    if not isinstance(data,dict) or set(data)!=set(settings()[1]):raise ValueError('Informe Instagram e Blog')
    for c in settings()[1]:
        item=data[c]
        if not isinstance(item,dict) or set(item)!={'daily','gap_minutes'}:raise ValueError('Configuração de canal inválida')
        if type(item['daily']) is not int or not 1<=item['daily']<=6:raise ValueError('Escolha entre 1 e 6 publicações por dia em cada canal')
        if type(item['gap_minutes']) is not int or not 5<=item['gap_minutes']<=360:raise ValueError('Intervalo entre 5 e 360 minutos')
    put_setting(db,'publication_policy',json.dumps(data))
    # Only empty reservations are rebuilt. Assigned dates and approvals are preserved.
    db.execute('DELETE FROM editorial_slots WHERE content_id IS NULL')
    ensure_horizon(db)
    audit(db,'admin','publication.policy','calendar',json.dumps(data,ensure_ascii=False))
    return data


def create_schema(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS editorial_slots(channel TEXT NOT NULL,local_date TEXT NOT NULL,
      slot_index INTEGER NOT NULL DEFAULT 0,scheduled_at TEXT NOT NULL,test_arm TEXT NOT NULL,
      content_id INTEGER UNIQUE REFERENCES content(id),PRIMARY KEY(channel,local_date,slot_index));
    CREATE TABLE IF NOT EXISTS media_measurements(content_id INTEGER NOT NULL REFERENCES content(id),
      window TEXT NOT NULL,captured_at TEXT NOT NULL,metrics_json TEXT NOT NULL,missing_json TEXT NOT NULL,
      PRIMARY KEY(content_id,window));
    CREATE TABLE IF NOT EXISTS worker_heartbeats(role TEXT PRIMARY KEY,at TEXT NOT NULL,status TEXT NOT NULL);''')
    # Obtain the write lock before inspecting; concurrent service starts cannot migrate twice.
    db.execute('SAVEPOINT multi_slot_schema')
    try:
        db.execute("UPDATE settings SET value=value WHERE name='publication_policy'")
        if 'slot_index' not in {r['name'] for r in db.execute('PRAGMA table_info(editorial_slots)')}:
            db.execute('''CREATE TABLE editorial_slots_multi(channel TEXT NOT NULL,local_date TEXT NOT NULL,
              slot_index INTEGER NOT NULL DEFAULT 0,scheduled_at TEXT NOT NULL,test_arm TEXT NOT NULL,
              content_id INTEGER UNIQUE REFERENCES content(id),PRIMARY KEY(channel,local_date,slot_index))''')
            db.execute('INSERT INTO editorial_slots_multi(channel,local_date,scheduled_at,test_arm,content_id) SELECT channel,local_date,scheduled_at,test_arm,content_id FROM editorial_slots')
            db.execute('DROP TABLE editorial_slots')
            db.execute('ALTER TABLE editorial_slots_multi RENAME TO editorial_slots')
        db.execute('RELEASE multi_slot_schema')
    except Exception:
        db.execute('ROLLBACK TO multi_slot_schema');db.execute('RELEASE multi_slot_schema');raise
    if 'published_url' not in {r['name'] for r in db.execute('PRAGMA table_info(content)')}:
        db.execute("ALTER TABLE content ADD COLUMN published_url TEXT NOT NULL DEFAULT ''")


def current_time(current=None):return (current or datetime.now(timezone.utc)).astimezone(settings()[0])
def iso(dt):return dt.astimezone(timezone.utc).isoformat(timespec='seconds')
def supported(kind,channel):return (channel=='Instagram' and kind in {'post','carousel','reel'}) or (channel=='Blog' and kind=='blog')


def publication_available(db,kind,channel,current=None):
    if not supported(kind,channel):return True
    local=current_time(current);start=local.replace(hour=0,minute=0,second=0,microsecond=0)
    kinds=('post','carousel','reel') if channel=='Instagram' else ('blog',)
    marks=','.join('?' for _ in kinds)
    settings=policy(db)[channel]
    count=db.execute(f"SELECT count(*) FROM content WHERE channel=? AND kind IN ({marks}) AND status='published' AND published_at>=? AND published_at<?",(channel,*kinds,iso(start),iso(start+timedelta(days=1)))).fetchone()[0]
    if count>=settings['daily']:return False
    last=db.execute(f"SELECT max(published_at) FROM content WHERE channel=? AND kind IN ({marks}) AND status='published'",(channel,*kinds)).fetchone()[0]
    return not last or datetime.fromisoformat(last)<=local.astimezone(timezone.utc)-timedelta(minutes=settings['gap_minutes'])


def ensure_horizon(db,current=None,days=21):
    local=current_time(current);today=local.date();rules=policy(db)
    for channel,times in settings()[1].items():
        limit=rules[channel]['daily'];gap=rules[channel]['gap_minutes']
        for offset in range(days):
            day=today+timedelta(days=offset);key=day.isoformat()
            rows=[dict(r) for r in db.execute('SELECT * FROM editorial_slots WHERE channel=? AND local_date=? ORDER BY slot_index',(channel,key))]
            used={r['slot_index'] for r in rows};stamps=[datetime.fromisoformat(r['scheduled_at']).astimezone(settings()[0]) for r in rows]
            if limit<=len(times):
                choices=sorted(times[(day.toordinal()+i)%len(times)] for i in range(limit))
            else:choices=[(7+(i*14//(limit-1)),30) for i in range(limit)]
            for position in range(limit):
                if position in used:continue
                hour,minute=choices[position];stamp=datetime(day.year,day.month,day.day,hour,minute,tzinfo=settings()[0])
                if stamps:
                    # Preserve previous explicit dates while finding a distinct new position.
                    for _ in range(96):
                        if all(abs((stamp-other).total_seconds())>=gap*60 for other in stamps):break
                        stamp+=timedelta(minutes=max(5,gap))
                if stamp.date()!=day:continue
                if day==today and stamp<=local+timedelta(minutes=5):
                    stamp=max(local+timedelta(minutes=30),max(stamps,default=local)+timedelta(minutes=gap))
                    if stamp.date()!=day:continue
                db.execute('INSERT OR IGNORE INTO editorial_slots(channel,local_date,slot_index,scheduled_at,test_arm) VALUES(?,?,?,?,?)',(channel,key,position,iso(stamp),stamp.strftime('%H:%M')))
                stamps.append(stamp)
        # Recover expired empty positions without modifying an assigned piece.
        cursor=local+timedelta(minutes=30)
        for row in db.execute('SELECT * FROM editorial_slots WHERE channel=? AND local_date=? AND content_id IS NULL AND scheduled_at<=? ORDER BY scheduled_at',(channel,today.isoformat(),iso(local))).fetchall():
            taken=[datetime.fromisoformat(r[0]).astimezone(settings()[0]) for r in db.execute('SELECT scheduled_at FROM editorial_slots WHERE channel=? AND local_date=? AND slot_index<>?',(channel,today.isoformat(),row['slot_index']))]
            while any(abs((cursor-other).total_seconds())<gap*60 for other in taken):cursor+=timedelta(minutes=max(5,gap))
            if cursor.date()!=today:continue
            db.execute('UPDATE editorial_slots SET scheduled_at=?,test_arm=? WHERE channel=? AND local_date=? AND slot_index=?',(iso(cursor),'Recuperação '+cursor.strftime('%H:%M'),channel,today.isoformat(),row['slot_index']))
            cursor+=timedelta(minutes=gap)


def reserve(db,content_id,current=None):
    row=db.execute('SELECT kind,channel,status,scheduled_at,published_at FROM content WHERE id=?',(content_id,)).fetchone()
    if not row or not supported(row['kind'],row['channel']) or row['status'] not in ACTIVE:return None
    old=db.execute('SELECT scheduled_at FROM editorial_slots WHERE content_id=?',(content_id,)).fetchone()
    if old:return old[0]
    ensure_horizon(db,current);local=current_time(current)
    existing_stamp=row['scheduled_at'] or (row['published_at'] if row['status']=='published' else None)
    if existing_stamp:
        stamp=datetime.fromisoformat(existing_stamp).astimezone(settings()[0]);day=stamp.date().isoformat()
        slots=db.execute('SELECT * FROM editorial_slots WHERE channel=? AND local_date=? ORDER BY slot_index',(row['channel'],day)).fetchall()
        empty=next((s for s in slots if s['content_id'] is None),None)
        if empty or len(slots)<policy(db)[row['channel']]['daily'] or row['status']=='published':
            index=empty['slot_index'] if empty else max([s['slot_index'] for s in slots],default=-1)+1
            db.execute('INSERT INTO editorial_slots(channel,local_date,slot_index,scheduled_at,test_arm,content_id) VALUES(?,?,?,?,?,?) ON CONFLICT(channel,local_date,slot_index) DO UPDATE SET scheduled_at=excluded.scheduled_at,test_arm=excluded.test_arm,content_id=excluded.content_id',(row['channel'],day,index,iso(stamp),stamp.strftime('%H:%M'),content_id))
            return iso(stamp)
    slot=db.execute('SELECT * FROM editorial_slots WHERE channel=? AND content_id IS NULL AND scheduled_at>? ORDER BY scheduled_at LIMIT 1',(row['channel'],iso(local+timedelta(minutes=5)))).fetchone()
    if not slot:raise ValueError('Calendário cheio; reprograme uma peça antes de criar outra')
    db.execute('UPDATE editorial_slots SET content_id=? WHERE channel=? AND local_date=? AND slot_index=?',(content_id,row['channel'],slot['local_date'],slot['slot_index']))
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
    if datetime.fromisoformat(stamp).astimezone(settings()[0]).date()<current_time(current).date():
        db.execute('UPDATE editorial_slots SET content_id=NULL WHERE content_id=?',(content_id,))
        db.execute('UPDATE content SET scheduled_at=NULL WHERE id=?',(content_id,));stamp=reserve(db,content_id,current)
    return stamp


def reschedule(db,content_id,stamp,current=None):
    from app import audit,now
    row=db.execute('SELECT * FROM content WHERE id=?',(content_id,)).fetchone()
    if not row or row['status'] not in {'draft','review','approved'} or not supported(row['kind'],row['channel']):raise ValueError('Esta peça não pode ser reprogramada')
    parsed=datetime.fromisoformat(stamp)
    if parsed.tzinfo is None:raise ValueError('Informe o fuso horário da data')
    parsed=parsed.astimezone(settings()[0])
    if parsed<=current_time(current)+timedelta(minutes=2):raise ValueError('Escolha um horário pelo menos dois minutos à frente')
    box=db.execute('SELECT stage FROM instagram_outbox WHERE content_id=?',(content_id,)).fetchone()
    if box and box[0] in {'publishing','needs_review','published'}:raise ValueError('Concilie a publicação em andamento antes de reprogramar')
    day=parsed.date().isoformat();channel=row['channel'];rule=policy(db)[channel]
    others=db.execute('SELECT content_id,slot_index,scheduled_at FROM editorial_slots WHERE channel=? AND local_date=? AND content_id IS NOT NULL AND content_id<>?',(channel,day,content_id)).fetchall()
    if len(others)>=rule['daily']:raise ValueError('A capacidade diária já está reservada; aumente o limite ou escolha outro dia')
    if any(abs((parsed-datetime.fromisoformat(r['scheduled_at']).astimezone(settings()[0])).total_seconds())<rule['gap_minutes']*60 for r in others):raise ValueError('Respeite o intervalo mínimo entre publicações deste canal')
    empty=db.execute('SELECT slot_index FROM editorial_slots WHERE channel=? AND local_date=? AND (content_id IS NULL OR content_id=?) ORDER BY slot_index LIMIT 1',(channel,day,content_id)).fetchone()
    index=empty[0] if empty else max([r['slot_index'] for r in others],default=-1)+1
    db.execute('UPDATE editorial_slots SET content_id=NULL WHERE content_id=?',(content_id,))
    db.execute('INSERT INTO editorial_slots(channel,local_date,slot_index,scheduled_at,test_arm,content_id) VALUES(?,?,?,?,?,?) ON CONFLICT(channel,local_date,slot_index) DO UPDATE SET scheduled_at=excluded.scheduled_at,test_arm=excluded.test_arm,content_id=excluded.content_id',(channel,day,index,iso(parsed),parsed.strftime('%H:%M'),content_id))
    db.execute('UPDATE content SET scheduled_at=?,updated_at=? WHERE id=?',(iso(parsed),now(),content_id));audit(db,'admin','calendar.reschedule',f'content:{content_id}',iso(parsed))

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
      FROM editorial_slots s LEFT JOIN content c ON c.id=s.content_id WHERE local_date BETWEEN ? AND ? ORDER BY local_date,s.scheduled_at,channel''',(start,end)):
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
            'timezone':__import__('brand').get()['timezone'],'daily_target':{c:r['daily'] for c,r in policy(db).items()},'publication_policy':policy(db),
            'blog_metrics':'Horários são hipóteses; consulte GA4/Search Console em Resultados. Comparações de horário não comprovam causalidade.'}
