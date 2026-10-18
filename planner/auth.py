"""Account registration, sign-in and ownership enforcement.

Task 2 REQ-1.1 requires each student's records to be restricted to that
student. NFR-S1 adds the sharper condition: hiding another student's record
from a menu is not enough, a direct request carrying its identifier must still
be rejected. Every route that touches a record therefore passes the session
owner through to the query layer rather than filtering afterwards.

Passwords are hashed with Werkzeug's default (scrypt in Flask 3.1), which
satisfies NFR-S2's "appropriate password-hashing mechanism" without adding a
dependency that could differ between team members' machines.
"""
import re
import sqlite3

from flask import g, session
from werkzeug.security import check_password_hash, generate_password_hash

from .db import connect

MIN_USERNAME = 3
MAX_USERNAME = 40
MIN_PASSWORD = 8
MAX_PASSWORD = 200
# The reserved account created by the v1->v3 migration. Its password hash is
# '!', which is not a valid hash, so it can never sign in.
LEGACY_USERNAME = '(legacy)'

_USERNAME_RE = re.compile(r'^[A-Za-z0-9._-]+$')


class AuthError(ValueError):
    """A sign-in or registration problem that should be shown near the form."""


def validate_username(value):
    username = (value or '').strip()
    if not username:
        raise AuthError('Enter a username.')
    if len(username) < MIN_USERNAME or len(username) > MAX_USERNAME:
        raise AuthError(f'Use a username of {MIN_USERNAME} to {MAX_USERNAME} characters.')
    if not _USERNAME_RE.fullmatch(username):
        raise AuthError('Use letters, digits, dot, underscore or hyphen only.')
    if username.lower() == LEGACY_USERNAME:
        raise AuthError('That username is reserved.')
    return username


def validate_password(value):
    password = value or ''
    if len(password) < MIN_PASSWORD:
        raise AuthError(f'Use a password of at least {MIN_PASSWORD} characters.')
    if len(password) > MAX_PASSWORD:
        raise AuthError(f'Use a password of at most {MAX_PASSWORD} characters.')
    return password


def _find_user(db, username):
    # COLLATE NOCASE on the column makes the lookup case-insensitive, so
    # 'Wang' and 'wang' cannot become two accounts holding separate records.
    return db.execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()


def register(db, username, password):
    """Create an account and return its id.

    The first account registered on a migrated database adopts the records
    left behind by the single-profile prototype, then the reserved row goes.
    """
    username = validate_username(username)
    password = validate_password(password)
    if _find_user(db, username) is not None:
        # Deliberately vague: confirming that a username exists would let anyone
        # enumerate registered accounts (Task 2 6.1.9).
        raise AuthError('That username is already taken. Choose another, or sign in.')
    try:
        new_id = db.execute('INSERT INTO users(username,password_hash) VALUES (?,?)',
                            (username, generate_password_hash(password))).lastrowid
    except sqlite3.IntegrityError as exc:
        # Two simultaneous registrations of the same name: the UNIQUE index is
        # the real guard, the SELECT above is only for a friendlier message.
        raise AuthError('That username is already taken. Choose another, or sign in.') from exc
    db.execute('INSERT INTO user_state(owner_id,timetable_revision) VALUES (?,0)', (new_id,))
    _adopt_legacy(db, new_id)
    db.commit()
    return new_id


def _adopt_legacy(db, new_id):
    """Move prototype-era records to the first real account."""
    legacy = db.execute('SELECT id FROM users WHERE username=?', (LEGACY_USERNAME,)).fetchone()
    if legacy is None:
        return False
    owner = legacy['id']
    for table in ('events', 'notes', 'reports', 'import_batches', 'event_changes',
                  'courses', 'projects', 'academic_items'):
        db.execute(f'UPDATE {table} SET owner_id=? WHERE owner_id=?', (new_id, owner))
    db.execute('UPDATE OR IGNORE user_state SET timetable_revision='
               '(SELECT timetable_revision FROM user_state WHERE owner_id=?) WHERE owner_id=?',
               (owner, new_id))
    db.execute('DELETE FROM user_state WHERE owner_id=?', (owner,))
    db.execute('DELETE FROM users WHERE id=?', (owner,))
    return True


def authenticate(db, username, password):
    """Return the account id on success, or raise AuthError.

    The error message does not distinguish an unknown username from a wrong
    password, and no private data is returned either way.
    """
    username = (username or '').strip()
    password = password or ''
    user = _find_user(db, username) if username else None
    if user is None or user['username'] == LEGACY_USERNAME:
        # Hash a throwaway value so a missing account takes a similar amount of
        # time to a wrong password; timing would otherwise reveal which
        # usernames exist.
        check_password_hash(generate_password_hash('timing-equaliser'), password)
        raise AuthError('The username or password is incorrect.')
    if not check_password_hash(user['password_hash'], password):
        raise AuthError('The username or password is incorrect.')
    return user['id']


def login(user_id, username):
    session.clear()
    session['user_id'] = user_id
    session['username'] = username
    session.permanent = False


def logout():
    session.clear()
    g.pop('owner_id', None)


def current_owner_id():
    """The signed-in account id, or None. Cached per request in ``g``."""
    if 'owner_id' not in g:
        user_id = session.get('user_id')
        if user_id is None:
            g.owner_id = None
        else:
            db = connect(session_db_path())
            try:
                row = db.execute('SELECT id FROM users WHERE id=?', (user_id,)).fetchone()
                # A signed-in session whose account no longer exists must not be
                # trusted; treat it as signed out rather than erroring.
                g.owner_id = row['id'] if row is not None else None
            finally:
                db.close()
    return g.owner_id


def require_owner(app):
    """Install the before-request guard that populates ``g.owner_id``.

    Using the request lifecycle rather than a per-route decorator means a new
    route cannot forget the check: an unowned request is rejected by default
    and public paths are listed explicitly.
    """
    from flask import redirect, request, url_for

    public_endpoints = {'login', 'register', 'static'}

    def safe_next():
        """This request's path and query, or None when there is no query.

        Built by hand because ``request.full_path`` always appends a '?', which
        would land the student on '/?' after signing in.
        """
        query = request.query_string.decode()
        return f'{request.path}?{query}' if query else request.path

    @app.before_request
    def load_owner():
        g.db_path = app.config.get('DATABASE', '')
        if request.endpoint in public_endpoints:
            return None
        owner = current_owner_id()
        if owner is None:
            # A signed-out request is answered with a redirect to sign-in rather
            # than a form error, so the student can return to where they were.
            return redirect(url_for('login', next=safe_next()))
        g.owner_id = owner
        return None


def session_db_path():
    return g.get('db_path') or ''


def owned_or_404(db, table, row_id, owner_id):
    """Fetch a row and confirm it belongs to *owner_id*.

    Returns None when the row is missing **or** belongs to someone else, so the
    caller answers 404 either way. Telling a student that record 42 exists but
    is not theirs would leak the existence of another account's data.
    """
    return db.execute(f'SELECT * FROM {table} WHERE id=? AND owner_id=?',
                      (row_id, owner_id)).fetchone()
