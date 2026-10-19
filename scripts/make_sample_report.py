"""Reproduce the sample PDF without touching the running application's database."""
import sys
import tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from planner import create_app, weekly_records
from planner.db import connect
from planner.reports import render_pdf
from seed_demo import seed

ROOT=Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory() as directory:
        app=create_app({'DATABASE':str(Path(directory)/'sample.sqlite3'),'SECRET_KEY':'temporary-sample-only'})
        owner=seed(app)
        with connect(app.config['DATABASE']) as db:
            start,end,events,notes=weekly_records(db,owner,'2026-09-28')
        snapshot={'week':str(start),'end':str(end),'title':'Sample weekly study and research report',
                  'summary':'Fictional demonstration. This week combines coursework requirements with a research meeting and reading notes. Next week: finish the report outline and check the experiment setup.',
                  'events':events,'notes':notes}
        path=ROOT/'docs/sample-weekly-report.pdf'
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(render_pdf(snapshot))
        print(path)


if __name__=='__main__':
    main()
