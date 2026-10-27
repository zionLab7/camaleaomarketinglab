import http.client
import hashlib
import hmac
import json
import os
import tempfile
import threading
import time
import io
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TMP = tempfile.TemporaryDirectory()
os.environ["CML_DB_PATH"] = str(Path(TMP.name) / "test.db")
os.environ["CML_APP_SECRET"] = "integration-test-secret-with-more-than-32-characters"
os.environ["CML_ADMIN_PASSWORD"] = "integration-test-password-long"
os.environ["CML_COOKIE_SECURE"] = "false"
os.environ["CML_INGEST_SECRET"] = "integration-webhook-secret-more-than-32-characters"

import app  # noqa: E402
import jobs  # noqa: E402


class AppFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.init_db()
        import brand
        brand.save({**brand.DEFAULT,'sources':['https://example.org/reference']})
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cls.server.server_port

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        TMP.cleanup()

    def request(self, method, path, data=None, cookie=None, csrf=None, extra_headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {"Content-Type": "application/json"}
        if cookie:
            headers["Cookie"] = cookie
        if csrf:
            headers["X-CSRF-Token"] = csrf
        if extra_headers:
            headers.update(extra_headers)
        conn.request(method, path, json.dumps(data).encode() if data is not None else None, headers)
        response = conn.getresponse()
        body = json.loads(response.read())
        result = response.status, body, response.getheader("Set-Cookie")
        conn.close()
        return result

    def login(self):
        status, body, cookie = self.request("POST", "/api/login", {"username": "admin", "password": "integration-test-password-long"})
        self.assertEqual(status, 200)
        return cookie.split(";", 1)[0], body["csrf"]

    def attach_reviewed_media(self, cid):
        from creative_store import register_media
        import shutil
        target=app.DB_PATH.parent/'media';target.mkdir(exist_ok=True)
        file=target/f'post-{cid}.jpg'
        from PIL import Image
        Image.new('RGB',(1080,1350),'#142c35').save(file)
        with app.connect() as db:register_media(db,cid,{'alt':'Imagem ilustrativa de teste'},[file],{'verdict':'pass'})

    def test_white_label_configuration_and_upload_require_auth_and_csrf(self):
        import brand
        self.assertEqual(self.request('GET','/api/brand')[0],401)
        cookie,csrf=self.login()
        status,original,_=self.request('GET','/api/brand',cookie=cookie)
        self.assertEqual(status,200)
        modified={**original,'name':'Ateliê Horizonte','industry':'Design'}
        self.assertEqual(self.request('POST','/api/brand',modified,cookie)[0],403)
        self.assertEqual(self.request('POST','/api/brand',modified,cookie,csrf)[0],200)
        self.assertEqual(self.request('GET','/api/brand',cookie=cookie)[1]['industry'],'Design')
        self.assertEqual(self.request('POST','/api/library/upload',{'data':'not-an-image','rights_confirmed':True},cookie,csrf)[0],400)
        self.assertEqual(self.request('POST','/api/brand',original,cookie,csrf)[0],200)

    def test_auth_csrf_approval_audit_and_metrics(self):
        self.assertEqual(self.request("GET", "/api/dashboard")[0], 401)
        self.assertEqual(self.request("POST", "/api/login", ["admin"])[0], 400)
        cookie, csrf = self.login()
        self.assertEqual(self.request("POST", "/api/content", {"kind": "post"}, cookie)[0], 403)
        status, body, _ = self.request("POST", "/api/content", {"kind": "post", "title": "Primeira aula", "channel": "Instagram", "summary": "Uma dica", "body": "Prepare seus documentos"}, cookie, csrf)
        self.assertEqual(status, 201)
        cid = body["id"]
        self.assertEqual(self.request("POST", f"/api/content/{cid}/approve", {}, cookie, csrf)[0], 409)
        self.assertEqual(self.request("POST", f"/api/content/{cid}/submit", {}, cookie, csrf)[0], 200)
        self.attach_reviewed_media(cid)
        self.assertEqual(self.request("POST", f"/api/content/{cid}/approve", {}, cookie, csrf)[0], 200)
        expires = int(time.time()) + 300
        signed = app.instagram_media_signature(cid, expires)
        media = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        media.request("GET", f"/public/instagram/post-{cid}.jpg?expires={expires}&sig={signed}")
        response = media.getresponse()
        self.assertEqual(response.status, 200)
        self.assertTrue(response.read().startswith(b"\xff\xd8"))
        media.close()
        self.assertEqual(self.request("GET", f"/public/instagram/post-{cid}.jpg?expires={expires}&sig=bad")[0], 403)
        self.assertEqual(self.request("POST", f"/api/content/{cid}/update", {"kind": "post", "title": "Editado", "channel": "Instagram"}, cookie, csrf)[0], 409)
        self.assertEqual(self.request("POST", "/api/events", {"event_type": "lead", "source": "Instagram"}, cookie, csrf)[0], 201)
        self.assertEqual(self.request("POST", "/api/events", {"event_type": "enrollment", "source": "Instagram", "value": 1500}, cookie, csrf)[0], 201)
        self.assertEqual(self.request("POST", "/api/events", {"event_type": "lead", "source": "Instagram", "value": "NaN"}, cookie, csrf)[0], 400)
        status, dashboard, _ = self.request("GET", "/api/dashboard", cookie=cookie)
        self.assertEqual(status, 200)
        self.assertEqual(dashboard["summary"]["leads"], 1)
        self.assertEqual(dashboard["summary"]["enrollments"], 1)
        self.assertEqual(dashboard["summary"]["conversion"], 100)
        self.assertTrue(dashboard["audit_valid"])
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", "/api/report", headers={"Cookie": cookie})
        report = conn.getresponse()
        self.assertEqual(report.status, 200)
        self.assertIn(b"Relat", report.read())
        conn.close()
        with app.connect() as db:
            db.execute("UPDATE audit SET detail='alterado' WHERE id=1")
        self.assertFalse(self.request("GET", "/api/dashboard", cookie=cookie)[1]["audit_valid"])

    def test_radar_parser_and_scoring(self):
        feed = "<rss><channel><item><title>Nova dica para serviço</title><link>https://example.org/item</link></item></channel></rss>".encode()
        items = list(jobs.feed_items(feed, "example.org"))
        self.assertEqual(len(items), 1)
        self.assertGreaterEqual(items[0]["score"], 25)
        competitors = list(jobs.feed_items(feed, "example.org", "Concorrente"))
        self.assertEqual(competitors[0]["category"], "Concorrente")
        self.assertEqual(list(jobs.feed_items(b"<rss><item><title>Bad</title><link>javascript:alert(1)</link></item></rss>", "x")), [])

    def test_creative_queue_and_signed_media_require_auth_and_exact_approval(self):
        from creative_store import content_digest,file_signature
        cookie,csrf=self.login()
        self.assertEqual(self.request('POST','/api/creative/runs',{'brief':'Teste'},cookie)[0],403)
        self.assertEqual(self.request('POST','/api/creative/runs',{'brief':'Teste de pauta','kind':'post'},cookie,csrf)[0],202)
        self.assertEqual(self.request('GET','/api/library/agenda-3d')[0],401)
        cid=self.request('POST','/api/content',{'kind':'post','title':'Versão exata','channel':'Instagram','body':'Legenda revisada'},cookie,csrf)[1]['id']
        self.attach_reviewed_media(cid)
        self.request('POST',f'/api/content/{cid}/submit',{},cookie,csrf)
        self.assertEqual(self.request('POST',f'/api/content/{cid}/approve',{},cookie,csrf)[0],200)
        with app.connect() as db:seal=content_digest(db,cid)
        name=f'post-{cid}.jpg';expires=int(time.time())+300;sig=file_signature(name,expires,seal)
        url=f'/public/instagram/v2/{name}?expires={expires}&sig={sig}'
        conn=http.client.HTTPConnection('127.0.0.1',self.port,timeout=5)
        conn.request('GET',url,headers={'Range':'bytes=0-9'});response=conn.getresponse()
        self.assertEqual(response.status,206);self.assertEqual(len(response.read()),10)
        self.assertTrue(response.getheader('Content-Range').startswith('bytes 0-9/'));conn.close()
        with app.connect() as db:db.execute('UPDATE content SET body=? WHERE id=?',('Texto alterado após aprovação',cid))
        self.assertEqual(self.request('GET',url)[0],403)

    def test_signed_webhook_deduplicates(self):
        payload = {"external_id": "crm-lead-123", "event_type": "lead", "source": "Site", "lead_ref": "anon-123"}
        raw = json.dumps(payload).encode()
        signature = "sha256=" + hmac.new(os.environ["CML_INGEST_SECRET"].encode(), raw, hashlib.sha256).hexdigest()
        self.assertEqual(self.request("POST", "/api/webhooks/events", payload, extra_headers={"X-CML-Signature": "bad"})[0], 401)
        first = self.request("POST", "/api/webhooks/events", payload, extra_headers={"X-CML-Signature": signature})
        second = self.request("POST", "/api/webhooks/events", payload, extra_headers={"X-CML-Signature": signature})
        self.assertEqual(first[0], 201)
        self.assertEqual(second[0], 200)
        self.assertEqual(first[1]["id"], second[1]["id"])
        changed = {**payload, "source": "Google"}
        changed_sig = "sha256=" + hmac.new(os.environ["CML_INGEST_SECRET"].encode(), json.dumps(changed).encode(), hashlib.sha256).hexdigest()
        self.assertEqual(self.request("POST", "/api/webhooks/events", changed, extra_headers={"X-CML-Signature": changed_sig})[0], 409)
        enrollment = {"external_id": "crm-enrollment-123", "event_type": "enrollment", "source": "Site", "lead_ref": "anon-123", "value": 1800}
        signed = "sha256=" + hmac.new(os.environ["CML_INGEST_SECRET"].encode(), json.dumps(enrollment).encode(), hashlib.sha256).hexdigest()
        self.assertEqual(self.request("POST", "/api/webhooks/events", enrollment, extra_headers={"X-CML-Signature": signed})[0], 201)
        cookie, _ = self.login()
        summary = self.request("GET", "/api/dashboard", cookie=cookie)[1]["summary"]
        self.assertEqual(summary["linked_enrollments"], 1)
        self.assertEqual(summary["linked_revenue"], 1800)

    def test_n8n_header_credential_is_scoped_to_event_ingestion(self):
        data = {"external_id": "n8n-test-execution-1", "event_type": "lead", "source": "n8n-test"}
        self.assertEqual(self.request("POST", "/api/webhooks/events", data,
            extra_headers={"X-CML-Ingest-Key": "wrong-key"})[0], 401)
        header = {"X-CML-Ingest-Key": os.environ["CML_INGEST_SECRET"]}
        self.assertTrue(self.request("POST", "/api/webhooks/events?dry_run=1", data, extra_headers=header)[1]["dry_run"])
        with app.connect() as db:
            self.assertFalse(db.execute("SELECT 1 FROM webhook_receipts WHERE external_id=?", (data["external_id"],)).fetchone())
        self.assertEqual(self.request("POST", "/api/webhooks/events", data, extra_headers=header)[0], 201)
        self.assertTrue(self.request("POST", "/api/webhooks/events", data, extra_headers=header)[1]["duplicate"])
        self.assertEqual(self.request("GET", "/api/dashboard", extra_headers=header)[0], 401)
        with app.connect() as db:
            event_id = db.execute("SELECT event_id FROM webhook_receipts WHERE external_id=?", (data["external_id"],)).fetchone()[0]
            db.execute("DELETE FROM webhook_receipts WHERE external_id=?", (data["external_id"],))
            db.execute("DELETE FROM events WHERE id=?", (event_id,))

    def test_api_key_rotation_is_encrypted_and_opt_in(self):
        cookie, csrf = self.login()
        fake_key = "sk-test-secret-for-rotation-only"
        path = "/api/settings/openai"
        self.assertEqual(self.request("POST", path, {"key": fake_key, "mode": "api", "model": "gpt-5-mini"}, cookie)[0], 403)
        self.assertEqual(self.request("POST", path, {"key": fake_key, "mode": "api", "model": "gpt-5-mini"}, cookie, csrf)[0], 200)
        with app.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE name='openai_api_key'").fetchone()
            self.assertNotIn(fake_key, row[0])
            from secret_store import get_secret
            self.assertEqual(get_secret(db, "openai_api_key"), fake_key)
        data = self.request("GET", "/api/dashboard", cookie=cookie)[1]
        self.assertTrue(data["settings"]["openai_key_set"])
        self.assertEqual(data["settings"]["openai_mode"], "api")
        self.assertNotIn(fake_key, json.dumps(data))
        self.assertEqual(self.request("POST", path, {"clear": True, "mode": "api", "model": "gpt-5-mini"}, cookie, csrf)[0], 200)
        data = self.request("GET", "/api/dashboard", cookie=cookie)[1]
        self.assertFalse(data["settings"]["openai_key_set"])
        self.assertEqual(data["settings"]["openai_mode"], "subscription")

    def test_instagram_outbox_publishes_once_after_approval(self):
        import instagram_publish
        from secret_store import put_secret, put_setting
        cookie, csrf = self.login()
        created = self.request("POST", "/api/content", {"kind": "post", "title": "Aula prática com confiança",
            "channel": "Instagram", "summary": "Dicas para se preparar", "body": "Legenda de teste para publicação"}, cookie, csrf)[1]
        cid = created["id"]
        self.assertEqual(self.request("POST", f"/api/content/{cid}/submit", {}, cookie, csrf)[0], 200)
        self.attach_reviewed_media(cid)
        self.assertEqual(self.request("POST", f"/api/content/{cid}/approve", {}, cookie, csrf)[0], 200)
        with self.assertRaisesRegex(RuntimeError, "Horário"):
            instagram_publish.publish(cid)
        with app.connect() as db:
            put_secret(db, "instagram_access_token", "fake-token-only-for-test")
            put_setting(db, "instagram_user_id", "1234567890")
            put_setting(db, "instagram_enabled", "true")
            db.execute("UPDATE content SET scheduled_at=? WHERE id=?", ((datetime.now(ZoneInfo("UTC"))-timedelta(minutes=1)).isoformat(),cid))
        with patch.object(instagram_publish, "graph_call", side_effect=[{"id": "123"}, {"id": "456"}]) as mocked, patch.object(instagram_publish,"graph_status",return_value="FINISHED"):
            instagram_publish.publish(cid)
            self.assertEqual(mocked.call_count, 2)
        with app.connect() as db:
            self.assertEqual(db.execute("SELECT status FROM content WHERE id=?", (cid,)).fetchone()[0], "published")
            self.assertEqual(db.execute("SELECT stage,media_id FROM instagram_outbox WHERE content_id=?", (cid,)).fetchone()[:], ("published", "456"))
        with self.assertRaises(ValueError):
            instagram_publish.publish(cid)
        with app.connect() as db:
            self.assertFalse(app.daily_publication_available(db,"post","Instagram"))
            second = db.execute("INSERT INTO content(kind,title,channel,body,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                                ("post","Fila de amanhã","Instagram","Legenda revisada","approved",app.now(),app.now())).lastrowid
        with self.assertRaisesRegex(RuntimeError,"post de hoje"):
            instagram_publish.publish(second)

    def test_editorial_enters_review_with_grounded_reference(self):
        from secret_store import put_secret, put_setting
        with app.connect() as db:
            put_secret(db,"openai_api_key","sk-test-never-sent")
            put_setting(db,"openai_mode","api")
            db.execute("INSERT OR IGNORE INTO radar(title,source,url,category,score,seen_at) VALUES(?,?,?,?,?,?)",
                       ("Dicas para primeira aula","test","https://example.org/pauta","Tendência",60,app.now()))
        proposal={"title":"Organize suas dúvidas para a primeira aula","channel":"Blog",
                  "summary":"Anote seus objetivos e converse com o instrutor para aproveitar cada encontro.",
                  "body":"## Preparação\n"+"Planeje sua rotina com atenção e anote suas dúvidas. "*90,"source_url":'https://example.org/reference'}
        payload={"output":[{"content":[{"type":"output_text","text":json.dumps(proposal)}]}]}
        with patch.object(jobs,"official_context",return_value=("Trecho oficial confiável", "a"*64)), \
             patch.object(jobs.urllib.request,"urlopen",return_value=io.BytesIO(json.dumps(payload).encode())) as endpoint:
            jobs.editorial("blog")
            request=endpoint.call_args.args[0]
            self.assertIn("Trecho oficial confiável",json.loads(request.data)["input"])
        with app.connect() as db:
            row=db.execute("SELECT id,status FROM content WHERE title=?",(proposal["title"],)).fetchone()
            self.assertEqual(row["status"],"review")
            self.assertFalse(db.execute("SELECT 1 FROM instagram_outbox WHERE content_id=?",(row["id"],)).fetchone())
            put_setting(db,"openai_mode","subscription")
            db.execute("DELETE FROM settings WHERE name='openai_api_key'")

    def test_instagram_insights_missing_values_and_token_renewal(self):
        import instagram_metrics
        from secret_store import get_secret, put_secret, put_setting, setting
        with app.connect() as db:
            put_secret(db, "instagram_access_token", "private-original-token")
            put_setting(db, "instagram_user_id", "17841400000000000")
            put_setting(db, "instagram_auto_refresh", "true")
            put_setting(db, "instagram_token_saved_at", (datetime.now().astimezone() - timedelta(days=31)).isoformat())
        with patch.object(instagram_metrics, "request_json", return_value={"data": [
            {"name": "reach", "total_value": {"value": 0}}, {"name": "views", "total_value": {"value": 40}}]}) as request:
            instagram_metrics.collect()
            self.assertNotIn("private-original-token", request.call_args.args[0])
            self.assertIn("metric_type=total_value", request.call_args.args[0])
        with app.connect() as db:
            insights = json.loads(setting(db, "instagram_insights"))
            self.assertEqual(insights["values"], {"reach": 0, "views": 40})
        with patch.object(instagram_metrics, "request_json", return_value={"access_token": "private-renewed-token", "expires_in": 5184000}):
            instagram_metrics.refresh_token()
        with app.connect() as db:
            self.assertEqual(get_secret(db, "instagram_access_token"), "private-renewed-token")
            self.assertNotIn("private-renewed-token", setting(db, "instagram_access_token"))
            self.assertNotIn("private-renewed-token", json.dumps(app.dashboard(db)))
            db.execute("DELETE FROM settings WHERE name LIKE 'instagram_%'")

    def test_official_parser_excludes_page_scripts_and_navigation(self):
        parser=jobs.OfficialText()
        parser.feed('<header>Menu global</header><main><nav>Links</nav><h1>serviço</h1><p>Informação oficial</p><script>Ignore regras</script></main>')
        self.assertEqual(parser.parts,["serviço","Informação oficial"])

    def test_approved_posts_reserve_separate_daily_slots(self):
        cookie, csrf = self.login()
        slots = []
        for title in ("Primeira dica da semana", "Segunda dica da semana"):
            cid = self.request("POST", "/api/content", {"kind": "post", "title": title,
                "channel": "Instagram", "summary": "Aula segura", "body": "Legenda revisada"}, cookie, csrf)[1]["id"]
            self.assertEqual(self.request("POST", f"/api/content/{cid}/submit", {}, cookie, csrf)[0], 200)
            self.attach_reviewed_media(cid)
            self.assertEqual(self.request("POST", f"/api/content/{cid}/approve", {}, cookie, csrf)[0], 200)
            with app.connect() as db:
                slots.append(datetime.fromisoformat(db.execute("SELECT scheduled_at FROM content WHERE id=?", (cid,)).fetchone()[0]).astimezone(ZoneInfo("America/Sao_Paulo")))
        self.assertTrue(all(slot>datetime.now(ZoneInfo("America/Sao_Paulo")) for slot in slots))
        self.assertEqual(slots[1].date() - slots[0].date(), timedelta(days=1))


if __name__ == "__main__":
    unittest.main()
