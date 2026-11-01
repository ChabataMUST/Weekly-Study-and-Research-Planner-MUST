import unittest,tempfile,re,json
from pathlib import Path
from planner import create_app
from planner.db import connect

class Week4Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=str(Path(self.tmp.name)/'test.db');self.app=create_app({'TESTING':True,'DATABASE':self.path,'SECRET_KEY':'test'});self.c=self.app.test_client()
  self.post('/register',username='student1',password='password123',confirm='password123')
 def tearDown(self):self.tmp.cleanup()
 def post(self,path,**data):
  self.c.get('/login')
  with self.c.session_transaction() as s:data['csrf']=s['csrf']
  return self.c.post(path,data=data)
 def manual(self,**override):
  v=dict(course_code='SE',course_title='软件工程',date='2026-10-26',weeks='3',weekdays=['0','2'],start_time='09:00',end_time='11:50',room='C308',teacher='Teacher',series='fixedseries');v.update(override)
  return self.post('/courses/new',**v)
 def imported(self):
  r=self.manual();self.assertEqual(r.status_code,302);self.post(r.location+'/confirm')
 def record(self):
  self.imported()
  self.post('/notes',date='2026-10-26',kind='Assignment requirement',new_course='软件工程',title='Report',body='original 范围',status='In progress',event_id='1')
 def test_manual_repeat_and_missing_day(self):
  self.imported()
  with connect(self.path) as d:self.assertEqual(d.execute('SELECT COUNT(*) FROM events').fetchone()[0],6)
  r=self.manual();self.post(r.location+'/confirm')
  with connect(self.path) as d:self.assertEqual(d.execute('SELECT COUNT(*) FROM events').fetchone()[0],6)
  self.assertEqual(self.manual(weekdays=[]).status_code,400)
 def test_date_override_invalid_time(self):
  r=self.manual(until='2026-10-26');self.post(r.location+'/confirm')
  with connect(self.path) as d:self.assertEqual(d.execute('SELECT COUNT(*) FROM events').fetchone()[0],1)
  self.assertEqual(self.manual(end_time='08:00').status_code,400)
 def test_revision_and_historical_search(self):
  self.record();r=self.post('/notes/1',revision='0',title='New report',body='revised 范围',date='2026-11-02',status='Completed',reason='Teacher changed chapters')
  self.assertEqual(r.status_code,302)
  with connect(self.path) as d:self.assertEqual(d.execute('SELECT COUNT(*) FROM note_revisions').fetchone()[0],2)
  page=self.c.get('/search?q=original').get_data(as_text=True);self.assertIn('New report',page)
  self.assertIn('original 范围',self.c.get('/notes/1').get_data(as_text=True))
 def test_stale_edit_keeps_input_and_does_not_overwrite(self):
  self.record();v=dict(revision='0',title='New report',body='new body',date='2026-10-26',status='Completed',reason='update')
  self.post('/notes/1',**v);v['body']='my unsaved draft';r=self.post('/notes/1',**v)
  self.assertEqual(r.status_code,400);self.assertIn('my unsaved draft',r.get_data(as_text=True))
  with connect(self.path) as d:self.assertEqual(d.execute('SELECT body FROM notes').fetchone()[0],'new body')
 def test_class_edit_preserves_identity_notes_and_stales_preview(self):
  self.record();preview=self.manual()
  with connect(self.path) as d:rev=d.execute('SELECT timetable_revision FROM user_state').fetchone()[0]
  r=self.post('/classes/1',revision=str(rev),course_title='软件工程 II',date='2026-10-27',start_time='10:00',end_time='12:00',room='C509',teacher='New teacher',state='cancelled')
  self.assertEqual(r.status_code,302)
  with connect(self.path) as d:
   self.assertEqual(d.execute('SELECT event_id FROM notes').fetchone()[0],1)
   self.assertEqual(d.execute('SELECT state FROM events WHERE id=1').fetchone()[0],'cancelled')
  self.assertEqual(self.post(preview.location+'/confirm').status_code,400)
  self.assertIn('C308',self.c.get('/classes/1').get_data(as_text=True))
 def test_cross_account_new_routes_isolated(self):
  self.record();self.post('/logout');self.post('/register',username='student2',password='password123',confirm='password123')
  for path in ['/notes/1','/classes/1']:
   self.assertEqual(self.c.get(path).status_code,404);self.assertEqual(self.post(path).status_code,404)
  self.assertNotIn('original 范围',self.c.get('/search?q=original').get_data(as_text=True))
 def test_password_change_requires_current_password(self):
  self.assertEqual(self.post('/settings',action='password',current_password='wrong',password='newpassword1',confirm='newpassword1').status_code,400)
  self.assertEqual(self.post('/settings',action='password',current_password='password123',password='newpassword1',confirm='newpassword1').status_code,302)
  self.post('/logout');self.assertEqual(self.post('/login',username='student1',password='password123').status_code,400)
  self.assertEqual(self.post('/login',username='student1',password='newpassword1').status_code,302)
 def test_languages_and_avatar_persist(self):
  for lang,word in [('zh-CN','我的一周'),('zh-TW','我的一週'),('en','My week')]:
   self.assertEqual(self.post('/settings',language=lang,avatar='🐱').status_code,302)
   page=self.c.get('/').get_data(as_text=True);self.assertIn(word,page);self.assertIn('🐱',page)
  self.assertEqual(self.post('/settings',language='invalid',avatar='🐱').status_code,400)
 def test_export_snapshot_survives_revision(self):
  self.record();r=self.post('/reports',week='2026-10-26',title='Weekly report',summary='test',note_ids=['1'],include_events='yes')
  before=self.c.get(r.location).data
  self.post('/notes/1',revision='0',title='Changed',body='new text',date='2026-10-26',status='Completed',reason='teacher')
  self.assertEqual(self.c.get(r.location).data,before)
 def test_course_filter_and_literal_search(self):
  self.record();self.assertNotIn('original 范围',self.c.get('/search?course=999').get_data(as_text=True))
  self.assertNotIn('original 范围',self.c.get('/search?q=%25').get_data(as_text=True))
 def test_new_forms_require_csrf(self):
  for p in ['/settings','/courses/new','/notes/1','/classes/1']:
   self.assertEqual(self.c.post(p,data={}).status_code,400)
 def test_pages_render(self):
  self.record()
  for p in ['/settings','/help','/courses/new','/search','/notes/1','/classes/1','/?week=2026-10-26']:
   self.assertEqual(self.c.get(p).status_code,200,p)

if __name__=='__main__':unittest.main()
