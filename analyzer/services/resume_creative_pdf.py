"""
Creative resume PDF renderer.

Vibrant layout with a coloured left sidebar-style accent, rounded contact
section, and playful typography. Suited for creative/design roles.

Template: creative — colourful, sidebar-inspired, sans-serif.
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

COLOR_PRIMARY = colors.HexColor('#6c3483')       # Deep purple
COLOR_SECONDARY = colors.HexColor('#8e44ad')     # Medium purple
COLOR_BODY = colors.HexColor('#2d3436')          # Near-black
COLOR_MUTED = colors.HexColor('#636e72')         # Muted grey
COLOR_ACCENT = colors.HexColor('#e74c3c')        # Red accent
COLOR_DIVIDER = colors.HexColor('#d2b4de')       # Light purple
COLOR_HIGHLIGHT = colors.HexColor('#f5eef8')     # Very light purple bg


# ── Styles ───────────────────────────────────────────────────────────────

def _build_styles():
    ss = getSampleStyleSheet()

    ss.add(ParagraphStyle(
        'ResumeName', parent=ss['Title'],
        fontSize=22, leading=26, textColor=COLOR_PRIMARY,
        spaceAfter=2, alignment=TA_CENTER,
        fontName='Helvetica-Bold',
    ))
    ss.add(ParagraphStyle(
        'ContactInfo', parent=ss['Normal'],
        fontSize=9, leading=12, textColor=COLOR_MUTED,
        alignment=TA_CENTER, spaceAfter=2,
    ))
    ss.add(ParagraphStyle(
        'SectionTitle', parent=ss['Heading2'],
        fontSize=11, leading=14, textColor=colors.white,
        fontName='Helvetica-Bold', spaceBefore=10, spaceAfter=3,
        backColor=COLOR_PRIMARY,
        borderPadding=(2, 4, 2, 8),
    ))
    ss.add(ParagraphStyle(
        'JobTitle', parent=ss['Normal'],
        fontSize=10, leading=13, textColor=COLOR_SECONDARY,
        fontName='Helvetica-Bold', spaceBefore=6, spaceAfter=1,
    ))
    ss.add(ParagraphStyle(
        'JobCompany', parent=ss['Normal'],
        fontSize=9, leading=12, textColor=COLOR_BODY,
        fontName='Helvetica-Oblique', spaceAfter=1,
    ))
    ss.add(ParagraphStyle(
        'JobDate', parent=ss['Normal'],
        fontSize=8, leading=11, textColor=COLOR_MUTED,
        spaceAfter=3,
    ))
    ss.add(ParagraphStyle(
        'ResumeBullet', parent=ss['Normal'],
        fontSize=9, leading=12, textColor=COLOR_BODY,
        leftIndent=12, spaceAfter=2,
    ))
    ss.add(ParagraphStyle(
        'BodyText_Resume', parent=ss['Normal'],
        fontSize=9, leading=13, textColor=COLOR_BODY,
        spaceAfter=4,
    ))
    ss.add(ParagraphStyle(
        'SkillList', parent=ss['Normal'],
        fontSize=9, leading=12, textColor=COLOR_BODY,
        leftIndent=12, spaceAfter=2,
    ))
    ss.add(ParagraphStyle(
        'EduDegree', parent=ss['Normal'],
        fontSize=10, leading=13, textColor=COLOR_SECONDARY,
        fontName='Helvetica-Bold', spaceBefore=4, spaceAfter=1,
    ))
    ss.add(ParagraphStyle(
        'EduInstitution', parent=ss['Normal'],
        fontSize=9, leading=12, textColor=COLOR_BODY,
        spaceAfter=1,
    ))
    ss.add(ParagraphStyle(
        'EduDate', parent=ss['Normal'],
        fontSize=8, leading=11, textColor=COLOR_MUTED,
        spaceAfter=3,
    ))
    ss.add(ParagraphStyle(
        'CertName', parent=ss['Normal'],
        fontSize=9, leading=12, textColor=COLOR_BODY,
        spaceBefore=2, spaceAfter=1,
    ))
    ss.add(ParagraphStyle(
        'ProjectName', parent=ss['Normal'],
        fontSize=9, leading=12, textColor=COLOR_SECONDARY,
        fontName='Helvetica-Bold', spaceBefore=4, spaceAfter=1,
    ))
    ss.add(ParagraphStyle(
        'ProjectDesc', parent=ss['Normal'],
        fontSize=9, leading=12, textColor=COLOR_BODY,
        leftIndent=12, spaceAfter=2,
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

    elements.append(Paragraph(_safe(name), styles['ResumeName']))

    parts = []
    if contact.get('email'):
        parts.append(f'✉ {_safe(contact["email"])}')
    if contact.get('phone'):
        parts.append(f'☎ {_safe(contact["phone"])}')
    if contact.get('location'):
        parts.append(f'📍 {_safe(contact["location"])}')
    if parts:
        elements.append(Paragraph(' &nbsp;&nbsp; '.join(parts), styles['ContactInfo']))

    links = []
    if contact.get('linkedin'):
        links.append(_safe(contact['linkedin']))
    if contact.get('portfolio'):
        links.append(_safe(contact['portfolio']))
    if links:
        elements.append(Paragraph(' &nbsp;|&nbsp; '.join(links), styles['ContactInfo']))

    elements.append(Spacer(1, 4 * mm))
    return elements


def _build_summary(content, styles):
    summary = content.get('summary', '')
    if not summary:
        return []
    return [
        Paragraph('About Me', styles['SectionTitle']),
        Spacer(1, 2 * mm),
        Paragraph(_safe(summary), styles['BodyText_Resume']),
        Spacer(1, 2 * mm),
    ]


def _build_experience(content, styles):
    experience = content.get('experience', [])
    if not experience:
        return []
    elements = [
        Paragraph('Work Experience', styles['SectionTitle']),
        Spacer(1, 2 * mm),
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
            job_block.append(Paragraph(f'→ {_safe(bullet)}', styles['ResumeBullet']))
        elements.append(KeepTogether(job_block))
    elements.append(Spacer(1, 2 * mm))
    return elements


def _build_education(content, styles):
    education = content.get('education', [])
    if not education:
        return []
    elements = [
        Paragraph('Education', styles['SectionTitle']),
        Spacer(1, 2 * mm),
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
    elements.append(Spacer(1, 2 * mm))
    return elements


def _build_skills(content, styles):
    skills = content.get('skills', {})
    if not skills:
        return []
    has_any = any(skills.get(cat) for cat in ('technical', 'tools', 'soft'))
    if not has_any:
        return []
    elements = [
        Paragraph('Skills & Tools', styles['SectionTitle']),
        Spacer(1, 2 * mm),
    ]
    category_labels = {'technical': 'Technical', 'tools': 'Tools & Platforms', 'soft': 'Soft Skills'}
    for cat_key, cat_label in category_labels.items():
        items = skills.get(cat_key, [])
        if items:
            skill_list = ' • '.join([_safe(s) for s in items])
            elements.append(Paragraph(f'<b>{_safe(cat_label)}:</b> {skill_list}', styles['SkillList']))
    elements.append(Spacer(1, 2 * mm))
    return elements


def _build_certifications(content, styles):
    certs = content.get('certifications', [])
    if not certs:
        return []
    elements = [
        Paragraph('Certifications', styles['SectionTitle']),
        Spacer(1, 2 * mm),
    ]
    for cert in certs:
        parts = [_safe(cert.get('name', ''))]
        if cert.get('issuer'):
            parts.append(f'— {_safe(cert["issuer"])}')
        if cert.get('year'):
            parts.append(f'({_safe(cert["year"])})')
        elements.append(Paragraph(' '.join(parts), styles['CertName']))
    elements.append(Spacer(1, 2 * mm))
    return elements


def _build_projects(content, styles):
    projects = content.get('projects', [])
    if not projects:
        return []
    elements = [
        Paragraph('Projects', styles['SectionTitle']),
        Spacer(1, 2 * mm),
    ]
    for proj in projects:
        proj_block = []
        proj_block.append(Paragraph(_safe(proj.get('name', '')), styles['ProjectName']))
        if proj.get('description'):
            proj_block.append(Paragraph(_safe(proj['description']), styles['ProjectDesc']))
        techs = proj.get('technologies', [])
        if techs:
            tech_str = ', '.join([_safe(t) for t in techs])
            proj_block.append(Paragraph(f'<i>Built with: {tech_str}</i>', styles['ProjectDesc']))
        if proj.get('url'):
            proj_block.append(Paragraph(_safe(proj['url']), styles['ProjectDesc']))
        elements.append(KeepTogether(proj_block))
    elements.append(Spacer(1, 2 * mm))
    return elements


# ── Main renderer ────────────────────────────────────────────────────────

def render_creative_pdf(resume_content: dict) -> bytes:
    """Render structured resume JSON into a creative-styled PDF."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
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
