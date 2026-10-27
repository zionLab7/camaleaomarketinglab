"""Verified atomic uploads through the hosting's existing pinned SSH access."""
from __future__ import annotations
import base64,hashlib,json,shlex,subprocess
from pathlib import Path

REMOTE=r'''
import base64,hashlib,json,os,re,sys,tarfile,datetime
from pathlib import Path
p=json.load(sys.stdin);root=Path(p['root']).resolve();assert root.is_dir()
files=p['files'];assert 1<=len(files)<=2000
for name,item in files.items():
 assert re.fullmatch(r'(?:blog/(?:[a-z0-9-]+/)?index\.html|blog/(?:brand-logo\.(?:png|svg)|style\.css|cml-track\.js|sitemap\.xml|\.htaccess)|blog/fonts/[a-zA-Z0-9_.-]+|sitemap\.xml|index\.html)',name),name
 assert (root/name).resolve().is_relative_to(root)
 data=base64.b64decode(item['body']);assert hashlib.sha256(data).hexdigest()==item['sha256']
backup_dir=Path.home()/'.cml-marketing-backups';backup_dir.mkdir(mode=0o700,exist_ok=True);backup_dir.chmod(0o700)
backup=backup_dir/('blog-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.tar.gz')
with tarfile.open(backup,'w:gz') as archive:
 for name in files:
  if (root/name).is_file():archive.add(root/name,arcname=name,recursive=False)
backup.chmod(0o600)
# Assets first, article bodies next, discovery indexes last.
ordered=sorted(files,key=lambda n:(n in ['blog/index.html','blog/sitemap.xml','sitemap.xml'],n.endswith('.html'),n))
for name in ordered:
 path=root/name;path.parent.mkdir(parents=True,exist_ok=True)
 temp=path.with_name(path.name+'.cml-upload-'+str(os.getpid()))
 temp.write_bytes(base64.b64decode(files[name]['body']));temp.chmod(0o644);os.replace(temp,path)
for name,item in files.items():assert hashlib.sha256((root/name).read_bytes()).hexdigest()==item['sha256']
print(json.dumps({'ok':True,'hashes':{n:v['sha256'] for n,v in files.items()},'backup':backup.name}))
'''


def upload(host,user,port,key,known,remote_blog,files):
    manifest={name:{'body':base64.b64encode(Path(path).read_bytes()).decode(),
                    'sha256':hashlib.sha256(Path(path).read_bytes()).hexdigest()} for name,path in files.items()}
    payload={'root':remote_blog.removesuffix('/blog'),'files':manifest}
    result=subprocess.run(['ssh','-oBatchMode=yes','-oStrictHostKeyChecking=yes','-oUserKnownHostsFile='+str(known),
                           '-i',str(key),'-p',str(port),user+'@'+host,'python3 -c '+shlex.quote(REMOTE)],
                          input=json.dumps(payload),capture_output=True,text=True,timeout=120)
    if result.returncode:raise RuntimeError('A hospedagem não confirmou a transferência SSH verificada')
    try:confirmation=json.loads(result.stdout.strip())
    except (ValueError,TypeError):raise RuntimeError('Resposta de confirmação da hospedagem inválida') from None
    expected={n:v['sha256'] for n,v in manifest.items()}
    if confirmation.get('ok') is not True or confirmation.get('hashes')!=expected:
        raise RuntimeError('A hospedagem não confirmou todos os arquivos; artigo continua aprovado')
    return confirmation
