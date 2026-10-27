"""Publish one human-approved article to the CML shared hosting over pinned SFTP."""
from __future__ import annotations

import html
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from app import audit, connect, daily_publication_available, now
from blog_builder import build
from jobs import record_job


def settings() -> tuple[str, str, int, Path, Path, str]:
    host = os.getenv("CML_BLOG_SSH_HOST", "")
    user = os.getenv("CML_BLOG_SSH_USER", "")
    remote = os.getenv("CML_BLOG_REMOTE_BLOG_DIR", "")
    port = int(os.getenv("CML_BLOG_SSH_PORT", "22"))
    key = Path(os.getenv("CML_BLOG_SSH_KEY", "/home/cml/.ssh/id_ed25519"))
    known = Path(os.getenv("CML_BLOG_KNOWN_HOSTS", "/home/cml/.ssh/known_hosts"))
    if not re.fullmatch(r"[a-zA-Z0-9.-]+", host) or not re.fullmatch(r"[a-zA-Z0-9_]+", user):
        raise ValueError("Destino SFTP inválido")
    if not 1 <= port <= 65535 or not re.fullmatch(r"/[a-zA-Z0-9_./-]+/blog", remote) or ".." in remote:
        raise ValueError("Porta ou pasta remota inválida")
    if not key.is_file() or not known.is_file():
        raise RuntimeError("Chave SFTP ou host conhecido não configurado")
    return host, user, port, key, known, remote


def publish(content_id: int) -> None:
    with connect() as db:
        row = db.execute("SELECT kind,channel,status,scheduled_at FROM content WHERE id=?", (content_id,)).fetchone()
        if not row or row["kind"] != "blog" or row["channel"] != "Blog" or row["status"] != "approved":
            raise ValueError("O artigo precisa estar aprovado para Blog")
        if row["scheduled_at"] and row["scheduled_at"] > now():
            raise RuntimeError("Horário da publicação ainda não chegou")
        if not daily_publication_available(db, "blog", "Blog"):
            raise RuntimeError("O artigo de hoje já foi publicado; fila continua amanhã")
    host, user, port, key, known, remote = settings()
    with tempfile.TemporaryDirectory(prefix="cml-blog-") as scratch:
        output = Path(scratch) / "blog"
        urls = build(output, pending_id=content_id)
        from hosting_upload import upload
        files={'blog/'+str(path.relative_to(output)):path for path in output.rglob('*') if path.is_file()}
        confirmation=upload(host,user,port,key,known,remote,files)
        published_url=next((url for url in urls if url.endswith('-'+str(content_id)+'/')),'')
    with connect() as db:
        updated = db.execute("UPDATE content SET status='published',published_at=?,updated_at=?,published_url=? WHERE id=? AND status='approved'",
                             (now(), now(), published_url, content_id)).rowcount
        if updated != 1:
            raise RuntimeError("Upload concluído, mas o estado do artigo mudou; verifique antes de repetir")
        audit(db, "worker", "content.publish", f"content:{content_id}", "Blog publicado via SSH com confirmação SHA-256")
        record_job(db, f"blog_publish_{content_id}", "ok", "Artigo, fontes e sitemaps confirmados na hospedagem")


if __name__ == "__main__":
    if len(sys.argv) != 2 or not sys.argv[1].isdigit():
        raise SystemExit("Uso: python3 blog_publish.py ID")
    content_id = int(sys.argv[1])
    try:
        publish(content_id)
    except Exception as exc:
        with connect() as db:
            record_job(db, f"blog_publish_{content_id}", "error", str(exc))
        raise
