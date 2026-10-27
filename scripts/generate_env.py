"""Create a private local environment file without displaying credentials."""
from pathlib import Path
import secrets
root=Path(__file__).resolve().parents[1];target=root/'.env'
if target.exists():raise SystemExit('.env já existe; não foi sobrescrito.')
text=(root/'.env.example').read_text()
for key in ['CML_APP_SECRET','CML_ADMIN_PASSWORD','CML_INGEST_SECRET']:text=text.replace(key+'=\n',key+'='+secrets.token_urlsafe(48)+'\n')
with target.open('x') as f:f.write(text)
target.chmod(0o600)
print('Arquivo .env privado criado. Usuário: admin. Consulte CML_ADMIN_PASSWORD localmente; não publique esse arquivo.')
