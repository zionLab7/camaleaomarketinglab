"""Read official account insights and refresh an authorized long-lived token."""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from app import audit, connect, now
from jobs import record_job
from secret_store import get_secret, put_secret, put_setting, setting


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        raise RuntimeError("Redirecionamento Meta recusado")


def request_json(url: str, token: str | None = None) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "CamaleaoMarketingLab/0.5"})
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=25) as response:
            raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ValueError("Resposta muito grande")
        payload = json.loads(raw)
        if not isinstance(payload, dict) or "error" in payload:
            raise ValueError("Resposta inválida")
        return payload
    except Exception:
        # Do not include exception URLs: a refresh URL contains the token.
        raise RuntimeError("A Meta não confirmou a operação; verifique permissões e validade do token") from None


def collect() -> None:
    with connect() as db:
        user_id = setting(db, "instagram_user_id")
        token = get_secret(db, "instagram_access_token")
    if not token or not re.fullmatch(r"\d{5,30}", user_id):
        raise RuntimeError("Instagram ainda não conectado")
    host = os.getenv("CML_META_GRAPH_HOST", "graph.instagram.com")
    version = os.getenv("CML_META_GRAPH_VERSION", "v25.0")
    if host not in {"graph.instagram.com", "graph.facebook.com"} or not re.fullmatch(r"v\d+\.\d+", version):
        raise ValueError("Endpoint Meta inválido")
    # Stop 48h before today because Meta account insights can be delayed.
    end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=2)
    start = end - timedelta(days=28)
    metrics = ("reach", "views", "total_interactions")
    query = urllib.parse.urlencode({"metric": ",".join(metrics), "metric_type": "total_value",
                                  "period": "day", "since": int(start.timestamp()), "until": int(end.timestamp())})
    payload = request_json(f"https://{host}/{version}/{user_id}/insights?{query}", token)
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise RuntimeError("Resposta de insights inválida")
    values = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("name") not in metrics:
            continue
        value = row.get("total_value", {}).get("value")
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
            values[row["name"]] = value
    with connect() as db:
        put_setting(db, "instagram_insights", json.dumps({"start": start.date().isoformat(),
            "end": end.date().isoformat(), "captured_at": now(), "values": values}))
        record_job(db, "instagram_insights", "ok", f"{len(values)} métricas oficiais; intervalo de 28 dias")


def refresh_token() -> None:
    with connect() as db:
        if setting(db, "instagram_auto_refresh") != "true":
            return
        token = get_secret(db, "instagram_access_token")
        saved_at = setting(db, "instagram_token_saved_at")
    if not token or not saved_at:
        return
    if datetime.fromisoformat(saved_at) > datetime.now(timezone.utc) - timedelta(days=30):
        return
    if os.getenv("CML_META_GRAPH_HOST", "graph.instagram.com") != "graph.instagram.com":
        raise RuntimeError("Renovação automática exige Login do Instagram")
    query = urllib.parse.urlencode({"grant_type": "ig_refresh_token", "access_token": token})
    payload = request_json(f"https://graph.instagram.com/refresh_access_token?{query}")
    updated, seconds = payload.get("access_token"), payload.get("expires_in")
    if not isinstance(updated, str) or not updated or len(updated) > 4096 or not isinstance(seconds, int) or seconds < 86400:
        raise RuntimeError("A Meta não retornou um token de longa duração válido")
    with connect() as db:
        # Respect a concurrent manual disconnect/rotation.
        if get_secret(db, "instagram_access_token") != token or setting(db, "instagram_auto_refresh") != "true":
            return
        put_secret(db, "instagram_access_token", updated)
        put_setting(db, "instagram_token_saved_at", now())
        put_setting(db, "instagram_token_expires_at", (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat(timespec="seconds"))
        audit(db, "publisher", "credential.refresh", "instagram", "Renovação oficial; valor oculto")
        record_job(db, "instagram_refresh", "ok", "Token renovado oficialmente pela Meta")


if __name__ == "__main__":
    job = "instagram_refresh" if len(sys.argv) > 1 and sys.argv[1] == "refresh" else "instagram_insights"
    try:
        refresh_token() if job == "instagram_refresh" else collect()
    except Exception:
        with connect() as db:
            record_job(db, job, "error", "Confira conexão Meta, permissões e token em Conexões")
        raise SystemExit(1)
