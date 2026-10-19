import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from pypdf import PdfReader
from planner import create_app, weekly_records
from planner.auth import AuthError, authenticate, register
from planner.db import SCHEMA_VERSION, connect, detect_version, initialize
from planner.importer import ValidationError, parse_csv, prepare, confirm
from planner.reports import render_pdf

ROOT = Path(__file__).resolve().parents[1]
DEMO = (ROOT/'samples/timetable-demo.csv').read_bytes()
PASSWORD = 'test-password-1'


class MilestoneTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = str(Path(self.temp.name)/'test.sqlite3')
        self.app = create_app({'TESTING':True,'DATABASE':self.database,'SECRET_KEY':'test-only'})
        self.client = self.app.test_client()
        self.register('tester', PASSWORD)
        with connect(self.database) as db:
            self.owner = db.execute("SELECT id FROM users WHERE username='tester'").fetchone()['id']

    def tearDown(self):
        self.temp.cleanup()

    def csrf(self):
        # A GET seeds the token; /login is public so this works signed in or out.
        self.client.get('/login')
        with self.client.session_transaction() as s:
            return s['csrf']

    def register(self, username, password):
        return self.client.post('/register', data={'csrf':self.csrf(),'username':username,
                                                   'password':password,'confirm':password})

    def login(self, username, password):
        return self.client.post('/login', data={'csrf':self.csrf(),'username':username,'password':password})

    def post(self, path, data, **kwargs):
        return self.client.post(path, data={**data,'csrf':self.csrf()}, **kwargs)

    def imported(self, raw=DEMO, owner=None):
        owner = self.owner if owner is None else owner
        with connect(self.database) as db:
            token, _ = prepare(db, owner, raw)
            return confirm(db, owner, token)

    def note(self, **override):
        values = {'date':'2026-09-30','kind':'Assignment requirement',
                  'course_id':'','project_id':'','new_course':'Demo course','new_project':'',
                  'title':'Lab report','body':'Include the method and result.','status':'In progress',
                  'event_id':''}
        return self.post('/notes', {**values, **override})

    def week_page(self, week='2026-09-28'):
        return self.client.get(f'/?week={week}').get_data(as_text=True)

    def event_id(self, source_key, owner=None):
        owner = self.owner if owner is None else owner
        with connect(self.database) as db:
            return db.execute('SELECT id FROM events WHERE source_key=? AND owner_id=?',
                              (source_key, owner)).fetchone()['id']

    # ---- CSV parsing (unchanged contract) ----

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

    def test_one_course_code_with_two_titles_rejected(self):
        raw = DEMO.replace(b'demo-se-002,DEMO-SE,Software Engineering',
                           b'demo-se-002,DEMO-SE,Contradictory Title')
        with self.assertRaises(ValidationError):
            parse_csv(raw)

    # ---- import transactions ----

    def test_preview_does_not_save_classes_and_cancel_is_safe(self):
        with connect(self.database) as db:
            token,changes = prepare(db,self.owner,DEMO)
            self.assertEqual(len(changes),5)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM events').fetchone()[0],0)
        self.assertEqual(self.post(f'/import/{token}/cancel',{}).status_code,302)
        with connect(self.database) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM events').fetchone()[0],0)
            with self.assertRaises(ValidationError):
                confirm(db,self.owner,token)

    def test_reimport_is_idempotent(self):
        self.assertEqual(self.imported(),{'Added':5,'Updated':0,'Unchanged':0})
        self.assertEqual(self.imported(),{'Added':0,'Updated':0,'Unchanged':5})
        with connect(self.database) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM events WHERE owner_id=?',(self.owner,)).fetchone()[0],5)

    def test_update_preserves_note_link_and_identity(self):
        self.imported()
        eid = self.event_id('demo-se-001')
        with connect(self.database) as db:
            cid = db.execute("SELECT id FROM courses WHERE code='DEMO-SE' AND owner_id=?",(self.owner,)).fetchone()['id']
        self.note(course_id=cid, new_course='', event_id=eid)
        counts=self.imported((ROOT/'samples/timetable-update.csv').read_bytes())
        self.assertEqual(counts['Updated'],1)
        with connect(self.database) as db:
            self.assertEqual(db.execute("SELECT room FROM events WHERE source_key='demo-se-001' AND owner_id=?",(self.owner,)).fetchone()[0],'Demo room A2')
            # Same surrogate id, same link: the update did not create a new row.
            self.assertEqual(db.execute('SELECT id,event_id FROM notes').fetchone()[:],(1,eid))

    def test_stale_preview_cannot_overwrite_newer_timetable(self):
        with connect(self.database) as db:
            token,_=prepare(db,self.owner,DEMO)
        self.imported()
        with connect(self.database) as db,self.assertRaises(ValidationError):
            confirm(db,self.owner,token)

    def test_failed_batch_rolls_back_all_rows(self):
        with connect(self.database) as db:
            token,_=prepare(db,self.owner,DEMO)
            db.execute("CREATE TRIGGER reject_second BEFORE INSERT ON events WHEN NEW.source_key='demo-math-001' BEGIN SELECT RAISE(ABORT,'test failure'); END")
            db.commit()
            with self.assertRaises(sqlite3.IntegrityError):
                confirm(db,self.owner,token)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM events').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM import_batches').fetchone()[0],0)

    def test_invalid_batch_keeps_existing_timetable(self):
        self.imported()
        with connect(self.database) as db:
            with self.assertRaises(ValidationError):
                prepare(db,self.owner,DEMO.replace(b'17:00',b'10:00'))
            self.assertEqual(db.execute('SELECT COUNT(*) FROM events WHERE owner_id=?',(self.owner,)).fetchone()[0],5)

    def test_missing_rows_are_not_deleted(self):
        self.imported()
        self.imported(('\n'.join(DEMO.decode().splitlines()[:2])).encode())
        with connect(self.database) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM events WHERE owner_id=?',(self.owner,)).fetchone()[0],5)

    def test_cancelled_class_state_survives_reimport(self):
        self.imported()
        eid = self.event_id('demo-net-001')
        with connect(self.database) as db:
            db.execute("UPDATE events SET state='cancelled' WHERE id=? AND owner_id=?",(eid,self.owner))
            db.commit()
        self.imported()  # same file again
        with connect(self.database) as db:
            self.assertEqual(db.execute('SELECT state FROM events WHERE id=?',(eid,)).fetchone()[0],'cancelled')

    def test_event_change_history_records_previous_values(self):
        self.imported()
        self.imported((ROOT/'samples/timetable-update.csv').read_bytes())
        with connect(self.database) as db:
            row = db.execute(
                """SELECT change_state,previous_json,current_json FROM event_changes
                   WHERE owner_id=? AND change_state='Updated' ORDER BY id DESC LIMIT 1""",(self.owner,)).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(json.loads(row['previous_json'])['room'],'Demo room A')
            self.assertEqual(json.loads(row['current_json'])['room'],'Demo room A2')

    # ---- weekly workspace ----

    def test_week_boundaries_and_research_without_courses(self):
        self.note(date='2026-10-04',kind='Research meeting',title='Sunday meeting',
                  new_course='',new_project='Demo research project')
        self.note(date='2026-10-05',title='Next week')
        with connect(self.database) as db:
            start,end,events,notes=weekly_records(db,self.owner,'2026-09-30')
        self.assertEqual((str(start),str(end)),('2026-09-28','2026-10-04'))
        self.assertEqual(events,[])
        self.assertEqual([n['title'] for n in notes],['Sunday meeting'])

    def test_saved_data_survives_app_recreation(self):
        self.imported()
        self.note()
        again=create_app({'TESTING':True,'DATABASE':self.database,'SECRET_KEY':'test-only'})
        client2=again.test_client()
        client2.get('/login')
        with client2.session_transaction() as s:
            token=s['csrf']
        client2.post('/login',data={'csrf':token,'username':'tester','password':PASSWORD})
        page=client2.get('/?week=2026-09-28').get_data(as_text=True)
        self.assertIn('Computer Networks',page)
        self.assertIn('Lab report',page)

    def test_note_text_is_escaped_in_html_and_invalid_link_rejected(self):
        self.note(body='<script>alert(1)</script>')
        page=self.week_page()
        self.assertIn('&lt;script&gt;',page)
        self.assertNotIn('<script>alert',page)
        self.assertEqual(self.note(event_id='missing').status_code,400)

    def test_form_forgery_rejected(self):
        response=self.client.post('/notes',data={'title':'Forged'})
        self.assertEqual(response.status_code,400)
        with connect(self.database) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM notes').fetchone()[0],0)

    # ---- import over HTTP ----

    def test_http_upload_confirm_and_one_time_preview(self):
        response=self.post('/import',{'timetable':(io.BytesIO(DEMO),'demo.csv')},content_type='multipart/form-data')
        self.assertEqual(response.status_code,302)
        location=response.headers['Location']
        self.assertIn('Check the changes',self.client.get(location).get_data(as_text=True))
        self.assertEqual(self.post(location+'/confirm',{}).status_code,302)
        # The token is single-use; a replay reads as "not found", not as an error
        # that would confirm the token once existed.
        self.assertEqual(self.post(location+'/confirm',{}).status_code,404)

    # ---- PDF export ----

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
            self.assertEqual(db.execute('SELECT COUNT(*) FROM reports WHERE owner_id=?',(self.owner,)).fetchone()[0],2)

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

    # ---- accounts, ownership and isolation (REQ-1.1, NFR-S1, AC-01) ----

    def test_two_accounts_can_import_the_same_source_keys(self):
        self.imported()
        self.register('other','other-password-1')
        with connect(self.database) as db:
            other=db.execute("SELECT id FROM users WHERE username='other'").fetchone()['id']
        self.assertEqual(self.imported(DEMO, other)['Added'],5)
        with connect(self.database) as db:
            # Same source_key under two owners is two distinct rows, not a clash.
            self.assertEqual(db.execute("SELECT COUNT(*) FROM events WHERE source_key='demo-se-001'").fetchone()[0],2)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM events WHERE owner_id=?',(self.owner,)).fetchone()[0],5)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM events WHERE owner_id=?',(other,)).fetchone()[0],5)

    def test_report_download_is_owner_scoped(self):
        self.note(title='Private record',body='secret body')
        response=self.post('/reports',{'week':'2026-09-28','title':'Mine','note_ids':['1']})
        location=response.headers['Location']
        self.client.post('/logout',data={'csrf':self.csrf()})
        self.register('intruder','intruder-pass-1')
        # Direct request for another account's report id must 404, not 403.
        self.assertEqual(self.client.get(location).status_code,404)

    def test_cross_account_preview_token_rejected(self):
        with connect(self.database) as db:
            token,_=prepare(db,self.owner,DEMO)
        self.register('intruder','intruder-pass-1')
        with connect(self.database) as db:
            intruder=db.execute("SELECT id FROM users WHERE username='intruder'").fetchone()['id']
            with self.assertRaises(ValidationError):
                confirm(db,intruder,token)
            # The rightful owner's token was not consumed by the failed attempt.
            self.assertIsNotNone(db.execute('SELECT 1 FROM previews WHERE token=? AND owner_id=?',
                                            (token,self.owner)).fetchone())

    def test_revisions_are_per_account(self):
        with connect(self.database) as db:
            token,_=prepare(db,self.owner,DEMO)
        self.register('intruder','intruder-pass-1')
        with connect(self.database) as db:
            intruder=db.execute("SELECT id FROM users WHERE username='intruder'").fetchone()['id']
        self.imported(DEMO, intruder)  # intruder's import must not stale tester's preview
        with connect(self.database) as db:
            # tester's preview is still confirmable: the revision counters are
            # separate, so intruder's import did not invalidate it.
            self.assertEqual(confirm(db,self.owner,token)['Added'],5)

    def test_unauthenticated_access_redirects_to_login(self):
        anon=self.app.test_client()
        for path in ['/','/import','/reports/1.pdf']:
            r=anon.get(path)
            self.assertEqual(r.status_code,302)
            self.assertIn('/login',r.headers['Location'])
        r=anon.post('/notes',data={'title':'x'})
        self.assertEqual(r.status_code,302)
        self.assertIn('/login',r.headers['Location'])

    def test_logout_then_access_blocked(self):
        self.imported()
        self.client.post('/logout',data={'csrf':self.csrf()})
        r=self.client.get('/')
        self.assertEqual(r.status_code,302)
        self.assertIn('/login',r.headers['Location'])

    def test_password_not_stored_as_plaintext(self):
        with connect(self.database) as db:
            h=db.execute("SELECT password_hash FROM users WHERE username='tester'").fetchone()[0]
        self.assertNotIn(PASSWORD,h)
        self.assertTrue(h.startswith('scrypt') or h.startswith('pbkdf2'))

    def test_duplicate_username_rejected_case_insensitively(self):
        with connect(self.database) as db:
            with self.assertRaises(AuthError):
                register(db,'TESTER','another-pass-1')

    # ---- migration from the Week 1-2 single-profile database ----

    def _make_v1(self, path):
        con=sqlite3.connect(path)
        con.executescript('''
        CREATE TABLE meta (key TEXT PRIMARY KEY, value INTEGER NOT NULL);
        INSERT INTO meta VALUES ('timetable_revision', 2);
        CREATE TABLE events (source_key TEXT PRIMARY KEY, course_code TEXT NOT NULL,
            course_title TEXT NOT NULL, date TEXT NOT NULL, start_time TEXT NOT NULL,
            end_time TEXT NOT NULL, room TEXT NOT NULL DEFAULT '', teacher TEXT NOT NULL DEFAULT '');
        CREATE TABLE previews (token TEXT PRIMARY KEY, rows_json TEXT NOT NULL, revision INTEGER NOT NULL);
        CREATE TABLE import_batches (id INTEGER PRIMARY KEY,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            added INTEGER NOT NULL, updated INTEGER NOT NULL, unchanged INTEGER NOT NULL);
        CREATE TABLE notes (id INTEGER PRIMARY KEY, date TEXT NOT NULL, kind TEXT NOT NULL,
            context TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL, status TEXT NOT NULL,
            event_key TEXT REFERENCES events(source_key),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE reports (id INTEGER PRIMARY KEY, week TEXT NOT NULL, title TEXT NOT NULL,
            snapshot_json TEXT NOT NULL, pdf BLOB NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        ''')
        con.execute("INSERT INTO events VALUES ('k1','C1','Course One','2026-09-28','09:00','10:00','R1','T1')")
        con.execute("INSERT INTO events VALUES ('k2','C2','Course Two','2026-09-29','09:00','10:00','R2','')")
        con.execute("INSERT INTO notes(date,kind,context,title,body,status,event_key) "
                    "VALUES ('2026-09-28','Assignment requirement','C1','Note one','b','In progress','k1')")
        con.execute("INSERT INTO notes(date,kind,context,title,body,status,event_key) "
                    "VALUES ('2026-10-01','Research meeting','Proj X','Note two','b','Completed',NULL)")
        con.execute("INSERT INTO import_batches(added,updated,unchanged) VALUES (2,0,0)")
        con.execute("INSERT INTO reports(week,title,snapshot_json,pdf) VALUES ('2026-09-28','R','{}',X'00')")
        con.commit(); con.close()

    def test_v1_database_is_migrated_with_data_intact(self):
        v1=str(Path(self.temp.name)/'v1.sqlite3')
        self._make_v1(v1)
        with connect(v1) as db:
            self.assertEqual(detect_version(db),1)
        initialize(v1)
        with connect(v1) as db:
            self.assertEqual(detect_version(db),SCHEMA_VERSION)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM events').fetchone()[0],2)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM notes').fetchone()[0],2)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM reports').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM import_batches').fetchone()[0],1)
            orphan=db.execute('SELECT COUNT(*) FROM notes WHERE event_id IS NOT NULL '
                              'AND event_id NOT IN (SELECT id FROM events)').fetchone()[0]
            self.assertEqual(orphan,0)
            self.assertIsNotNone(db.execute("SELECT 1 FROM users WHERE username='(legacy)'").fetchone())
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])
        self.assertTrue(Path(v1+'.pre-v3.bak').exists())

    def test_first_registration_adopts_legacy_data(self):
        v1=str(Path(self.temp.name)/'adopt.sqlite3')
        self._make_v1(v1)
        initialize(v1)
        app=create_app({'TESTING':True,'DATABASE':v1,'SECRET_KEY':'adopt-only'})
        client=app.test_client()
        client.get('/login')
        with client.session_transaction() as s:
            token=s['csrf']
        client.post('/register',data={'csrf':token,'username':'realuser','password':PASSWORD,'confirm':PASSWORD})
        with connect(v1) as db:
            real=db.execute("SELECT id FROM users WHERE username='realuser'").fetchone()['id']
            self.assertIsNone(db.execute("SELECT 1 FROM users WHERE username='(legacy)'").fetchone())
            self.assertEqual(db.execute('SELECT COUNT(*) FROM events WHERE owner_id=?',(real,)).fetchone()[0],2)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM notes WHERE owner_id=?',(real,)).fetchone()[0],2)


if __name__ == '__main__':
    unittest.main()
