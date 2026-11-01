"""Local preview features: capture first, organize later; explicit time conflicts only."""
import csv, io, json, secrets, re, hashlib
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from PIL import Image, ImageOps, UnidentifiedImageError
from flask import request, session, render_template, redirect, url_for, abort, flash, jsonify, send_file
from .db import connect
from .auth import current_owner_id
from .importer import ValidationError, valid_date, prepare, FIELDS

def read_image(raw, max_bytes=10*1024*1024):
    if not raw or len(raw)>max_bytes:raise ValidationError('Upload a JPG or PNG smaller than 10 MB.')
    try:
        im=Image.open(io.BytesIO(raw))
        if im.format not in ('JPEG','PNG') or im.width*im.height>16000000:raise ValidationError('Use JPG or PNG with at most 16 million pixels.')
        im.load();return ImageOps.exif_transpose(im).convert('RGB')
    except (UnidentifiedImageError,OSError,Image.DecompressionBombError) as exc:raise ValidationError('The image could not be read.') from exc

def conflicts(c,owner,day,start,end,exclude=0):
    classes=c.execute("SELECT e.id,c.title,e.start_time,e.end_time FROM events e JOIN courses c ON c.id=e.course_id WHERE e.owner_id=? AND e.date=? AND e.state!='cancelled' AND e.start_time<? AND e.end_time>?",(owner,day,end,start)).fetchall()
    blocks=c.execute('SELECT id,title,start_time,end_time FROM time_blocks WHERE owner_id=? AND date=? AND id!=? AND start_time<? AND end_time>?',(owner,day,exclude,end,start)).fetchall()
    return [dict(x,kind='Class') for x in classes]+[dict(x,kind='Plan') for x in blocks]

def install(app):
    app.config['MAX_CONTENT_LENGTH']=11*1024*1024
    def db():return connect(app.config['DATABASE'])
    with db() as c:
        c.execute('CREATE TABLE IF NOT EXISTS user_avatars(owner_id INTEGER PRIMARY KEY REFERENCES users(id),png BLOB NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS quick_receipts(owner_id INTEGER NOT NULL,token TEXT NOT NULL,note_id INTEGER NOT NULL REFERENCES notes(id),PRIMARY KEY(owner_id,token))')
        c.execute('CREATE TABLE IF NOT EXISTS study_tasks(id INTEGER PRIMARY KEY,owner_id INTEGER NOT NULL REFERENCES users(id),title TEXT NOT NULL,due TEXT,minutes INTEGER NOT NULL DEFAULT 30,priority TEXT NOT NULL DEFAULT "Normal",done INTEGER NOT NULL DEFAULT 0,note_id INTEGER REFERENCES notes(id),parent_id INTEGER REFERENCES study_tasks(id))')
        c.execute('CREATE TABLE IF NOT EXISTS time_blocks(id INTEGER PRIMARY KEY,owner_id INTEGER NOT NULL REFERENCES users(id),task_id INTEGER REFERENCES study_tasks(id),title TEXT NOT NULL,date TEXT NOT NULL,start_time TEXT NOT NULL,end_time TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 0)')
        c.execute('CREATE TABLE IF NOT EXISTS screenshot_drafts(token TEXT PRIMARY KEY,owner_id INTEGER NOT NULL,rows_json TEXT NOT NULL,raw_text TEXT NOT NULL)')
    def owned(c,table,id):
        row=c.execute(f'SELECT * FROM {table} WHERE id=? AND owner_id=?',(id,current_owner_id())).fetchone()
        if row is None:abort(404)
        return dict(row)
    @app.context_processor
    def tools_context():
        blocks=[];has_avatar=False
        if current_owner_id():
            with db() as c:
                has_avatar=c.execute('SELECT 1 FROM user_avatars WHERE owner_id=?',(current_owner_id(),)).fetchone() is not None
                if request.endpoint=='index':
                    d=valid_date(request.args.get('week',date.today().isoformat()));start=d-timedelta(days=d.weekday())
                    blocks=c.execute('SELECT * FROM time_blocks WHERE owner_id=? AND date BETWEEN ? AND ? ORDER BY start_time',(current_owner_id(),start.isoformat(),(start+timedelta(days=6)).isoformat())).fetchall()
        return dict(quick_token=secrets.token_hex(24),has_avatar=has_avatar,plan_blocks=blocks)

    @app.post('/quick-note')
    def quick_note():
        body=request.form.get('body','').strip();token=request.form.get('token','')
        if not body or len(body)>20000 or not re.fullmatch('[a-f0-9]{48}',token):return jsonify(error='Write a note of 1–20000 characters.'),400
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            old=c.execute('SELECT note_id FROM quick_receipts WHERE owner_id=? AND token=?',(current_owner_id(),token)).fetchone()
            if old:return jsonify(url=url_for('note_detail',id=old['note_id']),token=secrets.token_hex(24))
            course_id=event_id=project_id=None;context='Quick inbox'
            if request.form.get('event_id'):
                event=owned(c,'events',request.form['event_id']);event_id=event['id'];course_id=event['course_id'];context=owned(c,'courses',course_id)['title']
            else:
                row=c.execute("SELECT id FROM projects WHERE owner_id=? AND title='Quick inbox'",(current_owner_id(),)).fetchone()
                project_id=row['id'] if row else c.execute("INSERT INTO projects(owner_id,title) VALUES (?,'Quick inbox')",(current_owner_id(),)).lastrowid
            today=datetime.now(ZoneInfo('Asia/Macau')).date().isoformat()
            n=c.execute('INSERT INTO notes(owner_id,course_id,project_id,event_id,date,kind,title,body,status,context) VALUES (?,?,?,?,?,?,?,?,?,?)',(current_owner_id(),course_id,project_id,event_id,today,'Quick note',body.splitlines()[0][:80],body,'Not started',context)).lastrowid
            c.execute('INSERT INTO quick_receipts VALUES (?,?,?)',(current_owner_id(),token,n))
        return jsonify(url=url_for('note_detail',id=n),token=secrets.token_hex(24))

    @app.route('/notes/<int:id>/organize',methods=['GET','POST'])
    def organize_note(id):
        with db() as c:
            note=owned(c,'notes',id)
            if request.method=='POST':
                course=request.form.get('course');project=request.form.get('project')
                if bool(course)==bool(project):raise ValidationError('Choose one course or one project.')
                target=owned(c,'courses' if course else 'projects',course or project)
                # Filing changes also preserve the prior note snapshot.
                if not c.execute('SELECT 1 FROM note_revisions WHERE note_id=?',(id,)).fetchone():
                    c.execute('INSERT INTO note_revisions(owner_id,note_id,snapshot,reason) VALUES (?,?,?,?)',(current_owner_id(),id,json.dumps(note,ensure_ascii=False),'Original record'))
                event_id=note['event_id'] if course and str(note['course_id'])==course else None
                c.execute('UPDATE notes SET course_id=?,project_id=?,event_id=?,context=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',(course or None,project or None,event_id,target['title'],id))
                c.execute('INSERT INTO note_revisions(owner_id,note_id,snapshot,reason) VALUES (?,?,?,?)',(current_owner_id(),id,json.dumps(owned(c,'notes',id),ensure_ascii=False),'Filed note'))
                return redirect(url_for('note_detail',id=id))
            courses=c.execute('SELECT * FROM courses WHERE owner_id=?',(current_owner_id(),)).fetchall();projects=c.execute('SELECT * FROM projects WHERE owner_id=?',(current_owner_id(),)).fetchall()
        return render_template('organize.html',note=note,courses=courses,projects=projects)

    @app.post('/avatar')
    def upload_avatar():
        with db() as c:
            if request.form.get('reset')=='yes':c.execute('DELETE FROM user_avatars WHERE owner_id=?',(current_owner_id(),))
            else:
                file=request.files.get('avatar_file')
                if not file:raise ValidationError('Choose an image.')
                im=ImageOps.fit(read_image(file.read()),(256,256));out=io.BytesIO();im.save(out,'PNG')
                c.execute('INSERT INTO user_avatars VALUES (?,?) ON CONFLICT(owner_id) DO UPDATE SET png=excluded.png',(current_owner_id(),out.getvalue()))
        return redirect(url_for('settings'))
    @app.get('/avatar.png')
    def avatar_file():
        with db() as c:row=c.execute('SELECT png FROM user_avatars WHERE owner_id=?',(current_owner_id(),)).fetchone()
        if row is None:abort(404)
        response=send_file(io.BytesIO(row['png']),mimetype='image/png');response.headers['Cache-Control']='no-store';return response

    @app.route('/tasks',methods=['GET','POST'])
    def tasks():
        error=None;source=None
        with db() as c:
            if request.args.get('note'):source=owned(c,'notes',request.args['note'])
            if request.method=='POST':
                try:
                    title=request.form.get('title','').strip();due=request.form.get('due','');minutes=int(request.form.get('minutes','30'));priority=request.form.get('priority','Normal');parent=request.form.get('parent');note=request.form.get('note')
                    if not title or len(title)>200 or not 1<=minutes<=100000 or priority not in ('Low','Normal','High'):raise ValidationError('Check the task title, duration and priority.')
                    if due:valid_date(due)
                    if parent:owned(c,'study_tasks',parent)
                    if note:owned(c,'notes',note)
                    c.execute('INSERT INTO study_tasks(owner_id,title,due,minutes,priority,parent_id,note_id) VALUES (?,?,?,?,?,?,?)',(current_owner_id(),title,due or None,minutes,priority,parent or None,note or None))
                    return redirect(url_for('tasks'))
                except ValueError as exc:error=str(exc)
            tasks=c.execute('SELECT * FROM study_tasks WHERE owner_id=? ORDER BY done,COALESCE(due,"9999"),id',(current_owner_id(),)).fetchall()
        return render_template('tasks.html',tasks=tasks,error=error,source=source,form=request.form),400 if error else 200
    @app.post('/tasks/<int:id>/status')
    def task_status(id):
        with db() as c:
            owned(c,'study_tasks',id)
            c.execute('UPDATE study_tasks SET done=? WHERE id=?',(int(request.form.get('done')=='yes'),id))
        return redirect(url_for('tasks'))

    @app.route('/schedule',methods=['GET','POST'])
    @app.route('/schedule/<int:id>',methods=['GET','POST'])
    def schedule(id=None):
        error=None;clashes=[];form=request.form
        with db() as c:
            old=owned(c,'time_blocks',id) if id else None
            if request.method=='POST':
                try:
                    c.execute('BEGIN IMMEDIATE')
                    if old and str(owned(c,'time_blocks',id)['version'])!=request.form.get('version'):raise ValidationError('This plan changed. Reload before saving.')
                    title=request.form.get('title','').strip();day=request.form.get('date','');start=request.form.get('start_time','');end=request.form.get('end_time','');task=request.form.get('task')
                    valid_date(day)
                    if not title or len(title)>200 or not all(re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',x) for x in (start,end)) or start>=end:raise ValidationError('Enter a title and a valid same-day time range.')
                    if task:owned(c,'study_tasks',task)
                    clashes=conflicts(c,current_owner_id(),day,start,end,id or 0)
                    if clashes and request.form.get('allow_conflict')!='yes':raise ValidationError('These times overlap. Adjust the time or explicitly keep both.')
                    if id:c.execute('UPDATE time_blocks SET title=?,task_id=?,date=?,start_time=?,end_time=?,version=version+1 WHERE id=?',(title,task or None,day,start,end,id))
                    else:c.execute('INSERT INTO time_blocks(owner_id,title,task_id,date,start_time,end_time) VALUES (?,?,?,?,?,?)',(current_owner_id(),title,task or None,day,start,end))
                    c.commit();return redirect(url_for('index',week=day))
                except ValueError as exc:c.rollback();error=str(exc)
            if request.method=='GET':form=old or dict(task=request.args.get('task',''),date=request.args.get('date',date.today().isoformat()))
            if request.method=='GET' and not id and form.get('task'):
                selected=owned(c,'study_tasks',form['task']);form['title']=selected['title']
            tasks=c.execute('SELECT * FROM study_tasks WHERE owner_id=? ORDER BY done,id',(current_owner_id(),)).fetchall()
            blocks=[dict(x) for x in c.execute('SELECT * FROM time_blocks WHERE owner_id=? ORDER BY date,start_time',(current_owner_id(),))]
            for b in blocks:b['conflicts']=conflicts(c,current_owner_id(),b['date'],b['start_time'],b['end_time'],b['id'])
        return render_template('schedule.html',form=form,old=old,error=error,clashes=clashes,tasks=tasks,blocks=blocks),400 if error else 200

    @app.route('/screenshot',methods=['GET','POST'])
    def screenshot_import():
        error=None
        if request.method=='POST':
            try:
                monday=valid_date(request.form.get('monday',''))
                if monday.weekday()!=0:raise ValidationError('Select the Monday shown in the screenshot.')
                file=request.files.get('image')
                if not file:raise ValidationError('Choose an image.')
                image=read_image(file.read())
                from .screenshot_ocr import recognize
                rows,raw=recognize(image,monday)
                token=secrets.token_hex(24)
                with db() as c:c.execute('INSERT INTO screenshot_drafts VALUES (?,?,?,?)',(token,current_owner_id(),json.dumps(rows,ensure_ascii=False),raw))
                return redirect(url_for('screenshot_review',token=token))
            except (ValueError,RuntimeError) as exc:error=str(exc)
        return render_template('screenshot.html',error=error),400 if error else 200
    @app.route('/screenshot/<token>',methods=['GET','POST'])
    def screenshot_review(token):
        error=None
        with db() as c:
            draft=c.execute('SELECT * FROM screenshot_drafts WHERE token=? AND owner_id=?',(token,current_owner_id())).fetchone()
            if draft is None:abort(404)
            rows=json.loads(draft['rows_json'])
            if request.method=='POST':
                try:
                    weeks=int(request.form.get('weeks','1'))
                    if not 1<=weeks<=52:raise ValidationError('Choose between 1 and 52 weeks.')
                    corrected=[]
                    for i,row in enumerate(rows):
                        edited={k:request.form.get(f'{i}_{k}',row.get(k,'')) for k in FIELDS}
                        rows[i]=dict(edited,approx_time=row.get('approx_time',False))
                        if request.form.get(f'{i}_include')!='yes':continue
                        for w in range(0,weeks,2 if request.form.get('cadence')=='alternate' else 1):
                            n=dict(edited);n['date']=(valid_date(edited['date'])+timedelta(weeks=w)).isoformat();n['source_key']=edited['source_key']+'-w'+str(w);corrected.append(n)
                    out=io.StringIO();writer=csv.DictWriter(out,fieldnames=FIELDS);writer.writeheader();writer.writerows(corrected)
                    preview,_=prepare(c,current_owner_id(),out.getvalue().encode())
                    return redirect(url_for('preview',token=preview))
                except ValueError as exc:error=str(exc)
        return render_template('screenshot_review.html',rows=rows,raw=draft['raw_text'],error=error,fields=FIELDS),400 if error else 200
