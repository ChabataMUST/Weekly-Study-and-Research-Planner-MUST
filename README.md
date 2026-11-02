# Weekly Study and Research Planner | Week 4

## Weekly development branches

- [Week 1 · Timetable design](https://github.com/ChabataMUST/Weekly-Study-and-Research-Planner-MUST/tree/weekly/week-01)
- [Week 2 · CSV reconciliation and PDF reports](https://github.com/ChabataMUST/Weekly-Study-and-Research-Planner-MUST/tree/weekly/week-02)
- [Week 3 · Accounts and ownership](https://github.com/ChabataMUST/Weekly-Study-and-Research-Planner-MUST/tree/feature/account-ownership)
- [Week 4 · Course search and quick notes](https://github.com/ChabataMUST/Weekly-Study-and-Research-Planner-MUST/tree/weekly/week-04)

[Download the Windows source package · V1.2.0](https://github.com/ChabataMUST/Weekly-Study-and-Research-Planner-MUST/releases/tag/V1.2.0)

## Browser preview

![Weekly timetable in the Week 4 build](https://github.com/ChabataMUST/Weekly-Study-and-Research-Planner-MUST/raw/weekly/week-04/docs/images/week-04-preview.png)

Select a class on the timetable to read its details, capture a quick note or correct that meeting. The return button reopens the same teaching week.

## What changed this week

Students can search requirements across weeks, filter by course or project and review earlier wording after a teacher changes an instruction. A quick note takes only the text itself. Opening it from a class links the note to that class. The home page also provides quick capture, so a student can file the note after class.

The timetable accepts a CSV, manually entered recurring classes or a screenshot. Screenshot import shows editable candidates before confirmation. In our WeMust example the importer proposed six meetings. Two times were estimated from the grid and flagged for review. Students can open a meeting, edit its details and return to the week they were viewing.

A note can become a task with subtasks and a study time. The planner identifies overlapping classes or study blocks and lets the student adjust the time or keep both. Settings include an uploaded avatar and English, simplified Chinese and traditional Chinese interfaces.


## Following a change in exam scope

Record the chapters announced in class. When the teacher revises the scope, update the original note with a reason. Search for a keyword from the earlier wording and open the history to compare both versions. A PDF exported before the change retains the earlier wording.

## Correcting a meeting without losing its notes

Keep the source key when updating a room or time by CSV. The preview then identifies an update to the existing meeting. A missing row leaves its meeting in place. For an uncertain screenshot time, correct the proposed value before confirming the import.

## Run on Windows
Install 64-bit Python (tested on 3.13). With internet access, double-click setup.cmd and wait for setup to finish. Then double-click start.cmd, leave its window open and visit http://127.0.0.1:8080/login in a browser. Create your own local account. Accounts and records are stored on this computer.

## Try it
1. Import samples/timetable-demo.csv and confirm the preview, or enter a recurring class manually.
2. To try screenshot import, choose a full JPG or PNG weekly timetable with visible weekday headings and a time axis. Choose the Monday in the screenshot. Check the names, rooms and times, especially estimates from truncated text, before confirming. OCR runs locally and may require a model download on first use.
3. Open a class, type a quick note and press Ctrl+Enter. Return to the timetable, find the note by keyword, and turn it into a task.
4. Schedule a task during a class to see the conflict warning. Use Settings to select English, simplified Chinese or traditional Chinese and upload an avatar.

## Tests
After setup, run these commands in the project directory using CMD:
~~~
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m unittest discover -s tests
~~~
See docs/import-format.md for CSV fields and THIRD_PARTY_NOTICES.md for bundled font attribution.

The extracted release passed all 55 automated tests.