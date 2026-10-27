import os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import app,leads

class LeadLedger(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.old=app.DB_PATH;app.DB_PATH=Path(self.temp.name)/'cml.db'
  self.env=patch.dict(os.environ,{'CML_APP_SECRET':'private-test-master-more-than-32-characters','CML_ADMIN_PASSWORD':'test-password-more-than-sixteen'});self.env.start();app.init_db()
  self.payload={'external_id':'execution:12345','lead_ref':'test-lead-123456','name':'Contato de teste','phone':'11999990000','email':'test@example.invalid','analytics_consent':'accepted','attribution_first':{'source':'instagram','utm_campaign':'conteudo-diario','landing_path':'/blog/artigo-14/'},'attribution_last':{'source':'instagram','utm_campaign':'conteudo-diario'},'assisted_content':'artigo-14'}
 def tearDown(self):self.env.stop();app.DB_PATH=self.old;self.temp.cleanup()
 def test_contact_encryption_retries_and_payment_correction(self):
  with app.connect() as db:
   self.assertFalse(leads.ingest(db,self.payload)['duplicate']);self.assertTrue(leads.ingest(db,self.payload)['duplicate'])
   self.assertTrue(leads.ingest(db,{**self.payload,'external_id':'execution:67890'})['duplicate'])
   self.assertEqual(db.execute('SELECT count(*) FROM events').fetchone()[0],1)
   self.assertNotIn('Contato',db.execute('SELECT contact_encrypted FROM leads').fetchone()[0])
   with self.assertRaises(ValueError):leads.ingest(db,{**self.payload,'name':'Changed'})
   with self.assertRaises(ValueError):leads.update_status(db,{'lead_ref':self.payload['lead_ref'],'status':'Convertido'})
   paid={'lead_ref':self.payload['lead_ref'],'status':'Convertido','paid_at':'2026-10-23','paid_value':1500}
   self.assertFalse(leads.update_status(db,paid)['duplicate']);self.assertTrue(leads.update_status(db,paid)['duplicate'])
   leads.update_status(db,{**paid,'paid_value':1600})
   self.assertEqual(db.execute("SELECT count(*),sum(value) FROM events WHERE event_type='enrollment'").fetchone()[:],(1,1600))
   self.assertEqual(leads.overview(db)['leads'][0]['name'],'Contato de teste')
   audit=' '.join(r[0] for r in db.execute('SELECT detail FROM audit'))
   self.assertNotIn('test@example.invalid',audit);self.assertNotIn('11999990000',audit)
   leads.update_status(db,{'lead_ref':self.payload['lead_ref'],'status':'Perdido','loss_reason':'Desistiu do processo'})
   self.assertEqual(db.execute("SELECT count(*) FROM events WHERE event_type='enrollment'").fetchone()[0],0)
 def test_no_consent_does_not_accept_attribution(self):
  with app.connect() as db:
   leads.ingest(db,{**self.payload,'analytics_consent':'rejected'})
   row=leads.overview(db)['leads'][0]
   self.assertEqual(row['first_source'],'Sem consentimento de medição');self.assertEqual(row['campaign'],'');self.assertEqual(row['content_ref'],'')
 def test_dry_run_rollback_and_transaction(self):
  with app.connect() as db:
   leads.ingest(db,self.payload);db.rollback()
   self.assertEqual(db.execute('SELECT count(*) FROM leads').fetchone()[0],0)
   self.assertEqual(db.execute('SELECT count(*) FROM events').fetchone()[0],0)

if __name__=='__main__':unittest.main()
