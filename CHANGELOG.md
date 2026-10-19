# Changelog

All notable changes to this project are documented in this file. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

_Nothing yet._

## [1.1.0] — 2026-10-19

### Added

- **Private accounts.** Registration, sign-in and per-account ownership enforced on every record query (REQ-1.1, NFR-S1). A foreign record id returns 404 rather than 403 so its existence is not leaked (AC-01).
- **Course and project entities.** Classes and notes belong to a real course or research project instead of free text. A project can be named inline so a research student needs no taught timetable (DR-3).
- **Versioned schema migration.** A Weeks 1–2 single-profile database is upgraded automatically on first start: a `.pre-v3.bak` backup is written beside it, the old records move to a reserved account, and the first registration adopts them. The migration runs in one transaction and rolls back entirely on any failure.
- **Per-account timetable revisions.** One student's import no longer invalidates another's pending preview.
- **Field-level change history.** Confirmed timetable updates write previous and new values with a confirmation time to `event_changes` (Task 2 6.2.8).
- **Cancelled-class state preservation.** Reimporting a file does not un-cancel a class or report it as a change.
- **Sign-in and register pages** with password hashing (Werkzeug scrypt, no new dependency).
- **Chinese development guide** (`docs/development-guide.zh-CN.md`) added to the repository; the previous copy existed only in the handover ZIP.

### Changed

- `events.source_key` is now unique per account rather than globally; the surrogate `id` is the occurrence's identity.
- Homepage defaults to the current week instead of the hardcoded 2026-09-28 demonstration date.
- Report download answers a foreign id with 404; previously the sequential id could be guessed to fetch another student's report.
- CSV parser rejects one `course_code` carrying two titles in the same file.
- Seed script creates a `demo` account (password `demo-password`) and files research notes under a project.

### Fixed

- Report download endpoint had no ownership check (security fix).

### Tests

- 33 automated tests pass (20 preserved from v1.0.0, 13 added for Week 3).
- Migration tested against a real v1 database with four injected failure paths.
- End-to-end browser walkthrough covers registration, import, record creation, PDF export and cross-account isolation.

## [1.0.0] — 2026-10-14

Initial release. Timetable import (CSV validation, preview, confirm/cancel, reimport), weekly workspace with coursework and research records, PDF export with selected content and saved versions, local SQLite persistence. 20 automated tests. Single local profile; no account isolation.

[Unreleased]: https://github.com/ChabataMUST/Weekly-Study-and-Research-Planner-MUST/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/ChabataMUST/Weekly-Study-and-Research-Planner-MUST/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/ChabataMUST/Weekly-Study-and-Research-Planner-MUST/releases/tag/v1.0.0
