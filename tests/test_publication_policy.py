import json,os,tempfile,unittest
from pathlib import Path
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
import app,editorial_calendar as calendar

class PublicationPolicy(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.patches=[patch.object(app,'DB_PATH',Path(self.temp.name)/'test.db'),patch.dict(os.environ,{'CML_ADMIN_PASSWORD':'test-password-long-enough'})]
  for p in self.patches:p.start()
  app.init_db();self.current=datetime(2026,10,28,9,0,tzinfo=timezone.utc)
 def tearDown(self):
  for p in reversed(self.patches):p.stop()
  self.temp.cleanup()
 def config(self,db,daily=2):
  calendar.save_policy(db,{c:{'daily':daily,'gap_minutes':60} for c in ['Instagram','Blog']})
 def content(self,db,kind='post',channel='Instagram',status='review',published=None):
  return db.execute("INSERT INTO content(kind,title,channel,status,published_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",(kind,'Conteúdo de teste',channel,status,published,app.now(),app.now())).lastrowid
 def test_multiple_positions_per_day_have_distinct_times_and_content(self):
  with app.connect() as db:
   self.config(db);db.execute('DELETE FROM editorial_slots');calendar.ensure_horizon(db,self.current)
   for channel in ['Blog','Instagram']:
    rows=db.execute('SELECT * FROM editorial_slots WHERE channel=? AND local_date=?',(channel,'2026-10-29')).fetchall()
    self.assertEqual(len(rows),2);self.assertEqual(len({r['scheduled_at'] for r in rows}),2)
   ids=[self.content(db) for _ in range(2)]
   stamps=[calendar.reserve(db,cid,self.current) for cid in ids]
   self.assertEqual(stamps[0][:10],stamps[1][:10]);self.assertNotEqual(*stamps)
   self.assertEqual(db.execute('SELECT count(*) FROM editorial_slots WHERE content_id IS NOT NULL').fetchone()[0],2)
 def test_shared_instagram_cap_and_gap_blog_independent(self):
  with app.connect() as db:
   self.config(db)
   self.content(db,kind='carousel',status='published',published='2026-10-28T08:45:00+00:00')
   self.assertFalse(calendar.publication_available(db,'reel','Instagram',self.current))
   later=self.current+timedelta(hours=1)
   self.assertTrue(calendar.publication_available(db,'post','Instagram',later))
   self.content(db,kind='reel',status='published',published='2026-10-28T09:50:00+00:00')
   self.assertFalse(calendar.publication_available(db,'post','Instagram',later+timedelta(hours=2)))
   self.assertTrue(calendar.publication_available(db,'blog','Blog',later))
 def test_reschedule_two_in_one_day_rejects_third_and_close_time(self):
  with app.connect() as db:
   self.config(db);ids=[self.content(db) for _ in range(3)]
   for cid in ids:calendar.reserve(db,cid,self.current)
   calendar.reschedule(db,ids[0],'2026-10-31T12:00:00-03:00',self.current)
   with self.assertRaisesRegex(ValueError,'intervalo'):calendar.reschedule(db,ids[1],'2026-10-31T12:30:00-03:00',self.current)
   calendar.reschedule(db,ids[1],'2026-10-31T14:00:00-03:00',self.current)
   with self.assertRaisesRegex(ValueError,'capacidade'):calendar.reschedule(db,ids[2],'2026-10-31T18:00:00-03:00',self.current)
 def test_lowering_limit_preserves_assigned_dates_and_approvals(self):
  with app.connect() as db:
   self.config(db);cid=self.content(db,status='approved');stamp=calendar.reserve(db,cid,self.current)
   self.config(db,1)
   row=db.execute('SELECT status,scheduled_at FROM content WHERE id=?',(cid,)).fetchone()
   self.assertEqual(tuple(row),('approved',stamp));self.assertEqual(calendar.reserve(db,cid,self.current),stamp)
 def test_schema_migration_preserves_old_reservation_exactly(self):
  with app.connect() as db:
   cid=self.content(db,status='approved')
   db.execute('DROP TABLE editorial_slots')
   db.execute('CREATE TABLE editorial_slots(channel TEXT NOT NULL,local_date TEXT NOT NULL,scheduled_at TEXT NOT NULL,test_arm TEXT NOT NULL,content_id INTEGER UNIQUE REFERENCES content(id),PRIMARY KEY(channel,local_date))')
   db.execute('INSERT INTO editorial_slots VALUES(?,?,?,?,?)',('Instagram','2026-10-29','2026-10-29T18:00:00+00:00','15:00',cid))
   calendar.create_schema(db);calendar.create_schema(db)
   row=db.execute('SELECT * FROM editorial_slots WHERE content_id=?',(cid,)).fetchone()
   self.assertEqual(row['scheduled_at'],'2026-10-29T18:00:00+00:00');self.assertEqual(row['slot_index'],0)
 def test_invalid_policy_is_rejected(self):
  with app.connect() as db:
   for daily in [0,7,True,1.5]:
    with self.assertRaises(ValueError):calendar.save_policy(db,{c:{'daily':daily,'gap_minutes':60} for c in ['Instagram','Blog']})
