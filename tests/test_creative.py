import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch

import app
import creative_pipeline as pipeline
import creative_store as store
import instagram_publish as publisher
import jobs


def sample_spec():
    source=json.loads((Path(__file__).resolve().parents[1]/'tests/fixtures/content.json').read_text())[2]
    result={k:source.get(k,0 if k=='duration' else [] if k in {'slides','scenes'} else '') for k in pipeline.SPEC['properties']}
    result['slides']=[{k:s.get(k,[] if k=='items' else '') for k in pipeline.SLIDE['properties']} for s in source['slides']]
    return result


class Runner:
    def __init__(self,fail=None,revise=False):self.calls=[];self.fail=fail;self.revise=revise
    def __call__(self,role,payload,images=()):
        self.calls.append(role)
        if role==self.fail:raise RuntimeError('Etapa interrompida para teste de retomada')
        if role=='analyst':return {'observations':[],'limitations':['Sem atribuição de vendas'],'next_test':'Medir salvamentos'}
        if role=='strategist':return {'theme':'Começar','angle':'Próximo passo','audience':'Primeira serviço','goal':'Conversas','hook':'Começar','cta':'Link da bio','format':'post'}
        if role=='researcher':return {'insights':['Hipótese editorial'],'evidence':[],'limitations':['Sem pesquisa de campo']}
        if role=='copywriter':return sample_spec()
        if role=='seo-editor':return {'caption':sample_spec()['caption'],'source_url':'','notes':[]}
        if role=='art-director':return {'asset_id':'orbit','cover_layout':'road-post','rationale':'Metáfora','checks':[]}
        if role=='reviewer':
            assert images and all(Path(x).exists() for x in images)
            return {'verdict':'revise' if self.revise else 'pass','score':7 if self.revise else 9,'issues':['Encurtar gancho'] if self.revise else [],'summary':'Revisão de teste'}
        raise AssertionError(role)


class CreativeFlow(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.db=Path(self.temp.name)/'creative.db'
        self.patches=[patch.object(app,'DB_PATH',self.db),patch.object(pipeline,'DB_PATH',self.db),
                      patch.object(publisher,'DB_PATH',self.db),patch.object(app,'SECRET','test-secret-with-at-least-thirty-two-characters'),
                      patch.dict(os.environ,{'CML_ADMIN_PASSWORD':'creative-test-password-with-32-characters','CML_APP_SECRET':'test-secret-with-at-least-thirty-two-characters'})]
        for p in self.patches:p.start()
        app.init_db()
        import brand
        self.brand_patch=patch.object(brand,'get',return_value={**brand.DEFAULT,'sources':['https://example.org/reference']});self.brand_patch.start()

    def tearDown(self):
        self.brand_patch.stop()
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()

    def queue(self,kind='post'):
        with app.connect() as db:return store.enqueue(db,'Uma ideia útil sobre começar na CML',kind)

    def render(self,spec,kind,cid,work):
        target=self.db.parent/'media';target.mkdir(exist_ok=True)
        file=target/f'post-{cid}.jpg';file.write_bytes(b'fixture-media-for-approval-testing')
        return {'files':[str(file)],'frames':[str(file)],'hashes':[hashlib.sha256(file.read_bytes()).hexdigest()]}

    def test_codex_fallback_keeps_subscription_auth_and_private_environment(self):
        calls=[]
        answer={'observations':[],'limitations':['Sem vendas conectadas'],'next_test':'Medir salvamentos'}
        def run(args,**kwargs):
            self.assertNotIn('OPENAI_API_KEY',kwargs['env'])
            self.assertNotIn('CML_APP_SECRET',kwargs['env'])
            if args[1]=='login':
                return subprocess.CompletedProcess(args,0,'Logged in using ChatGPT','')
            calls.append(args[args.index('--model')+1])
            self.assertIn('read-only',args)
            if len(calls)==1:
                raise subprocess.TimeoutExpired(args,180,stderr='private-provider-detail')
            Path(args[args.index('--output-last-message')+1]).write_text(json.dumps(answer))
            return subprocess.CompletedProcess(args,0,'','')
        with patch.dict(os.environ,{'OPENAI_API_KEY':'not-forwarded','CML_CREATIVE_MODEL':'gpt-6-sol','CML_CREATIVE_FALLBACK_MODEL':'gpt-6.1-sol'}),patch.object(pipeline.shutil,'which',return_value='/test/codex'),patch.object(pipeline.subprocess,'run',side_effect=run):
            self.assertEqual(pipeline.CodexRunner()('analyst',{}),answer)
        self.assertEqual(calls,['gpt-6-sol','gpt-6.1-sol'])
        with app.connect() as db:
            row=db.execute("SELECT detail FROM audit WHERE action='creative.model' ORDER BY id DESC LIMIT 1").fetchone()
        self.assertIn('gpt-6.1-sol',row[0]);self.assertNotIn('private-provider-detail',row[0])

    def test_blog_subscription_does_not_forward_application_credentials(self):
        from secret_store import put_setting
        with app.connect() as db:
            put_setting(db,'openai_mode','subscription')
            db.execute('INSERT INTO radar(title,source,url,category,score,seen_at) VALUES(?,?,?,?,?,?)',
                       ('Dúvidas sobre começar','test','https://example.org/pauta','Tendência',50,app.now()))
        proposal={'title':'Uma conversa para começar sua serviço','channel':'Blog','summary':'Organize as dúvidas antes de conversar com a CML.',
                  'body':'## Primeira conversa\n'+('Anote suas dúvidas e confirme as opções com a equipe da marca. '*70),'source_url':'https://example.org/reference'}
        calls=[]
        def run(args,**kwargs):
            self.assertNotIn('CML_APP_SECRET',kwargs['env'])
            self.assertNotIn('CML_INGEST_SECRET',kwargs['env'])
            self.assertNotIn('OPENAI_API_KEY',kwargs['env'])
            if args[1]=='login':return subprocess.CompletedProcess(args,0,'Logged in using ChatGPT','')
            calls.append(args)
            Path(args[args.index('--output-last-message')+1]).write_text(json.dumps(proposal))
            return subprocess.CompletedProcess(args,0,'','')
        with patch.dict(os.environ,{'CML_CODEX_ENABLED':'true','CML_INGEST_SECRET':'private-test','OPENAI_API_KEY':'not-forwarded','CML_BLOG_CODEX_MODEL':'gpt-6-sol'}),patch.object(jobs,'DB_PATH',self.db),patch.object(jobs,'official_context',return_value=('Trecho oficial','a'*64)),patch.object(jobs.shutil,'which',return_value='/test/codex'),patch.object(jobs.subprocess,'run',side_effect=run):
            jobs.editorial('blog')
        self.assertEqual(calls[0][calls[0].index('--model')+1],'gpt-6-sol')
        self.assertIn('features.shell_tool=false',calls[0])
        with app.connect() as db:
            self.assertEqual(db.execute('SELECT status FROM content WHERE title=?',(proposal['title'],)).fetchone()[0],'review')

    def test_reel_selected_illustrations_remain_visible_in_text_scene_types(self):
        source=json.loads((Path(__file__).resolve().parents[1]/'tests/fixtures/content.json').read_text())[4]
        spec={k:source.get(k,[] if k in {'slides','scenes'} else '') for k in pipeline.SPEC['properties']}
        spec['scenes']=[{k:scene.get(k,'') for k in pipeline.SCENE['properties']} for scene in source['scenes']]
        spec['scenes'][0].update(type='fear',image='orbit.svg')
        spec['scenes'][-1].update(type='cta',image='layers.svg')
        class ReelRunner(Runner):
            def __call__(self,role,payload,images=()):
                if role=='copywriter':self.calls.append(role);return spec
                if role=='motion-director':
                    self.calls.append(role)
                    return {'scenes':spec['scenes'],'duration':spec['duration'],'notes':[]}
                return super().__call__(role,payload,images)
        rendered=[]
        def renderer(value,*args):
            rendered.append(value)
            return self.render(value,*args)
        runner=ReelRunner();pipeline.execute(self.queue('reel'),runner,renderer)
        self.assertEqual(rendered[0]['scenes'][0]['type'],'road')
        self.assertEqual(rendered[0]['scenes'][-1]['type'],'road')
        self.assertEqual(rendered[0]['scenes'][0]['image'],'orbit.svg')
        self.assertEqual(spec['scenes'][0]['type'],'fear')
        self.assertIn('motion-director',runner.calls)

    def test_interrupted_stage_resumes_without_repeating_completed_roles(self):
        rid=self.queue();first=Runner(fail='art-director')
        with self.assertRaises(RuntimeError):pipeline.execute(rid,first,self.render)
        with app.connect() as db:
            before=db.execute('SELECT * FROM creative_runs WHERE id=?',(rid,)).fetchone()
            self.assertEqual(before['status'],'failed');cid=before['content_id']
        second=Runner();pipeline.execute(rid,second,self.render)
        self.assertNotIn('copywriter',second.calls);self.assertNotIn('strategist',second.calls)
        with app.connect() as db:
            run=db.execute('SELECT * FROM creative_runs WHERE id=?',(rid,)).fetchone()
            content=db.execute('SELECT * FROM content WHERE id=?',(cid,)).fetchone()
            self.assertEqual(run['content_id'],cid);self.assertEqual(run['status'],'review')
            self.assertEqual(content['status'],'review');self.assertEqual(content['approved_digest'],'')
            self.assertFalse(db.execute('SELECT 1 FROM instagram_outbox').fetchone())

    def test_revision_loop_stops_after_two_reviews(self):
        rid=self.queue();runner=Runner(revise=True);pipeline.execute(rid,runner,self.render)
        self.assertEqual(runner.calls.count('reviewer'),2)
        self.assertEqual(runner.calls.count('analyst'),1)
        with app.connect() as db:
            run=db.execute('SELECT * FROM creative_runs WHERE id=?',(rid,)).fetchone()
            self.assertEqual(run['status'],'needs_attention')
            self.assertEqual(db.execute('SELECT status FROM content WHERE id=?',(run['content_id'],)).fetchone()[0],'draft')

    def test_changed_file_invalidates_human_approval_before_network_call(self):
        rid=self.queue();pipeline.execute(rid,Runner(),self.render)
        with app.connect() as db:
            cid=db.execute('SELECT content_id FROM creative_runs WHERE id=?',(rid,)).fetchone()[0]
            seal=store.content_digest(db,cid)
            db.execute("UPDATE content SET status='approved',approved_digest=? WHERE id=?",(seal,cid))
            self.assertEqual(store.assert_approved_version(db,cid),seal)
        (self.db.parent/'media'/f'post-{cid}.jpg').write_bytes(b'changed-after-approval')
        with app.connect() as db:
            with self.assertRaisesRegex(ValueError,'alterado'):store.assert_approved_version(db,cid)

    def test_daily_feed_slot_is_shared_between_posts_carousels_and_reels(self):
        with app.connect() as db:
            first=app.next_publish_at(db,'post','Instagram')
            db.execute('INSERT INTO content(kind,title,channel,status,scheduled_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',
                       ('post','First','Instagram','approved',first,app.now(),app.now()))
            second=app.next_publish_at(db,'reel','Instagram')
            self.assertGreater(datetime.fromisoformat(second),datetime.fromisoformat(first))
            db.execute("UPDATE content SET status='published',published_at=?",(app.now(),))
            self.assertFalse(app.daily_publication_available(db,'carousel','Instagram'))

    def fixture_approved(self,kind):
        from secret_store import put_secret,put_setting
        with app.connect() as db:
            cid=db.execute('INSERT INTO content(kind,title,channel,body,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',
                           (kind,'Test','Instagram','Legenda de teste aprovada','approved',app.now(),app.now())).lastrowid
            folder=self.db.parent/'media';folder.mkdir(exist_ok=True)
            names=[f'carousel-{cid}-{i+1}.jpg' for i in range(5)] if kind=='carousel' else [f'reel-{cid}.mp4']
            files=[]
            for name in names:
                file=folder/name;file.write_bytes(b'fixture');files.append(file)
            store.register_media(db,cid,{'alt':'Teste','ai_generated':True,'slides':[{'title':str(i+1)} for i in range(5)]},files,{'verdict':'pass'})
            db.execute('UPDATE content SET approved_digest=? WHERE id=?',(store.content_digest(db,cid),cid))
            put_secret(db,'instagram_access_token','fake-test-token');put_setting(db,'instagram_user_id','1234567890');put_setting(db,'instagram_enabled','true')
        return cid

    def test_carousel_child_order_and_ai_disclosure_are_on_the_parent(self):
        cid=self.fixture_approved('carousel')
        with patch.object(publisher,'graph_call',side_effect=[{'id':str(n)} for n in range(100,107)]) as call,patch.object(publisher,'graph_status',return_value='FINISHED'):
            publisher.publish(cid)
        children=[x.args[4] for x in call.call_args_list[:5]]
        self.assertTrue(all(x['is_carousel_item']=='true' and 'is_ai_generated' not in x for x in children))
        parent=call.call_args_list[5].args[4]
        self.assertEqual(parent['children'],'100,101,102,103,104');self.assertEqual(parent['media_type'],'CAROUSEL')
        self.assertEqual(parent['is_ai_generated'],'true')
        with app.connect() as db:self.assertEqual(db.execute('SELECT status FROM content WHERE id=?',(cid,)).fetchone()[0],'published')

    def test_instagram_preparation_never_calls_the_publication_endpoint(self):
        cid=self.fixture_approved('reel')
        with app.connect() as db:db.execute('UPDATE content SET scheduled_at=? WHERE id=?',((datetime.now(timezone.utc)+timedelta(hours=2)).isoformat(),cid))
        with patch.object(publisher,'graph_call',return_value={'id':'100'}) as call,patch.object(publisher,'graph_status',return_value='FINISHED'):
            publisher.publish(cid,prepare_only=True)
            self.assertEqual(call.call_count,1)
            self.assertTrue(call.call_args.args[2].endswith('/media'))
        with app.connect() as db:self.assertEqual(db.execute('SELECT status FROM content WHERE id=?',(cid,)).fetchone()[0],'approved')

    def test_uncertain_reel_publish_is_never_retried_automatically(self):
        cid=self.fixture_approved('reel')
        with patch.object(publisher,'graph_call',side_effect=[{'id':'100'},RuntimeError('timeout')]) as call,patch.object(publisher,'graph_status',return_value='FINISHED'):
            with self.assertRaises(RuntimeError):publisher.publish(cid)
            fields=call.call_args_list[0].args[4]
            self.assertEqual(fields['media_type'],'REELS');self.assertIn('video_url',fields)
        with patch.object(publisher,'graph_call') as call:
            with self.assertRaisesRegex(RuntimeError,'conciliação'):publisher.publish(cid)
            call.assert_not_called()
