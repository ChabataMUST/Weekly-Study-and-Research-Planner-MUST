"""Week 4: searchable records, immutable revisions, manual timetable and preferences."""
import csv, io, json, secrets
from datetime import timedelta, date
from flask import request, session, render_template, redirect, url_for, abort, flash
from werkzeug.security import check_password_hash, generate_password_hash
from .db import connect
from .auth import current_owner_id, validate_password, AuthError
from .importer import prepare, confirm, valid_date, ValidationError, FIELDS, parse_csv

AVATARS = ('🌱','📚','🐱','🌟','🦉','🚀')
def install(app):
    def db(): return connect(app.config['DATABASE'])
    # Additive tables: retain the Week 3 schema and all existing records.
    with db() as c:
        c.execute('CREATE TABLE IF NOT EXISTS preferences (owner_id INTEGER PRIMARY KEY REFERENCES users(id), language TEXT NOT NULL DEFAULT "en", avatar TEXT NOT NULL DEFAULT "🌱")')
        c.execute('CREATE TABLE IF NOT EXISTS note_revisions (id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL REFERENCES users(id), note_id INTEGER NOT NULL REFERENCES notes(id), snapshot TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_note_revisions ON note_revisions(owner_id,note_id,id)')
    from .i18n import translate
    @app.context_processor
    def preferences():
        lang=session.get('language') or request.accept_languages.best_match(['en','zh-CN','zh-TW']) or 'en';avatar='🌱'
        if current_owner_id():
            with db() as c: p=c.execute('SELECT * FROM preferences WHERE owner_id=?',(current_owner_id(),)).fetchone()
            if p:lang=p['language'];avatar=p['avatar']
        return dict(t=lambda text:translate(text,lang), language=lang, avatar=avatar)

    def owned(c,table,id):
        row=c.execute(f'SELECT * FROM {table} WHERE id=? AND owner_id=?',(id,current_owner_id())).fetchone()
        if row is None:abort(404)
        return dict(row)

    @app.route('/settings',methods=['GET','POST'])
    def settings():
        error=None
        if request.method=='POST':
            try:
                with db() as c:
                    if request.form.get('action')=='password':
                        user=c.execute('SELECT * FROM users WHERE id=?',(current_owner_id(),)).fetchone()
                        if not check_password_hash(user['password_hash'],request.form.get('current_password','')):raise ValidationError('Current password is incorrect.')
                        pwd=validate_password(request.form.get('password',''))
                        if pwd!=request.form.get('confirm'):raise ValidationError('The passwords do not match.')
                        c.execute('UPDATE users SET password_hash=? WHERE id=?',(generate_password_hash(pwd),current_owner_id()))
                    else:
                        lang=request.form.get('language');avatar=request.form.get('avatar')
                        if lang not in ('en','zh-CN','zh-TW') or avatar not in AVATARS:raise ValidationError('Choose a valid preference.')
                        c.execute('INSERT INTO preferences(owner_id,language,avatar) VALUES (?,?,?) ON CONFLICT(owner_id) DO UPDATE SET language=excluded.language,avatar=excluded.avatar',(current_owner_id(),lang,avatar))
                flash('Settings saved.');return redirect(url_for('settings'))
            except (ValidationError,AuthError) as exc:error=str(exc)
        return render_template('settings.html',avatars=AVATARS,error=error),400 if error else 200

    @app.get('/help')
    def help_page():return render_template('help.html')

    @app.get('/search')
    def search():
        term=request.args.get('q','').strip()[:200];course=request.args.get('course','');project=request.args.get('project','')
        args=[current_owner_id()];where=['n.owner_id=?']
        if term:
            # instr treats %, _ and quotes literally; search includes earlier versions.
            where.append('(instr(lower(n.title||char(10)||n.body),lower(?))>0 OR EXISTS (SELECT 1 FROM note_revisions r WHERE r.note_id=n.id AND r.owner_id=n.owner_id AND instr(lower(r.snapshot),lower(?))>0))');args.extend([term,term])
        for key,value in [('course_id',course),('project_id',project)]:
            if value:where.append('n.'+key+'=?');args.append(value)
        with db() as c:
            rows=c.execute('SELECT n.*,COALESCE(c.title,p.title,n.context) AS label FROM notes n LEFT JOIN courses c ON c.id=n.course_id LEFT JOIN projects p ON p.id=n.project_id WHERE '+' AND '.join(where)+' ORDER BY n.date DESC,n.id DESC LIMIT 201',args).fetchall()
            courses=c.execute('SELECT * FROM courses WHERE owner_id=? ORDER BY title',(current_owner_id(),)).fetchall()
            projects=c.execute('SELECT * FROM projects WHERE owner_id=? ORDER BY title',(current_owner_id(),)).fetchall()
        return render_template('search.html',rows=rows[:200],more=len(rows)>200,courses=courses,projects=projects,query=term,course=course,project=project)

    @app.route('/notes/<int:id>',methods=['GET','POST'])
    def note_detail(id):
        error=None
        with db() as c:
            note=owned(c,'notes',id)
            revision=c.execute('SELECT COALESCE(MAX(id),0) FROM note_revisions WHERE note_id=? AND owner_id=?',(id,current_owner_id())).fetchone()[0]
            if request.method=='POST':
                try:
                    c.execute('BEGIN IMMEDIATE')
                    latest=c.execute('SELECT COALESCE(MAX(id),0) FROM note_revisions WHERE note_id=? AND owner_id=?',(id,current_owner_id())).fetchone()[0]
                    if str(latest)!=request.form.get('revision'):raise ValidationError('This record changed in another tab. Reload before saving.')
                    values={k:request.form.get(k,'').strip() for k in ('title','body','date','status','reason')}
                    valid_date(values['date'])
                    if not values['title'] or not values['body'] or not values['reason'] or len(values['title'])>200 or len(values['body'])>20000 or len(values['reason'])>500:raise ValidationError('Complete the title, details and change reason within the limits.')
                    if values['status'] not in ('Not started','In progress','Completed'):raise ValidationError('Select a valid progress status.')
                    # Capture the initial version before the first edit, then append each revision.
                    if not latest:c.execute('INSERT INTO note_revisions(owner_id,note_id,snapshot,reason) VALUES (?,?,?,?)',(current_owner_id(),id,json.dumps(note,ensure_ascii=False),'Original record'))
                    c.execute('UPDATE notes SET title=?,body=?,date=?,status=?,updated_at=CURRENT_TIMESTAMP WHERE id=? AND owner_id=?',(values['title'],values['body'],values['date'],values['status'],id,current_owner_id()))
                    updated=owned(c,'notes',id)
                    c.execute('INSERT INTO note_revisions(owner_id,note_id,snapshot,reason) VALUES (?,?,?,?)',(current_owner_id(),id,json.dumps(updated,ensure_ascii=False),values['reason']))
                    c.commit();return redirect(url_for('note_detail',id=id,**{k:request.args[k] for k in ('via','q','course','project') if k in request.args}))
                except ValidationError as exc:c.rollback();error=str(exc)
            versions=[dict(r,snapshot=json.loads(r['snapshot'])) for r in c.execute('SELECT * FROM note_revisions WHERE note_id=? AND owner_id=? ORDER BY id DESC',(id,current_owner_id()))]
        return render_template('note_detail.html',note=note,versions=versions,revision=revision,error=error,form=request.form if error else note),400 if error else 200

    def csv_bytes(rows):
        f=io.StringIO();w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerows(rows);return f.getvalue().encode('utf-8')

    @app.route('/courses/new',methods=['GET','POST'])
    def manual_course():
        error=None
        if request.method=='POST':
            try:
                start=valid_date(request.form.get('date',''));weeks=int(request.form.get('weeks','1'))
                if not 1<=weeks<=52:raise ValidationError('Choose between 1 and 52 weeks.')
                weekdays=sorted({int(x) for x in request.form.getlist('weekdays')})
                if not weekdays or any(x<0 or x>6 for x in weekdays):raise ValidationError('Choose at least one weekday.')
                until=valid_date(request.form['until']) if request.form.get('until') else start+timedelta(weeks=weeks)-timedelta(days=1)
                if until<start or until>start+timedelta(weeks=52):raise ValidationError('Use an end date within 52 weeks of the start.')
                rows=[];series=request.form.get('series','')
                if not series or len(series)>80 or not all(ch.isalnum() or ch in '-_' for ch in series):raise ValidationError('Invalid timetable form. Reload the page.')
                day=start
                while day<=until:
                    if day.weekday() in weekdays:
                        row={k:request.form.get(k,'').strip() for k in FIELDS};row.update(source_key='manual-'+series+'-'+day.isoformat(),date=day.isoformat());rows.append(row)
                    day+=timedelta(days=1)
                with db() as c:token,_=prepare(c,current_owner_id(),csv_bytes(rows))
                return redirect(url_for('preview',token=token))
            except (ValueError,ValidationError) as exc:error=str(exc)
        return render_template('course_form.html',error=error,form=request.form,series=request.form.get('series') or secrets.token_hex(12)),400 if error else 200

    @app.route('/classes/<int:id>',methods=['GET','POST'])
    def class_detail(id):
        error=None
        with db() as c:
            event=owned(c,'events',id);course=owned(c,'courses',event['course_id'])
            rev=c.execute('SELECT timetable_revision FROM user_state WHERE owner_id=?',(current_owner_id(),)).fetchone()[0]
            if request.method=='POST':
                try:
                    c.execute('BEGIN IMMEDIATE')
                    current=c.execute('SELECT timetable_revision FROM user_state WHERE owner_id=?',(current_owner_id(),)).fetchone()[0]
                    if request.form.get('revision')!=str(current):raise ValidationError('The timetable changed. Reload before saving.')
                    old=dict(event,course_code=course['code'],course_title=course['title'])
                    row={k:request.form.get(k,old.get(k,'')) for k in FIELDS};row['source_key']=event['source_key'];row['course_code']=course['code']
                    row=parse_csv(csv_bytes([row]))[0]
                    state=request.form.get('state','scheduled')
                    if state not in ('scheduled','cancelled'):raise ValidationError('Select a valid class state.')
                    c.execute('UPDATE courses SET title=? WHERE id=? AND owner_id=?',(row['course_title'],course['id'],current_owner_id()))
                    c.execute('UPDATE events SET date=?,start_time=?,end_time=?,room=?,teacher=?,state=? WHERE id=? AND owner_id=?',(row['date'],row['start_time'],row['end_time'],row['room'],row['teacher'],state,id,current_owner_id()))
                    c.execute("INSERT INTO event_changes(owner_id,event_id,change_state,previous_json,current_json) VALUES (?,?,'Updated',?,?)",(current_owner_id(),id,json.dumps(old,ensure_ascii=False),json.dumps(dict(row,state=state),ensure_ascii=False)))
                    c.execute('UPDATE user_state SET timetable_revision=timetable_revision+1 WHERE owner_id=?',(current_owner_id(),));c.commit()
                    return redirect(url_for('class_detail',id=id,week=request.args.get('week',event['date'])))
                except ValidationError as exc:c.rollback();error=str(exc)
            notes=c.execute('SELECT * FROM notes WHERE owner_id=? AND (course_id=? OR event_id=?) ORDER BY date DESC',(current_owner_id(),course['id'],id)).fetchall()
            history=[dict(r,previous=json.loads(r['previous_json']),current=json.loads(r['current_json'])) for r in c.execute('SELECT * FROM event_changes WHERE owner_id=? AND event_id=? ORDER BY id DESC',(current_owner_id(),id))]
        return render_template('class_detail.html',event=event,course=course,notes=notes,history=history,revision=rev,error=error,form=request.form if error else dict(event,course_title=course['title'])),400 if error else 200
