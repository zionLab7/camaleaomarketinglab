# Relatórios por e-mail

O relatório HTML está disponível no painel sem SMTP. Para entrega semanal, configure no Portainer:

- `CML_SMTP_HOST`, `CML_SMTP_PORT` (587 padrão, STARTTLS; 465 usa TLS direto).
- `CML_SMTP_USER`, `CML_SMTP_PASSWORD` se o provedor exigir autenticação; use senha de aplicativo quando aplicável.
- `CML_REPORT_FROM`: remetente autorizado pelo provedor.
- `CML_REPORT_TO`: destinatário autorizado.

Recrie o editorial preservando volumes. O executor tenta enviar quando não existe sucesso nos últimos sete dias, incluindo uma primeira tentativa após configurar. Só configure destinatário quando quiser ativar o envio. Não exige Gmail nem cria conta de e-mail. SPF/DKIM e entregabilidade dependem do seu domínio/provedor. O relatório usa agregados e não inclui nomes/telefones de leads.
