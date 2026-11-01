# Week 3 baseline review

Reviewed on 30 October 2026 against repository commit `5664920` (default branch), including the Week 3 merge `a46b037`.

The baseline passes all 33 existing automated tests. Registration and login already exist; Week 4 retains them. Passwords are hashed, queries are scoped to the signed-in owner, and direct access to another account's previews, notes and reports is rejected. Week 3 also introduces course/project entities, legacy database migration, field-level timetable history and a cancellation flag that survives reimport.

The baseline does not expose cross-week keyword search, a note editor with revision history, manual recurring classes, class-edit screens, account preferences or a time-positioned timetable. `academic_items` is a foundation table; this release does not claim a complete assignment/task workflow.

CSV preview, duplicate detection, rollback, stale-preview rejection and retained note links already work. Week 4 extends their presentation and tests rather than replacing the import engine. Missing CSV rows remain stored and new source keys create new occurrences; automatic changed-key matching is still outside this build.

The first baseline test attempt encountered sandbox temporary-directory permissions. A subsequent normal-permission run completed all 33 tests successfully. These checks concern development behavior, not final customer acceptance.
