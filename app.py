"""Camaleão Marketing Lab: dependency-free, single-owner operations dashboard."""
from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import math
import os
import re
import secrets
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
DB_PATH = Path(os.getenv("CML_DB_PATH", str(ROOT / "data" / "cml-marketing.db")))
SECRET = os.getenv("CML_APP_SECRET", "")
INGEST_SECRET = os.getenv("CML_INGEST_SECRET", "")
SECURE_COOKIE = os.getenv("CML_COOKIE_SECURE", "false").lower() == "true"
MAX_BODY = 6_000_000
LOGIN_ATTEMPTS: dict[str, list[float]] = {}
RADAR_LOCK = threading.Lock()
STATUSES = {"draft", "review", "approved", "rejected", "published"}
TYPES = {"post", "carousel", "blog", "reel", "idea"}
CHANNELS = {"Instagram", "Facebook", "Blog", "Google", "Multi"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def next_publish_at(db: sqlite3.Connection, kind: str, channel: str) -> str | None:
    """Reserve one approved article/post per São Paulo day."""
    social = channel == 'Instagram' and kind in {'post','carousel','reel'}
    hour = 8 if kind == "blog" and channel == "Blog" else 18 if social else None
    if hour is None:
        return None
    local_tz = ZoneInfo(__import__("brand").get()["timezone"])
    current = datetime.now(local_tz)
    slot = current.replace(hour=hour, minute=0, second=0, microsecond=0)
    if slot <= current:
        slot += timedelta(days=1)
    kinds = ('post','carousel','reel') if social else (kind,)
    placeholders=','.join('?' for _ in kinds)
    reservations = db.execute(f"SELECT COALESCE(scheduled_at,published_at) FROM content WHERE kind IN ({placeholders}) AND channel=? AND status IN ('approved','published') AND COALESCE(scheduled_at,published_at) IS NOT NULL",
                              (*kinds, channel))
    reserved_days = set()
    for row in reservations:
        try:
            reserved_days.add(datetime.fromisoformat(row[0]).astimezone(local_tz).date())
        except ValueError:
            continue
    while slot.date() in reserved_days:
        slot += timedelta(days=1)
    return slot.astimezone(timezone.utc).isoformat(timespec="seconds")


def daily_publication_available(db: sqlite3.Connection, kind: str, channel: str) -> bool:
    local = datetime.now(ZoneInfo(__import__("brand").get()["timezone"]))
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    bounds = (start.astimezone(timezone.utc).isoformat(timespec="seconds"),
              (start + timedelta(days=1)).astimezone(timezone.utc).isoformat(timespec="seconds"))
    kinds=('post','carousel','reel') if channel=='Instagram' and kind in {'post','carousel','reel'} else (kind,)
    placeholders=','.join('?' for _ in kinds)
    return not db.execute(f"SELECT 1 FROM content WHERE kind IN ({placeholders}) AND channel=? AND status='published' AND published_at>=? AND published_at<? LIMIT 1",
                          (*kinds, channel, *bounds)).fetchone()


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=10, factory=ClosingConnection)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA journal_mode=WAL")
    return db


def init_db() -> None:
    from library import initialize
    initialize()
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL,
          salt TEXT NOT NULL, password_hash TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS content(id INTEGER PRIMARY KEY, kind TEXT NOT NULL,
          title TEXT NOT NULL, channel TEXT NOT NULL, summary TEXT NOT NULL DEFAULT '',
          body TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'draft',
          source_url TEXT NOT NULL DEFAULT '', scheduled_at TEXT, created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL, published_at TEXT);
        CREATE TABLE IF NOT EXISTS radar(id INTEGER PRIMARY KEY, title TEXT NOT NULL,
          source TEXT NOT NULL, url TEXT UNIQUE NOT NULL, category TEXT NOT NULL,
          score INTEGER NOT NULL, seen_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, event_type TEXT NOT NULL,
          source TEXT NOT NULL, campaign TEXT NOT NULL DEFAULT '', lead_ref TEXT NOT NULL DEFAULT '',
          value REAL NOT NULL DEFAULT 0, occurred_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, at TEXT NOT NULL,
          actor TEXT NOT NULL, action TEXT NOT NULL, entity TEXT NOT NULL,
          detail TEXT NOT NULL, prev_hash TEXT NOT NULL, hash TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS job_runs(id INTEGER PRIMARY KEY, job TEXT NOT NULL,
          status TEXT NOT NULL, detail TEXT NOT NULL, at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS webhook_receipts(external_id TEXT PRIMARY KEY, event_id INTEGER NOT NULL,
          received_at TEXT NOT NULL, payload_hash TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS settings(name TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS instagram_outbox(content_id INTEGER PRIMARY KEY REFERENCES content(id),
          stage TEXT NOT NULL, container_id TEXT NOT NULL DEFAULT '', media_id TEXT NOT NULL DEFAULT '',
          error TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_content_status ON content(status);
        CREATE INDEX IF NOT EXISTS idx_events_type_time ON events(event_type, occurred_at);
        """)
        columns = {r["name"] for r in db.execute("PRAGMA table_info(webhook_receipts)")}
        if "payload_hash" not in columns:
            db.execute("ALTER TABLE webhook_receipts ADD COLUMN payload_hash TEXT NOT NULL DEFAULT ''")
        content_columns = {r["name"] for r in db.execute("PRAGMA table_info(content)")}
        if "scheduled_at" not in content_columns:
            db.execute("ALTER TABLE content ADD COLUMN scheduled_at TEXT")
        from creative_store import create_schema
        create_schema(db)
        from editorial_calendar import create_schema as calendar_schema,synchronize
        calendar_schema(db)
        synchronize(db)
        from leads import create_schema as lead_schema
        lead_schema(db)
        if not db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            password = os.getenv("CML_ADMIN_PASSWORD", "")
            if len(password) < 16:
                raise RuntimeError("CML_ADMIN_PASSWORD precisa ter pelo menos 16 caracteres no primeiro início")
            salt = secrets.token_hex(16)
            digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1).hex()
            db.execute("INSERT INTO users(username,salt,password_hash) VALUES(?,?,?)", ("admin", salt, digest))
            audit(db, "system", "bootstrap", "user:admin", "Administrador criado")


def audit(db: sqlite3.Connection, actor: str, action: str, entity: str, detail: str) -> None:
    previous = db.execute("SELECT hash FROM audit ORDER BY id DESC LIMIT 1").fetchone()
    prev_hash = previous[0] if previous else "0" * 64
    at = now()
    payload = json.dumps([at, actor, action, entity, detail, prev_hash], ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode()).hexdigest()
    db.execute("INSERT INTO audit(at,actor,action,entity,detail,prev_hash,hash) VALUES(?,?,?,?,?,?,?)",
               (at, actor, action, entity, detail, prev_hash, digest))


def verify_audit(db: sqlite3.Connection) -> bool:
    previous = "0" * 64
    for row in db.execute("SELECT at,actor,action,entity,detail,prev_hash,hash FROM audit ORDER BY id"):
        payload = json.dumps([row["at"], row["actor"], row["action"], row["entity"], row["detail"], previous], ensure_ascii=False, separators=(",", ":"))
        if row["prev_hash"] != previous or hashlib.sha256(payload.encode()).hexdigest() != row["hash"]:
            return False
        previous = row["hash"]
    return True


def sign_session() -> tuple[str, str]:
    raw = json.dumps({"u": "admin", "exp": int(time.time()) + 7 * 86400, "n": secrets.token_hex(12)}, separators=(",", ":"))
    token = base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")
    signature = hmac.new(SECRET.encode(), token.encode(), hashlib.sha256).hexdigest()
    value = f"{token}.{signature}"
    csrf = hmac.new(SECRET.encode(), ("csrf:" + value).encode(), hashlib.sha256).hexdigest()
    return value, csrf


def validate_session(value: str) -> str | None:
    try:
        token, signature = value.split(".", 1)
        expected = hmac.new(SECRET.encode(), token.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        payload = json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
        return payload["u"] if payload["exp"] > time.time() and payload["u"] == "admin" else None
    except (ValueError, KeyError, TypeError):
        return None


def clean(value: object, limit: int = 300) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()[:limit]


def row_dict(row: sqlite3.Row) -> dict:
    return dict(row)


def instagram_media_signature(content_id: int, expires: int) -> str:
    message = f"instagram:{content_id}:{expires}".encode()
    return hmac.new(SECRET.encode(), message, hashlib.sha256).hexdigest()


def seo_score(item: dict) -> int:
    if item["kind"] != "blog":
        return 0
    title, summary, body = item["title"], item["summary"], item["body"]
    words = len(re.findall(r"\b\w+\b", body))
    return min(100, (25 if 35 <= len(title) <= 65 else 10) +
               (25 if 120 <= len(summary) <= 160 else 10) +
               (30 if words >= 600 else 15 if words >= 250 else 0) +
               (10 if "## " in body else 0) + (10 if "http" in body else 0))


def dashboard(db: sqlite3.Connection) -> dict:
    from secret_store import setting
    content = [row_dict(r) for r in db.execute("SELECT * FROM content ORDER BY updated_at DESC LIMIT 100")]
    for item in content:
        item["seo_score"] = seo_score(item)
        media_name = f"{item['kind']}-{item['id']}.{'mp4' if item['kind'] == 'reel' else 'jpg'}"
        item["media_url"] = f"/api/media/{media_name}" if item["kind"] in {"post", "reel"} and (DB_PATH.parent / "media" / media_name).exists() else None
        from creative_store import media_details
        item['creative_media']=media_details(db,item['id'])
    radar = [row_dict(r) for r in db.execute("SELECT * FROM radar ORDER BY score DESC, seen_at DESC LIMIT 30")]
    events = [row_dict(r) for r in db.execute("SELECT * FROM events ORDER BY occurred_at DESC LIMIT 30")]
    audit_rows = [row_dict(r) for r in db.execute("SELECT id,at,actor,action,entity,detail FROM audit ORDER BY id DESC LIMIT 30")]
    since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    lead_count = db.execute("SELECT COUNT(*) FROM events WHERE event_type='lead' AND occurred_at>=?", (since,)).fetchone()[0]
    enrollment_count = db.execute("SELECT COUNT(*) FROM events WHERE event_type='enrollment' AND occurred_at>=?", (since,)).fetchone()[0]
    revenue = db.execute("SELECT COALESCE(SUM(value),0) FROM events WHERE event_type='enrollment' AND occurred_at>=?", (since,)).fetchone()[0]
    linked = db.execute("""SELECT COUNT(*) AS count, COALESCE(SUM(e.value),0) AS revenue FROM events e
        WHERE e.event_type='enrollment' AND e.occurred_at>=? AND e.lead_ref<>''
        AND EXISTS(SELECT 1 FROM events l WHERE l.event_type='lead' AND l.lead_ref=e.lead_ref)""", (since,)).fetchone()
    sources = [row_dict(r) for r in db.execute("SELECT source, COUNT(*) AS leads FROM events WHERE event_type='lead' AND occurred_at>=? GROUP BY source ORDER BY leads DESC", (since,))]
    series = []
    for days_back in range(13, -1, -1):
        day = (datetime.now(timezone.utc) - timedelta(days=days_back)).date().isoformat()
        row = db.execute("SELECT SUM(event_type='lead') AS leads, SUM(event_type='enrollment') AS enrollments FROM events WHERE substr(occurred_at,1,10)=?", (day,)).fetchone()
        series.append({"date": day, "leads": row["leads"] or 0, "enrollments": row["enrollments"] or 0})
    jobs = [row_dict(r) for r in db.execute("SELECT * FROM job_runs ORDER BY id DESC LIMIT 10")]
    operations = {}
    for job in ("radar", "editorial_post", "editorial_blog", "instagram_insights", "instagram_refresh", "ga4", "search_console", "google_sheet"):
        latest = db.execute("SELECT status,at FROM job_runs WHERE job=? ORDER BY id DESC LIMIT 1", (job,)).fetchone()
        operations[job] = row_dict(latest) if latest else None
    latest_mail = db.execute("SELECT status FROM job_runs WHERE job='report' ORDER BY id DESC LIMIT 1").fetchone()
    mail_connected = bool(latest_mail and latest_mail["status"] == "ok")
    from creative_store import overview as creative_overview
    from editorial_calendar import overview as calendar_overview
    return {"content": content, "radar": radar, "events": events, "audit": audit_rows,
            "creative":creative_overview(db), "calendar":calendar_overview(db),
            "audit_valid": verify_audit(db), "jobs": jobs, "operations": operations, "series": series, "sources": sources,
            "instagram_insights": json.loads(setting(db, "instagram_insights", "null")),
            "summary": {"leads": lead_count, "enrollments": enrollment_count, "revenue": revenue,
                        "linked_enrollments": linked["count"], "linked_revenue": linked["revenue"],
                        "conversion": round(enrollment_count / lead_count * 100, 1) if lead_count else 0,
                        "review": sum(x["status"] == "review" for x in content),
                        "approved": sum(x["status"] == "approved" for x in content)},
            "integrations": [
                {"name": "Instagram", "status": "connected" if setting(db, "instagram_enabled") == "true" else "pending", "detail": "Meta Graph API · posts aprovados" if setting(db, "instagram_enabled") == "true" else "Aguardando conta profissional e token oficial da Meta"},
                {"name": "Site / Blog", "status": "connected", "detail": "Blog público e publicação de artigos aprovados com transferência verificada"},
                {"name": "Google Analytics 4", "status": "connected" if (operations.get('ga4') or {}).get('status')=='ok' else "pending", "detail": "API oficial · propriedade nova da marca" if (operations.get('ga4') or {}).get('status')=='ok' else "Tags criadas; leitura da API aguardando autorização"},
                {"name": "Search Console", "status": "connected" if (operations.get('search_console') or {}).get('status')=='ok' else "pending", "detail": "API oficial · propriedade de domínio existente" if (operations.get('search_console') or {}).get('status')=='ok' else "Propriedade existente preservada; conexão da API pendente"},
                {"name": "E-mail", "status": "connected" if mail_connected else "pending", "detail": "Relatório semanal por SMTP" if mail_connected else "Servidor SMTP ou provedor da marca"},
            ],
            "settings": {"google_key_set": bool(db.execute("SELECT 1 FROM settings WHERE name='google_service_account'").fetchone()),
                         "openai_key_set": bool(db.execute("SELECT 1 FROM settings WHERE name='openai_api_key'").fetchone()),
                         "openai_mode": setting(db, "openai_mode", "subscription"),
                         "openai_model": setting(db, "openai_model", "gpt-5-mini"),
                         "instagram_token_set": bool(db.execute("SELECT 1 FROM settings WHERE name='instagram_access_token'").fetchone()),
                         "instagram_user_id": setting(db, "instagram_user_id"),
                         "instagram_enabled": setting(db, "instagram_enabled") == "true",
                         "instagram_auto_refresh": setting(db, "instagram_auto_refresh") == "true",
                         "instagram_token_expires_at": setting(db, "instagram_token_expires_at")}}


def executive_report(data: dict) -> str:
    s = data["summary"]
    revenue = f"{s['revenue']:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    linked_revenue = f"{s['linked_revenue']:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    source_rows = "".join(f"<tr><td>{html.escape(x['source'])}</td><td>{x['leads']}</td></tr>" for x in data["sources"]) or "<tr><td colspan='2'>Nenhuma origem registrada</td></tr>"
    radar_rows = "".join(f"<li>{html.escape(x['title'])} <small>({html.escape(x['source'])})</small></li>" for x in data["radar"][:5]) or "<li>Sem sinais no período</li>"
    published = sum(x["status"] == "published" for x in data["content"])
    return f"""<!doctype html><html lang='pt-BR'><meta charset='utf-8'><title>Relatório Camaleão Marketing Lab</title>
    <style>body{{font-family:Arial,sans-serif;max-width:960px;margin:55px auto;color:#3a0927;padding:0 25px;background:#fff9f5}}header{{background:#3a0927;color:white;padding:34px;border-radius:12px}}header small{{letter-spacing:.2em;color:#f68f1d}}h1{{font-size:34px;margin:12px 0}}h2{{margin-top:40px}}.grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:30px}}.card{{padding:20px;border:1px solid #eadde3;border-radius:8px;background:white}}.card strong{{display:block;font-size:27px;margin-top:10px}}table{{border-collapse:collapse;width:100%}}td,th{{padding:12px;text-align:left;border-bottom:1px solid #eadde3}}footer{{margin-top:45px;color:#745568;font-size:12px}}@media print{{body{{margin:0}}}}</style>
    <header><small>CAMALEÃO LAB · MARKETING OS</small><h1>Relatório executivo</h1><div>Últimos 30 dias · gerado em {html.escape(now()[:10])}</div></header>
    <div class='grid'><div class='card'>Leads<strong>{s['leads']}</strong></div><div class='card'>Vendas<strong>{s['enrollments']}</strong></div><div class='card'>Conversão<strong>{s['conversion']}%</strong></div><div class='card'>Receita registrada<strong>R$ {revenue}</strong></div></div>
    <h2>Origens dos leads</h2><table><tr><th>Origem</th><th>Leads</th></tr>{source_rows}</table>
    <h2>Atribuição por referência</h2><p>{s['linked_enrollments']} venda(s) vinculada(s) a um lead pelo identificador pseudônimo; receita vinculada: R$ {linked_revenue}. Os demais números são totais registrados, sem vínculo comprovado.</p>
    <h2>Operação editorial</h2><p>{s['review']} peça(s) em aprovação, {s['approved']} aprovada(s), {published} publicada(s) registrada(s).</p>
    <h2>Assuntos observados</h2><ul>{radar_rows}</ul>
    <footer>Dados registrados no Camaleão Marketing Lab. Atribuição baseada na origem informada em cada evento; não representa causalidade comprovada. Integridade da trilha de auditoria: {'válida' if data['audit_valid'] else 'falhou'}.</footer></html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "CamaleaoMarketingLab/0.1"

    def _headers(self, status=200, content_type="application/json; charset=utf-8", length=None, cookie=None, disposition=None, extra=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; media-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        if content_type.startswith("text/html"):
            self.send_header("Clear-Site-Data", '"cache"')
        if length is not None:
            self.send_header("Content-Length", str(length))
        if cookie:
            self.send_header("Set-Cookie", cookie)
        if disposition:
            self.send_header("Content-Disposition", disposition)
        for key,value in (extra or {}).items():
            self.send_header(key,value)
        self.end_headers()

    def send_file(self,file,mime):
        size=file.stat().st_size
        start,end=0,size-1
        requested=self.headers.get('Range','')
        if requested:
            match=re.fullmatch(r'bytes=(\d*)-(\d*)',requested)
            if not match or not any(match.groups()):
                return self.error(416,'Intervalo inválido')
            if match[1]:
                start=int(match[1]);end=min(int(match[2]) if match[2] else end,end)
            else:
                start=max(0,size-int(match[2]))
            if start>end or start>=size:
                return self.error(416,'Intervalo fora do arquivo')
        extra={'Accept-Ranges':'bytes'}
        if requested:extra['Content-Range']=f'bytes {start}-{end}/{size}'
        self._headers(206 if requested else 200,mime,end-start+1,extra=extra)
        with file.open('rb') as stream:
            stream.seek(start);remaining=end-start+1
            while remaining:
                block=stream.read(min(65536,remaining))
                if not block:break
                self.wfile.write(block);remaining-=len(block)

    def send_json(self, data, status=200, cookie=None):
        body = json.dumps(data, ensure_ascii=False).encode()
        self._headers(status, length=len(body), cookie=cookie)
        self.wfile.write(body)

    def error(self, status, message):
        self.send_json({"error": message}, status)

    def read_json(self):
        return json.loads(self.read_body())

    def read_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length < 1 or length > (MAX_BODY if urlparse(self.path).path == "/api/library/upload" else 128_000):
            raise ValueError("Tamanho de requisição inválido")
        return self.rfile.read(length)

    def cookie_value(self):
        jar = SimpleCookie()
        try:
            jar.load(self.headers.get("Cookie", ""))
            return jar["cml_session"].value if "cml_session" in jar else ""
        except Exception:
            return ""

    def authorized(self, mutate=False):
        value = self.cookie_value()
        if not validate_session(value):
            self.error(401, "Sessão necessária")
            return False
        if mutate:
            expected = hmac.new(SECRET.encode(), ("csrf:" + value).encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(self.headers.get("X-CSRF-Token", ""), expected):
                self.error(403, "Token CSRF inválido")
                return False
        return True

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/healthz":
            self.send_json({"ok": True})
        elif path == "/api/session":
            value = self.cookie_value()
            user = validate_session(value)
            csrf = hmac.new(SECRET.encode(), ("csrf:" + value).encode(), hashlib.sha256).hexdigest() if user else None
            self.send_json({"user": user, "csrf": csrf})
        elif path == "/api/dashboard":
            if self.authorized():
                with connect() as db:
                    self.send_json(dashboard(db))
        elif path == '/api/brand':
            if self.authorized():
                from brand import get
                self.send_json(get())
        elif path == '/api/leads':
            if self.authorized():
                from leads import overview
                with connect() as db:
                    self.send_json(overview(db))
        elif path == '/api/google/metrics':
            if self.authorized():
                from google_sync import overview
                with connect() as db:self.send_json(overview(db))
        elif path.startswith('/api/library/'):
            if not self.authorized():return
            from creative_store import library_file
            try:file=library_file(path.rsplit('/',1)[1])
            except ValueError:return self.error(404,'Elemento não encontrado')
            import mimetypes
            self.send_file(file,mimetypes.guess_type(file.name)[0] or 'application/octet-stream')
        elif path.startswith('/public/instagram/v2/'):
            from creative_store import MEDIA_PATTERN,assert_approved_version,file_signature,media_path
            name=path.rsplit('/',1)[1]
            if not re.fullmatch(MEDIA_PATTERN,name):return self.error(404,'Mídia não encontrada')
            cid=int(re.search(r'-(\d+)',name)[1])
            try:
                query=parse_qs(parsed.query);expires=int(query.get('expires',['0'])[0])
                signature=query.get('sig',[''])[0]
                if not time.time()<expires<=time.time()+3600:raise ValueError('Expirado')
                with connect() as db:
                    digest=assert_approved_version(db,cid)
                    from creative_store import media_details
                    details=media_details(db,cid)
                    if name not in {x['name'] for x in details['files']}:raise ValueError('Arquivo não pertence à versão')
                if not hmac.compare_digest(signature,file_signature(name,expires,digest)):raise ValueError('Assinatura inválida')
                file=media_path(name)
                self.send_file(file,'video/mp4' if file.suffix=='.mp4' else 'image/jpeg')
            except (ValueError,IndexError):return self.error(403,'Mídia sem aprovação ou link expirado')
        elif path == "/api/report":
            if self.authorized():
                with connect() as db:
                    body = executive_report(dashboard(db)).encode()
                self._headers(200, "text/html; charset=utf-8", len(body), disposition='attachment; filename="cml-relatorio.html"')
                self.wfile.write(body)
        elif path.startswith("/api/content/") and path.endswith("/export"):
            if not self.authorized():
                return
            try:
                content_id = int(path.split("/")[3])
            except ValueError:
                return self.error(400, "ID inválido")
            with connect() as db:
                row = db.execute("SELECT * FROM content WHERE id=?", (content_id,)).fetchone()
            if not row:
                return self.error(404, "Conteúdo não encontrado")
            item = row_dict(row)
            self.send_json({"title": item["title"], "description": item["summary"], "body_markdown": item["body"], "channel": item["channel"], "status": item["status"], "seo_score": seo_score(item)})
        elif re.fullmatch(r"/public/instagram/post-(\d+)\.jpg", path):
            content_id = int(re.fullmatch(r"/public/instagram/post-(\d+)\.jpg", path)[1])
            query = parse_qs(parsed.query)
            try:
                expires = int(query.get("expires", [""])[0])
                signature = query.get("sig", [""])[0]
            except (ValueError, IndexError):
                return self.error(403, "Link inválido")
            if not (time.time() < expires <= time.time() + 3600) or not hmac.compare_digest(signature, instagram_media_signature(content_id, expires)):
                return self.error(403, "Link expirado")
            with connect() as db:
                row = db.execute("SELECT status,kind FROM content WHERE id=?", (content_id,)).fetchone()
            if not row or row["kind"] != "post" or row["status"] not in {"approved", "published"}:
                return self.error(404, "Arte indisponível")
            media_file = DB_PATH.parent / "media" / f"post-{content_id}.jpg"
            if not media_file.exists():
                return self.error(404, "Arte indisponível")
            data = media_file.read_bytes()
            self._headers(200, "image/jpeg", len(data))
            self.wfile.write(data)
        elif re.fullmatch(r"/api/media/(?:post-\d+\.jpg|carousel-\d+-\d+\.jpg|reel-\d+(?:-cover|-frame-\d+)?\.(?:mp4|jpg))", path):
            if not self.authorized():
                return
            media_file = DB_PATH.parent / "media" / path.rsplit("/", 1)[1]
            if not media_file.exists():
                return self.error(404, "Vídeo não encontrado")
            self.send_file(media_file,'video/mp4' if media_file.suffix=='.mp4' else 'image/jpeg')
        elif path in ("/", "/index.html", "/app.js", "/styles.css", "/favicon.svg", "/creative.js", "/creative.css", "/calendar.js", "/leads.js", "/google.js", "/brand.js"):
            filename = "index.html" if path in ("/", "/index.html") else path[1:]
            data = (STATIC / filename).read_bytes()
            mime = ("text/html; charset=utf-8" if filename.endswith(".html") else
                    "text/javascript; charset=utf-8" if filename.endswith(".js") else
                    "image/svg+xml" if filename.endswith(".svg") else "text/css; charset=utf-8")
            self._headers(200, mime, len(data))
            self.wfile.write(data)
        else:
            self.error(404, "Não encontrado")

    def do_POST(self):
        path = urlparse(self.path).path
        if path in {"/api/webhooks/events", "/api/webhooks/leads", "/api/webhooks/lead-status"}:
            if len(INGEST_SECRET) < 32:
                return self.error(503, "Webhook não configurado")
            try:
                raw = self.read_body()
                payload_hash = hashlib.sha256(raw).hexdigest()
                signature = self.headers.get("X-CML-Signature", "")
                expected = "sha256=" + hmac.new(INGEST_SECRET.encode(), raw, hashlib.sha256).hexdigest()
                integration_key = self.headers.get("X-CML-Ingest-Key", "")
                if not (hmac.compare_digest(signature, expected) or
                        hmac.compare_digest(integration_key, INGEST_SECRET)):
                    return self.error(401, "Credencial do webhook inválida")
                data = json.loads(raw)
                if not isinstance(data, dict):
                    raise ValueError("Objeto JSON esperado")
                if path != '/api/webhooks/events':
                    from leads import ingest, update_status
                    with connect() as db:
                        db.execute('BEGIN IMMEDIATE')
                        result=(ingest if path.endswith('/leads') else update_status)(db,data)
                        if parse_qs(urlparse(self.path).query).get('dry_run') == ['1']:
                            db.rollback()
                            return self.send_json({'ok':True,'dry_run':True})
                        return self.send_json(result,200 if result['duplicate'] else 201)
                external_id = clean(data.get("external_id"), 120)
                event_type = clean(data.get("event_type"), 30)
                source = clean(data.get("source"), 80)
                if not external_id or event_type not in {"lead", "enrollment"} or not source:
                    raise ValueError("external_id, event_type e source são obrigatórios")
                value = float(data.get("value") or 0)
                if not math.isfinite(value) or value < 0 or value > 1_000_000:
                    raise ValueError("Valor fora do intervalo")
                if parse_qs(urlparse(self.path).query).get("dry_run") == ["1"]:
                    return self.send_json({"ok": True, "dry_run": True})
                with connect() as db:
                    db.execute("BEGIN IMMEDIATE")
                    existing = db.execute("SELECT event_id,payload_hash FROM webhook_receipts WHERE external_id=?", (external_id,)).fetchone()
                    if existing:
                        if existing["payload_hash"] and not hmac.compare_digest(existing["payload_hash"], payload_hash):
                            return self.error(409, "external_id já usado com dados diferentes")
                        return self.send_json({"id": existing["event_id"], "duplicate": True})
                    cur = db.execute("INSERT INTO events(event_type,source,campaign,lead_ref,value,occurred_at) VALUES(?,?,?,?,?,?)",
                        (event_type, source, clean(data.get("campaign"), 80), clean(data.get("lead_ref"), 80), value, now()))
                    db.execute("INSERT INTO webhook_receipts(external_id,event_id,received_at,payload_hash) VALUES(?,?,?,?)", (external_id, cur.lastrowid, now(), payload_hash))
                    audit(db, "webhook", "event.create", f"event:{cur.lastrowid}", f"{event_type}:{source}")
                    return self.send_json({"id": cur.lastrowid, "duplicate": False}, 201)
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                return self.error(400, str(exc))
        if path == "/api/login":
            ip = self.client_address[0]
            attempts = [t for t in LOGIN_ATTEMPTS.get(ip, []) if time.time() - t < 900]
            if len(attempts) >= 8:
                return self.error(429, "Muitas tentativas. Aguarde 15 minutos")
            try:
                data = self.read_json()
            except (ValueError, json.JSONDecodeError):
                return self.error(400, "JSON inválido")
            if not isinstance(data, dict):
                return self.error(400, "Objeto JSON esperado")
            with connect() as db:
                row = db.execute("SELECT * FROM users WHERE username=?", (clean(data.get("username"), 40),)).fetchone()
            good = False
            if row:
                digest = hashlib.scrypt(str(data.get("password", "")).encode(), salt=bytes.fromhex(row["salt"]), n=2**14, r=8, p=1).hex()
                good = hmac.compare_digest(digest, row["password_hash"])
            if not good:
                LOGIN_ATTEMPTS[ip] = attempts + [time.time()]
                return self.error(401, "Credenciais inválidas")
            LOGIN_ATTEMPTS.pop(ip, None)
            value, csrf = sign_session()
            cookie = f"cml_session={value}; HttpOnly; SameSite=Lax; Path=/; Max-Age=604800" + ("; Secure" if SECURE_COOKIE else "")
            self.send_json({"user": "admin", "csrf": csrf}, cookie=cookie)
            return
        if not self.authorized(mutate=True):
            return
        try:
            data = self.read_json() if path != "/api/logout" else {}
            if not isinstance(data, dict):
                raise ValueError("Objeto JSON esperado")
            if path == "/api/logout":
                self.send_json({"ok": True}, cookie="cml_session=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0" + ("; Secure" if SECURE_COOKIE else ""))
            elif path == '/api/brand':
                from brand import save
                value=save(data)
                with connect() as db:
                    audit(db,'admin','brand.update','brand','Contexto da empresa atualizado; conteúdo já aprovado preservado')
                    from editorial_calendar import ensure_horizon
                    db.execute('DELETE FROM editorial_slots WHERE content_id IS NULL')
                    ensure_horizon(db)
                self.send_json(value)
            elif path == '/api/library/upload':
                from library import upload
                self.send_json(upload(data),201)
            elif path=='/api/creative/runs':
                from creative_store import enqueue
                with connect() as db:
                    run_id=enqueue(db,data.get('brief'),data.get('kind','auto'))
                self.send_json({'id':run_id,'status':'queued'},202)
            elif re.fullmatch(r'/api/creative/runs/[a-z0-9-]+/retry',path):
                run_id=path.split('/')[4]
                with connect() as db:
                    row=db.execute('SELECT status FROM creative_runs WHERE id=?',(run_id,)).fetchone()
                    if not row or row['status']!='failed':return self.error(409,'Somente uma execução interrompida pode ser retomada')
                    db.execute("UPDATE creative_runs SET status='queued',error='',updated_at=? WHERE id=?",(now(),run_id))
                    audit(db,'admin','creative.retry',f'run:{run_id}','Retomada a partir das etapas guardadas')
                self.send_json({'id':run_id,'status':'queued'},202)
            elif path == '/api/settings/google':
                from secret_store import put_secret
                from google_sync import verify,validate_info
                raw=data.get('credential','')
                if not isinstance(raw,str) or not 100<len(raw)<16000:raise ValueError('Selecione o arquivo JSON da conta de serviço')
                try:
                    info=validate_info(json.loads(raw))
                    verified=verify(info)
                except Exception:
                    raise ValueError('Não foi possível validar o acesso ao GA4, Search Console e planilha. Confira as APIs e as permissões da conta de serviço.') from None
                with connect() as db:
                    put_secret(db,'google_service_account',json.dumps(info))
                    audit(db,'admin','credential.rotate','google','Credencial de integração validada e criptografada; valor oculto')
                self.send_json({'ok':True,'verified':verified})
            elif path == "/api/settings/openai":
                from secret_store import put_secret, put_setting
                key = data.get("key", "")
                mode = data.get("mode", "subscription")
                model = clean(data.get("model", "gpt-5-mini"), 80)
                if not isinstance(key, str) or len(key) > 500 or (key and not key.startswith("sk-")):
                    raise ValueError("Chave OpenAI inválida")
                if mode not in {"subscription", "api"} or not re.fullmatch(r"[a-zA-Z0-9_.-]{3,80}", model):
                    raise ValueError("Modo ou modelo inválido")
                with connect() as db:
                    if key:
                        put_secret(db, "openai_api_key", key)
                        audit(db, "admin", "credential.rotate", "openai", "Chave substituída; valor oculto")
                    if data.get("clear") is True:
                        db.execute("DELETE FROM settings WHERE name='openai_api_key'")
                        mode = "subscription"
                        audit(db, "admin", "credential.remove", "openai", "Chave removida")
                    if mode == "api" and not db.execute("SELECT 1 FROM settings WHERE name='openai_api_key'").fetchone():
                        raise ValueError("Cadastre uma chave antes de ativar a API")
                    put_setting(db, "openai_mode", mode)
                    put_setting(db, "openai_model", model)
                    audit(db, "admin", "settings.update", "openai", f"Modo {mode}; modelo {model}")
                self.send_json({"ok": True, "mode": mode, "key_set": mode == "api" or bool(key)})
            elif path == "/api/settings/instagram":
                from secret_store import get_secret, put_secret, put_setting
                user_id = clean(data.get("user_id"), 40)
                token = data.get("token", "")
                enabled = data.get("enabled") is True
                if user_id and not re.fullmatch(r"\d{5,30}", user_id):
                    raise ValueError("ID da conta Meta inválido")
                if not isinstance(token, str) or len(token) > 4096:
                    raise ValueError("Token Meta inválido")
                if enabled:
                    with connect() as db:
                        current_token = get_secret(db, "instagram_access_token")
                    probe_token = token or current_token
                    if not user_id or not probe_token:
                        raise ValueError("Cadastre o ID e o token oficial da conta antes de ativar")
                    host = os.getenv("CML_META_GRAPH_HOST", "graph.instagram.com")
                    version = os.getenv("CML_META_GRAPH_VERSION", "v25.0")
                    if host not in {"graph.instagram.com", "graph.facebook.com"} or not re.fullmatch(r"v\d+\.\d+", version):
                        raise ValueError("Endpoint Meta inválido")
                    request = urllib.request.Request(f"https://{host}/{version}/{user_id}?fields=id,username",
                        headers={"Authorization": f"Bearer {probe_token}", "User-Agent": "CamaleaoMarketingLab/0.4"})
                    try:
                        with urllib.request.urlopen(request, timeout=15) as response:
                            account = json.load(response)
                    except urllib.error.HTTPError as exc:
                        raise ValueError(f"A Meta recusou o acesso (HTTP {exc.code})") from exc
                    except urllib.error.URLError as exc:
                        raise ValueError("Não foi possível verificar a conta na Meta") from exc
                    if str(account.get("id")) != user_id:
                        raise ValueError("O token não corresponde ao ID informado")
                with connect() as db:
                    if token:
                        put_secret(db, "instagram_access_token", token)
                        put_setting(db, "instagram_token_saved_at", now())
                        put_setting(db, "instagram_token_expires_at", "")
                        audit(db, "admin", "credential.rotate", "instagram", "Token substituído; valor oculto")
                    if data.get("clear") is True:
                        db.execute("DELETE FROM settings WHERE name='instagram_access_token'")
                        db.execute("DELETE FROM settings WHERE name IN ('instagram_insights','instagram_token_saved_at','instagram_token_expires_at')")
                        enabled = False
                        audit(db, "admin", "credential.remove", "instagram", "Token removido")
                    if enabled and (not user_id or not db.execute("SELECT 1 FROM settings WHERE name='instagram_access_token'").fetchone()):
                        raise ValueError("Cadastre o ID e o token oficial da conta antes de ativar")
                    put_setting(db, "instagram_user_id", user_id)
                    put_setting(db, "instagram_enabled", "true" if enabled else "false")
                    put_setting(db, "instagram_auto_refresh", "true" if data.get("auto_refresh") is True and data.get("clear") is not True else "false")
                    audit(db, "admin", "settings.update", "instagram", "Publicação ativada" if enabled else "Publicação desativada")
                self.send_json({"ok": True, "enabled": enabled})
            elif path == "/api/content":
                kind, channel = clean(data.get("kind"), 20), clean(data.get("channel"), 30)
                title = clean(data.get("title"), 180)
                if kind not in TYPES or channel not in CHANNELS or not title:
                    raise ValueError("Tipo, canal ou título inválido")
                stamp = now()
                with connect() as db:
                    cur = db.execute("INSERT INTO content(kind,title,channel,summary,body,status,source_url,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                        (kind, title, channel, clean(data.get("summary"), 500), clean(data.get("body"), 20000), "draft", clean(data.get("source_url"), 800), stamp, stamp))
                    from editorial_calendar import reserve
                    reserve(db,cur.lastrowid)
                    audit(db, "admin", "content.create", f"content:{cur.lastrowid}", title)
                    self.send_json({"id": cur.lastrowid}, 201)
            elif path == "/api/events":
                event_type = clean(data.get("event_type"), 30)
                if event_type not in {"lead", "enrollment"}:
                    raise ValueError("Evento inválido")
                source = clean(data.get("source"), 80)
                if not source:
                    raise ValueError("Origem necessária")
                value = float(data.get("value") or 0)
                if not math.isfinite(value) or value < 0 or value > 1_000_000:
                    raise ValueError("Valor fora do intervalo")
                with connect() as db:
                    cur = db.execute("INSERT INTO events(event_type,source,campaign,lead_ref,value,occurred_at) VALUES(?,?,?,?,?,?)",
                        (event_type, source, clean(data.get("campaign"), 80), clean(data.get("lead_ref"), 80), value, now()))
                    audit(db, "admin", "event.create", f"event:{cur.lastrowid}", f"{event_type}:{source}")
                    self.send_json({"id": cur.lastrowid}, 201)
            elif path == "/api/jobs/radar":
                if not RADAR_LOCK.acquire(blocking=False):
                    return self.error(409, "Radar já está em execução")
                try:
                    run = subprocess.run([sys.executable, str(ROOT / "jobs.py"), "radar"],
                                         capture_output=True, text=True, timeout=75)
                    if run.returncode:
                        return self.error(502, clean(run.stderr.splitlines()[-1] if run.stderr else "Falha no radar", 300))
                    self.send_json({"ok": True, "detail": clean(run.stdout, 300)})
                except subprocess.TimeoutExpired:
                    self.error(504, "Radar excedeu o tempo limite")
                finally:
                    RADAR_LOCK.release()
            else:
                render = re.fullmatch(r"/api/content/(\d+)/render", path)
                if render:
                    content_id = int(render[1])
                    with connect() as db:
                        item = db.execute("SELECT * FROM content WHERE id=?", (content_id,)).fetchone()
                    if not item:
                        return self.error(404, "Conteúdo não encontrado")
                    if item["kind"] not in {"reel", "post", "carousel"}:
                        return self.error(400, "Renderização disponível para posts e vídeos")
                    if item['status'] in {'approved','published'}:return self.error(409,'Reabra o conteúdo antes de criar uma nova versão')
                    from creative_store import enqueue
                    with connect() as db:
                        if item['creative_run_id'] and db.execute("SELECT 1 FROM creative_runs WHERE id=? AND status IN ('queued','running')",(item['creative_run_id'],)).fetchone():
                            return self.error(409,'Esta peça já está com a equipe')
                        run_id=enqueue(db,'Criar uma nova versão da pauta: '+item['title']+'\n'+item['summary']+'\n'+item['body'],item['kind'])
                        db.execute('UPDATE creative_runs SET content_id=? WHERE id=?',(content_id,run_id))
                        db.execute("UPDATE content SET status='draft',creative_run_id=?,approved_digest='',updated_at=? WHERE id=?",(run_id,now(),content_id))
                        audit(db, "admin", "media.queue", f"content:{content_id}", 'Nova versão solicitada à equipe criativa')
                    self.send_json({'run_id':run_id,'status':'queued'},202)
                    return
                update = re.fullmatch(r"/api/content/(\d+)/update", path)
                if update:
                    content_id = int(update[1])
                    kind, channel = clean(data.get("kind"), 20), clean(data.get("channel"), 30)
                    title = clean(data.get("title"), 180)
                    if kind not in TYPES or channel not in CHANNELS or not title:
                        raise ValueError("Tipo, canal ou título inválido")
                    with connect() as db:
                        row = db.execute("SELECT status FROM content WHERE id=?", (content_id,)).fetchone()
                        if not row:
                            return self.error(404, "Conteúdo não encontrado")
                        if row["status"] not in {"draft", "rejected"}:
                            return self.error(409, "Apenas rascunhos ou rejeitados podem ser editados")
                        if db.execute("SELECT 1 FROM creative_runs WHERE content_id=? AND status IN ('queued','running')",(content_id,)).fetchone():
                            return self.error(409,'Aguarde a equipe concluir esta peça antes de editar')
                        db.execute("UPDATE content SET approved_digest='',kind=?,title=?,channel=?,summary=?,body=?,source_url=?,status='draft',updated_at=? WHERE id=?",
                            (kind,title,channel,clean(data.get("summary"),500),clean(data.get("body"),20000),clean(data.get("source_url"),800),now(),content_id))
                        audit(db, "admin", "content.update", f"content:{content_id}", title)
                        db.execute('DELETE FROM creative_media WHERE content_id=?',(content_id,))
                    for media_name in (f"post-{content_id}.png", f"post-{content_id}.jpg", f"reel-{content_id}.mp4"):
                        (DB_PATH.parent / "media" / media_name).unlink(missing_ok=True)
                    self.send_json({"id": content_id, "status": "draft"})
                    return
                calendar_match=re.fullmatch(r"/api/content/(\d+)/schedule",path)
                if calendar_match:
                    from editorial_calendar import reschedule
                    with connect() as db:
                        db.execute('BEGIN IMMEDIATE')
                        reschedule(db,int(calendar_match[1]),str(data.get('scheduled_at','')))
                    self.send_json({'ok':True});return
                match = re.fullmatch(r"/api/content/(\d+)/(submit|approve|reject|reopen)", path)
                if not match:
                    return self.error(404, "Não encontrado")
                content_id, action = int(match[1]), match[2]
                transitions = {"submit": ("draft", "review"), "approve": ("review", "approved"),
                               "reject": ("review", "rejected"), "reopen": ("approved", "draft")}
                expected, target = transitions[action]
                with connect() as db:
                    db.execute("BEGIN IMMEDIATE")
                    row = db.execute("SELECT title,summary,status,kind,channel,creative_run_id,scheduled_at FROM content WHERE id=?", (content_id,)).fetchone()
                    if not row:
                        return self.error(404, "Conteúdo não encontrado")
                    if row["status"] != expected:
                        return self.error(409, f"Ação exige status {expected}")
                    if action == "reopen" and row["kind"] in {'post','carousel','reel'} and db.execute(
                        "SELECT 1 FROM instagram_outbox WHERE content_id=?", (content_id,)).fetchone():
                        return self.error(409, "A publicação Instagram já começou; concilie antes de reabrir")
                    approved_digest=''
                    if action == "approve" and row["kind"] in {'post','carousel','reel'} and row["channel"] == "Instagram":
                        from creative_store import content_digest,media_details
                        details=media_details(db,content_id)
                        if not details or details['review'].get('verdict')!='pass':
                            raise ValueError('A peça precisa de render e revisão visual antes da aprovação. Solicite uma nova versão à equipe.')
                        approved_digest=content_digest(db,content_id)
                    from editorial_calendar import approve_schedule
                    schedule = approve_schedule(db,content_id) if action == "approve" else row["scheduled_at"]
                    db.execute("UPDATE content SET status=?,scheduled_at=?,updated_at=?,approved_digest=? WHERE id=?", (target, schedule, now(), approved_digest, content_id))
                    if row['kind'] in {'post','carousel','reel'}:
                        db.execute('INSERT INTO creative_feedback(content_id,action,note,created_at) VALUES(?,?,?,?)',
                                   (content_id,action,clean(data.get('reason'),500),now()))
                    audit(db, "admin", f"content.{action}", f"content:{content_id}", clean(data.get("reason"), 300) or row["title"])
                    self.send_json({"id": content_id, "status": target})
        except (ValueError, TypeError, json.JSONDecodeError, RuntimeError) as exc:
            self.error(400, str(exc))

    def log_message(self, format, *args):
        # Query strings can contain short-lived signed media URLs; never log them.
        status = args[1] if len(args) > 1 else ""
        print(f"{self.address_string()} {self.command} {urlparse(self.path).path} {status}", flush=True)


def main():
    if len(SECRET) < 32:
        raise RuntimeError("CML_APP_SECRET precisa ter pelo menos 32 caracteres")
    init_db()
    host = os.getenv("CML_HOST", "127.0.0.1")
    port = int(os.getenv("CML_PORT", "8080"))
    print(f"Camaleão Marketing Lab em http://{host}:{port}", flush=True)
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
