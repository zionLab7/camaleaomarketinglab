"""Send the executive report through the company's existing SMTP account."""
from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage

from app import connect, dashboard, executive_report
from jobs import record_job


def send_report() -> None:
    host = os.getenv("CML_SMTP_HOST", "")
    sender = os.getenv("CML_REPORT_FROM", "")
    recipient = os.getenv("CML_REPORT_TO", "")
    if not all((host, sender, recipient)) or any("\n" in x or "\r" in x for x in (sender, recipient)):
        raise RuntimeError("Configure CML_SMTP_HOST, CML_REPORT_FROM e CML_REPORT_TO")
    port = int(os.getenv("CML_SMTP_PORT", "587"))
    if port not in {465, 587}:
        raise RuntimeError("Use SMTP 465 (TLS direto) ou 587 (STARTTLS)")
    user = os.getenv("CML_SMTP_USER", "")
    password = os.getenv("CML_SMTP_PASSWORD", "")
    if bool(user) != bool(password):
        raise RuntimeError("CML_SMTP_USER e CML_SMTP_PASSWORD devem ser configurados juntos")
    with connect() as db:
        report = executive_report(dashboard(db))
    message = EmailMessage()
    message["Subject"] = "Camaleão Marketing Lab · relatório semanal"
    message["From"] = sender
    message["To"] = recipient
    message.set_content("O relatório semanal da Sua empresa está disponível na versão HTML desta mensagem.")
    message.add_alternative(report, subtype="html")
    context = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=context, timeout=15) as smtp:
            if user:
                smtp.login(user, password)
            smtp.send_message(message)
    else:
        with smtplib.SMTP(host, port, timeout=15) as smtp:
            smtp.starttls(context=context)
            if user:
                smtp.login(user, password)
            smtp.send_message(message)
    with connect() as db:
        record_job(db, "report", "ok", "Relatório semanal enviado")
    print("Relatório semanal enviado")


if __name__ == "__main__":
    try:
        send_report()
    except Exception as exc:
        with connect() as db:
            record_job(db, "report", "error", str(exc))
        raise
