# Third-party components

The Python dependencies are installed through pip rather than copied into this repository. Their own distributions include their license files.

| Component | Use | Upstream |
| --- | --- | --- |
| Flask | Web forms and routes | https://flask.palletsprojects.com/ |
| ReportLab | PDF generation | https://www.reportlab.com/opensource/ |
| pypdf | Test-time PDF inspection | https://pypdf.readthedocs.io/ |
| Noto Sans SC | Embedded PDF font | https://github.com/google/fonts/tree/main/ofl/notosanssc |

`planner/fonts/NotoSansSC.ttf` is a static weight-400 instance generated from the upstream `NotoSansSC[wght].ttf` with fontTools. The font was obtained on 12 October 2026. Its SIL Open Font License and copyright notice are included unchanged in `planner/fonts/OFL.txt`. The font is distributed under that license. fontTools was used to prepare the bundled font and is not a runtime dependency.

No university screenshots, private questionnaire, paid assets or school login credentials are distributed with this code. The observed-source CSV contains a single class's visible title/date/time with local identifiers; the larger timetable and all learning-record examples are fictional.
