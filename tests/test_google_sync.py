import json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import app,leads,google_sync,marketing_learning

class SheetAPI:
 def __init__(self):self.values=[google_sync.HEADERS.copy()];self.writes=[]
 def request(self,method,url,payload=None):
  if method=='GET':return {'values':self.values}
  self.assert_raw='valueInputOption=RAW' in url
  self.writes.append(payload['values'][0]);self.values.append(payload['values'][0]);return {'updatedCells':18}

class GoogleLedger(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.old=app.DB_PATH;app.DB_PATH=Path(self.temp.name)/'cml.db'
  self.env=patch.dict(os.environ,{'CML_APP_SECRET':'private-test-master-more-than-32-characters','CML_ADMIN_PASSWORD':'test-password-more-than-sixteen'});self.env.start();app.init_db()
  self.config=patch.object(google_sync,'CONFIG',{'ga4_property_id':'123456789','search_console_site':'sc-domain:example.org','lead_sheet_id':'example-spreadsheet-id'});self.config.start()
  self.payload={'external_id':'execution:12345','lead_ref':'test-lead-123456','name':'=PRIVATE_NAME','phone':'11999990000','email':'private@example.invalid','analytics_consent':'accepted','attribution_first':{'source':'instagram','landing_path':'/blog/artigo-14/'},'assisted_content':'artigo-14'}
 def tearDown(self):self.config.stop();self.env.stop();app.DB_PATH=self.old;self.temp.cleanup()
 def test_sync_raw_write_idempotency_and_human_payment(self):
  with app.connect() as db:leads.ingest(db,self.payload)
  api=SheetAPI();self.assertEqual(google_sync.sync_sheet(api)['created'],1)
  self.assertTrue(api.assert_raw);self.assertEqual(api.writes[0][1],'=PRIVATE_NAME')
  self.assertEqual(google_sync.sync_sheet(api)['created'],0);self.assertEqual(len(api.writes),1)
  api.values[1][5]='Convertido';api.values[1][7]='23/10/2026';api.values[1][8]='R$ 1.500,00';api.values[1][10]='PRIVATE_NOTE'
  self.assertEqual(google_sync.sync_sheet(api)['updated'],1)
  self.assertEqual(google_sync.sync_sheet(api)['updated'],0)
  with app.connect() as db:
   self.assertEqual(db.execute("SELECT count(*),sum(value) FROM events WHERE event_type='enrollment'").fetchone()[:],(1,1500))
   output=json.dumps(marketing_learning.summary(db))
   for private in ['PRIVATE_NAME','11999990000','private@example.invalid','PRIVATE_NOTE','test-lead-123456']:self.assertNotIn(private,output)
   self.assertIn('paid_enrollments',output)
  api.values[1][5]='Perdido';api.values[1][7]='';api.values[1][8]='';api.values[1][9]='Sem interesse'
  google_sync.sync_sheet(api)
  with app.connect() as db:self.assertEqual(db.execute("SELECT count(*) FROM events WHERE event_type='enrollment'").fetchone()[0],0)
 def test_reject_header_change_and_do_not_resurrect_deleted_row(self):
  with app.connect() as db:leads.ingest(db,self.payload)
  api=SheetAPI();google_sync.sync_sheet(api);api.values=[google_sync.HEADERS.copy()]
  self.assertEqual(google_sync.sync_sheet(api)['errors'],1);self.assertEqual(len(api.writes),1)
  api.values[0][0]='Changed'
  with self.assertRaises(RuntimeError):google_sync.sync_sheet(api)
 def test_invalid_payment_preserves_status(self):
  with app.connect() as db:leads.ingest(db,self.payload)
  api=SheetAPI();google_sync.sync_sheet(api);api.values[1][5]='Convertido'
  self.assertEqual(google_sync.sync_sheet(api)['errors'],1)
  with app.connect() as db:self.assertEqual(db.execute('SELECT status FROM leads').fetchone()[0],'Novo')
 def test_credential_rejects_non_google_token_endpoint(self):
  with self.assertRaises(ValueError):google_sync.validate_info({'type':'service_account','token_uri':'https://example.invalid/token','client_email':'app@test.iam.gserviceaccount.com'})
 def test_metrics_keep_true_totals_and_do_not_give_queries_to_agents(self):
  class API:
   def request(self,method,url,payload=None):
    if 'searchAnalytics' in url:return {'rows':[{'keys':['https://example.com/blog/artigo-14/?email=private@example.invalid','PRIVATE_SEARCH_QUERY'],'clicks':2,'impressions':20}]}
    if payload['dimensions']==[{'name':'eventName'}]:return {'rows':[{'dimensionValues':[{'value':'page_view'}],'metricValues':[{'value':'4'},{'value':'1'}]}]}
    return {'metricHeaders':[{'name':'sessions'},{'name':'screenPageViews'}],
      'totals':[{'metricValues':[{'value':'1'},{'value':'4'}]}],
      'rows':[{'dimensionValues':[{'value':'20261023'},{'value':'/blog/artigo-14/'},{'value':'instagram / social'}],
        'metricValues':[{'value':'1'},{'value':'4'}]}],'rowCount':1}
  google_sync.collect_metrics(API())
  with app.connect() as db:
   result=google_sync.overview(db);self.assertEqual(result['ga4']['totals']['sessions'],1)
   self.assertEqual(result['ga4']['events'][0]['count'],4)
   output=json.dumps(marketing_learning.summary(db))
   self.assertIn('site_metrics',output)
   for private in ['PRIVATE_SEARCH_QUERY','private@example.invalid','?email=']:self.assertNotIn(private,output)
 def test_credential_verification_writes_only_instruction_cell(self):
  calls=[];instruction=[]
  class API:
   def request(self,method,url,payload=None):
    calls.append((method,url))
    if method=='PUT':instruction.extend(payload['values']);return {}
    if '/values/' in url:return {'values':instruction}
    return {}
  with patch.object(google_sync,'Client',return_value=API()):self.assertTrue(google_sync.verify({})['sheet_write'])
  writes=[url for method,url in calls if method=='PUT'];self.assertEqual(len(writes),1)
  self.assertIn(google_sync.CONFIG['lead_sheet_id'],writes[0]);self.assertIn('B12',writes[0]);self.assertNotIn('Leads!',writes[0])

if __name__=='__main__':unittest.main()
