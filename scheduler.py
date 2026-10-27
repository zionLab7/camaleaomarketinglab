"""Persistent cadence for the trusted worker container."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import connect, daily_publication_available, init_db, now

ROOT = Path(__file__).resolve().parent


def due(job: str, interval_hours: int) -> bool:
    with connect() as db:
        row = db.execute("SELECT at,status FROM job_runs WHERE job=? ORDER BY id DESC LIMIT 1", (job,)).fetchone()
    if not row:
        return True
    cooldown = interval_hours if row["status"] == "ok" else (1/12 if job.startswith(("blog_publish_","instagram_publish_","google_sheet")) else 2)
    return datetime.fromisoformat(row["at"]) <= datetime.now(timezone.utc) - timedelta(hours=cooldown)


def run(job: str) -> None:
    result = subprocess.run([sys.executable, str(ROOT / "jobs.py"), job], timeout=2400 if job=='editorial_post' else 240)
    print(f"{job}: exit {result.returncode}", flush=True)


def tick() -> None:
    from editorial_calendar import synchronize
    role = os.getenv("CML_WORKER_ROLE", "all")
    with connect() as db:
        synchronize(db)
        db.execute('INSERT INTO worker_heartbeats(role,at,status) VALUES(?,?,?) ON CONFLICT(role) DO UPDATE SET at=excluded.at,status=excluded.status',(role,now(),'active'))
    if role not in {"all", "editorial", "publisher"}:
        raise ValueError("CML_WORKER_ROLE inválido")
    if role in {"all", "editorial"}:
        with connect() as db:
            queued=db.execute("SELECT id FROM creative_runs WHERE status IN ('queued','running') ORDER BY created_at LIMIT 1").fetchone()
        if queued:
            result=subprocess.run([sys.executable,str(ROOT/'creative_pipeline.py'),queued['id']],timeout=2400)
            print(f'creative queue: exit {result.returncode}',flush=True)
        if __import__("brand").get()["feeds"] and due("radar", 6):
            run("radar")
        from secret_store import setting
        with connect() as db:
            mode = setting(db, "openai_mode", "subscription")
        if mode == "api" or os.getenv("CML_CODEX_ENABLED", "false").lower() == "true":
            for job in ("editorial_post", "editorial_blog"):
                if job=="editorial_post" and os.getenv("CML_CODEX_ENABLED","false").lower()!="true":continue
                if job=="editorial_blog" and not __import__("brand").get()["sources"]:continue
                channel='Instagram' if job=='editorial_post' else 'Blog'
                from editorial_calendar import current_time
                local=current_time();end=(local+timedelta(days=6)).date().isoformat()
                with connect() as db:
                    gap=db.execute('SELECT 1 FROM editorial_slots WHERE channel=? AND local_date BETWEEN ? AND ? AND content_id IS NULL AND scheduled_at>? LIMIT 1',(channel,local.date().isoformat(),end,now())).fetchone()
                    latest=db.execute('SELECT status FROM job_runs WHERE job=? ORDER BY id DESC LIMIT 1',(job,)).fetchone()
                if gap and (not latest or latest['status']=='ok' or due(job,24)):
                    run(job)
    if role in {"all", "publisher"} and os.getenv("CML_BLOG_PUBLISH_ENABLED", "false").lower() == "true":
        with connect() as db:
            pending = [row[0] for row in db.execute("SELECT id FROM content WHERE kind='blog' AND channel='Blog' AND status='approved' AND (scheduled_at IS NULL OR scheduled_at<=?) ORDER BY scheduled_at,id LIMIT 1", (datetime.now(timezone.utc).isoformat(timespec="seconds"),))] if daily_publication_available(db, "blog", "Blog") else []
        for content_id in pending:
            if due(f"blog_publish_{content_id}", 24):
                result = subprocess.run([sys.executable, str(ROOT / "blog_publish.py"), str(content_id)], timeout=150)
                print(f"blog_publish_{content_id}: exit {result.returncode}", flush=True)
    if role in {"all", "publisher"}:
        from secret_store import setting
        with connect() as db:
            google_connected=bool(db.execute("SELECT 1 FROM settings WHERE name='google_service_account'").fetchone())
            enabled = setting(db, "instagram_enabled") == "true"
            connected = bool(setting(db, "instagram_user_id") and setting(db, "instagram_access_token"))
            pending = [row[0] for row in db.execute("""SELECT c.id FROM content c
                LEFT JOIN instagram_outbox o ON o.content_id=c.id
                WHERE c.kind IN ('post','carousel','reel') AND c.channel='Instagram' AND c.status='approved'
                  AND (c.scheduled_at IS NULL OR c.scheduled_at<=?)
                  AND (o.stage IS NULL OR o.stage IN ('preparing','prepared'))
                ORDER BY c.scheduled_at,c.id LIMIT 1""", (datetime.now(timezone.utc).isoformat(timespec="seconds"),))] if enabled and daily_publication_available(db, "post", "Instagram") else []
        for content_id in pending:
            if due(f"instagram_publish_{content_id}", 24):
                result = subprocess.run([sys.executable, str(ROOT / "instagram_publish.py"), str(content_id)], timeout=600)
                print(f"instagram_publish_{content_id}: exit {result.returncode}", flush=True)
        if connected:
            from publication_metrics import collect as collect_publications
            try:collect_publications()
            except Exception as exc:print('Métricas por peça temporariamente indisponíveis',flush=True)
            for job, args in (("instagram_refresh", ["refresh"]), ("instagram_insights", [])):
                if due(job, 24):
                    result = subprocess.run([sys.executable, str(ROOT / "instagram_metrics.py"), *args], timeout=60)
                    print(f"{job}: exit {result.returncode}", flush=True)
        if google_connected:
            for job,args,interval in [('google_sheet',['sheet'],1/12),('ga4',['metrics'],6)]:
                if due(job,interval):
                    result=subprocess.run([sys.executable,str(ROOT/'google_sync.py'),*args],timeout=240)
                    print(f'{job}: exit {result.returncode}',flush=True)
    if role in {"all", "editorial"} and os.getenv("CML_REPORT_TO") and os.getenv("CML_SMTP_HOST") and due("report", 168):
        result = subprocess.run([sys.executable, str(ROOT / "mailer.py")], timeout=60)
        print(f"report: exit {result.returncode}", flush=True)


if __name__ == "__main__":
    init_db()
    if os.getenv('CML_WORKER_ROLE','all') in {'all','editorial'}:
        from creative_store import import_seed
        import_seed()
    if len(sys.argv) > 1 and sys.argv[1] == "--once":
        tick()
    else:
        while True:
            try:
                tick()
            except Exception as exc:
                print(f"scheduler: {exc}", flush=True)
            time.sleep(60)
