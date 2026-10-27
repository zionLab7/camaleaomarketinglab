import base64,copy,io,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import app,brand,library,blog_builder,creative_store,editorial_calendar,google_sync

class WhiteLabel(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
  self.patches=[patch.object(brand,'DATA',self.root),patch.object(brand,'PATH',self.root/'brand.json'),patch.object(library,'LIBRARY',self.root/'library'),patch.object(creative_store,'LIBRARY',self.root/'library'),patch.object(app,'DB_PATH',self.root/'db.sqlite'),patch.dict(os.environ,{'CML_ADMIN_PASSWORD':'only-a-private-test-password','CML_APP_SECRET':'only-a-private-test-master-secret-more-than-32'})]
  for p in self.patches:p.start()
  app.init_db()
 def tearDown(self):
  for p in reversed(self.patches):p.stop()
  self.temp.cleanup()
 def test_fresh_installation_has_no_customer_content_or_connections(self):
  with app.connect() as db:
   self.assertEqual(db.execute('SELECT count(*) FROM content').fetchone()[0],0)
   self.assertEqual(db.execute('SELECT count(*) FROM leads').fetchone()[0],0)
   self.assertEqual(db.execute('SELECT count(*) FROM settings').fetchone()[0],0)
  self.assertFalse(brand.get()['tracking_enabled'])
  self.assertEqual(len(creative_store.catalog()['assets']),3)
 def test_two_sectors_brand_context_calendar_and_static_export(self):
  for name,industry,timezone,color in [('Ateliê Horizonte','Design','Europe/Lisbon','#173645'),('Café Aurora','Cafeteria','America/Manaus','#4A281E')]:
   config={**copy.deepcopy(brand.DEFAULT),'name':name,'industry':industry,'website':'https://example.org','cta_url':'https://example.org/#contato','timezone':timezone,'primary':color,'instagram_times':['09:10'],'agents':{**brand.DEFAULT['agents'],'copywriter':'Frases curtas e acolhedoras'}}
   brand.save(config)
   self.assertEqual(brand.context()['name'],name);self.assertIn('Frases curtas',brand.direction())
   self.assertEqual(str(editorial_calendar.settings()[0]),timezone)
   self.assertEqual(editorial_calendar.settings()[1]['Instagram'],[(9,10)])
   output=self.root/name;blog_builder.build(output)
   text=(output/'index.html').read_text();self.assertIn(name,text);self.assertIn(color,text);self.assertNotIn('autoescola',text.lower());self.assertNotIn('cml-tracking',text)
 def test_brand_validation_blocks_injection_private_targets_and_invalid_ids(self):
  for change in [{'primary':'red;display:none'},{'timezone':'Invalid/Nowhere'},{'website':'http://example.org'},{'sources':['https://127.0.0.1/private']},{'ga4_property_id':'../private'},{'agents':{'shell':'run'}},{'instagram_times':['25:00']}]:
   with self.assertRaises(ValueError):brand.save({**copy.deepcopy(brand.DEFAULT),**change})
 def test_uploaded_logo_is_reencoded_catalogued_and_exported_only_when_selected(self):
  from PIL import Image
  image=io.BytesIO();Image.new('RGB',(100,100),'white').save(image,format='PNG')
  data={'data':base64.b64encode(image.getvalue()).decode(),'title':'Logo próprio','rights_confirmed':True}
  result=library.upload(data);self.assertEqual(len(creative_store.catalog()['assets']),4)
  with self.assertRaises(ValueError):library.upload({**data,'rights_confirmed':False})
  brand.save({**brand.DEFAULT,'logo_asset':result['id']})
  output=self.root/'export';blog_builder.build(output)
  self.assertTrue((output/'brand-logo.png').exists());self.assertIn('/blog/brand-logo.png',(output/'index.html').read_text())
 def test_tracking_uses_only_configured_ids_and_consent(self):
  from tracking_install import snippet
  self.assertEqual(snippet(),'')
  brand.save({**brand.DEFAULT,'tracking_enabled':True,'gtm_public_id':'GTM-EXAMPLE','ga4_measurement_id':'G-EXAMPLE'})
  self.assertIn('GTM-EXAMPLE',snippet());self.assertIn('G-EXAMPLE',snippet())
 def test_dns_private_target_is_blocked_before_connection(self):
  import network,socket
  with patch.object(network.socket,'getaddrinfo',return_value=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('127.0.0.1',443))]):
   with self.assertRaisesRegex(ValueError,'não público'):network.read_public('https://example.org/reference')
 def test_google_can_be_configured_without_a_spreadsheet(self):
  brand.save({**brand.DEFAULT,'ga4_property_id':'123456789'})
  with patch.object(google_sync,'Client') as client:
   result=google_sync.verify({});self.assertEqual(result,{'ga4':True})
   self.assertEqual(client.return_value.request.call_count,1)
 def test_iso_publication_date_is_normalized_in_brand_timezone(self):
  brand.save({**brand.DEFAULT,'timezone':'America/Manaus'})
  a={'slug':'artigo','title':'Guia','description':'Descrição','body':'Texto útil. '*50,'published':'2026-10-24T01:00:00+00:00','sources':[{'url':'https://example.org','label':'Fonte'}]}
  self.assertEqual(blog_builder.validate(a)['published'],'2026-10-23')
