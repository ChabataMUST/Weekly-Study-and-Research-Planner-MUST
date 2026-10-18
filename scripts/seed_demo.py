"""Add fictional demo data once. Existing user data is never cleared.

Since Week 3 every record belongs to an account, the demo runs under a fixed
demonstration account. On a database migrated from the single-profile
prototype, that account also adopts the pre-existing records, matching what the
first real registration would do.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from planner import create_app
from planner.auth import register, AuthError, authenticate
from planner.db import connect
from planner.importer import prepare, confirm

ROOT = Path(__file__).resolve().parents[1]
DEMO_USER = 'demo'
DEMO_PASSWORD = 'demo-password'


def seed(app):
    """Populate an empty database with a demo account and fictional records.

    Returns the demo account's id, or None when the database already held data
    and nothing was seeded.
    """
    with connect(app.config['DATABASE']) as db:
        if db.execute('SELECT COUNT(*) FROM events').fetchone()[0] or \
           db.execute('SELECT COUNT(*) FROM notes').fetchone()[0]:
            print('Demo seed skipped: this database already has records.')
            return None
        try:
            owner = register(db, DEMO_USER, DEMO_PASSWORD)
        except AuthError:
            # The demo account already exists (for example a second run against
            # a database that was emptied by hand); sign in as it instead.
            owner = authenticate(db, DEMO_USER, DEMO_PASSWORD)
        token, _ = prepare(db, owner, (ROOT/'samples/timetable-demo.csv').read_bytes())
        confirm(db, owner, token)

        course_of = {row['code']: row['id'] for row in
                     db.execute('SELECT id,code FROM courses WHERE owner_id=?', (owner,))}
        event_of = {row['source_key']: row['id'] for row in
                    db.execute('SELECT id,source_key FROM events WHERE owner_id=?', (owner,))}
        # The research records belong to a project rather than a course, so the
        # demo shows both containers (Task 2 DR-3).
        project = db.execute('INSERT INTO projects(owner_id,title) VALUES (?,?)',
                             (owner, 'Demo research project')).lastrowid

        notes = [
            ('2026-09-28', 'Assignment requirement', course_of['DEMO-SE'], None, event_of['demo-se-001'],
             'Requirements report checklist',
             'Describe the student workflow, keep requirement identifiers consistent, and link each '
             'accepted feature to its source question. This is fictional demonstration content.',
             'In progress'),
            ('2026-09-29', 'Exam scope', course_of['DEMO-MATH'], None, event_of['demo-math-001'],
             'Review scope / 复习范围',
             'Review matrices, vector spaces and the worked examples from the practice sheet.\n'
             '复习时标出不理解的步骤，下次课集中提问。 Fictional study note.', 'Not started'),
            ('2026-10-01', 'Research meeting', None, project, None,
             'Meeting notes: baseline experiment',
             'Compare two small baseline settings and record the data split. Keep the unsuccessful '
             'run in the log. Next step: check whether the preprocessing is consistent. '
             'Fictional research example.', 'Completed'),
            ('2026-10-02', 'Reading / experiment', None, project, None,
             'Reading notes and follow-up',
             'Read the methods section and list the assumptions that affect our experiment. Prepare '
             'one question for the next meeting. Fictional research example.', 'In progress'),
        ]
        db.executemany(
            'INSERT INTO notes(owner_id,date,kind,course_id,project_id,event_id,title,body,status,context) '
            'VALUES (?,?,?,?,?,?,?,?,?,?)',
            [(owner, d, k, c, p, e, t, b, s, 'Demo') for d, k, c, p, e, t, b, s in notes])
    print(f'Demo ready: account "{DEMO_USER}" with five class occurrences and four fictional '
          f'learning records. Open 2026-09-28.')
    return owner


if __name__ == '__main__':
    seed(create_app())
