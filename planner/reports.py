"""PDF feasibility path: selected records, edited summary, immutable snapshots."""
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

pdfmetrics.registerFont(TTFont('PlannerSans', str(Path(__file__).parent/'fonts/NotoSansSC.ttf')))


def render_pdf(snapshot):
    output = BytesIO()
    doc = SimpleDocTemplate(output, pagesize=A4, rightMargin=48, leftMargin=48,
                           topMargin=48, bottomMargin=48, title=snapshot['title'],
                           author='Weekly Study and Research Planner', pageCompression=1)
    styles = {
        'title': ParagraphStyle('title', fontName='PlannerSans', fontSize=22, leading=29, spaceAfter=12),
        'heading': ParagraphStyle('heading', fontName='PlannerSans', fontSize=15, leading=21,
                                  spaceBefore=12, spaceAfter=6, keepWithNext=True),
        'body': ParagraphStyle('body', fontName='PlannerSans', fontSize=11, leading=16,
                              spaceAfter=7, wordWrap='CJK'),
        'muted': ParagraphStyle('muted', fontName='PlannerSans', fontSize=10, leading=15,
                               textColor=colors.HexColor('#526374'), spaceAfter=6, keepWithNext=True),
    }
    story = []

    def p(text, style='body'):
        story.append(Paragraph(escape(str(text)).replace('\n', '<br/>'), styles[style]))

    p(snapshot['title'], 'title')
    p(f"{snapshot['week']} to {snapshot['end']} | Weekly study and research", 'muted')
    if snapshot['summary']:
        p('Weekly summary', 'heading')
        p(snapshot['summary'])
    if snapshot['events']:
        p('Taught courses', 'heading')
        for event in snapshot['events']:
            room = f" ({event['room']})" if event['room'] else ''
            p(f"{event['date']}  {event['start_time']}-{event['end_time']} | {event['course_title']}{room}")
    p('Selected learning records', 'heading')
    if not snapshot['notes']:
        p('No learning records were selected for this report.')
    for note in snapshot['notes']:
        p(note['title'], 'heading')
        p(f"{note['date']} | {note['kind']} | {note['context']} | {note['status']}", 'muted')
        p(note['body'])
    story.append(Spacer(1, 12))

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont('Helvetica', 9)
        canvas.setFillColor(colors.HexColor('#526374'))
        canvas.drawString(48, 28, 'Weekly Study and Research Planner')
        canvas.drawRightString(A4[0]-48, 28, str(document.page))
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()
