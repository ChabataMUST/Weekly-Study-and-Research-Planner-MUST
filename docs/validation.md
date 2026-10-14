# Weeks 1–2 validation

Delivery reviewed on 13 October 2026. Local environment: Windows, Python 3.12, Flask 3.1.2, ReportLab 4.4.9 and pypdf 6.10.0. The tests use temporary databases rather than the application's saved records.

## Automated checks

Run `python -m unittest discover -s tests -v` after installing `requirements-dev.txt`.

| Check | Result |
| --- | --- |
| Observed-source course title, date and time match the transcribed example | Pass |
| UTF-8 BOM, Chinese titles and optional columns | Pass |
| Invalid dates/times and duplicate source keys rejected | Pass |
| Empty, unknown-column and oversized input rejected | Pass |
| Preview writes no classes; cancellation preserves the timetable | Pass |
| Repeated import creates no duplicate occurrences | Pass |
| Room update preserves the linked note and its identity | Pass |
| Stale preview cannot overwrite a newer import | Pass |
| Injected database failure rolls back the whole batch | Pass |
| Invalid batch leaves existing classes unchanged | Pass |
| Missing rows in a later file do not delete classes | Pass |
| Sunday/Monday boundaries and research without courses | Pass |
| Saved classes and notes survive application recreation | Pass |
| POST without a valid form token is rejected | Pass |
| Note text is HTML-escaped; a missing class link is rejected | Pass |
| HTTP upload, confirmation and single-use preview | Pass |
| Selected PDF content, Chinese text, exclusions and frozen versions | Pass |
| Report cannot include a note from another week | Pass |
| Empty-week report remains readable | Pass |
| Long report spans pages without losing the final record | Pass |

Result: **20 tests passed**. These checks cover the early prototype only. They do not establish final multi-user security, full-semester usability, customer acceptance or the performance targets in Task 2.

## Browser and PDF checks

A Chrome walkthrough used a 1440 × 1000 desktop viewport and a 390 × 844 mobile viewport. The seeded week showed four classes and four records. Moving to the next week showed the fifth class. The update file proposed one changed room; cancelling it left the timetable unchanged. A report was downloaded after unchecking one record, and text extraction verified that the excluded title was absent while the research meeting remained. No JavaScript page errors or horizontal overflow were detected in those checks.

The sample PDF was rendered to images and inspected for readable English and Chinese text, page breaks and missing content. An initial font substitution problem was corrected by embedding Noto Sans SC. The included sample can be regenerated with `python scripts/make_sample_report.py`.

## Further acceptance work

The customer group has confirmed the requirements questionnaire. Software acceptance remains a later activity. The project owner has run and viewed the local application. The release walkthrough should also be repeated on the other member's computer. Multi-user isolation, amendment history, task dependencies, full report draft editing and resource search need implementation and tests in later milestones.

## Distribution check

The release was checked with Python 3.13.9 on Windows. Both packages contain identical application code, dependencies, templates, fonts, scripts, samples and tests. The handover package adds development explanations. The release test output is recorded in `test-results.txt`.
