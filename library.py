"""Small original starter library plus validated private raster uploads."""
import base64,hashlib,io,json,os,shutil,struct,wave
from pathlib import Path
from brand import DATA,ROOT,get
LIBRARY=DATA/'library'

def initialize():
 LIBRARY.mkdir(parents=True,exist_ok=True);(LIBRARY/'assets').mkdir(exist_ok=True)
 catalog=LIBRARY/'catalog.json'
 if not catalog.exists():
  shutil.copytree(ROOT/'creative-library',LIBRARY,dirs_exist_ok=True)
 # A silent audio track keeps video encoding deterministic; no licensed music shipped.
 sound=LIBRARY/'assets/trilha-original.wav'
 if not sound.exists():
  with wave.open(str(sound),'wb') as f:
   f.setnchannels(1);f.setsampwidth(2);f.setframerate(44100);f.writeframes(b'\0\0'*44100*36)
 return LIBRARY

def upload(data):
 from PIL import Image,ImageOps
 if not isinstance(data.get('data'),str) or len(data['data'])>5_600_000:raise ValueError('Imagem maior que 4 MB')
 try:raw=base64.b64decode(data['data'],validate=True)
 except Exception:raise ValueError('Imagem inválida') from None
 if len(raw)>4_000_000:raise ValueError('Imagem maior que 4 MB')
 Image.MAX_IMAGE_PIXELS=20_000_000
 try:
  image=Image.open(io.BytesIO(raw))
  if image.format not in {'PNG','JPEG','WEBP'} or image.width*image.height>20_000_000:raise ValueError()
  image=ImageOps.exif_transpose(image).convert('RGBA');image.thumbnail((2400,2400))
  output=io.BytesIO();image.save(output,format='PNG');clean=output.getvalue()
 except Exception:raise ValueError('Use PNG, JPEG ou WebP válido, até 20 megapixels') from None
 if not data.get('rights_confirmed'):raise ValueError('Confirme autorização de uso')
 initialize();asset_id='asset-'+hashlib.sha256(clean).hexdigest()[:20]
 file=LIBRARY/'assets'/(asset_id+'.png');file.write_bytes(clean)
 path=LIBRARY/'catalog.json';catalog=json.loads(path.read_text())
 if not any(x['id']==asset_id for x in catalog['assets']):
  catalog['assets'].append({'id':asset_id,'file':'assets/'+file.name,'title':str(data.get('title','Elemento da marca'))[:120],
   'style':'illustration' if data.get('illustrative') else 'photo','tags':[],
   'provenance':{'origin':'owner-upload','rights':'authorized by installation owner','illustrative':bool(data.get('illustrative')),'ai_generated':bool(data.get('ai_generated'))}})
  tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(catalog,ensure_ascii=False,indent=2));tmp.replace(path)
 return {'id':asset_id,'url':'/api/library/'+asset_id}

def render_brand(work):
 import html
 b=get();initialize()
 catalog=json.loads((LIBRARY/'catalog.json').read_text())
 logo=next((a for a in catalog['assets'] if a['id']==b['logo_asset']),None)
 if logo:
  filename=Path(logo['file']).name;b['render_logo']=filename
 else:
  b['render_logo']='brand-wordmark.svg'
  (work/'assets'/b['render_logo']).write_text('<svg xmlns="http://www.w3.org/2000/svg" width="640" height="170"><rect width="640" height="170" rx="20" fill="'+b['background']+'"/><text x="28" y="100" font-family="Arial,sans-serif" font-size="48" fill="'+b['primary']+'">'+html.escape(b['name'][:24])+'</text></svg>')
 (work/'brand.json').write_text(json.dumps(b,ensure_ascii=False))
