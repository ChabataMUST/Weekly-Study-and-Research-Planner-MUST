# Weekly Study and Research Planner
Macau University of Science and Technology · Team 1 · 赵玥 and 王宇乐

Students can capture a teacher’s instructions from the home page or a class, search earlier weeks and revisions, and export a weekly PDF. Research activities can be filed under projects. Tasks and personal study blocks share the weekly timetable with classes. When times overlap, the planner identifies the conflict and lets the student adjust or keep both.

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
