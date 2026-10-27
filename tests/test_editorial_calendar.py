import base64,hashlib,json,os,subprocess,sys,tempfile,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch
import app
import editorial_calendar as calendar
import hosting_upload
from creative_store import register_media,content_digest,assert_approved_version


class EditorialCalendar(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.patches=[patch.object(app,'DB_PATH',self.root/'db.sqlite'),patch.dict(os.environ,{'CML_ADMIN_PASSWORD':'test-calendar-password-very-long'})]
        for p in self.patches:p.start()
        app.init_db()
        with app.connect() as db:db.execute('DELETE FROM editorial_slots')
        self.current=datetime(2026,10,22,10,0,tzinfo=timezone.utc)
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()
    def content(self,db,kind='post',channel='Instagram',status='review',caption='Uma mensagem útil e um convite para conversar com a CML. Link da bio.'):
        return db.execute('INSERT INTO content(kind,title,channel,body,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',(kind,'Test',channel,caption,status,app.now(),app.now())).lastrowid
    def test_schedule_is_set_before_approval_and_kept_after_approval(self):
        with app.connect() as db:
            cid=self.content(db);stamp=calendar.reserve(db,cid,self.current)
            self.assertIsNotNone(db.execute('SELECT scheduled_at FROM content WHERE id=?',(cid,)).fetchone()[0])
            self.assertEqual(calendar.approve_schedule(db,cid,self.current),stamp)
            self.assertEqual(db.execute('SELECT status FROM content WHERE id=?',(cid,)).fetchone()[0],'review')
    def test_daily_slots_include_weekend_and_multiple_test_hours(self):
        with app.connect() as db:
            calendar.ensure_horizon(db,self.current)
            rows=db.execute('SELECT * FROM editorial_slots WHERE channel=? ORDER BY local_date LIMIT 7',('Instagram',)).fetchall()
            self.assertEqual(len(rows),7);self.assertEqual(len({r['test_arm'] for r in rows}),3)
            self.assertTrue(any(datetime.fromisoformat(r['local_date']).weekday()==6 for r in rows))
    def test_rescheduling_rejects_day_collision_without_losing_original_slot(self):
        with app.connect() as db:
            a=self.content(db);b=self.content(db)
            first=calendar.reserve(db,a,self.current);second=calendar.reserve(db,b,self.current)
            with self.assertRaisesRegex(ValueError,'reservada'):calendar.reschedule(db,a,second,self.current)
            self.assertEqual(db.execute('SELECT scheduled_at FROM content WHERE id=?',(a,)).fetchone()[0],first)
    def test_caption_notes_cover_singular_plural_and_keep_the_public_copy(self):
        for note in ['Imagem ilustrativa criada com IA; não representa alunos reais.',
                     'Imagens ilustrativas criadas com IA. Não mostram a CML.',
                     'Ilustração criada com inteligência artificial.',
                     'Conteúdo feito com IA.']:
            self.assertEqual(calendar.clean_caption('Converse com a CML pelo link da bio.\n\n'+note),'Converse com a CML pelo link da bio.')

    def test_caption_cleanup_keeps_copy_and_explicit_approval_for_unchanged_media(self):
        with app.connect() as db:
            cid=self.content(db,status='approved',caption='Salve as perguntas para conversar com a CML. Link da bio.\n\nImagens ilustrativas criadas com IA. Não mostram a equipe ou instalações reais da marca.\n\n#MinhaMarca')
            media=self.root/'media';media.mkdir();file=media/f'post-{cid}.jpg';file.write_bytes(b'approved-media')
            register_media(db,cid,{'caption':'old'},[file],{'verdict':'pass'})
            db.execute('UPDATE content SET approved_digest=? WHERE id=?',(content_digest(db,cid),cid))
            self.assertEqual(calendar.clean_existing_captions(db),[cid])
            row=db.execute('SELECT * FROM content WHERE id=?',(cid,)).fetchone()
            self.assertEqual(row['status'],'approved');self.assertIn('#MinhaMarca',row['body']);self.assertNotIn('criadas com IA',row['body'])
            self.assertEqual(assert_approved_version(db,cid),row['approved_digest'])
    def test_ssh_transfer_confirms_hashes_and_private_backup(self):
        root=self.root/'public_html';root.mkdir();(root/'blog').mkdir();(root/'blog/index.html').write_text('old')
        body=b'<h1>Approved article</h1>';manifest={'blog/index.html':{'body':base64.b64encode(body).decode(),'sha256':hashlib.sha256(body).hexdigest()}}
        result=subprocess.run([sys.executable,'-c',hosting_upload.REMOTE],input=json.dumps({'root':str(root),'files':manifest}),capture_output=True,text=True,env={**os.environ,'HOME':str(self.root)})
        self.assertEqual(result.returncode,0,result.stderr);self.assertEqual((root/'blog/index.html').read_bytes(),body)
        self.assertTrue(json.loads(result.stdout)['ok']);self.assertFalse(list(root.glob('*.tar.gz')))
    def test_failed_publication_retries_after_five_minutes_instead_of_two_hours(self):
        import scheduler
        with app.connect() as db:
            db.execute('INSERT INTO job_runs(job,status,detail,at) VALUES(?,?,?,?)',('blog_publish_15','error','test',(datetime.now(timezone.utc)-timedelta(minutes=6)).isoformat()))
        self.assertTrue(scheduler.due('blog_publish_15',24))

    def test_missing_host_confirmation_is_not_a_successful_publication(self):
        file=self.root/'index.html';file.write_text('article')
        response=subprocess.CompletedProcess([],0,'{"ok":true,"hashes":{}}','')
        with patch.object(hosting_upload.subprocess,'run',return_value=response):
            with self.assertRaisesRegex(RuntimeError,'confirmou todos'):hosting_upload.upload('host','user',22,Path('/key'),Path('/known'),'/site/blog',{'blog/index.html':file})
