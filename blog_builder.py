"""Build portable static blog pages using the installation's brand configuration."""
from __future__ import annotations
import argparse,html,json,re,shutil
from datetime import date,datetime
from pathlib import Path
from urllib.parse import urlparse,quote
from zoneinfo import ZoneInfo
from app import connect
from brand import get
ROOT=Path(__file__).resolve().parent
SOURCE=ROOT/'blog/articles.json'
OUTPUT=ROOT/'site-export/blog'

def safe_url(value):
 p=urlparse(value)
 if p.scheme!='https' or not p.hostname or p.username or p.password:raise ValueError('Referência precisa usar HTTPS')
 return html.escape(value,quote=True)

def inline(value):
 escaped=html.escape(value)
 escaped=re.sub(r'\*\*(.+?)\*\*',r'<strong>\1</strong>',escaped)
 return re.sub(r'\[([^\]\n]{1,120})\]\((https://[^)\s]+)\)',lambda m:f'<a href="{safe_url(html.unescape(m[2]))}" rel="noopener noreferrer">{m[1]}</a>',escaped)

def markdown(value):
 result=[];paragraph=[];listing=False
 def flush():
  if paragraph:result.append('<p>'+inline(' '.join(paragraph))+'</p>');paragraph.clear()
 for raw in value.splitlines():
  line=raw.strip()
  if line.startswith('## '):
   flush()
   if listing:result.append('</ul>');listing=False
   result.append('<h2>'+inline(line[3:])+'</h2>')
  elif line.startswith('- '):
   flush()
   if not listing:result.append('<ul>');listing=True
   result.append('<li>'+inline(line[2:])+'</li>')
  elif not line:
   flush()
   if listing:result.append('</ul>');listing=False
  else:
   if listing:result.append('</ul>');listing=False
   paragraph.append(line)
 flush()
 if listing:result.append('</ul>')
 return '\n'.join(result)

def validate(article):
 if any(not article.get(k) for k in ['slug','title','description','body','published','sources']):raise ValueError('Artigo incompleto')
 if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',article['slug']):raise ValueError('Slug inválido')
 try:published=date.fromisoformat(article['published'])
 except ValueError:
  stamp=datetime.fromisoformat(article['published'].replace('Z','+00:00'))
  if stamp.tzinfo:stamp=stamp.astimezone(ZoneInfo(get()['timezone']))
  published=stamp.date()
 if len(article['title'])>110 or len(article['description'])>220 or len(article['body'])<350:raise ValueError('Dimensão editorial inválida')
 for source in article['sources']:safe_url(source['url'])
 return {**article,'published':published.isoformat()}

def shell(title,description,canonical,body,structured=None):
 b=get();e=html.escape
 from tracking_install import snippet
 payload=json.dumps(structured,ensure_ascii=False).replace('<',r'\u003c') if structured else ''
 ld='<script type="application/ld+json">'+payload+'</script>' if payload else ''
 css=(ROOT/'blog/style.css').read_text()
 for a,c in [('#3a0927',b['primary']),('#f68f1d',b['accent']),('#fff9f5',b['background'])]:css=css.replace(a,c)
 # Portable system fonts; every page is self-contained except optional consented analytics.
 from creative_store import catalog
 logo=next((a for a in catalog()['assets'] if a['id']==b['logo_asset']),None)
 logo_tag='<img src="/blog/brand-logo'+Path(logo['file']).suffix+'" alt="" width="64" height="64" style="object-fit:contain">' if logo else ''
 name=e(b['name']);cta=safe_url(b['cta_url']);label=e(b['cta_label'])
 return f'''<!doctype html><html lang="{b['locale']}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)} | {name}</title><meta name="description" content="{e(description,quote=True)}"><meta name="robots" content="index,follow,max-image-preview:large"><link rel="canonical" href="{safe_url(canonical)}"><meta property="og:title" content="{e(title,quote=True)}"><meta property="og:description" content="{e(description,quote=True)}"><style>{css}body{{font-family:Arial,sans-serif}}</style>{ld}{snippet()}</head><body><header class="top"><a class="brand" href="{safe_url(b['website'])}">{logo_tag}{name}</a><nav><a href="/blog/">Blog</a><a class="nav-cta" href="{cta}">{label} ↗</a></nav></header>{body}<footer><strong>{name}</strong><a href="{cta}">{label}</a><small>© {date.today().year} {name}</small></footer></body></html>'''

def load_articles(pending_id=None):
 articles=[validate(x) for x in json.loads(SOURCE.read_text())]
 with connect() as db:
  rows=db.execute("SELECT id,title,summary,body,source_url,published_at,updated_at FROM content WHERE kind='blog' AND (status='published' OR (id=? AND status='approved')) ORDER BY id",(pending_id or -1,)).fetchall()
 for row in rows:
  import unicodedata
  title=unicodedata.normalize('NFKD',row['title']).encode('ascii','ignore').decode()
  slug=re.sub(r'[^a-z0-9]+','-',title.lower()).strip('-')[:65].rstrip('-') or 'artigo'
  articles.append(validate({'slug':f"{slug}-{row['id']}",'title':row['title'],'description':row['summary'],'body':row['body'],'published':row['published_at'] or (date.today().isoformat() if row['id']==pending_id else row['updated_at'][:10]),'sources':[{'label':'Fonte de referência','url':row['source_url']}]}))
 if len({a['slug'] for a in articles})!=len(articles):raise ValueError('Slugs repetidos')
 return sorted(articles,key=lambda a:a['published'],reverse=True)

def build(output=OUTPUT,pending_id=None):
 b=get();base=b['website'].rstrip('/');articles=load_articles(pending_id);output=Path(output);output.mkdir(parents=True,exist_ok=True)
 (output/'.htaccess').write_text((ROOT/'blog/performance.htaccess').read_text())
 from creative_store import catalog,library_file
 logo=next((a for a in catalog()['assets'] if a['id']==b['logo_asset']),None)
 if logo:shutil.copyfile(library_file(logo['id']),output/('brand-logo'+Path(logo['file']).suffix))
 from tracking_install import snippet
 if snippet():shutil.copyfile(ROOT/'tracking/cml-track.js',output/'cml-track.js')
 urls=[base+'/blog/'];cards=[]
 for a in articles:
  url=base+'/blog/'+quote(a['slug'])+'/';urls.append(url)
  sources=''.join(f'<li><a href="{safe_url(s["url"])}">{html.escape(s["label"])}</a></li>' for s in a['sources'])
  body=f'<main class="article-wrap"><p class="eyebrow">BLOG · {a["published"]}</p><article><h1>{html.escape(a["title"])}</h1><p class="dek">{html.escape(a["description"])}</p><div class="article-body">{markdown(a["body"])}</div><section class="sources"><h2>Fontes e referências</h2><ul>{sources}</ul></section></article><aside class="cta"><h2>{html.escape(b["cta_label"])}</h2><a href="{safe_url(b["cta_url"])}">Conversar com a equipe ↗</a></aside></main>'
  ld={'@context':'https://schema.org','@type':'BlogPosting','headline':a['title'],'description':a['description'],'datePublished':a['published'],'dateModified':a['published'],'mainEntityOfPage':url,'author':{'@type':'Organization','name':b['name']},'publisher':{'@type':'Organization','name':b['name']}}
  dest=output/a['slug'];dest.mkdir(exist_ok=True);(dest/'index.html').write_text(shell(a['title'],a['description'],url,body,ld))
  cards.append(f'<a class="card" href="/blog/{quote(a["slug"])}/"><h2>{html.escape(a["title"])}</h2><p>{html.escape(a["description"])}</p><span>Ler artigo ↗</span></a>')
 body=f'<main><section class="hero"><p class="eyebrow">{html.escape(b["name"])} / BLOG</p><h1>Ideias para o seu próximo passo.</h1><p>{html.escape(b["tagline"])}</p></section><section class="feed"><div class="cards">'+(''.join(cards) or '<p>Os primeiros artigos serão publicados após aprovação.</p>')+'</div></section></main>'
 (output/'index.html').write_text(shell('Blog',b['tagline'],urls[0],body))
 (output/'sitemap.xml').write_text('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+''.join('<url><loc>'+html.escape(u)+'</loc></url>' for u in urls)+'</urlset>')
 return urls

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=OUTPUT);args=parser.parse_args()
 for url in build(args.output):print(url)
