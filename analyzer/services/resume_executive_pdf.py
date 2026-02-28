"""
Executive resume PDF renderer.

Formal, authoritative layout with dark charcoal header, serif headings,
and a professional tone suited for senior/C-level positions.

Template: executive — formal, single-column, serif accents, dark header.
"""
import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, HRFlowable, KeepTogether,
)


# ── Colour palette ──────────────────────────────────────────────────────

COLOR_PRIMARY = colors.HexColor('#1b2631')       # Dark charcoal
COLOR_SECONDARY = colors.HexColor('#2c3e50')     # Slate
COLOR_BODY = colors.HexColor('#2c3e50')          # Body
COLOR_MUTED = colors.HexColor('#7f8c8d')         # Muted
COLOR_ACCENT = colors.HexColor('#c0392b')        # Deep red accent
COLOR_DIVIDER = colors.HexColor('#1b2631')       # Dark divider (matches header)
COLOR_GOLD = colors.HexColor('#b7950b')          # Gold accent for name


# ── Styles ───────────────────────────────────────────────────────────────

def _build_styles():
    ss = getSampleStyleSheet()

    ss.add(ParagraphStyle(
        'ResumeName', parent=ss['Title'],
        fontSize=24, leading=28, textColor=COLOR_PRIMARY,
        spaceAfter=2, alignment=TA_CENTER,
        fontName='Times-Bold',
    ))
    ss.add(ParagraphStyle(
        'ContactInfo', parent=ss['Normal'],
        fontSize=9, leading=12, textColor=COLOR_MUTED,
        alignment=TA_CENTER, spaceAfter=2,
    ))
    ss.add(ParagraphStyle(
        'SectionTitle', parent=ss['Heading2'],
        fontSize=12, leading=15, textColor=COLOR_PRIMARY,
        fontName='Times-Bold', spaceBefore=12, spaceAfter=2,
        borderWidth=0, textTransform='uppercase',
    ))
    ss.add(ParagraphStyle(
        'JobTitle', parent=ss['Normal'],
        fontSize=10, leading=13, textColor=COLOR_PRIMARY,
        fontName='Times-Bold', spaceBefore=6, spaceAfter=1,
    ))
    ss.add(ParagraphStyle(
        'JobCompany', parent=ss['Normal'],
        fontSize=9, leading=12, textColor=COLOR_BODY,
        fontName='Times-Italic', spaceAfter=1,
    ))
    ss.add(ParagraphStyle(
        'JobDate', parent=ss['Normal'],
        fontSize=8, leading=11, textColor=COLOR_MUTED,
        fontName='Times-Roman', spaceAfter=3,
    ))
    ss.add(ParagraphStyle(
        'ResumeBullet', parent=ss['Normal'],
        fontSize=9, leading=13, textColor=COLOR_BODY,
        fontName='Times-Roman',
        leftIndent=14, spaceAfter=2,
    ))
    ss.add(ParagraphStyle(
        'BodyText_Resume', parent=ss['Normal'],
        fontSize=10, leading=14, textColor=COLOR_BODY,
        fontName='Times-Roman', spaceAfter=4,
    ))
    ss.add(ParagraphStyle(
        'SkillList', parent=ss['Normal'],
        fontSize=9, leading=12, textColor=COLOR_BODY,
        fontName='Times-Roman', leftIndent=14, spaceAfter=2,
    ))
    ss.add(ParagraphStyle(
        'EduDegree', parent=ss['Normal'],
        fontSize=10, leading=13, textColor=COLOR_PRIMARY,
        fontName='Times-Bold', spaceBefore=4, spaceAfter=1,
    ))
    ss.add(ParagraphStyle(
        'EduInstitution', parent=ss['Normal'],
        fontSize=9, leading=12, textColor=COLOR_BODY,
        fontName='Times-Roman', spaceAfter=1,
    ))
    ss.add(ParagraphStyle(
        'EduDate', parent=ss['Normal'],
        fontSize=8, leading=11, textColor=COLOR_MUTED,
        fontName='Times-Roman', spaceAfter=3,
    ))
    ss.add(ParagraphStyle(
        'CertName', parent=ss['Normal'],
        fontSize=9, leading=12, textColor=COLOR_BODY,
        fontName='Times-Roman', spaceBefore=2, spaceAfter=1,
    ))
    ss.add(ParagraphStyle(
        'ProjectName', parent=ss['Normal'],
        fontSize=9, leading=12, textColor=COLOR_PRIMARY,
        fontName='Times-Bold', spaceBefore=4, spaceAfter=1,
    ))
    ss.add(ParagraphStyle(
        'ProjectDesc', parent=ss['Normal'],
        fontSize=9, leading=12, textColor=COLOR_BODY,
        fontName='Times-Roman', leftIndent=14, spaceAfter=2,
    ))

    return ss


def _safe(text):
    if not text:
        return ''
    return str(text).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


# ── Section builders ─────────────────────────────────────────────────────

def _build_contact(content, styles):
    elements = []
    contact = content.get('contact', {})
    name = contact.get('name', 'Candidate')

    elements.append(Spacer(1, 5 * mm))
    elements.append(Paragraph(_safe(name).upper(), styles['ResumeName']))

    parts = []
    if contact.get('email'):
        parts.append(_safe(contact['email']))
    if contact.get('phone'):
        parts.append(_safe(contact['phone']))
    if contact.get('location'):
        parts.append(_safe(contact['location']))
    if parts:
        elements.append(Paragraph(' | '.join(parts), styles['ContactInfo']))

    links = []
    if contact.get('linkedin'):
        links.append(_safe(contact['linkedin']))
    if contact.get('portfolio'):
        links.append(_safe(contact['portfolio']))
    if links:
        elements.append(Paragraph(' | '.join(links), styles['ContactInfo']))

    elements.append(Spacer(1, 3 * mm))
    elements.append(HRFlowable(width='100%', thickness=2, color=COLOR_DIVIDER, spaceAfter=6))
    return elements


def _build_summary(content, styles):
    summary = content.get('summary', '')
    if not summary:
        return []
    return [
        Paragraph('EXECUTIVE SUMMARY', styles['SectionTitle']),
        HRFlowable(width='100%', thickness=0.5, color=COLOR_DIVIDER, spaceAfter=4),
        Paragraph(_safe(summary), styles['BodyText_Resume']),
        Spacer(1, 3 * mm),
    ]


def _build_experience(content, styles):
    experience = content.get('experience', [])
    if not experience:
        return []
    elements = [
        Paragraph('PROFESSIONAL EXPERIENCE', styles['SectionTitle']),
        HRFlowable(width='100%', thickness=0.5, color=COLOR_DIVIDER, spaceAfter=4),
    ]
    for exp in experience:
        job_block = []
        title = _safe(exp.get('title', ''))
        company = _safe(exp.get('company', ''))
        location = _safe(exp.get('location', ''))
        start = _safe(exp.get('start_date', ''))
        end = _safe(exp.get('end_date', ''))

        job_block.append(Paragraph(title, styles['JobTitle']))
        company_line = company
        if location:
            company_line += f' — {location}'
        job_block.append(Paragraph(company_line, styles['JobCompany']))
        if start or end:
            date_line = f'{start} – {end}' if start and end else (start or end)
            job_block.append(Paragraph(date_line, styles['JobDate']))
        for bullet in exp.get('bullets', []):
            job_block.append(Paragraph(f'■ {_safe(bullet)}', styles['ResumeBullet']))
        elements.append(KeepTogether(job_block))
    elements.append(Spacer(1, 3 * mm))
    return elements


def _build_education(content, styles):
    education = content.get('education', [])
    if not education:
        return []
    elements = [
        Paragraph('EDUCATION', styles['SectionTitle']),
        HRFlowable(width='100%', thickness=0.5, color=COLOR_DIVIDER, spaceAfter=4),
    ]
    for edu in education:
        edu_block = []
        edu_block.append(Paragraph(_safe(edu.get('degree', '')), styles['EduDegree']))
        inst_line = _safe(edu.get('institution', ''))
        if edu.get('location'):
            inst_line += f' — {_safe(edu["location"])}'
        edu_block.append(Paragraph(inst_line, styles['EduInstitution']))
        details = []
        if edu.get('year'):
            details.append(_safe(edu['year']))
        if edu.get('gpa'):
            details.append(f'GPA: {_safe(edu["gpa"])}')
        if details:
            edu_block.append(Paragraph(' | '.join(details), styles['EduDate']))
        elements.append(KeepTogether(edu_block))
    elements.append(Spacer(1, 3 * mm))
    return elements


def _build_skills(content, styles):
    skills = content.get('skills', {})
    if not skills:
        return []
    has_any = any(skills.get(cat) for cat in ('technical', 'tools', 'soft'))
    if not has_any:
        return []
    elements = [
        Paragraph('CORE COMPETENCIES', styles['SectionTitle']),
        HRFlowable(width='100%', thickness=0.5, color=COLOR_DIVIDER, spaceAfter=4),
    ]
    category_labels = {'technical': 'Technical', 'tools': 'Tools & Platforms', 'soft': 'Leadership & Soft Skills'}
    for cat_key, cat_label in category_labels.items():
        items = skills.get(cat_key, [])
        if items:
            skill_list = ', '.join([_safe(s) for s in items])
            elements.append(Paragraph(f'<b>{_safe(cat_label)}:</b> {skill_list}', styles['SkillList']))
    elements.append(Spacer(1, 3 * mm))
    return elements


def _build_certifications(content, styles):
    certs = content.get('certifications', [])
    if not certs:
        return []
    elements = [
        Paragraph('CERTIFICATIONS & CREDENTIALS', styles['SectionTitle']),
        HRFlowable(width='100%', thickness=0.5, color=COLOR_DIVIDER, spaceAfter=4),
    ]
    for cert in certs:
        parts = [_safe(cert.get('name', ''))]
        if cert.get('issuer'):
            parts.append(f'— {_safe(cert["issuer"])}')
        if cert.get('year'):
            parts.append(f'({_safe(cert["year"])})')
        elements.append(Paragraph(' '.join(parts), styles['CertName']))
    elements.append(Spacer(1, 3 * mm))
    return elements


def _build_projects(content, styles):
    projects = content.get('projects', [])
    if not projects:
        return []
    elements = [
        Paragraph('KEY PROJECTS', styles['SectionTitle']),
        HRFlowable(width='100%', thickness=0.5, color=COLOR_DIVIDER, spaceAfter=4),
    ]
    for proj in projects:
        proj_block = []
        proj_block.append(Paragraph(_safe(proj.get('name', '')), styles['ProjectName']))
        if proj.get('description'):
            proj_block.append(Paragraph(_safe(proj['description']), styles['ProjectDesc']))
        techs = proj.get('technologies', [])
        if techs:
            tech_str = ', '.join([_safe(t) for t in techs])
            proj_block.append(Paragraph(f'<i>Technologies: {tech_str}</i>', styles['ProjectDesc']))
        if proj.get('url'):
            proj_block.append(Paragraph(_safe(proj['url']), styles['ProjectDesc']))
        elements.append(KeepTogether(proj_block))
    elements.append(Spacer(1, 3 * mm))
    return elements


# ── Main renderer ────────────────────────────────────────────────────────

def render_executive_pdf(resume_content: dict) -> bytes:
    """Render structured resume JSON into an executive-styled PDF."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=22 * mm, rightMargin=22 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
        title='Resume',
        author=resume_content.get('contact', {}).get('name', 'Candidate'),
    )
    styles = _build_styles()
    elements = []
    elements.extend(_build_contact(resume_content, styles))
    elements.extend(_build_summary(resume_content, styles))
    elements.extend(_build_experience(resume_content, styles))
    elements.extend(_build_education(resume_content, styles))
    elements.extend(_build_skills(resume_content, styles))
    elements.extend(_build_certifications(resume_content, styles))
    elements.extend(_build_projects(resume_content, styles))
    doc.build(elements)
    return buf.getvalue()
