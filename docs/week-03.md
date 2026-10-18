# Week 3: account ownership and course/project records

Led by WangYule. The goal was the Week 3 row of the [ten-week plan](week-01-02.md): add accounts, ownership checks and separate course/assignment records. This is the foundation Week 4 revisions and Week 6 resource retrieval hang from, so it was done before either.

All 33 automated tests pass and an end-to-end check on a real server covers the full workflow. See [validation.md](validation.md).

## What changed and why

The Week 1–2 build was a single local profile. Four things in it could not survive more than one user, and each is now fixed:

| Problem in the prototype | Why it mattered | Week 3 change |
| --- | --- | --- |
| `events.source_key` was the global primary key | Two accounts importing the same CSV would collide, and the key cannot be silently prefixed without breaking the "keep the same key when you correct a class" contract | `events` gained a surrogate `id`; `source_key` is now `UNIQUE(owner_id, source_key)` |
| `/reports/<id>.pdf` had no ownership check | `report_id` is a sequential integer, so editing the number in the URL downloaded another account's report — exactly the case AC-01 and NFR-S1 test | Every record query now carries `owner_id`; a foreign id returns 404, not 403, so existence is not leaked |
| `meta.timetable_revision` was one global counter | One account's import invalidated another's pending preview, which both broke imports and leaked that someone else was importing | Moved to per-account `user_state.timetable_revision` |
| `notes.context` was free text | No assignment page, no reliable course filter for search, and no stable parent for Week 4 revisions | Real `courses`, `projects` and `academic_items` entities; a note points at one of them |

## Decisions worth knowing before Week 4

These were judgement calls. If a later week disagrees, change them deliberately rather than by accident.

1. **The first registered account adopts migrated data.** A v1 database is migrated to a reserved `(legacy)` account whose password hash is `!`, so it can never sign in. The first real registration moves every legacy record to itself and deletes the reserved row. This keeps `owner_id NOT NULL` without building a "claim old data" screen for what is still a one-machine application. Tested by `test_first_registration_adopts_legacy_data`.

2. **`context` was mapped to a course or project by the note's `kind`.** The kind list is a fixed in-program enumeration, not user text, so the inference is reliable: `Assignment requirement`, `Exam scope` and `Teacher feedback` became courses; `Research meeting` and `Reading / experiment` became projects. This is one-way — after migration the original free text is kept in `notes.context` for reference but is no longer the source of truth.

3. **Timetable change history was built now, its interface is Week 4.** Task 2 6.2.8 requires storing previous and new values with a confirmation time, which is part of REQ-1.3 (Must). The `event_changes` table and its writes are in Week 3 so the `events` rebuild happened once; there is no screen for it yet.

4. **`events.state` is excluded from import comparison.** A class the student cancelled stays cancelled when the same file is reimported, and reimport does not report it as a change. Cancelling a class from the interface is not built yet — the column and its preservation are; Week 4 adds the control.

5. **`course_title` is no longer duplicated on each occurrence.** `events` holds `course_id` and joins to `courses` for display. Retitling a course updates it everywhere. Already-saved report snapshots store the title as text at export time and are unaffected, which is the intended behaviour — a saved report reproduces what was chosen then (DR-7).

6. **Homepage defaults to the current week**, not the hardcoded 2026-09-28 that matched the bundled samples. The demonstration weeks are reached through the week picker or `?week=`.

## Files touched

| File | Change |
| --- | --- |
| `planner/db.py` | New schema (v3), versioned migration framework, `_migrate_v1_to_v3`, backup and row-count verification |
| `planner/auth.py` | **New.** Registration, sign-in, session owner, `require_owner` guard, `owned_or_404`, legacy adoption |
| `planner/__init__.py` | Ownership on all 21 record queries, login/register/logout routes, course/project resolution on the note form, current-week default |
| `planner/importer.py` | `prepare`/`confirm`/`comparison` take `owner_id`; per-account revision; writes `event_changes`; `ensure_course`; new check for one code with two titles |
| `planner/reports.py` | Marks a cancelled class in the PDF |
| `planner/templates/*` | `login.html`, `register.html` new; `base.html` shows the signed-in user and sign-out; `index.html` note form uses course/project selectors |
| `planner/static/style.css` | Styles for the auth pages, sign-out control, migration notice and cancelled-class marker |
| `scripts/seed_demo.py`, `scripts/make_sample_report.py` | Adapted to create and use a demo account |
| `tests/test_milestone.py` | 20 checks preserved, 13 added |

## How to run the Week 3 build

Fresh start: `setup.cmd` then `start.cmd`, open http://127.0.0.1:5000, create an account. For sample data instead, run `scripts\seed_demo.py` before starting and sign in as `demo` / `demo-password`.

Migrating an existing Weeks 1–2 database: just start the application. It detects version 1, writes `instance/planner.sqlite3.pre-v3.bak`, migrates in one transaction, and prints any warnings on the next page. If you want to watch it, `python -c "from planner.db import detect_version, initialize; ..."` against a copy is the safe way.

Tests: `.venv\Scripts\python.exe -m unittest discover -s tests -v` — expect 33 passed.

## Not done in Week 3 (deliberate)

- **Requirement revision history and cross-week retrieval** — Week 4. `academic_items` exists and is empty until then.
- **A UI to cancel a class** — the `state` column and its preservation exist; the control is Week 4.
- **Report draft persistence** — REQ-1.13 wants an editable draft and NFR-A4 wants entered text kept after a failed save; today a failed export still loses the draft. Week 7.
- **Resource upload and retrieval** — Week 6. Note that `MAX_CONTENT_LENGTH` is a global 1 MB (the CSV guard); NFR-C3 wants 10 MB uploads, which must be limited per-route rather than by raising the global value.
- **Tasks, subtasks, prerequisites** — Week 5.
- **Performance at semester volume** (NFR-P1/P2, AC-09) — indexes `(owner_id, date)` are in place now so Week 8 does not discover a missing one, but the 735-record timing has not been run.
- **Mobile-viewport and PDF-as-image re-check** — the Weeks 1–2 visual walkthrough has not been repeated against the new sign-in and course/project forms. Worth doing before Week 4 builds on them.

## For whoever takes Week 4

Requirement revisions need a stable parent. `academic_items` is that parent: give a requirement an item, then store each wording change as a dated revision under it, keeping the earlier text retrievable (REQ-1.6, DR-4). The acceptance example in [development-guide.zh-CN.md](development-guide.zh-CN.md) still applies: a teacher updates the exam scope, the new wording shows as current, the old stays findable, and an already-exported PDF is unchanged. Follow the same ownership pattern — filter every query by `owner_id`, and answer a foreign id with 404.
