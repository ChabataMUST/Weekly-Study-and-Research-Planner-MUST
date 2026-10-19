"""Weekly planner application: accounts, owned records, import and reports.

Week 3 turns the single-profile prototype into an account-scoped application.
The rule this file follows everywhere is that ownership is decided by the
query, not by the interface: a route never renders a list and then filters it,
because Task 2 NFR-S1 requires a direct request carrying someone else's
identifier to be rejected as well.
"""
import hmac
import json
import secrets
from datetime import date, timedelta
from io import BytesIO
from pathlib import Path

from flask import (Flask, abort, flash, g, redirect, render_template, request,
                   send_file, session, url_for)

from . import auth
from .auth import AuthError
from .db import connect, initialize
from .importer import ValidationError, comparison, confirm, ensure_course, prepare, valid_date
from .reports import render_pdf

KINDS = ('Assignment requirement', 'Exam scope', 'Research meeting', 'Reading / experiment', 'Teacher feedback')
STATUSES = ('Not started', 'In progress', 'Completed')
# Kinds whose subject is a taught course rather than a research project. Used
# only to preselect the container dropdown, never to decide anything on the
# student's behalf.
COURSE_KINDS = ('Assignment requirement', 'Exam scope', 'Teacher feedback')
MAX_TITLE = 200
MAX_BODY = 20000


def week_bounds(value):
    selected = valid_date(value)
    monday = selected - timedelta(days=selected.weekday())
    return monday, monday + timedelta(days=6)


def weekly_records(db, owner_id, week):
    """This account's classes and records for the week containing *week*.

    Both queries carry ``owner_id``: that predicate, not the interface, is what
    keeps one student from seeing another's records.
    """
    start, end = week_bounds(week)
    args = (owner_id, start.isoformat(), end.isoformat())
    events = [dict(x) for x in db.execute(
        """SELECT e.id, e.source_key, e.date, e.start_time, e.end_time, e.room,
                  e.teacher, e.state, c.code AS course_code, c.title AS course_title
           FROM events e JOIN courses c ON c.id = e.course_id
           WHERE e.owner_id=? AND e.date BETWEEN ? AND ?
           ORDER BY e.date, e.start_time""", args)]
    notes = [dict(x) for x in db.execute(
        """SELECT n.id, n.date, n.kind, n.title, n.body, n.status, n.event_id,
                  n.course_id, n.project_id, n.item_id, n.created_at,
                  COALESCE(c.title, p.title, i.title, n.context) AS context,
                  c.title AS course_title, p.title AS project_title
           FROM notes n
           LEFT JOIN courses c ON c.id = n.course_id
           LEFT JOIN projects p ON p.id = n.project_id
           LEFT JOIN academic_items i ON i.id = n.item_id
           WHERE n.owner_id=? AND n.date BETWEEN ? AND ?
           ORDER BY n.date, n.id""", args)]
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
    # initialize() creates a new database or upgrades a Week 1-2 one. Warnings
    # are about data that needed a judgement call, not failures; they are
    # surfaced on the next page the student sees rather than blocking startup.
    app.config['MIGRATION_WARNINGS'] = initialize(app.config['DATABASE'])

    # Ownership first: a signed-out request must land on the sign-in page rather
    # than be told its form expired. AC-01 repeats requests after logging out.
    auth.require_owner(app)

    @app.before_request
    def protect_forms():
        session.setdefault('csrf', secrets.token_hex(24))
        if request.method == 'POST':
            if not hmac.compare_digest(session['csrf'], request.form.get('csrf', '')):
                abort(400, description='This form expired. Reload the page and try again.')

    def db_connection():
        return connect(app.config['DATABASE'])

    @app.errorhandler(ValidationError)
    def validation_error(exc):
        return render_template('error.html', message=str(exc)), 400

    @app.errorhandler(AuthError)
    def auth_error(exc):
        return render_template('error.html', message=str(exc)), 400

    @app.errorhandler(413)
    def too_large(exc):
        return render_template('error.html', message='The upload is too large. Use a CSV file smaller than 1 MB.'), 413

    @app.errorhandler(400)
    @app.errorhandler(404)
    def http_error(exc):
        return render_template('error.html', message=exc.description), exc.code

    @app.context_processor
    def inject_globals():
        return {'current_username': session.get('username'),
                'migration_warnings': app.config.get('MIGRATION_WARNINGS') or []}

    @app.route('/register', methods=['GET', 'POST'])
    def register():
        if request.method == 'GET':
            return render_template('register.html', form={}, error=None)
        username = request.form.get('username', '')
        password = request.form.get('password', '')
        if password != request.form.get('confirm', ''):
            # Checked before touching the database so a typo cannot create an
            # account the student then cannot sign into.
            return render_template('register.html', form={'username': username},
                                   error='The two passwords do not match. Enter the same password twice.'), 400
        try:
            with db_connection() as db:
                user_id = auth.register(db, username, password)
        except AuthError as exc:
            # Re-render the form with the username intact: Task 2 7.2 requires
            # useful input to survive a failed validation. The password is
            # deliberately not echoed back.
            return render_template('register.html', form={'username': username}, error=str(exc)), 400
        auth.login(user_id, username.strip())
        flash('Account created. Your records are private to this account.')
        return redirect(url_for('index'))

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        # Carried in a hidden field so a successful sign-in still lands on the
        # page the student was originally trying to reach.
        next_target = request.values.get('next', '')
        if request.method == 'GET':
            return render_template('login.html', form={}, error=None, next_target=next_target)
        username = request.form.get('username', '')
        try:
            with db_connection() as db:
                user_id = auth.authenticate(db, username, request.form.get('password', ''))
        except AuthError as exc:
            return render_template('login.html', form={'username': username}, error=str(exc),
                                   next_target=next_target), 400
        auth.login(user_id, username.strip())
        # Only follow a path that stays inside this application; an absolute or
        # protocol-relative URL would turn sign-in into a redirect elsewhere.
        if next_target.startswith('/') and not next_target.startswith('//'):
            return redirect(next_target)
        return redirect(url_for('index'))

    @app.post('/logout')
    def logout():
        auth.logout()
        flash('Signed out.')
        return redirect(url_for('login'))

    @app.get('/')
    def index():
        # The prototype defaulted to 2026-09-28 to match the bundled samples.
        # A signed-in student should land on the week they are actually in; the
        # demonstration weeks are reachable from the week picker.
        week = request.args.get('week', date.today().isoformat())
        owner_id = auth.current_owner_id()
        with db_connection() as db:
            start, end, events, notes = weekly_records(db, owner_id, week)
            reports = db.execute(
                'SELECT id,title,created_at FROM reports WHERE owner_id=? AND week=? ORDER BY id DESC',
                (owner_id, start.isoformat())).fetchall()
            courses = db.execute('SELECT id,code,title FROM courses WHERE owner_id=? ORDER BY title',
                                 (owner_id,)).fetchall()
            projects = db.execute('SELECT id,title FROM projects WHERE owner_id=? ORDER BY title',
                                  (owner_id,)).fetchall()
        days = [start+timedelta(days=i) for i in range(7)]
        return render_template('index.html', start=start, end=end, events=events, notes=notes, days=days,
                               previous=start-timedelta(days=7), following=start+timedelta(days=7),
                               reports=reports, kinds=KINDS, statuses=STATUSES, course_kinds=COURSE_KINDS,
                               courses=courses, projects=projects,
                               completed=sum(x['status']=='Completed' for x in notes))

    @app.route('/import', methods=['GET', 'POST'])
    def import_file():
        if request.method == 'GET':
            return render_template('import.html')
        upload = request.files.get('timetable')
        if not upload or not upload.filename.lower().endswith('.csv'):
            raise ValidationError('Choose a CSV timetable file.')
        with db_connection() as db:
            token, _ = prepare(db, auth.current_owner_id(), upload.read())
        return redirect(url_for('preview', token=token))

    @app.get('/import/<token>')
    def preview(token):
        owner_id = auth.current_owner_id()
        with db_connection() as db:
            # Owner-scoped lookup: another account's token reads as "not found",
            # which is the same answer as a token that never existed.
            item = db.execute('SELECT * FROM previews WHERE token=? AND owner_id=?',
                              (token, owner_id)).fetchone()
            if item is None:
                abort(404)
            changes = comparison(db, owner_id, json.loads(item['rows_json']))
            revision = db.execute('SELECT timetable_revision FROM user_state WHERE owner_id=?',
                                  (owner_id,)).fetchone()[0]
        return render_template('preview.html', changes=changes, token=token, stale=revision!=item['revision'])

    @app.post('/import/<token>/confirm')
    def confirm_import(token):
        owner_id = auth.current_owner_id()
        with db_connection() as db:
            item = db.execute('SELECT rows_json FROM previews WHERE token=? AND owner_id=?',
                              (token, owner_id)).fetchone()
            if item is None:
                abort(404)
            rows = json.loads(item['rows_json'])
            # Land on the week the imported classes actually belong to rather
            # than a hardcoded demonstration date.
            week = rows[0]['date'] if rows else date.today().isoformat()
            counts = confirm(db, owner_id, token)
        flash(f"Import saved: {counts['Added']} added, {counts['Updated']} updated, {counts['Unchanged']} unchanged.")
        return redirect(url_for('index', week=week))

    @app.post('/import/<token>/cancel')
    def cancel_import(token):
        owner_id = auth.current_owner_id()
        with db_connection() as db:
            db.execute('DELETE FROM previews WHERE token=? AND owner_id=?', (token, owner_id))
        flash('Preview cancelled. The timetable has not changed.')
        return redirect(url_for('import_file'))

    def resolve_container(db, owner_id, form):
        """Return (course_id, project_id, display_name) for the note form.

        A student may pick an existing course or project, or name a new one.
        Naming a new project matters for DR-3: a research student with no
        taught timetable must not have to invent a course to use the planner.
        """
        course_choice = form.get('course_id', '').strip()
        project_choice = form.get('project_id', '').strip()
        new_course = form.get('new_course', '').strip()
        new_project = form.get('new_project', '').strip()
        existing = [x for x in (course_choice, project_choice) if x]
        if len(existing) > 1:
            raise ValidationError('Choose either a course or a research project, not both.')
        named = [x for x in (new_course, new_project) if x]
        if len(named) > 1:
            raise ValidationError('Name either a new course or a new research project, not both.')
        if existing and named:
            raise ValidationError('Choose an existing course or project, or name a new one, not both.')
        for value in named:
            if len(value) > MAX_TITLE:
                raise ValidationError(f'Use at most {MAX_TITLE} characters for a course or project name.')

        def owned(table, row_id, label):
            """Fetch one of this account's rows, or raise as if it did not exist.

            An id belonging to another account gets the same answer as a
            missing one, so the form cannot be used to probe for records.
            """
            row = db.execute(f'SELECT * FROM {table} WHERE id=? AND owner_id=?',
                             (row_id, owner_id)).fetchone()
            if row is None:
                raise ValidationError(f'The selected {label} does not exist. Choose a current one.')
            return row

        def by_title(table, title):
            return db.execute(f'SELECT id,title FROM {table} WHERE owner_id=? AND title=?',
                              (owner_id, title)).fetchone()

        def as_int(value, label):
            try:
                return int(value)
            except ValueError as exc:
                raise ValidationError(f'Choose a valid {label}.') from exc

        if new_course:
            found = by_title('courses', new_course)
            if found is None:
                # Code and title start identical; a later import carrying the
                # real course_code retitles this row rather than adding another.
                new_id = db.execute('INSERT INTO courses(owner_id,code,title) VALUES (?,?,?)',
                                    (owner_id, new_course, new_course)).lastrowid
                return new_id, None, new_course
            return found['id'], None, found['title']
        if new_project:
            found = by_title('projects', new_project)
            project_id = found['id'] if found else db.execute(
                'INSERT INTO projects(owner_id,title) VALUES (?,?)', (owner_id, new_project)).lastrowid
            return None, project_id, new_project
        if course_choice:
            course = owned('courses', as_int(course_choice, 'course'), 'course')
            return course['id'], None, course['title']
        if project_choice:
            project = owned('projects', as_int(project_choice, 'research project'), 'research project')
            return None, project['id'], project['title']
        raise ValidationError('Choose the course or research project this record belongs to.')

    @app.post('/notes')
    def add_note():
        owner_id = auth.current_owner_id()
        values = {k: request.form.get(k, '').strip()
                  for k in ('date', 'kind', 'title', 'body', 'status', 'event_id')}
        valid_date(values['date'])
        if values['kind'] not in KINDS or values['status'] not in STATUSES:
            raise ValidationError('Select a valid record type and progress status.')
        if not values['title'] or not values['body']:
            raise ValidationError('Complete the title and details fields.')
        if len(values['title']) > MAX_TITLE or len(values['body']) > MAX_BODY:
            raise ValidationError(f'Use at most {MAX_TITLE} characters for the title '
                                  f'and {MAX_BODY:,} for details.')
        with db_connection() as db:
            course_id, project_id, display = resolve_container(db, owner_id, request.form)
            event_id = None
            if values['event_id']:
                try:
                    event_id = int(values['event_id'])
                except ValueError as exc:
                    raise ValidationError('The linked class is not valid. Choose a current class.') from exc
                # The class must belong to this account as well as exist.
                row = db.execute('SELECT id FROM events WHERE id=? AND owner_id=?',
                                 (event_id, owner_id)).fetchone()
                if row is None:
                    raise ValidationError('The linked class does not exist. Choose a current class.')
            db.execute(
                """INSERT INTO notes(owner_id,course_id,project_id,item_id,event_id,date,kind,
                                     title,body,status,context)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (owner_id, course_id, project_id, None, event_id, values['date'], values['kind'],
                 values['title'], values['body'], values['status'], display))
        flash('Learning record saved.')
        return redirect(url_for('index', week=values['date']))

    @app.post('/reports')
    def export_report():
        owner_id = auth.current_owner_id()
        week = request.form.get('week', '')
        title = request.form.get('title', '').strip()
        summary = request.form.get('summary', '').strip()
        if not title or len(title) > MAX_TITLE or len(summary) > MAX_BODY:
            raise ValidationError(f'Enter a title up to {MAX_TITLE} characters '
                                    f'and a summary up to {MAX_BODY:,} characters.')
        try:
            selected = {int(x) for x in request.form.getlist('note_ids')}
        except ValueError as exc:
            raise ValidationError('Invalid record selection.') from exc
        with db_connection() as db:
            start, end, events, notes = weekly_records(db, owner_id, week)
            own = {x['id'] for x in notes}
            if not selected.issubset(own):
                # Another account's note id is answered exactly like one from a
                # different week: the export is refused without saying which.
                raise ValidationError('Only records from the selected week can be exported.')
            # Only the selected fields enter the snapshot, so an excluded record
            # is absent from the PDF's text, annotations and metadata alike
            # (NFR-S3). The snapshot stores the values as they are now; a later
            # edit to the source record must not rewrite this report (DR-7).
            snapshot = {'week': start.isoformat(), 'end': end.isoformat(), 'title': title, 'summary': summary,
                        'events': events if request.form.get('include_events') == 'yes' else [],
                        'notes': [x for x in notes if x['id'] in selected]}
            pdf = render_pdf(snapshot)
            result = db.execute('INSERT INTO reports(owner_id,week,title,snapshot_json,pdf) VALUES (?,?,?,?,?)',
                                (owner_id, start.isoformat(), title, json.dumps(snapshot, ensure_ascii=False), pdf))
            report_id = result.lastrowid
        return redirect(url_for('download_report', report_id=report_id))

    @app.get('/reports/<int:report_id>.pdf')
    def download_report(report_id):
        with db_connection() as db:
            row = auth.owned_or_404(db, 'reports', report_id, auth.current_owner_id())
        if row is None:
            # 404 rather than 403: confirming that report 42 exists would tell a
            # student that another account has saved reports (NFR-S1, AC-01).
            abort(404)
        return send_file(BytesIO(row['pdf']), mimetype='application/pdf', as_attachment=True,
                         download_name=f'weekly-report-{row["week"]}-v{report_id}.pdf')

    return app
