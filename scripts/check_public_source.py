"""Release guard: source-only, no runtime state, private keys or vendor tokens."""
from pathlib import Path
import re,sys,subprocess
ROOT=Path(__file__).resolve().parents[1]
SKIP={'.git','.venv','node_modules','__pycache__','data','site-export'}
patterns=[r'sk-(?:proj-)?[A-Za-z0-9_-]{30,}',r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',r'IGAA[A-Za-z0-9]{50,}',r'gh[pousr]_[A-Za-z0-9]{30,}',r'[a-z0-9.-]+@(?:gmail|icloud)\.com',r'gpautoescola\.com\.br',r'82\.25\.64\.218',r'camaleao\.cloud']
errors=[];count=0
if (ROOT/'.git').exists():
 paths=[ROOT/name for name in subprocess.check_output(['git','ls-files'],cwd=ROOT,text=True).splitlines()]
else:paths=[p for p in ROOT.rglob('*') if p.is_file() and not set(p.relative_to(ROOT).parts)&SKIP]
for p in paths:
 if set(p.relative_to(ROOT).parts)&SKIP:errors.append(str(p.relative_to(ROOT))+': runtime dependency/state must not be tracked');continue
 if p.name=='.env' or p.suffix in {'.db','.sqlite','.zip','.pem','.key'}:errors.append(str(p.relative_to(ROOT))+': runtime/private file');continue
 try:text=p.read_text()
 except UnicodeDecodeError:errors.append(str(p.relative_to(ROOT))+': unexpected binary');continue
 for pattern in patterns:
  if re.search(pattern,text,re.I):errors.append(str(p.relative_to(ROOT))+': sensitive content pattern')
 count+=1
if errors:print('\n'.join(errors));sys.exit(1)
print(f'Public source guard OK: {count} text files, no customer credentials or runtime data.')
