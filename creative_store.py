"""Creative queue, immutable media manifests and curated brand library."""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parent
from library import LIBRARY, initialize
initialize()
ENGINE = ROOT / 'creative-engine'
SOCIAL_KINDS = {'post', 'carousel', 'reel'}
MEDIA_PATTERN = r'(?:post-\d+\.jpg|carousel-\d+-\d+\.jpg|reel-\d+(?:-cover|-frame-\d+)?\.(?:mp4|jpg))'
ROLES = [
    ('analyst', 'Analista', 'Resultados reais e aprendizados'),
    ('strategist', 'Estrategista', 'Objetivo, público e conceito'),
    ('researcher', 'Pesquisador', 'Dúvidas, sinais e evidências'),
    ('copywriter', 'Copywriter', 'Gancho, narrativa e legenda'),
    ('seo-editor', 'Editor SEO', 'Relação com blog e próximo passo'),
    ('art-director', 'Diretor de arte', 'Composição e biblioteca da marca'),
    ('motion-director', 'Diretor de motion', 'Ritmo, cenas e roteiro visual'),
    ('reviewer', 'Revisor', 'Texto, fatos e arquivos renderizados'),
]


def create_schema(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS creative_runs(
      id TEXT PRIMARY KEY, day_key TEXT UNIQUE, kind TEXT NOT NULL, brief TEXT NOT NULL,
      status TEXT NOT NULL, stage TEXT NOT NULL DEFAULT '', round INTEGER NOT NULL DEFAULT 0,
      state_json TEXT NOT NULL DEFAULT '{}', content_id INTEGER REFERENCES content(id),
      error TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS creative_steps(
      run_id TEXT NOT NULL REFERENCES creative_runs(id), stage TEXT NOT NULL, round INTEGER NOT NULL,
      status TEXT NOT NULL, input_hash TEXT NOT NULL DEFAULT '', output_json TEXT NOT NULL DEFAULT '{}',
      skill_hash TEXT NOT NULL DEFAULT '', duration_ms INTEGER NOT NULL DEFAULT 0,
      updated_at TEXT NOT NULL, PRIMARY KEY(run_id,stage,round));
    CREATE TABLE IF NOT EXISTS creative_media(
      content_id INTEGER PRIMARY KEY REFERENCES content(id), manifest_json TEXT NOT NULL,
      spec_json TEXT NOT NULL, review_json TEXT NOT NULL, updated_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS creative_feedback(
      id INTEGER PRIMARY KEY, content_id INTEGER REFERENCES content(id), action TEXT NOT NULL,
      note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
    ''')
    columns = {r['name'] for r in db.execute('PRAGMA table_info(content)')}
    for name in ('creative_run_id', 'approved_digest'):
        if name not in columns:
            db.execute(f"ALTER TABLE content ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")


def catalog():
    file = LIBRARY / 'catalog.json'
    return json.loads(file.read_text()) if file.exists() else {'version': 2, 'assets': []}


def library_file(asset_id):
    item = next((a for a in catalog()['assets'] if a['id'] == asset_id), None)
    if not item:
        raise ValueError('Elemento não encontrado')
    file = (LIBRARY / item['file']).resolve()
    if not file.is_relative_to(LIBRARY.resolve()) or not file.is_file():
        raise ValueError('Arquivo da biblioteca indisponível')
    return file


def enqueue(db, brief, kind='auto', day_key=None):
    from app import audit, clean, now
    if kind not in SOCIAL_KINDS | {'auto'}:
        raise ValueError('Formato criativo inválido')
    brief = clean(brief, 1500)
    if not brief:
        raise ValueError('Descreva o objetivo ou a pauta')
    if day_key:
        old = db.execute('SELECT id FROM creative_runs WHERE day_key=?', (day_key,)).fetchone()
        if old:
            return old['id']
    if db.execute("SELECT count(*) FROM creative_runs WHERE status IN ('queued','running')").fetchone()[0] >= 5:
        raise ValueError('A equipe já tem cinco trabalhos na fila. Aguarde a conclusão.')
    run_id = secrets.token_hex(12)
    db.execute('INSERT INTO creative_runs(id,day_key,kind,brief,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',
               (run_id, day_key, kind, brief, 'queued', now(), now()))
    audit(db, 'admin' if not day_key else 'scheduler', 'creative.enqueue', f'run:{run_id}', brief[:150])
    return run_id


def public_run(row, db):
    result = {k: row[k] for k in ('id','kind','brief','status','stage','round','content_id','error','created_at','updated_at')}
    result['steps'] = [dict(r) for r in db.execute(
        'SELECT stage,round,status,duration_ms,updated_at FROM creative_steps WHERE run_id=? ORDER BY round,updated_at', (row['id'],))]
    return result


def overview(db):
    return {'roles': [{'id': x, 'name': y, 'purpose': z} for x,y,z in ROLES],
            'runs': [public_run(r, db) for r in db.execute('SELECT * FROM creative_runs ORDER BY created_at DESC LIMIT 20')],
            'feedback': [dict(r) for r in db.execute('SELECT * FROM creative_feedback ORDER BY id DESC LIMIT 12')],
            'library': [{**a, 'url': f"/api/library/{a['id']}"} for a in catalog()['assets']],
            'engine': 'LangGraph + Codex CLI', 'automatic_images': False}


def media_details(db, content_id):
    row = db.execute('SELECT manifest_json,review_json FROM creative_media WHERE content_id=?', (content_id,)).fetchone()
    if not row:
        return None
    manifest = json.loads(row['manifest_json'])
    return {'files': [{**x, 'url': '/api/media/' + x['name']} for x in manifest],
            'review': json.loads(row['review_json'])}


def media_path(name):
    from app import DB_PATH
    if not re.fullmatch(MEDIA_PATTERN, name):
        raise ValueError('Nome de mídia inválido')
    return DB_PATH.parent / 'media' / name


def content_digest(db, content_id, verify_files=True):
    row = db.execute('SELECT id,title,body,kind,channel FROM content WHERE id=?', (content_id,)).fetchone()
    media = db.execute('SELECT manifest_json,spec_json FROM creative_media WHERE content_id=?', (content_id,)).fetchone()
    if not row or not media:
        raise ValueError('A peça precisa ser criada e renderizada pela equipe antes da aprovação')
    manifest = json.loads(media['manifest_json'])
    if not manifest:
        raise ValueError('A peça não tem arquivos renderizados')
    for item in manifest:
        if verify_files:
            file = media_path(item['name'])
            if not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest() != item['sha256']:
                raise ValueError('Um arquivo foi alterado. Renderize e revise novamente antes de publicar.')
    payload = {'content': dict(row), 'manifest': manifest, 'spec': json.loads(media['spec_json'])}
    return hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def assert_approved_version(db, content_id):
    row = db.execute('SELECT status,approved_digest FROM content WHERE id=?', (content_id,)).fetchone()
    if not row or row['status'] not in {'approved','published'} or not row['approved_digest']:
        raise ValueError('A versão não tem aprovação humana registrada')
    digest = content_digest(db, content_id)
    if not hmac.compare_digest(digest, row['approved_digest']):
        raise ValueError('O conteúdo mudou depois da aprovação. É necessária uma nova aprovação.')
    return digest


def file_signature(name, expires, digest):
    from app import SECRET
    return hmac.new(SECRET.encode(),f'instagram:v2:{name}:{expires}:{digest}'.encode(),hashlib.sha256).hexdigest()


def register_media(db, content_id, spec, files, review):
    from app import now
    selected={p.get('image','') for p in [*spec.get('slides',[]),*spec.get('scenes',[])]}
    generated=any(a.get('provenance',{}).get('ai_generated') for a in catalog()['assets'] if Path(a['file']).name in selected)
    spec={**spec,'ai_generated':bool(spec.get('ai_generated') or generated)}
    manifest=[]
    for file in files:
        path=Path(file)
        if media_path(path.name).resolve() != path.resolve() or not path.is_file():
            raise ValueError('Render fora da pasta de mídia')
        manifest.append({'name':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'bytes':path.stat().st_size})
    db.execute('''INSERT INTO creative_media(content_id,manifest_json,spec_json,review_json,updated_at) VALUES(?,?,?,?,?)
      ON CONFLICT(content_id) DO UPDATE SET manifest_json=excluded.manifest_json,spec_json=excluded.spec_json,
      review_json=excluded.review_json,updated_at=excluded.updated_at''',
      (content_id,json.dumps(manifest),json.dumps(spec,ensure_ascii=False),json.dumps(review,ensure_ascii=False),now()))


def import_seed():
    """Fresh installations start empty; no customer content is bundled."""
    return None
