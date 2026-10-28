"""Official image/carousel/Reels publishing with version-bound approval and an outbox."""
from __future__ import annotations

import fcntl
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from app import DB_PATH, audit, connect, daily_publication_available, now
from creative_store import assert_approved_version, file_signature
from jobs import record_job
from secret_store import get_secret, setting

GRAPH_HOSTS={'graph.instagram.com','graph.facebook.com'}


def graph_response(host,version,path,token,fields=None,query=None):
    if host not in GRAPH_HOSTS or not re.fullmatch(r'v\d+\.\d+',version) or not re.fullmatch(r'[0-9A-Za-z_/]+',path):
        raise ValueError('Endpoint Meta inválido')
    url=f'https://{host}/{version}/{path}'
    if query:url+='?'+urllib.parse.urlencode(query)
    body=urllib.parse.urlencode(fields).encode() if fields is not None else None
    request=urllib.request.Request(url,data=body,headers={'Authorization':f'Bearer {token}','User-Agent':'CamaleaoMarketingLab/0.6'})
    try:
        with urllib.request.urlopen(request,timeout=30) as response:payload=json.load(response)
    except urllib.error.HTTPError as exc:
        try:
            error=json.loads(exc.read(32000)).get('error',{})
            message=str(error.get('message',''))
            message=re.sub(r'https?://\S+','[URL]',message)
            message=re.sub(r'\b(?:IGAA|EAA)[A-Za-z0-9_-]+','[credencial]',message)
            code=str(error.get('code',''));subcode=str(error.get('error_subcode',''))
        except Exception:message='';code='';subcode=''
        raise RuntimeError(f'Meta HTTP {exc.code} · código {code}/{subcode} · {message[:220]}') from None
    if not isinstance(payload,dict):raise RuntimeError('Resposta Meta inválida')
    return payload


def graph_call(host,version,path,token,fields=None):
    payload=graph_response(host,version,path,token,fields)
    if not re.fullmatch(r'\d+',str(payload.get('id',''))):raise RuntimeError('Resposta Meta sem ID')
    return payload


def graph_status(host,version,container,token):
    return graph_response(host,version,container,token,query={'fields':'status_code'}).get('status_code','')


def wait_ready(host,version,container,token):
    for attempt in range(5):
        status=graph_status(host,version,container,token)
        if status=='FINISHED':return
        if status=='PUBLISHED':raise RuntimeError('O contêiner já foi publicado; concilie o ID antes de continuar')
        if status in {'ERROR','EXPIRED'}:raise RuntimeError('O contêiner Meta falhou ou expirou; revisão necessária')
        if status!='IN_PROGRESS':raise RuntimeError('A Meta não informou o estado de processamento')
        if attempt<4:time.sleep(60)
    raise RuntimeError('A Meta continua processando a mídia; retome a fila depois')


def signed_url(file,digest):
    expires=int(time.time())+3600
    domain=os.getenv('CML_DOMAIN','marketing.example.com')
    if not re.fullmatch(r'[a-zA-Z0-9.-]+',domain):raise ValueError('Domínio público inválido')
    sig=file_signature(file,expires,digest)
    return f'https://{domain}/public/instagram/v2/{file}?expires={expires}&sig={sig}'


def publish(content_id,prepare_only=False):
    lockfile=DB_PATH.parent/'instagram-publisher.lock'
    with lockfile.open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('Outra publicação já está em execução')
        _publish(content_id,prepare_only)


def _publish(content_id,prepare_only=False):
    host=os.getenv('CML_META_GRAPH_HOST','graph.instagram.com')
    version=os.getenv('CML_META_GRAPH_VERSION','v26.0')
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT * FROM content WHERE id=?',(content_id,)).fetchone()
        if not row or row['kind'] not in {'post','carousel','reel'} or row['channel']!='Instagram' or row['status']!='approved':
            raise ValueError('Conteúdo precisa estar aprovado para Instagram')
        if not prepare_only and row['scheduled_at'] and row['scheduled_at']>now():raise RuntimeError('Horário da publicação ainda não chegou')
        if not prepare_only and not daily_publication_available(db,'post','Instagram'):raise RuntimeError('Limite diário atingido ou intervalo mínimo em andamento; a fila aguardará')
        if setting(db,'instagram_enabled')!='true':raise RuntimeError('Publicação Instagram desativada')
        user_id=setting(db,'instagram_user_id');token=get_secret(db,'instagram_access_token')
        if not re.fullmatch(r'\d{5,30}',user_id) or not token:raise RuntimeError('Conta Instagram não configurada')
        digest=assert_approved_version(db,content_id)
        media=db.execute('SELECT manifest_json,spec_json FROM creative_media WHERE content_id=?',(content_id,)).fetchone()
        manifest=json.loads(media['manifest_json']);spec=json.loads(media['spec_json'])
        outbox=db.execute('SELECT * FROM instagram_outbox WHERE content_id=?',(content_id,)).fetchone()
        if outbox and outbox['stage'] in {'publishing','needs_review','published'}:
            raise RuntimeError('Publicação anterior exige conciliação manual para evitar duplicidade')
        container_id=outbox['container_id'] if outbox else ''
        caption=row['body'].strip()
        if not caption or len(caption)>2200:raise ValueError('Legenda fora do limite do Instagram')
        kind=row['kind'];files=[x['name'] for x in manifest]
        names=([x for x in files if x.endswith('.mp4')] if kind=='reel' else
               [x for x in files if x.endswith('.jpg') and '-cover' not in x and '-frame-' not in x])
        if len(names)!=(5 if kind=='carousel' else 1):raise ValueError('Arquivos de publicação incompletos')
        if not outbox:
            db.execute("INSERT INTO instagram_outbox(content_id,stage,updated_at) VALUES(?,'preparing',?)",(content_id,now()))
    if not container_id:
        # Children can be recreated after preparation failure: they are not public posts.
        fields={'caption':caption}
        if spec.get('ai_generated'):fields['is_ai_generated']='true'
        if kind=='carousel':
            children=[]
            for i,name in enumerate(names):
                alt=spec.get('slides',[{}]*5)[i].get('title',spec.get('alt',''))
                child=graph_call(host,version,f'{user_id}/media',token,
                                 {'image_url':signed_url(name,digest),'is_carousel_item':'true','alt_text':alt[:1000]})
                children.append(child['id'])
            fields.update(media_type='CAROUSEL',children=','.join(children))
        elif kind=='reel':fields.update(media_type='REELS',video_url=signed_url(names[0],digest),share_to_feed='true')
        else:fields.update(image_url=signed_url(names[0],digest),alt_text=spec.get('alt','')[:1000])
        response=graph_call(host,version,f'{user_id}/media',token,fields)
        container_id=str(response['id'])
        with connect() as db:
            db.execute("UPDATE instagram_outbox SET stage='prepared',container_id=?,updated_at=? WHERE content_id=?",(container_id,now(),content_id))
            audit(db,'publisher','instagram.prepare',f'content:{content_id}',f'{kind} · contêiner {container_id}')
    wait_ready(host,version,container_id,token)
    if prepare_only:
        with connect() as db:record_job(db,f'instagram_prepare_{content_id}','ok','Mídia aprovada e pronta na Meta; aguardando horário programado')
        return
    with connect() as db:
        assert_approved_version(db,content_id)
        db.execute("UPDATE instagram_outbox SET stage='publishing',updated_at=? WHERE content_id=?",(now(),content_id))
    try:response=graph_call(host,version,f'{user_id}/media_publish',token,{'creation_id':container_id})
    except Exception:
        with connect() as db:
            db.execute("UPDATE instagram_outbox SET stage='needs_review',error='Resultado de publicação incerto; conciliar antes de repetir',updated_at=? WHERE content_id=?",(now(),content_id))
        raise
    media_id=str(response['id'])
    with connect() as db:
        db.execute("UPDATE instagram_outbox SET stage='published',media_id=?,error='',updated_at=? WHERE content_id=?",(media_id,now(),content_id))
        db.execute("UPDATE content SET status='published',published_at=?,updated_at=? WHERE id=? AND status='approved'",(now(),now(),content_id))
        audit(db,'publisher','instagram.publish',f'content:{content_id}',f'Meta media ID {media_id}')
        record_job(db,f'instagram_publish_{content_id}','ok',f'Publicado na Meta: {media_id}')


if __name__=='__main__':
    if len(sys.argv)!=2 or not sys.argv[1].isdigit():raise SystemExit('Uso: python instagram_publish.py CONTENT_ID')
    try:publish(int(sys.argv[1]))
    except Exception as exc:
        with connect() as db:record_job(db,f'instagram_publish_{sys.argv[1]}','error',str(exc)[:280])
        raise
