"""Weeks 1-2 local prototype. No multi-user authentication is claimed yet."""
import hmac
import json
import secrets
import sqlite3
from datetime import date, timedelta
from io import BytesIO
from pathlib import Path
from flask import Flask, abort, flash, redirect, render_template, request, send_file, session, url_for
from .db import connect, initialize
from .importer import ValidationError, valid_date, prepare, confirm, comparison
from .reports import render_pdf

KINDS = ('Assignment requirement', 'Exam scope', 'Research meeting', 'Reading / experiment', 'Teacher feedback')
STATUSES = ('Not started', 'In progress', 'Completed')


def week_bounds(value):
    selected = valid_date(value)
    monday = selected - timedelta(days=selected.weekday())
    return monday, monday + timedelta(days=6)


def weekly_records(db, week):
    start, end = week_bounds(week)
    args = (start.isoformat(), end.isoformat())
    events = [dict(x) for x in db.execute('SELECT * FROM events WHERE date BETWEEN ? AND ? ORDER BY date,start_time', args)]
    notes = [dict(x) for x in db.execute('SELECT * FROM notes WHERE date BETWEEN ? AND ? ORDER BY date,id', args)]
    return start, end, events, notes


def create_app(config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.update(DATABASE=str(Path(app.instance_path)/'planner.sqlite3'), MAX_CONTENT_LENGTH=1024*1024,
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Strict')
    if config:
        app.config.update(config)
    Path(app.config['DATABASE']).parent.mkdir(parents=True, exist_ok=True)
    if not app.config.get('SECRET_KEY'):
        key_file = Path(app.config['DATABASE']).parent/'secret.key'
        if not key_file.exists():
            key_file.write_text(secrets.token_hex(32), encoding='ascii')
        app.config['SECRET_KEY'] = key_file.read_text(encoding='ascii')
    initialize(app.config['DATABASE'])

    @app.before_request
    def protect_forms():
        session.setdefault('csrf', secrets.token_hex(24))
        if request.method == 'POST':
            if not hmac.compare_digest(session['csrf'], request.form.get('csrf', '')):
                abort(400, description='This form expired. Reload the page and try again.')

    @app.errorhandler(ValidationError)
    def validation_error(exc):
        return render_template('error.html', message=str(exc)), 400

    @app.errorhandler(413)
    def too_large(exc):
        return render_template('error.html', message='The upload is too large. Use a CSV file smaller than 1 MB.'), 413

    @app.errorhandler(400)
    @app.errorhandler(404)
    def http_error(exc):
        return render_template('error.html', message=exc.description), exc.code

    @app.get('/')
    def index():
        week = request.args.get('week', '2026-09-28')
        with connect(app.config['DATABASE']) as db:
            start, end, events, notes = weekly_records(db, week)
            reports = db.execute('SELECT id,title,created_at FROM reports WHERE week=? ORDER BY id DESC', (start.isoformat(),)).fetchall()
        days = [start+timedelta(days=i) for i in range(7)]
        return render_template('index.html', start=start, end=end, events=events, notes=notes, days=days,
                               previous=start-timedelta(days=7), following=start+timedelta(days=7),
                               reports=reports, kinds=KINDS, statuses=STATUSES,
                               completed=sum(x['status']=='Completed' for x in notes))

    @app.route('/import', methods=['GET', 'POST'])
    def import_file():
        if request.method == 'GET':
            return render_template('import.html')
        upload = request.files.get('timetable')
        if not upload or not upload.filename.lower().endswith('.csv'):
            raise ValidationError('Choose a CSV timetable file.')
        with connect(app.config['DATABASE']) as db:
            token, _ = prepare(db, upload.read())
        return redirect(url_for('preview', token=token))

    @app.get('/import/<token>')
    def preview(token):
        with connect(app.config['DATABASE']) as db:
            item = db.execute('SELECT * FROM previews WHERE token=?', (token,)).fetchone()
            if item is None:
                abort(404)
            changes = comparison(db, json.loads(item['rows_json']))
            revision = db.execute("SELECT value FROM meta WHERE key='timetable_revision'").fetchone()[0]
        return render_template('preview.html', changes=changes, token=token, stale=revision!=item['revision'])

    @app.post('/import/<token>/confirm')
    def confirm_import(token):
        with connect(app.config['DATABASE']) as db:
            item = db.execute('SELECT rows_json FROM previews WHERE token=?', (token,)).fetchone()
            week = json.loads(item[0])[0]['date'] if item else '2026-09-28'
            counts = confirm(db, token)
        flash(f"Import saved: {counts['Added']} added, {counts['Updated']} updated, {counts['Unchanged']} unchanged.")
        return redirect(url_for('index', week=week))

    @app.post('/import/<token>/cancel')
    def cancel_import(token):
        with connect(app.config['DATABASE']) as db:
            db.execute('DELETE FROM previews WHERE token=?', (token,))
        flash('Preview cancelled. The timetable has not changed.')
        return redirect(url_for('import_file'))

    @app.post('/notes')
    def add_note():
        values = {k: request.form.get(k, '').strip() for k in ('date','kind','context','title','body','status','event_key')}
        valid_date(values['date'])
        if values['kind'] not in KINDS or values['status'] not in STATUSES:
            raise ValidationError('Select a valid record type and progress status.')
        if not values['context'] or not values['title'] or not values['body']:
            raise ValidationError('Complete the course/project, title and details fields.')
        if len(values['context']) > 200 or len(values['title']) > 200 or len(values['body']) > 20000:
            raise ValidationError('Use at most 200 characters for headings and 20,000 for details.')
        with connect(app.config['DATABASE']) as db:
            if values['event_key'] and not db.execute('SELECT 1 FROM events WHERE source_key=?', (values['event_key'],)).fetchone():
                raise ValidationError('The linked class does not exist. Choose a current class.')
            db.execute('INSERT INTO notes(date,kind,context,title,body,status,event_key) VALUES (?,?,?,?,?,?,?)',
                       [values[k] for k in ('date','kind','context','title','body','status')]+[values['event_key'] or None])
        flash('Learning record saved.')
        return redirect(url_for('index', week=values['date']))

    @app.post('/reports')
    def export_report():
        week = request.form.get('week', '')
        title = request.form.get('title', '').strip()
        summary = request.form.get('summary', '').strip()
        if not title or len(title)>200 or len(summary)>20000:
            raise ValidationError('Enter a title up to 200 characters and a summary up to 20,000 characters.')
        try:
            selected = {int(x) for x in request.form.getlist('note_ids')}
        except ValueError as exc:
            raise ValidationError('Invalid record selection.') from exc
        with connect(app.config['DATABASE']) as db:
            start,end,events,notes = weekly_records(db,week)
            if not selected.issubset({x['id'] for x in notes}):
                raise ValidationError('Only records from the selected week can be exported.')
            # Keep only selected fields in the snapshot: excluded notes never enter the PDF.
            snapshot = {'week': start.isoformat(), 'end': end.isoformat(), 'title':title, 'summary':summary,
                        'events':events if request.form.get('include_events')=='yes' else [],
                        'notes':[x for x in notes if x['id'] in selected]}
            pdf = render_pdf(snapshot)
            result = db.execute('INSERT INTO reports(week,title,snapshot_json,pdf) VALUES (?,?,?,?)',
                                (start.isoformat(),title,json.dumps(snapshot,ensure_ascii=False),pdf))
            report_id = result.lastrowid
        return redirect(url_for('download_report', report_id=report_id))

    @app.get('/reports/<int:report_id>.pdf')
    def download_report(report_id):
        with connect(app.config['DATABASE']) as db:
            row = db.execute('SELECT week,pdf FROM reports WHERE id=?',(report_id,)).fetchone()
        if row is None:
            abort(404)
        return send_file(BytesIO(row['pdf']), mimetype='application/pdf', as_attachment=True,
                         download_name=f'weekly-report-{row["week"]}-v{report_id}.pdf')

    return app
