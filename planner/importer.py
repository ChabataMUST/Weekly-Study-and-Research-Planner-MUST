"""Strict CSV parsing, explicit preview and atomic reconciliation.

The CSV contract documented in docs/import-format.md is unchanged: the same
eight columns, the same validation rules and the same source_key semantics.
What changed underneath is that every occurrence now belongs to an account and
points at a course entity rather than repeating the course title on each row.

Two consequences are worth stating because they are easy to get wrong later:

* ``state`` is not part of the comparison. A class the student cancelled stays
  cancelled when the same file is imported again; a reimport must not silently
  resurrect it, and must not report every cancelled class as a change.
* A confirmed change is written to ``event_changes`` with its previous and new
  values and its confirmation time (Task 2 6.2.8), so that a room change can be
  explained afterwards rather than only counted.
"""
import csv
import io
import json
import re
import secrets
from datetime import date

FIELDS = ['source_key', 'course_code', 'course_title', 'date', 'start_time',
          'end_time', 'room', 'teacher']
REQUIRED = FIELDS[:6]
MAX_ROWS = 500
MAX_CELL = 200


class ValidationError(ValueError):
    pass


def valid_date(value):
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValidationError('Use a date in YYYY-MM-DD format.')
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError('The date does not exist.') from exc


def parse_csv(raw):
    if len(raw) > 1024 * 1024:
        raise ValidationError('CSV files must be at most 1 MB.')
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        raise ValidationError('Save the file as CSV UTF-8 before importing.') from exc
    try:
        reader = csv.DictReader(io.StringIO(text, newline=''), strict=True)
        header = reader.fieldnames or []
        if len(header) != len(set(header)) or not set(REQUIRED).issubset(header):
            raise ValidationError('Include each required column once: ' + ', '.join(REQUIRED))
        if set(header) - set(FIELDS):
            raise ValidationError('Unknown columns: ' + ', '.join(sorted(set(header) - set(FIELDS))))
        rows, keys, titles = [], set(), {}
        for line, record in enumerate(reader, 2):
            if len(rows) >= MAX_ROWS:
                raise ValidationError('Use at most 500 occurrences per import.')
            if None in record or any(value is None for value in record.values()):
                raise ValidationError(f'Row {line}: the number of cells does not match the header.')
            row = {field: record.get(field, '').strip() for field in FIELDS}
            try:
                if any(not row[field] for field in REQUIRED):
                    raise ValidationError('Fill all required fields.')
                if any(len(value) > MAX_CELL for value in row.values()):
                    raise ValidationError(f'Each cell must contain at most {MAX_CELL} characters.')
                if any(any(ord(c) < 32 for c in v) for v in row.values()):
                    raise ValidationError('Cells cannot contain control characters or line breaks.')
                valid_date(row['date'])
                for field in ('start_time', 'end_time'):
                    if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', row[field]):
                        raise ValidationError('Use 24-hour HH:MM times.')
                if row['start_time'] >= row['end_time']:
                    raise ValidationError('End time must be after start time on the same day.')
                if row['source_key'] in keys:
                    raise ValidationError('Duplicate source_key in this file.')
                # A course code is the identity of a course entity now, so one
                # file must not describe the same code with two titles. Without
                # this check the title would flip-flop between rows and the last
                # one would silently win.
                earlier = titles.get(row['course_code'])
                if earlier is None:
                    titles[row['course_code']] = row['course_title']
                elif earlier != row['course_title']:
                    raise ValidationError(
                        f'course_code {row["course_code"]} is used with two different titles '
                        f'in this file: {earlier!r} and {row["course_title"]!r}.')
            except ValidationError as exc:
                raise ValidationError(f'Row {line}: {exc}') from exc
            keys.add(row['source_key'])
            rows.append(row)
    except csv.Error as exc:
        raise ValidationError('The CSV quoting is invalid.') from exc
    if not rows:
        raise ValidationError('The file contains no class occurrences.')
    return rows


def _stored_view(db, owner_id, source_key):
    """Return the stored occurrence in CSV shape, plus its internal ids.

    The preview screen compares a row against what is already saved, so the old
    values are projected back into the same eight columns the student supplied.
    """
    row = db.execute(
        """SELECT e.id, e.course_id, e.state, e.source_key, e.date, e.start_time,
                  e.end_time, e.room, e.teacher, c.code AS course_code,
                  c.title AS course_title
           FROM events e JOIN courses c ON c.id = e.course_id
           WHERE e.source_key=? AND e.owner_id=?""", (source_key, owner_id)).fetchone()
    if row is None:
        return None
    stored = dict(row)
    return {'event_id': stored.pop('id'), 'course_id': stored.pop('course_id'),
            'state': stored.pop('state'), 'csv': stored}


def comparison(db, owner_id, rows):
    """Classify each incoming row as Added, Updated or Unchanged.

    ``state`` is deliberately excluded from the comparison, and from the old
    values shown in the preview: it is the student's own cancellation flag, not
    something a timetable file can express.
    """
    changes = []
    for row in rows:
        stored = _stored_view(db, owner_id, row['source_key'])
        if stored is None:
            state, old = 'Added', None
        elif stored['csv'] == row:
            state, old = 'Unchanged', None
        else:
            state, old = 'Updated', stored['csv']
        changes.append({'state': state, 'row': row, 'old': old,
                        'event_id': stored['event_id'] if stored else None,
                        'course_id': stored['course_id'] if stored else None})
    return changes


def ensure_course(db, owner_id, code, title):
    """Find or create the course for this account and return its id.

    A retitled course is updated in place so that every occurrence of it, and
    every note filed under it, follows the new title instead of keeping a stale
    copy (Task 2 6.1.8: a later change to the title must not create a new item).
    """
    row = db.execute('SELECT id,title FROM courses WHERE owner_id=? AND code=?',
                     (owner_id, code)).fetchone()
    if row is None:
        return db.execute('INSERT INTO courses(owner_id,code,title) VALUES (?,?,?)',
                          (owner_id, code, title)).lastrowid
    if row['title'] != title:
        db.execute('UPDATE courses SET title=? WHERE id=?', (title, row['id']))
    return row['id']


def _revision(db, owner_id):
    """This account's timetable revision, creating the row if it is missing."""
    db.execute('INSERT OR IGNORE INTO user_state(owner_id,timetable_revision) VALUES (?,0)', (owner_id,))
    return db.execute('SELECT timetable_revision FROM user_state WHERE owner_id=?',
                      (owner_id,)).fetchone()[0]


def prepare(db, owner_id, raw):
    """Validate a file and store it as a preview owned by this account."""
    rows = parse_csv(raw)
    # Capture a consistent version of the timetable for the confirmation step.
    db.execute('BEGIN IMMEDIATE')
    revision = _revision(db, owner_id)
    token = secrets.token_urlsafe(24)
    changes = comparison(db, owner_id, rows)
    db.execute('INSERT INTO previews(token,owner_id,rows_json,revision) VALUES (?,?,?,?)',
               (token, owner_id, json.dumps(rows, ensure_ascii=False), revision))
    db.commit()
    return token, changes


def confirm(db, owner_id, token):
    """Apply a confirmed batch in one transaction, or change nothing."""
    db.execute('BEGIN IMMEDIATE')
    try:
        # The token is looked up with its owner, so a token belonging to another
        # account is indistinguishable from one that never existed.
        preview = db.execute('SELECT * FROM previews WHERE token=? AND owner_id=?',
                             (token, owner_id)).fetchone()
        if preview is None:
            raise ValidationError('This preview was already confirmed or cancelled. Upload again.')
        if preview['revision'] != _revision(db, owner_id):
            raise ValidationError('The timetable changed after this preview. Upload again to review current changes.')
        rows = json.loads(preview['rows_json'])
        changes = comparison(db, owner_id, rows)
        counts = {state: sum(x['state'] == state for x in changes)
                  for state in ('Added', 'Updated', 'Unchanged')}

        batch_id = db.execute(
            'INSERT INTO import_batches(owner_id,added,updated,unchanged) VALUES (?,?,?,?)',
            (owner_id, counts['Added'], counts['Updated'], counts['Unchanged'])).lastrowid

        for change in changes:
            row = change['row']
            course_id = ensure_course(db, owner_id, row['course_code'], row['course_title'])
            if change['state'] == 'Added':
                event_id = db.execute(
                    """INSERT INTO events(owner_id,course_id,source_key,date,start_time,
                                          end_time,room,teacher,state)
                       VALUES (?,?,?,?,?,?,?,?, 'scheduled')""",
                    (owner_id, course_id, row['source_key'], row['date'], row['start_time'],
                     row['end_time'], row['room'], row['teacher'])).lastrowid
                previous = '{}'
            elif change['state'] == 'Updated':
                event_id = change['event_id']
                # UPDATE rather than delete-and-reinsert: the surrogate id is the
                # occurrence's identity, and notes.event_id points at it. A
                # replacement row would orphan every linked record (REQ-1.3).
                # ``state`` is left alone so a cancelled class stays cancelled.
                db.execute(
                    """UPDATE events SET course_id=?, date=?, start_time=?, end_time=?,
                                          room=?, teacher=?
                       WHERE id=? AND owner_id=?""",
                    (course_id, row['date'], row['start_time'], row['end_time'],
                     row['room'], row['teacher'], event_id, owner_id))
                previous = json.dumps(change['old'], ensure_ascii=False)
            else:
                continue
            db.execute(
                """INSERT INTO event_changes(owner_id,batch_id,event_id,change_state,
                                             previous_json,current_json)
                   VALUES (?,?,?,?,?,?)""",
                (owner_id, batch_id, event_id, change['state'], previous,
                 json.dumps(row, ensure_ascii=False)))

        db.execute('UPDATE user_state SET timetable_revision=timetable_revision+1 WHERE owner_id=?',
                   (owner_id,))
        db.execute('DELETE FROM previews WHERE token=? AND owner_id=?', (token, owner_id))
        db.commit()
        return counts
    except Exception:
        db.rollback()
        raise
