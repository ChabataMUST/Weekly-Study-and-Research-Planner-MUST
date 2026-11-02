# Week 1: timetable source and CSV agreement

Initial CSV contract, 12 October 2026.

## Source inspection

The available WeMust image shows the week 28 September–4 October 2026. One complete class is visible: 計算機網絡I, Wednesday 30 September, 09:00–11:50. The Tuesday Linear Algebra card is cut off before its end time, so we did not turn it into an observed-source row or infer the missing time. The image does not establish a full-semester pattern, cancellations or odd/even weeks.

The selected route is **screenshot → student-prepared CSV → automatic parsing → preview → confirmation**. The preparation is manual; CSV parsing and database reconciliation are automatic. We selected this route for the initial implementation. A full school export or an OCR adapter has not been supplied or tested.

`timetable-observed.csv` preserves the visible course title, date and times. `LOCAL-NET` and `observed-net-001` are local identifiers assigned for the example. Teacher and room details are omitted. The original screenshot, student account details and private questionnaire are not included in the public package.

## Field contract

| Field | Required | Meaning |
| --- | --- | --- |
| source_key | Yes | Stable identifier for one dated occurrence, not the whole course |
| course_code | Yes | A course label; a locally assigned label is acceptable |
| course_title | Yes | Display name in English or Chinese |
| date | Yes | Actual date, YYYY-MM-DD |
| start_time | Yes | 24-hour HH:MM |
| end_time | Yes | 24-hour HH:MM, later than start on the same date |
| room | No | Optional location; may be blank or the column omitted |
| teacher | No | Optional display text; may be blank or the column omitted |

Files use UTF-8, with or without a byte-order mark. Export from Excel using **CSV UTF-8**. Use the standard CSV quoting rules for commas in a title. The header is case-sensitive. Unknown or duplicate column names, missing cells, invalid dates/times and duplicate source keys within one file are rejected. There may be at most 500 rows and 200 characters per cell; keep the upload below 1 MB. One bad row rejects the entire batch with a row number. No classes are saved by previewing.

## Reimport rules

- A new source key adds a class occurrence.
- The same key and the same fields produce an unchanged row.
- The same key with different values proposes an update. The preview displays previous and proposed values.
- Confirmation applies the whole batch in one database transaction. A database failure rolls the whole batch back.
- Cancellation changes no class. An already confirmed or cancelled token cannot be applied again.
- If another import changes the timetable after a preview, confirmation is rejected and the student must create a new preview.
- A row absent from the uploaded file does not delete its saved class. Deletion/cancellation controls are later work.

Changing a source key is treated as creating a different occurrence. This early importer does not guess whether differently keyed rows refer to the same class. Preserving the original key is therefore part of the file preparation instructions.

## Repeats and limits

For a recurring course, list each actual teaching date as a separate row with its own source key. An alternate-week course includes only its actual dates. The application does not infer repeats, holidays or cancellations from a single screenshot. Cross-midnight classes and iCalendar input are not supported in this milestone. An additional source format needs its own examples and validation before it is added.

## Reproduction

Start with an empty database and import `samples/timetable-observed.csv`. The preview must show exactly one added class, on 2026-09-30 from 09:00 to 11:50. Confirm, then import the same file again: it must show one unchanged class. The automated test `test_observed_source_matches_checked_event` independently checks the four transcribed values.

Use the fictional `timetable-demo.csv` for the larger walkthrough. Its five classes include one in the following week. `timetable-update.csv` changes one room using the same key; `timetable-invalid.csv` contains an end time before the start time and must be rejected.
