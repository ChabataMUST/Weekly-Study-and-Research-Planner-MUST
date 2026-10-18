"""Versioned schema, migration and account-scoped storage.

The Week 1-2 prototype ran as a single local profile. Week 3 adds account
ownership, separate course/project entities, per-account timetable revisions
and a field-level record of confirmed timetable changes.

Every table that stores a student's own work carries ``owner_id``. Ownership is
enforced by the query layer as well as by these foreign keys: a foreign key
stops a record pointing at a missing account, but only the explicit
``owner_id=?`` predicate in each SELECT stops one student reading another
student's records by guessing an identifier (Task 2 NFR-S1, AC-01).
"""
import shutil
import sqlite3
from pathlib import Path

SCHEMA_VERSION = 3

# Individual statements rather than one script. ``Connection.executescript``
# commits any pending transaction first, which would destroy the atomicity the
# migration depends on, and a single ``CREATE TABLE IF NOT EXISTS`` silently
# skips a pre-existing table instead of upgrading it.
_DDL = [
    """CREATE TABLE IF NOT EXISTS schema_meta (
        key TEXT PRIMARY KEY, value TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        username TEXT NOT NULL UNIQUE COLLATE NOCASE,
        password_hash TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS user_state (
        owner_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
        timetable_revision INTEGER NOT NULL DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS courses (
        id INTEGER PRIMARY KEY,
        owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        code TEXT NOT NULL,
        title TEXT NOT NULL,
        UNIQUE(owner_id, code)
    )""",
    """CREATE TABLE IF NOT EXISTS projects (
        id INTEGER PRIMARY KEY,
        owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        title TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        UNIQUE(owner_id, title)
    )""",
    """CREATE TABLE IF NOT EXISTS academic_items (
        id INTEGER PRIMARY KEY,
        owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        kind TEXT NOT NULL CHECK(kind IN
            ('Assignment','Examination','Meeting','Reading','Experiment','Writing')),
        course_id INTEGER REFERENCES courses(id) ON DELETE CASCADE,
        project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
        title TEXT NOT NULL,
        official_due TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CHECK (course_id IS NOT NULL OR project_id IS NOT NULL)
    )""",
    """CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY,
        owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
        source_key TEXT NOT NULL,
        date TEXT NOT NULL,
        start_time TEXT NOT NULL,
        end_time TEXT NOT NULL,
        room TEXT NOT NULL DEFAULT '',
        teacher TEXT NOT NULL DEFAULT '',
        state TEXT NOT NULL DEFAULT 'scheduled'
            CHECK(state IN ('scheduled','cancelled')),
        UNIQUE(owner_id, source_key)
    )""",
    """CREATE TABLE IF NOT EXISTS notes (
        id INTEGER PRIMARY KEY,
        owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        course_id INTEGER REFERENCES courses(id) ON DELETE CASCADE,
        project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
        item_id INTEGER REFERENCES academic_items(id) ON DELETE CASCADE,
        event_id INTEGER REFERENCES events(id) ON DELETE CASCADE,
        date TEXT NOT NULL,
        kind TEXT NOT NULL,
        title TEXT NOT NULL,
        body TEXT NOT NULL,
        status TEXT NOT NULL,
        context TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT,
        CHECK (course_id IS NOT NULL OR project_id IS NOT NULL OR item_id IS NOT NULL)
    )""",
    """CREATE TABLE IF NOT EXISTS previews (
        token TEXT PRIMARY KEY,
        owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        rows_json TEXT NOT NULL,
        revision INTEGER NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS import_batches (
        id INTEGER PRIMARY KEY,
        owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        added INTEGER NOT NULL, updated INTEGER NOT NULL, unchanged INTEGER NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS event_changes (
        id INTEGER PRIMARY KEY,
        owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        batch_id INTEGER REFERENCES import_batches(id) ON DELETE CASCADE,
        event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
        change_state TEXT NOT NULL CHECK(change_state IN ('Added','Updated')),
        previous_json TEXT NOT NULL DEFAULT '{}',
        current_json TEXT NOT NULL,
        confirmed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS reports (
        id INTEGER PRIMARY KEY,
        owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        week TEXT NOT NULL, title TEXT NOT NULL,
        snapshot_json TEXT NOT NULL, pdf BLOB NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""",
    'CREATE INDEX IF NOT EXISTS idx_events_owner_date ON events(owner_id, date)',
    'CREATE INDEX IF NOT EXISTS idx_notes_owner_date ON notes(owner_id, date)',
    'CREATE INDEX IF NOT EXISTS idx_notes_owner_item ON notes(owner_id, item_id)',
    'CREATE INDEX IF NOT EXISTS idx_items_owner_course ON academic_items(owner_id, course_id)',
    'CREATE INDEX IF NOT EXISTS idx_reports_owner_week ON reports(owner_id, week)',
    'CREATE INDEX IF NOT EXISTS idx_changes_owner_event ON event_changes(owner_id, event_id)',
]

# Tables that existed in the Week 1-2 prototype and must be rebuilt. They are
# renamed rather than dropped first so the new shape can be created under the
# original name and the data copied across inside one transaction.
_V1_TABLES = ('events', 'notes', 'reports', 'import_batches', 'previews')

# Kinds whose free-text context described a taught course rather than a
# research project. The kind list is a fixed in-program enumeration, not
# user-supplied text, so this inference is reliable for the prototype data.
_COURSE_KINDS = ('Assignment requirement', 'Exam scope', 'Teacher feedback')


class Connection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


def connect(path):
    db = sqlite3.connect(path, timeout=10, factory=Connection)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    return db


def _table_exists(db, name):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def detect_version(db):
    """Return the schema version of an existing database, or 0 for a new one."""
    if _table_exists(db, 'schema_meta'):
        row = db.execute("SELECT value FROM schema_meta WHERE key='version'").fetchone()
        return int(row[0]) if row is not None else 0
    return 1 if _table_exists(db, 'events') else 0


def initialize(path):
    """Create or upgrade the database at *path*. Safe to call on every start.

    Returns a list of human-readable warnings. A migration that needs review
    still succeeds; blocking startup over a cosmetic conflict would leave the
    student with an application that no longer opens.
    """
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as db:
        version = detect_version(db)
        if version == SCHEMA_VERSION:
            return []
        if version > SCHEMA_VERSION:
            raise RuntimeError(
                f'This database uses schema version {version}, newer than this '
                f'program supports ({SCHEMA_VERSION}). Update the application.')
        if version == 0:
            db.execute('BEGIN IMMEDIATE')
            try:
                _create_all(db)
                db.execute("INSERT INTO schema_meta(key,value) VALUES ('version',?)", (str(SCHEMA_VERSION),))
                db.commit()
            except Exception:
                db.rollback()
                raise
            return []
        return _migrate_v1_to_v3(path, db)


def _create_all(db):
    for statement in _DDL:
        db.execute(statement)


def _backup(path):
    """Copy the database aside before an irreversible rewrite (Task 2 NFR-A3)."""
    source = Path(path)
    target = source.with_name(source.name + '.pre-v3.bak')
    if not target.exists():
        shutil.copy2(source, target)
    return target


def _migrate_v1_to_v3(path, db):
    """Rewrite a Week 1-2 single-profile database into the owned schema.

    Runs in one transaction: a failure leaves the database exactly as it was
    rather than half converted. Row counts are re-checked before committing and
    any mismatch rolls the whole migration back.
    """
    warnings = []
    _backup(path)

    # Renaming and rebuilding tables while foreign keys are enforced makes
    # SQLite rewrite the references that point at them. The pragma is a no-op
    # inside a transaction, so it must be set before BEGIN.
    db.execute('PRAGMA foreign_keys=OFF')
    db.execute('BEGIN IMMEDIATE')
    try:
        expected = {table: db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                    for table in _V1_TABLES}

        for table in _V1_TABLES:
            db.execute(f'ALTER TABLE {table} RENAME TO {table}_v1')
        # The global revision counter moves into per-account user_state.
        revision = db.execute("SELECT value FROM meta WHERE key='timetable_revision'").fetchone()[0]

        _create_all(db)

        # A reserved account holds every pre-existing record. It cannot sign in
        # ('!' is not a valid password hash); the first registered account
        # adopts the data and the row is removed. This keeps owner_id NOT NULL
        # without building a claim-the-old-data screen for a single-profile
        # machine.
        legacy = db.execute(
            "INSERT INTO users(username,password_hash) VALUES ('(legacy)','!')").lastrowid
        db.execute('INSERT INTO user_state(owner_id,timetable_revision) VALUES (?,?)', (legacy, revision))

        # Courses come from the occurrences. One code may carry several titles
        # in a hand-prepared CSV; keep one deterministically and report it.
        variants = {}
        for row in db.execute('SELECT DISTINCT course_code, course_title FROM events_v1').fetchall():
            variants.setdefault(row['course_code'], set()).add(row['course_title'])
        course_of = {}
        for code, titles in variants.items():
            if len(titles) > 1:
                warnings.append(f'Course code {code} carried several titles; kept '
                                f'{sorted(titles)[0]!r} from {sorted(titles)!r}.')
            course_of[code] = db.execute('INSERT INTO courses(owner_id,code,title) VALUES (?,?,?)',
                                         (legacy, code, sorted(titles)[0])).lastrowid

        # source_key -> new event id, needed to repoint notes.event_key. The
        # surrogate id is what keeps an occurrence's identity stable when the
        # student later edits its source key (REQ-1.3).
        event_id_of = {}
        for row in db.execute('SELECT * FROM events_v1').fetchall():
            event_id_of[row['source_key']] = db.execute(
                """INSERT INTO events(owner_id,course_id,source_key,date,start_time,
                                      end_time,room,teacher,state)
                   VALUES (?,?,?,?,?,?,?,?, 'scheduled')""",
                (legacy, course_of[row['course_code']], row['source_key'], row['date'],
                 row['start_time'], row['end_time'], row['room'], row['teacher'])).lastrowid

        # Research-flavoured notes described a project; the rest described a
        # course. Either way the note gains a real parent record, which is what
        # Week 4 revisions and Week 6 resource retrieval will hang from.
        project_of = {}
        orphaned = 0
        for row in db.execute('SELECT * FROM notes_v1').fetchall():
            context = row['context']
            if row['kind'] in _COURSE_KINDS:
                course_id, project_id = _match_course(db, legacy, context, course_of), None
            else:
                course_id = None
                if context not in project_of:
                    project_of[context] = db.execute(
                        'INSERT INTO projects(owner_id,title) VALUES (?,?)', (legacy, context)).lastrowid
                project_id = project_of[context]
            event_key = row['event_key']
            event_id = event_id_of.get(event_key) if event_key else None
            if event_key and event_id is None:
                orphaned += 1
            db.execute(
                """INSERT INTO notes(owner_id,course_id,project_id,item_id,event_id,date,kind,
                                     title,body,status,context,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (legacy, course_id, project_id, None, event_id, row['date'], row['kind'],
                 row['title'], row['body'], row['status'], context, row['created_at']))
        if orphaned:
            warnings.append(f'{orphaned} note(s) referenced a class that no longer existed; '
                            'the link was dropped and the note kept.')

        for row in db.execute('SELECT * FROM reports_v1').fetchall():
            db.execute('INSERT INTO reports(owner_id,week,title,snapshot_json,pdf,created_at) '
                       'VALUES (?,?,?,?,?,?)',
                       (legacy, row['week'], row['title'], row['snapshot_json'], row['pdf'],
                        row['created_at']))
        for row in db.execute('SELECT * FROM import_batches_v1').fetchall():
            db.execute('INSERT INTO import_batches(owner_id,created_at,added,updated,unchanged) '
                       'VALUES (?,?,?,?,?)',
                       (legacy, row['created_at'], row['added'], row['updated'], row['unchanged']))

        # Pending previews are intentionally dropped: a token issued before
        # accounts existed has no owner, and confirming a pre-migration preview
        # against a rebuilt timetable is not meaningful. The student re-uploads.
        if expected['previews']:
            warnings.append(f"{expected['previews']} unconfirmed import preview(s) were discarded; "
                            'upload the timetable again.')

        for table in _V1_TABLES:
            db.execute(f'DROP TABLE {table}_v1')
        db.execute('DROP TABLE meta')

        db.execute("INSERT INTO schema_meta(key,value) VALUES ('version',?)", (str(SCHEMA_VERSION),))
        _verify_counts(db, expected, legacy)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.execute('PRAGMA foreign_keys=ON')
    return warnings


def _match_course(db, owner_id, context, course_of):
    """Resolve a note's free-text context to a course row.

    Matches the stored code first, then the title; falls back to creating a
    course from the text so the note is never orphaned.
    """
    if context in course_of:
        return course_of[context]
    row = db.execute('SELECT id FROM courses WHERE owner_id=? AND title=?', (owner_id, context)).fetchone()
    if row is not None:
        return row['id']
    course_of[context] = db.execute('INSERT INTO courses(owner_id,code,title) VALUES (?,?,?)',
                                    (owner_id, context, context)).lastrowid
    return course_of[context]


def _verify_counts(db, expected, owner_id):
    """Abort the transaction if the rewrite lost or duplicated any record."""
    for table in ('events', 'notes', 'reports', 'import_batches'):
        actual = db.execute(f'SELECT COUNT(*) FROM {table} WHERE owner_id=?', (owner_id,)).fetchone()[0]
        if actual != expected[table]:
            raise RuntimeError(
                f'Migration verification failed: {table} had {expected[table]} rows before '
                f'and {actual} after. No change has been committed.')
    for table in ('events', 'notes', 'reports', 'import_batches'):
        if db.execute(f'SELECT COUNT(*) FROM {table} WHERE owner_id IS NULL').fetchone()[0]:
            raise RuntimeError(f'Migration left {table} rows without an owner.')
    if db.execute('SELECT COUNT(*) FROM notes WHERE event_id IS NOT NULL AND course_id IS NULL '
                  'AND project_id IS NULL AND item_id IS NULL').fetchone()[0]:
        raise RuntimeError('Migration left notes without a course, project or item.')
