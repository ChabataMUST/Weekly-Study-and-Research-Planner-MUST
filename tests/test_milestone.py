import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from pypdf import PdfReader
from planner import create_app, weekly_records
from planner.db import connect
from planner.importer import ValidationError, parse_csv, prepare, confirm
from planner.reports import render_pdf

ROOT = Path(__file__).resolve().parents[1]
DEMO = (ROOT/'samples/timetable-demo.csv').read_bytes()


class MilestoneTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = str(Path(self.temp.name)/'test.sqlite3')
        self.app = create_app({'TESTING':True,'DATABASE':self.database,'SECRET_KEY':'test-only'})
        self.client = self.app.test_client()
        self.client.get('/')
        with self.client.session_transaction() as s:
            self.csrf = s['csrf']

    def tearDown(self):
        self.temp.cleanup()

    def post(self, path, data, **kwargs):
        return self.client.post(path, data={**data,'csrf':self.csrf}, **kwargs)

    def imported(self, raw=DEMO):
        with connect(self.database) as db:
            token, _ = prepare(db, raw)
            return confirm(db,token)

    def note(self, **override):
        values = {'date':'2026-09-30','kind':'Assignment requirement','context':'Demo course',
                  'title':'Lab report','body':'Include the method and result.','status':'In progress',
                  'event_key':''}
        return self.post('/notes',{**values,**override})

    def test_observed_source_matches_checked_event(self):
        rows = parse_csv((ROOT/'samples/timetable-observed.csv').read_bytes())
        self.assertEqual(len(rows),1)
        self.assertEqual([rows[0][k] for k in ('course_title','date','start_time','end_time')],
                         ['計算機網絡I','2026-09-30','09:00','11:50'])

    def test_utf8_bom_and_optional_columns(self):
        raw = '\ufeffsource_key,course_code,course_title,date,start_time,end_time\nk,C,课程,2026-10-01,09:00,10:00\n'.encode()
        row = parse_csv(raw)[0]
        self.assertEqual(row['course_title'],'课程')
        self.assertEqual(row['room'],'')

    def test_invalid_dates_times_and_duplicate_keys_rejected(self):
        row = DEMO.decode().splitlines()[1]
        head = DEMO.decode().splitlines()[0]
        for raw in [DEMO.replace(b'2026-09-28',b'2026-02-30'),
                    DEMO.replace(b'09:00',b'24:00'),
                    (ROOT/'samples/timetable-invalid.csv').read_bytes(),
                    (head+'\n'+row+'\n'+row).encode()]:
            with self.subTest(raw=raw[:60]), self.assertRaises(ValidationError):
                parse_csv(raw)

    def test_empty_unknown_and_oversized_csv_rejected(self):
        for raw in [b'',b'x,y\n1,2',b'a'*1048577,DEMO.replace(b'teacher',b'unknown')]:
            with self.subTest(raw=raw[:30]),self.assertRaises(ValidationError):
                parse_csv(raw)

    def test_preview_does_not_save_classes_and_cancel_is_safe(self):
        with connect(self.database) as db:
            token,changes = prepare(db,DEMO)
            self.assertEqual(len(changes),5)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM events').fetchone()[0],0)
        self.assertEqual(self.post(f'/import/{token}/cancel',{}).status_code,302)
        with connect(self.database) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM events').fetchone()[0],0)
            with self.assertRaises(ValidationError):
                confirm(db,token)

    def test_reimport_is_idempotent(self):
        self.assertEqual(self.imported(),{'Added':5,'Updated':0,'Unchanged':0})
        self.assertEqual(self.imported(),{'Added':0,'Updated':0,'Unchanged':5})
        with connect(self.database) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM events').fetchone()[0],5)

    def test_update_preserves_note_link_and_identity(self):
        self.imported()
        self.note(event_key='demo-se-001')
        counts=self.imported((ROOT/'samples/timetable-update.csv').read_bytes())
        self.assertEqual(counts['Updated'],1)
        with connect(self.database) as db:
            self.assertEqual(db.execute("SELECT room FROM events WHERE source_key='demo-se-001'").fetchone()[0],'Demo room A2')
            self.assertEqual(db.execute('SELECT id,event_key FROM notes').fetchone()[:],(1,'demo-se-001'))

    def test_stale_preview_cannot_overwrite_newer_timetable(self):
        with connect(self.database) as db:
            token,_=prepare(db,DEMO)
        self.imported()
        with connect(self.database) as db,self.assertRaises(ValidationError):
            confirm(db,token)

    def test_failed_batch_rolls_back_all_rows(self):
        with connect(self.database) as db:
            token,_=prepare(db,DEMO)
            db.execute("CREATE TRIGGER reject_second BEFORE INSERT ON events WHEN NEW.source_key='demo-math-001' BEGIN SELECT RAISE(ABORT,'test failure'); END")
            db.commit()
            with self.assertRaises(sqlite3.IntegrityError):
                confirm(db,token)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM events').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM import_batches').fetchone()[0],0)

    def test_invalid_batch_keeps_existing_timetable(self):
        self.imported()
        with connect(self.database) as db:
            with self.assertRaises(ValidationError):
                prepare(db,DEMO.replace(b'17:00',b'10:00'))
            self.assertEqual(db.execute('SELECT COUNT(*) FROM events').fetchone()[0],5)

    def test_missing_rows_are_not_deleted(self):
        self.imported()
        self.imported(('\n'.join(DEMO.decode().splitlines()[:2])).encode())
        with connect(self.database) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM events').fetchone()[0],5)

    def test_week_boundaries_and_research_without_courses(self):
        self.note(date='2026-10-04',kind='Research meeting',title='Sunday meeting')
        self.note(date='2026-10-05',title='Next week')
        with connect(self.database) as db:
            start,end,events,notes=weekly_records(db,'2026-09-30')
        self.assertEqual((str(start),str(end)),('2026-09-28','2026-10-04'))
        self.assertEqual(events,[])
        self.assertEqual([n['title'] for n in notes],['Sunday meeting'])

    def test_saved_data_survives_app_recreation(self):
        self.imported()
        self.note()
        again=create_app({'TESTING':True,'DATABASE':self.database,'SECRET_KEY':'test-only'})
        page=again.test_client().get('/').get_data(as_text=True)
        self.assertIn('Computer Networks',page)
        self.assertIn('Lab report',page)

    def test_form_forgery_rejected(self):
        response=self.client.post('/notes',data={'title':'Forged'})
        self.assertEqual(response.status_code,400)
        with connect(self.database) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM notes').fetchone()[0],0)

    def test_note_text_is_escaped_in_html_and_invalid_link_rejected(self):
        self.note(body='<script>alert(1)</script>')
        page=self.client.get('/').get_data(as_text=True)
        self.assertIn('&lt;script&gt;',page)
        self.assertNotIn('<script>alert',page)
        self.assertEqual(self.note(event_key='missing').status_code,400)

    def test_http_upload_confirm_and_one_time_preview(self):
        response=self.post('/import',{'timetable':(io.BytesIO(DEMO),'demo.csv')},content_type='multipart/form-data')
        self.assertEqual(response.status_code,302)
        location=response.headers['Location']
        self.assertIn('Check the changes',self.client.get(location).get_data(as_text=True))
        self.assertEqual(self.post(location+'/confirm',{}).status_code,302)
        self.assertEqual(self.post(location+'/confirm',{}).status_code,400)

    def test_pdf_selection_and_frozen_versions(self):
        self.note(title='Included',body='课程要求：附上实验结果。')
        self.note(title='EXCLUDED_SECRET',body='EXCLUDED_SECRET')
        response=self.post('/reports',{'week':'2026-09-28','title':'Mixed weekly report','summary':'Next: revise methods.','note_ids':['1']})
        self.assertEqual(response.status_code,302)
        first=self.client.get(response.headers['Location']).data
        reader=PdfReader(io.BytesIO(first))
        text='\n'.join(p.extract_text() for p in reader.pages)
        self.assertIn('Included',text)
        self.assertIn('课程要求',text)
        self.assertNotIn('EXCLUDED_SECRET',text+str(reader.metadata))
        with connect(self.database) as db:
            saved=db.execute('SELECT snapshot_json FROM reports').fetchone()[0]
            self.assertNotIn('EXCLUDED_SECRET',saved)
            db.execute("UPDATE notes SET body='New wording' WHERE id=1")
        self.assertEqual(self.client.get(response.headers['Location']).data,first)
        self.post('/reports',{'week':'2026-09-28','title':'Second version','note_ids':['1']})
        with connect(self.database) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM reports').fetchone()[0],2)

    def test_report_cannot_include_record_from_another_week(self):
        self.note(date='2026-10-05')
        response=self.post('/reports',{'week':'2026-09-28','title':'Test','note_ids':['1']})
        self.assertEqual(response.status_code,400)

    def test_empty_week_pdf(self):
        response=self.post('/reports',{'week':'2026-09-28','title':'Empty week'})
        pdf=self.client.get(response.headers['Location']).data
        self.assertIn('No learning records',PdfReader(io.BytesIO(pdf)).pages[0].extract_text())

    def test_long_pdf_preserves_last_record(self):
        note={'date':'2026-09-30','kind':'Research meeting','context':'Demo','status':'In progress',
              'title':'Long note','body':('Detailed experiment observations. '*40+'\n')*12}
        final={**note,'title':'FINAL_RECORD','body':'END_OF_REPORT'}
        pdf=render_pdf({'week':'2026-09-28','end':'2026-10-04','title':'Long report','summary':'','events':[], 'notes':[note,final]})
        reader=PdfReader(io.BytesIO(pdf))
        self.assertGreater(len(reader.pages),2)
        self.assertIn('END_OF_REPORT',reader.pages[-1].extract_text())


if __name__ == '__main__':
    unittest.main()
