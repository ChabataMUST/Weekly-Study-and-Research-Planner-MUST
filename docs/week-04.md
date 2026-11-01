# Week 4 retrieval and revision history

This release builds on Week 3 commit `5664920`. The original repository and earlier local project remain untouched; this directory is an independent checkout. No changes have been pushed to GitHub.

## Implemented

- Search notes across all weeks by keyword, course or research project. Keywords also find earlier note versions. Search returns up to 200 results and asks the user to narrow larger result sets.
- Edit a note's title, date, body and progress with a required reason. Keep the original snapshot and each later revision, and reject an outdated edit from another tab. A validation failure retains the submitted draft.
- Create recurring classes without CSV: select weekdays, start/end times and either a week count or an end date. The end date takes precedence. Generated occurrences pass through the existing CSV validation and confirmation workflow. Repeating confirmation cannot duplicate the batch.
- Show a seven-day timetable with a vertical time axis, clickable class cards and separate lanes for overlapping classes. Small screens can scroll horizontally.
- Edit one class occurrence's date, time, teacher, room or cancellation state. Rename its course across occurrences. Preserve class identity and linked notes, record old/new values, and invalidate older import previews.
- Select English, Simplified Chinese or Traditional Chinese for the interface, choose a preset avatar and change the password after checking the current password. Notes and course names are not translated.
- Retain weekly PDF export and immutable saved reports; revising a note does not rewrite a previously exported report.
- Add an in-app help page describing the actual workflows and import limits.

## Validation

45 automated tests pass: the original 33 plus 12 Week 4 tests. See `test-results-week04.txt`. New checks cover recurrence and date bounds, invalid input, repeat import, historical search, stale edits, owner isolation, password changes, three language preferences, class history and retained links, PDF snapshot preservation, literal keyword matching, CSRF protection and page rendering.

Browser review used a separate demonstration database and fictional sample courses. Registration data and real personal records are excluded from this release package. Automated tests do not establish accessibility conformance, production security or performance at the complete semester capacity targets.

## Remaining boundaries

The extra timetable input is a manual recurrence form, not screenshot recognition, ICS/Excel parsing or school-account synchronization. Avatars are selected from presets; image upload is not included. Editing one occurrence does not bulk-move the whole series. Changed CSV keys are not automatically matched. PDF wording retains the existing English report structure while supporting Unicode record text. Password changes do not invalidate another already signed-in session in this local prototype. Full resources, task dependencies, assignment entities, per-record report drafting and backup/restore acceptance remain future work.
