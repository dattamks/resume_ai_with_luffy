"""
PDF report generation for resume analysis results.
Uses ReportLab (pure Python — no native C dependencies).
"""
import io
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm, cm
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether,
)


# ── Colour palette ──────────────────────────────────────────────────────────

GRADE_COLORS = {
    'A': colors.HexColor('#22c55e'),
    'B': colors.HexColor('#3b82f6'),
    'C': colors.HexColor('#f59e0b'),
    'D': colors.HexColor('#f97316'),
    'F': colors.HexColor('#ef4444'),
}
COLOR_GREEN = colors.HexColor('#22c55e')
COLOR_YELLOW = colors.HexColor('#f59e0b')
COLOR_RED = colors.HexColor('#ef4444')
COLOR_INDIGO = colors.HexColor('#4f46e5')
COLOR_GRAY_900 = colors.HexColor('#111827')
COLOR_GRAY_700 = colors.HexColor('#374151')
COLOR_GRAY_500 = colors.HexColor('#6b7280')
COLOR_GRAY_400 = colors.HexColor('#9ca3af')
COLOR_GRAY_200 = colors.HexColor('#e5e7eb')
COLOR_GRAY_100 = colors.HexColor('#f3f4f6')
COLOR_INDIGO_BG = colors.HexColor('#eef2ff')
COLOR_GREEN_BG = colors.HexColor('#ecfdf5')
COLOR_RED_BG = colors.HexColor('#fef2f2')


def _bar_color(value):
    if value >= 75:
        return COLOR_GREEN
    if value >= 50:
        return COLOR_YELLOW
    return COLOR_RED


def _grade_color(grade):
    return GRADE_COLORS.get(grade.upper(), COLOR_GRAY_500)


# ── Styles ───────────────────────────────────────────────────────────────────

def _build_styles():
    ss = getSampleStyleSheet()

    ss.add(ParagraphStyle(
        'Title_Custom', parent=ss['Title'],
        fontSize=18, leading=22, textColor=COLOR_GRAY_900,
        spaceAfter=2, alignment=TA_LEFT,
    ))
    ss.add(ParagraphStyle(
        'Subtitle', parent=ss['Normal'],
        fontSize=10, textColor=COLOR_GRAY_500, spaceAfter=0,
    ))
    ss.add(ParagraphStyle(
        'Timestamp', parent=ss['Normal'],
        fontSize=8, textColor=COLOR_GRAY_400, spaceAfter=6,
    ))
    ss.add(ParagraphStyle(
        'SectionHeading', parent=ss['Heading2'],
        fontSize=12, leading=16, textColor=COLOR_GRAY_700,
        spaceBefore=14, spaceAfter=6, fontName='Helvetica-Bold',
    ))
    ss.add(ParagraphStyle(
        'SubHeading', parent=ss['Normal'],
        fontSize=10, leading=13, textColor=COLOR_INDIGO,
        fontName='Helvetica-Bold', spaceBefore=6, spaceAfter=2,
    ))
    ss.add(ParagraphStyle(
        'BodyText_Custom', parent=ss['Normal'],
        fontSize=9, leading=13, textColor=COLOR_GRAY_700,
    ))
    ss.add(ParagraphStyle(
        'SmallLabel', parent=ss['Normal'],
        fontSize=8, leading=10, textColor=COLOR_GRAY_500,
        fontName='Helvetica-Bold',
    ))
    ss.add(ParagraphStyle(
        'BulletItem', parent=ss['Normal'],
        fontSize=9, leading=13, textColor=COLOR_GRAY_700,
        leftIndent=12, bulletIndent=0, spaceBefore=1, spaceAfter=1,
    ))
    ss.add(ParagraphStyle(
        'BulletItemRed', parent=ss['Normal'],
        fontSize=9, leading=13, textColor=COLOR_RED,
        leftIndent=12, bulletIndent=0, spaceBefore=1, spaceAfter=1,
    ))
    ss.add(ParagraphStyle(
        'GradeLabel', parent=ss['Normal'],
        fontSize=24, leading=28, textColor=COLOR_GRAY_900,
        fontName='Helvetica-Bold', alignment=TA_CENTER,
    ))
    ss.add(ParagraphStyle(
        'GradeAts', parent=ss['Normal'],
        fontSize=9, leading=12, alignment=TA_CENTER,
        fontName='Helvetica-Bold',
    ))
    ss.add(ParagraphStyle(
        'OriginalText', parent=ss['Normal'],
        fontSize=9, leading=12, textColor=COLOR_GRAY_500,
    ))
    ss.add(ParagraphStyle(
        'SuggestedText', parent=ss['Normal'],
        fontSize=9, leading=12, textColor=COLOR_GRAY_900,
        fontName='Helvetica-Bold',
    ))
    ss.add(ParagraphStyle(
        'ReasonText', parent=ss['Normal'],
        fontSize=8, leading=11, textColor=COLOR_GRAY_400,
        fontStyle='italic',
    ))
    ss.add(ParagraphStyle(
        'Footer', parent=ss['Normal'],
        fontSize=7, textColor=COLOR_GRAY_400, alignment=TA_CENTER,
    ))
    ss.add(ParagraphStyle(
        'SummaryBody', parent=ss['Normal'],
        fontSize=9, leading=14, textColor=COLOR_GRAY_700,
    ))
    ss.add(ParagraphStyle(
        'PillGreen', parent=ss['Normal'],
        fontSize=8, textColor=colors.HexColor('#15803d'),
        backColor=COLOR_GREEN_BG,
    ))
    ss.add(ParagraphStyle(
        'PillRed', parent=ss['Normal'],
        fontSize=8, textColor=colors.HexColor('#b91c1c'),
        backColor=COLOR_RED_BG,
    ))

    return ss


# ── Score bar as a small table ───────────────────────────────────────────────

def _score_bar(label, value, available_width):
    """Return a list of flowables representing a labelled score bar."""
    bar_color = _bar_color(value)
    pct = max(0, min(100, value))
    filled_w = available_width * pct / 100
    empty_w = available_width - filled_w

    # Label row
    label_table_data = [[
        Paragraph(label, ParagraphStyle('_lbl', fontSize=9, textColor=COLOR_GRAY_500)),
        Paragraph(f'<b>{value}</b>', ParagraphStyle('_val', fontSize=9, textColor=COLOR_GRAY_700, alignment=TA_RIGHT)),
    ]]
    label_table = Table(label_table_data, colWidths=[available_width * 0.7, available_width * 0.3])
    label_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
    ]))

    # Bar row — two-cell table simulating a progress bar
    bar_cells = []
    col_widths = []
    if filled_w > 0:
        bar_cells.append('')
        col_widths.append(filled_w)
    if empty_w > 0:
        bar_cells.append('')
        col_widths.append(empty_w)

    bar_table = Table([bar_cells], colWidths=col_widths, rowHeights=[6])
    style_cmds = [
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]
    if filled_w > 0:
        style_cmds.append(('BACKGROUND', (0, 0), (0, 0), bar_color))
        style_cmds.append(('ROUNDEDCORNERS', [3, 0, 0, 3] if empty_w > 0 else [3, 3, 3, 3]))
    if empty_w > 0:
        idx = 1 if filled_w > 0 else 0
        style_cmds.append(('BACKGROUND', (idx, 0), (idx, 0), COLOR_GRAY_100))
    bar_table.setStyle(TableStyle(style_cmds))

    return [label_table, bar_table, Spacer(1, 4)]


# ── Keyword pills ────────────────────────────────────────────────────────────

def _keyword_pills(keywords, style_name, styles):
    """Render keywords as a comma-separated paragraph (pill-style)."""
    if not keywords:
        return []
    text = ' &nbsp;·&nbsp; '.join(f'<b>{kw}</b>' for kw in keywords)
    return [Paragraph(text, styles[style_name])]


# ── Main builder ─────────────────────────────────────────────────────────────

def generate_analysis_pdf(analysis):
    """
    Build a PDF report for the given analysis and return bytes.

    This is the single public entry point — called by both the Celery task
    and the on-the-fly fallback in the view.
    """
    buf = io.BytesIO()
    styles = _build_styles()

    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
        title='Resume Analysis Report',
    )

    content_width = doc.width  # usable width between margins
    story = []

    # ── Extract data ─────────────────────────────────────────────────────
    scores = analysis.scores or {}
    kw = analysis.keyword_analysis or {}
    sections = analysis.section_feedback or []
    suggestions = analysis.sentence_suggestions or []
    flags = analysis.formatting_flags or []
    wins = analysis.quick_wins or []
    grade = analysis.overall_grade or '?'
    generic_ats = scores.get('generic_ats', 0)
    workday_ats = scores.get('workday_ats', 0)
    greenhouse_ats = scores.get('greenhouse_ats', 0)
    kw_match = scores.get('keyword_match_percent', 0)

    # ── Header with grade ────────────────────────────────────────────────
    role_parts = [p for p in [analysis.jd_role, analysis.jd_company] if p]
    role_line = ' at '.join(role_parts) if role_parts else ''

    grade_col = _grade_color(grade)
    grade_para = Paragraph(grade, styles['GradeLabel'])
    ats_para = Paragraph(f'ATS: {generic_ats}', ParagraphStyle(
        '_ats', parent=styles['GradeAts'], textColor=grade_col,
    ))

    left_parts = [Paragraph('Resume Analysis Report', styles['Title_Custom'])]
    if role_line:
        left_parts.append(Paragraph(role_line, styles['Subtitle']))
    ts = analysis.created_at.strftime('%B %d, %Y at %I:%M %p')
    provider = analysis.ai_provider_used or 'AI'
    left_parts.append(Paragraph(f'{ts}  ·  via {provider}', styles['Timestamp']))

    # Build as a two-column table: [title info | grade circle]
    header_table = Table(
        [[left_parts, [grade_para, ats_para]]],
        colWidths=[content_width * 0.78, content_width * 0.22],
    )
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ALIGN', (1, 0), (1, 0), 'CENTER'),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 10))

    # ── Score breakdown ──────────────────────────────────────────────────
    story.append(HRFlowable(width='100%', thickness=0.5, color=COLOR_GRAY_200))
    story.append(Spacer(1, 6))
    story.append(Paragraph('<b>Score Breakdown</b>', styles['BodyText_Custom']))
    story.append(Spacer(1, 6))

    bar_width = content_width - 4 * mm
    for label, value in [
        ('Generic ATS', generic_ats),
        ('Workday ATS', workday_ats),
        ('Greenhouse ATS', greenhouse_ats),
        ('Keyword Match', kw_match),
    ]:
        story.extend(_score_bar(label, value, bar_width))

    story.append(Spacer(1, 4))
    story.append(HRFlowable(width='100%', thickness=0.5, color=COLOR_GRAY_200))

    # ── Summary ──────────────────────────────────────────────────────────
    if analysis.summary:
        story.append(Spacer(1, 8))
        story.append(Paragraph('Summary', styles['SectionHeading']))
        story.append(Paragraph(analysis.summary, styles['SummaryBody']))

    # ── Keyword analysis ─────────────────────────────────────────────────
    missing = kw.get('missing_keywords', [])
    matched = kw.get('matched_keywords', [])
    recs = kw.get('recommended_to_add', [])

    if matched or missing:
        story.append(Paragraph('Keyword Analysis', styles['SectionHeading']))

        if matched:
            story.append(Paragraph(f'Matched ({len(matched)})', ParagraphStyle(
                '_m', fontSize=8, textColor=colors.HexColor('#15803d'), fontName='Helvetica-Bold',
            )))
            story.extend(_keyword_pills(matched, 'PillGreen', styles))
            story.append(Spacer(1, 4))

        if missing:
            story.append(Paragraph(f'Missing ({len(missing)})', ParagraphStyle(
                '_mi', fontSize=8, textColor=colors.HexColor('#dc2626'), fontName='Helvetica-Bold',
            )))
            story.extend(_keyword_pills(missing, 'PillRed', styles))
            story.append(Spacer(1, 4))

        if recs:
            story.append(Paragraph('Recommended Actions:', styles['SmallLabel']))
            for r in recs:
                story.append(Paragraph(f'• {r}', styles['BulletItem']))

    # ── Section feedback ─────────────────────────────────────────────────
    if sections:
        story.append(Paragraph('Section Feedback', styles['SectionHeading']))
        for sec in sections:
            name = sec.get('section_name', '')
            score = sec.get('score', '')
            heading_text = f'{name.upper()}  —  {score}/100'
            block = [Paragraph(heading_text, styles['SubHeading'])]

            for fb in sec.get('feedback', []):
                block.append(Paragraph(f'• {fb}', styles['BulletItem']))
            for fl in sec.get('ats_flags', []):
                block.append(Paragraph(f'⚠ {fl}', styles['BulletItemRed']))

            story.append(KeepTogether(block))
            story.append(Spacer(1, 4))

    # ── Sentence suggestions ─────────────────────────────────────────────
    if suggestions:
        story.append(Paragraph(
            f'Sentence Suggestions ({len(suggestions)})', styles['SectionHeading'],
        ))
        for item in suggestions:
            block = []
            block.append(Paragraph('ORIGINAL', styles['SmallLabel']))
            block.append(Paragraph(
                f'<strike>{item.get("original", "")}</strike>', styles['OriginalText'],
            ))
            block.append(Spacer(1, 2))
            block.append(Paragraph('SUGGESTED', ParagraphStyle(
                '_sg', fontSize=8, textColor=COLOR_GREEN, fontName='Helvetica-Bold',
            )))
            block.append(Paragraph(item.get('suggested', ''), styles['SuggestedText']))
            if item.get('reason'):
                block.append(Spacer(1, 2))
                block.append(Paragraph(item['reason'], styles['ReasonText']))
            block.append(Spacer(1, 6))
            story.append(KeepTogether(block))

    # ── Formatting flags ─────────────────────────────────────────────────
    if flags:
        story.append(Paragraph('Formatting Issues', styles['SectionHeading']))
        for f in flags:
            story.append(Paragraph(f'⚠ {f}', styles['BulletItemRed']))

    # ── Quick wins ───────────────────────────────────────────────────────
    if wins:
        story.append(Paragraph('Quick Wins', styles['SectionHeading']))
        for w in wins:
            priority = w.get('priority', '')
            action = w.get('action', '')
            story.append(Paragraph(
                f'<b>{priority}.</b>  {action}', styles['BulletItem'],
            ))

    # ── Footer ───────────────────────────────────────────────────────────
    story.append(Spacer(1, 20))
    story.append(HRFlowable(width='100%', thickness=0.5, color=COLOR_GRAY_200))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        f'Generated by Resume AI  ·  {analysis.created_at.strftime("%Y-%m-%d")}',
        styles['Footer'],
    ))

    # ── Build ────────────────────────────────────────────────────────────
    doc.build(story)
    return buf.getvalue()
