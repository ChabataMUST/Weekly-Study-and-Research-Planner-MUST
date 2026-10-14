"""Strict CSV parsing, explicit preview and atomic reconciliation."""
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
        rows, keys = [], set()
        for line, record in enumerate(reader, 2):
            if len(rows) >= MAX_ROWS:
                raise ValidationError('Use at most 500 occurrences per import.')
            if None in record or any(value is None for value in record.values()):
                raise ValidationError(f'Row {line}: the number of cells does not match the header.')
            row = {field: record.get(field, '').strip() for field in FIELDS}
            try:
                if any(not row[field] for field in REQUIRED):
                    raise ValidationError('Fill all required fields.')
                if any(len(value) > 200 for value in row.values()):
                    raise ValidationError('Each cell must contain at most 200 characters.')
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
            except ValidationError as exc:
                raise ValidationError(f'Row {line}: {exc}') from exc
            keys.add(row['source_key'])
            rows.append(row)
    except csv.Error as exc:
        raise ValidationError('The CSV quoting is invalid.') from exc
    if not rows:
        raise ValidationError('The file contains no class occurrences.')
    return rows


def comparison(db, rows):
    changes = []
    for row in rows:
        old = db.execute('SELECT * FROM events WHERE source_key=?', (row['source_key'],)).fetchone()
        old = dict(old) if old else None
        state = 'Added' if old is None else ('Unchanged' if old == row else 'Updated')
        changes.append({'state': state, 'row': row, 'old': old})
    return changes


def prepare(db, raw):
    rows = parse_csv(raw)
    # Capture a consistent version of the timetable for the confirmation step.
    db.execute('BEGIN IMMEDIATE')
    revision = db.execute("SELECT value FROM meta WHERE key='timetable_revision'").fetchone()[0]
    token = secrets.token_urlsafe(24)
    changes = comparison(db, rows)
    db.execute('INSERT INTO previews VALUES (?,?,?)', (token, json.dumps(rows, ensure_ascii=False), revision))
    db.commit()
    return token, changes


def confirm(db, token):
    db.execute('BEGIN IMMEDIATE')
    try:
        preview = db.execute('SELECT * FROM previews WHERE token=?', (token,)).fetchone()
        if preview is None:
            raise ValidationError('This preview was already confirmed or cancelled. Upload again.')
        revision = db.execute("SELECT value FROM meta WHERE key='timetable_revision'").fetchone()[0]
        if preview['revision'] != revision:
            raise ValidationError('The timetable changed after this preview. Upload again to review current changes.')
        changes = comparison(db, json.loads(preview['rows_json']))
        counts = {state: sum(x['state'] == state for x in changes) for state in ('Added', 'Updated', 'Unchanged')}
        for change in changes:
            row = change['row']
            if change['state'] == 'Added':
                db.execute('INSERT INTO events VALUES (?,?,?,?,?,?,?,?)', [row[k] for k in FIELDS])
            elif change['state'] == 'Updated':
                # UPDATE preserves the key and any linked notes; REPLACE would delete the row.
                db.execute('UPDATE events SET ' + ','.join(k + '=?' for k in FIELDS[1:]) + ' WHERE source_key=?',
                           [row[k] for k in FIELDS[1:]] + [row['source_key']])
        db.execute('INSERT INTO import_batches(added,updated,unchanged) VALUES (?,?,?)',
                   (counts['Added'], counts['Updated'], counts['Unchanged']))
        db.execute("UPDATE meta SET value=value+1 WHERE key='timetable_revision'")
        db.execute('DELETE FROM previews WHERE token=?', (token,))
        db.commit()
        return counts
    except Exception:
        db.rollback()
        raise
