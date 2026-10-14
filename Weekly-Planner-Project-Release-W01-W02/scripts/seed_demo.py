"""Add fictional demo data once. Existing user data is never cleared."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from planner import create_app
from planner.db import connect
from planner.importer import prepare, confirm

ROOT=Path(__file__).resolve().parents[1]


def seed(app):
    with connect(app.config['DATABASE']) as db:
        if db.execute('SELECT COUNT(*) FROM events').fetchone()[0] or db.execute('SELECT COUNT(*) FROM notes').fetchone()[0]:
            print('Demo seed skipped: this database already has records.')
            return False
        token,_=prepare(db,(ROOT/'samples/timetable-demo.csv').read_bytes())
        confirm(db,token)
        notes=[
            ('2026-09-28','Assignment requirement','Software Engineering','Requirements report checklist',
             'Describe the student workflow, keep requirement identifiers consistent, and link each accepted feature to its source question. This is fictional demonstration content.', 'In progress','demo-se-001'),
            ('2026-09-29','Exam scope','Linear Algebra','Review scope / 复习范围',
             'Review matrices, vector spaces and the worked examples from the practice sheet.\n复习时标出不理解的步骤，下次课集中提问。 Fictional study note.','Not started','demo-math-001'),
            ('2026-10-01','Research meeting','Demo research project','Meeting notes: baseline experiment',
             'Compare two small baseline settings and record the data split. Keep the unsuccessful run in the log. Next step: check whether the preprocessing is consistent. Fictional research example.','Completed',None),
            ('2026-10-02','Reading / experiment','Demo research project','Reading notes and follow-up',
             'Read the methods section and list the assumptions that affect our experiment. Prepare one question for the next meeting. Fictional research example.','In progress',None),
        ]
        db.executemany('INSERT INTO notes(date,kind,context,title,body,status,event_key) VALUES (?,?,?,?,?,?,?)',notes)
    print('Demo ready: five class occurrences and four fictional learning records. Open 2026-09-28.')
    return True


if __name__=='__main__':
    seed(create_app())
