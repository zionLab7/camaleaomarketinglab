"""Read per-media outcomes in comparable 24h/72h/7d windows, never invent zeroes."""
from __future__ import annotations
import json,os
from datetime import datetime,timedelta,timezone
from app import connect,now
from secret_store import get_secret
from instagram_publish import graph_response

WINDOWS=[('24h',24),('72h',72),('7d',168)]


def collect(current=None):
    current=current or datetime.now(timezone.utc)
    with connect() as db:
        rows=[dict(x) for x in db.execute("SELECT c.id,c.published_at,o.media_id FROM content c JOIN instagram_outbox o ON o.content_id=c.id WHERE c.status='published' AND o.media_id<>'' ORDER BY c.published_at DESC LIMIT 60")]
        token=get_secret(db,'instagram_access_token')
    if not token:return
    host=os.getenv('CML_META_GRAPH_HOST','graph.instagram.com');version=os.getenv('CML_META_GRAPH_VERSION','v26.0')
    for row in rows:
        age=(current-datetime.fromisoformat(row['published_at'])).total_seconds()/3600
        for label,hours in WINDOWS:
            # Avoid calling a week-old outcome a 24h snapshot after an outage.
            if not hours<=age<hours+24:continue
            with connect() as db:
                if db.execute('SELECT 1 FROM media_measurements WHERE content_id=? AND window=?',(row['id'],label)).fetchone():continue
            metrics={};missing=[]
            for metric in ('reach','views','likes','comments','saved','shares','total_interactions'):
                try:
                    response=graph_response(host,version,row['media_id']+'/insights',token,query={'metric':metric})
                    item=next(x for x in response.get('data',[]) if x.get('name')==metric)
                    value=item.get('total_value',{}).get('value')
                    if value is None:value=item.get('values',[{}])[0].get('value')
                    if not isinstance(value,(int,float)):raise ValueError('Métrica sem valor')
                    metrics['interactions' if metric=='total_interactions' else metric]=value
                except (RuntimeError,ValueError,StopIteration,IndexError,TypeError):missing.append(metric)
            if not metrics:continue  # Retry later; missing authorization is not a zero-result post.
            with connect() as db:
                db.execute('INSERT OR IGNORE INTO media_measurements(content_id,window,captured_at,metrics_json,missing_json) VALUES(?,?,?,?,?)',
                           (row['id'],label,now(),json.dumps(metrics),json.dumps(missing)))
