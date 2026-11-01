# Weekly Study and Research Planner

Macau University of Science and Technology · Team 1 · 赵玥 and 王宇乐

**Latest milestone: Week 4 · V1.2.0** · [Download this version](https://github.com/ChabataMUST/Weekly-Study-and-Research-Planner-MUST/releases/tag/V1.2.0)

## Weekly READMEs

- [Week 1 | Timetable design and weekly records](weeks/week-01/README.md)
- [Week 2 | Importing classes and exporting weekly reports](weeks/week-02/README.md)
- [Week 3 | Accounts and ownership of records](weeks/week-03/README.md)
- [Week 4 | Search, timetable updates and quick notes](weeks/week-04/README.md)

## Week 4 | Search, timetable updates and quick notes

Students can search requirements across weeks, filter by course or project and review earlier wording after a teacher changes an instruction. A quick note takes only the text itself. Opening it from a class links the note to that class. The home page also provides quick capture, so a student can file the note after class.

The timetable accepts a CSV, manually entered recurring classes or a screenshot. Screenshot import shows editable candidates before confirmation. In our WeMust example the importer proposed six meetings. Two times were estimated from the grid and flagged for review. Students can open a meeting, edit its details and return to the week they were viewing.

A note can become a task with subtasks and a study time. The planner identifies overlapping classes or study blocks and lets the student adjust the time or keep both. Settings include an uploaded avatar and English, simplified Chinese and traditional Chinese interfaces.

## Run this version on Windows

Download the attached source ZIP from the Week 4 release linked above and extract it. Run setup.cmd once, then start.cmd. Keep the terminal open and visit http://127.0.0.1:8080/login to create a local account.

## Verification

All 55 automated tests passed on the extracted release using the existing Python environment. The screenshot review and alternate-week import were also checked with the supplied timetable.
