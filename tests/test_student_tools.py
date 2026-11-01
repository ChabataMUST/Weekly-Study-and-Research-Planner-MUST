import io,tempfile,unittest,json
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from planner import create_app
from planner.db import connect

class StudentToolsTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=str(Path(self.tmp.name)/'test.db');self.app=create_app({'TESTING':True,'DATABASE':self.path,'SECRET_KEY':'test'});self.c=self.app.test_client();self.post('/register',username='student1',password='password123',confirm='password123')
 def tearDown(self):self.tmp.cleanup()
 def post(self,path,**data):
  self.c.get('/login')
  with self.c.session_transaction() as s:data['csrf']=s['csrf']
  return self.c.post(path,data=data)
 def quick(self,**kwargs):return self.post('/quick-note',body='老师说：考试增加第三章',token='a'*48,**kwargs)
 def png(self):
  b=io.BytesIO();Image.new('RGB',(600,400),'red').save(b,'PNG');b.seek(0);return b
 def test_quick_minimal_idempotent_and_search(self):
  self.assertEqual(self.quick().status_code,200);self.assertEqual(self.quick().status_code,200)
  with connect(self.path) as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM notes').fetchone()[0],1)
  self.assertIn('考试增加第三章',self.c.get('/search?q=第三章').get_data(as_text=True))
 def test_quick_owner_and_empty_input(self):
  self.assertEqual(self.post('/quick-note',body='',token='a'*48).status_code,400)
  self.assertEqual(self.quick(event_id='99').status_code,404)
 def test_quick_class_link_and_return_week(self):
  with connect(self.path) as c:
   c.execute("INSERT INTO courses(owner_id,code,title) VALUES(1,'SE','软件工程')")
   c.execute("INSERT INTO events(owner_id,course_id,source_key,date,start_time,end_time) VALUES(1,1,'class','2026-10-26','09:00','10:00')")
  self.assertEqual(self.quick(event_id='1').status_code,200)
  with connect(self.path) as c:self.assertEqual(c.execute('SELECT course_id,event_id FROM notes').fetchone()[:],(1,1))
  page=self.c.get('/classes/1?week=2026-10-26').get_data(as_text=True);self.assertIn('/?week=2026-10-26',page);self.assertIn('quick-form',page)
 def test_avatar_validation_size_and_isolation(self):
  self.assertEqual(self.post('/avatar',avatar_file=(io.BytesIO(b'not an image'),'fake.png')).status_code,400)
  self.assertEqual(self.post('/avatar',avatar_file=(self.png(),'real.png')).status_code,302)
  response=self.c.get('/avatar.png');self.assertEqual(response.status_code,200);self.assertEqual(Image.open(io.BytesIO(response.data)).size,(256,256))
  self.post('/logout');self.post('/register',username='student2',password='password123',confirm='password123');self.assertEqual(self.c.get('/avatar.png').status_code,404)
 def test_task_source_subtask_and_done(self):
  self.quick();self.assertEqual(self.post('/tasks',title='复习第三章',minutes='60',priority='High',due='2026-11-06',note='1').status_code,302)
  self.assertEqual(self.post('/tasks',title='第一节',minutes='30',priority='Normal',parent='1').status_code,302)
  self.post('/tasks/2/status',done='yes')
  with connect(self.path) as c:self.assertEqual(c.execute('SELECT done,parent_id FROM study_tasks WHERE id=2').fetchone()[:],(1,1))
 def test_overlap_requires_confirmation_and_move_preserves_id(self):
  v=dict(title='阅读',date='2026-10-31',start_time='09:00',end_time='10:00')
  self.assertEqual(self.post('/schedule',**v).status_code,302)
  self.assertEqual(self.post('/schedule',**v).status_code,400)
  self.assertEqual(self.post('/schedule',**v,allow_conflict='yes').status_code,302)
  v.update(start_time='10:00',end_time='11:00')
  self.assertEqual(self.post('/schedule/1',**v,version='0').status_code,302)
  self.assertEqual(self.post('/schedule/1',**v,version='0').status_code,400)
  with connect(self.path) as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM time_blocks').fetchone()[0],2)
 def test_class_conflict_and_boundary(self):
  with connect(self.path) as c:
   c.execute("INSERT INTO courses(owner_id,code,title) VALUES(1,'SE','课程')")
   c.execute("INSERT INTO events(owner_id,course_id,source_key,date,start_time,end_time) VALUES(1,1,'e','2026-10-31','09:00','10:00')")
  self.assertEqual(self.post('/schedule',title='重叠',date='2026-10-31',start_time='09:30',end_time='10:30').status_code,400)
  self.assertEqual(self.post('/schedule',title='相邻',date='2026-10-31',start_time='10:00',end_time='11:00').status_code,302)
 def test_new_resources_owner_scoped(self):
  self.quick();self.post('/tasks',title='任务',minutes='30',priority='Normal');self.post('/schedule',title='时间',date='2026-10-31',start_time='09:00',end_time='10:00')
  self.post('/logout');self.post('/register',username='student2',password='password123',confirm='password123')
  for path in ['/notes/1/organize','/tasks/1/status','/schedule/1']:
   self.assertEqual(self.post(path).status_code,404,path)
  self.assertEqual(self.post('/tasks',title='x',minutes='30',priority='Normal',note='1').status_code,404)
 def test_screenshot_review_requires_confirmation(self):
  rows=[dict(source_key='ocr-test',course_code='SE',course_title='软件工程',date='2026-10-26',start_time='09:00',end_time='11:50',room='',teacher='')]
  with patch('planner.screenshot_ocr.recognize',return_value=(rows,'截图原文')):
   r=self.post('/screenshot',monday='2026-10-26',image=(self.png(),'shot.png'))
  self.assertEqual(r.status_code,302)
  self.assertEqual(self.c.get(r.location).status_code,200)
  with connect(self.path) as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM events').fetchone()[0],0)
  p=self.post(r.location,**{'0_include':'yes','weeks':'2'});self.assertEqual(p.status_code,302)
  self.post(p.location+'/confirm')
  with connect(self.path) as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM events').fetchone()[0],2)
 def test_new_pages_render(self):
  self.quick()
  for p in ['/','/tasks','/schedule','/screenshot','/settings','/notes/1/organize']:
   self.assertEqual(self.c.get(p).status_code,200,p)

if __name__=='__main__':unittest.main()
