import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import getpass,hashlib,secrets
from app import connect,audit
password=getpass.getpass('Nova senha admin (mínimo 16 caracteres): ')
if len(password)<16:raise SystemExit('Senha curta; nenhuma alteração.')
salt=secrets.token_hex(16);digest=hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=2**14,r=8,p=1).hex()
with connect() as db:
 result=db.execute('UPDATE users SET salt=?,password_hash=? WHERE username=?',(salt,digest,'admin'))
 if result.rowcount!=1:raise SystemExit('Administrador não encontrado.')
 audit(db,'operator','password.reset','user:admin','Senha redefinida localmente; sessões existentes não revogadas')
print('Senha redefinida. Sessões existentes não foram revogadas.')
