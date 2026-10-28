"""Encrypted integration credentials in the private SQLite volume."""
from __future__ import annotations

import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


ALLOWED_SECRETS = {"openai_api_key", "instagram_access_token", "google_service_account"}


def _cipher() -> AESGCM:
    master = os.getenv("CML_APP_SECRET", "")
    if len(master) < 32:
        raise RuntimeError("CML_APP_SECRET insuficiente")
    key = hashlib.sha256(b"cml-marketing-os:credentials:v1:" + master.encode()).digest()
    return AESGCM(key)


def put_secret(db, name: str, value: str) -> None:
    if name not in ALLOWED_SECRETS or not isinstance(value, str) or not value:
        raise ValueError("Credencial inválida")
    nonce = os.urandom(12)
    encrypted = _cipher().encrypt(nonce, value.encode(), name.encode())
    payload = base64.urlsafe_b64encode(nonce + encrypted).decode()
    db.execute("INSERT INTO settings(name,value,updated_at) VALUES(?,?,datetime('now')) "
               "ON CONFLICT(name) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
               (name, payload))


def get_secret(db, name: str) -> str | None:
    if name not in ALLOWED_SECRETS:
        raise ValueError("Credencial inválida")
    row = db.execute("SELECT value FROM settings WHERE name=?", (name,)).fetchone()
    if not row:
        return None
    data = base64.urlsafe_b64decode(row[0])
    return _cipher().decrypt(data[:12], data[12:], name.encode()).decode()


def setting(db, name: str, default: str = "") -> str:
    row = db.execute("SELECT value FROM settings WHERE name=?", (name,)).fetchone()
    return row[0] if row else default


def put_setting(db, name: str, value: str) -> None:
    if name not in {"openai_mode", "openai_model", "instagram_user_id", "instagram_enabled",
                    "instagram_auto_refresh", "instagram_token_saved_at", "instagram_token_expires_at", "instagram_insights", "publication_policy"}:
        raise ValueError("Configuração inválida")
    db.execute("INSERT INTO settings(name,value,updated_at) VALUES(?,?,datetime('now')) "
               "ON CONFLICT(name) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
               (name, value))
