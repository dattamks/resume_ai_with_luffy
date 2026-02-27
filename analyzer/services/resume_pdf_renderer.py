"""
ATS-optimized resume PDF renderer.

Renders structured resume JSON (from LLM rewrite) into a clean,
single-column, ATS-compatible PDF using ReportLab.

Template: ats_classic — maximally ATS-safe:
- Single column layout
- Standard section headings (Summary, Experience, Education, Skills)
- No tables, graphics, images, or multi-column content
- Clean serif/sans-serif font pairing
- Consistent spacing and hierarchy
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

COLOR_PRIMARY = colors.HexColor('#1a1a2e')      # Dark navy for headings
COLOR_SECONDARY = colors.HexColor('#16213e')     # Slightly lighter for subheadings
COLOR_BODY = colors.HexColor('#2c3e50')          # Body text
COLOR_MUTED = colors.HexColor('#7f8c8d')         # Dates, locations
COLOR_ACCENT = colors.HexColor('#2980b9')        # Links, subtle accents
COLOR_DIVIDER = colors.HexColor('#bdc3c7')       # Section dividers
COLOR_SKILL_BG = colors.HexColor('#ecf0f1')      # Skill tag background


# ── Styles ───────────────────────────────────────────────────────────────

def _build_styles():
    ss = getSampleStyleSheet()

    ss.add(ParagraphStyle(
        'ResumeName', parent=ss['Title'],
        fontSize=20, leading=24, textColor=COLOR_PRIMARY,
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
        fontSize=12, leading=15, textColor=COLOR_PRIMARY,
        fontName='Helvetica-Bold', spaceBefore=10, spaceAfter=4,
        borderWidth=0,
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
        bulletIndent=0, bulletFontSize=9,
    ))
    ss.add(ParagraphStyle(
        'BodyText_Resume', parent=ss['Normal'],
        fontSize=9, leading=13, textColor=COLOR_BODY,
        spaceAfter=4,
    ))
    ss.add(ParagraphStyle(
        'SkillCategory', parent=ss['Normal'],
        fontSize=9, leading=12, textColor=COLOR_SECONDARY,
        fontName='Helvetica-Bold', spaceAfter=1,
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
    """Escape XML special chars for ReportLab Paragraph."""
    if not text:
        return ''
    return (
        str(text)
        .replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
    )


# ── Section builders ─────────────────────────────────────────────────────

def _build_contact(content, styles):
    """Build contact header: name centered, contact details on one line."""
    elements = []
    contact = content.get('contact', {})
    name = contact.get('name', 'Candidate')

    elements.append(Paragraph(_safe(name), styles['ResumeName']))

    # Build contact line: email | phone | location | linkedin
    parts = []
    if contact.get('email'):
        parts.append(_safe(contact['email']))
    if contact.get('phone'):
        parts.append(_safe(contact['phone']))
    if contact.get('location'):
        parts.append(_safe(contact['location']))
    if parts:
        elements.append(Paragraph(' &nbsp;|&nbsp; '.join(parts), styles['ContactInfo']))

    # LinkedIn / portfolio on separate line
    links = []
    if contact.get('linkedin'):
        links.append(_safe(contact['linkedin']))
    if contact.get('portfolio'):
        links.append(_safe(contact['portfolio']))
    if links:
        elements.append(Paragraph(' &nbsp;|&nbsp; '.join(links), styles['ContactInfo']))

    elements.append(Spacer(1, 4 * mm))
    elements.append(HRFlowable(width='100%', thickness=0.5, color=COLOR_DIVIDER, spaceAfter=6))

    return elements


def _build_summary(content, styles):
    """Build professional summary section."""
    summary = content.get('summary', '')
    if not summary:
        return []

    return [
        Paragraph('PROFESSIONAL SUMMARY', styles['SectionTitle']),
        Paragraph(_safe(summary), styles['BodyText_Resume']),
        Spacer(1, 2 * mm),
    ]


def _build_experience(content, styles):
    """Build work experience section."""
    experience = content.get('experience', [])
    if not experience:
        return []

    elements = [
        Paragraph('WORK EXPERIENCE', styles['SectionTitle']),
        HRFlowable(width='100%', thickness=0.3, color=COLOR_DIVIDER, spaceAfter=4),
    ]

    for exp in experience:
        title = _safe(exp.get('title', ''))
        company = _safe(exp.get('company', ''))
        location = _safe(exp.get('location', ''))
        start = _safe(exp.get('start_date', ''))
        end = _safe(exp.get('end_date', ''))

        job_block = []
        job_block.append(Paragraph(title, styles['JobTitle']))

        company_line = company
        if location:
            company_line += f' — {location}'
        job_block.append(Paragraph(company_line, styles['JobCompany']))

        if start or end:
            date_line = f'{start} – {end}' if start and end else (start or end)
            job_block.append(Paragraph(date_line, styles['JobDate']))

        for bullet in exp.get('bullets', []):
            bullet_text = _safe(bullet)
            job_block.append(
                Paragraph(f'• {bullet_text}', styles['ResumeBullet'])
            )

        elements.append(KeepTogether(job_block))

    elements.append(Spacer(1, 2 * mm))
    return elements


def _build_education(content, styles):
    """Build education section."""
    education = content.get('education', [])
    if not education:
        return []

    elements = [
        Paragraph('EDUCATION', styles['SectionTitle']),
        HRFlowable(width='100%', thickness=0.3, color=COLOR_DIVIDER, spaceAfter=4),
    ]

    for edu in education:
        degree = _safe(edu.get('degree', ''))
        institution = _safe(edu.get('institution', ''))
        location = _safe(edu.get('location', ''))
        year = _safe(edu.get('year', ''))
        gpa = _safe(edu.get('gpa', ''))

        edu_block = []
        edu_block.append(Paragraph(degree, styles['EduDegree']))

        inst_line = institution
        if location:
            inst_line += f' — {location}'
        edu_block.append(Paragraph(inst_line, styles['EduInstitution']))

        details = []
        if year:
            details.append(year)
        if gpa:
            details.append(f'GPA: {gpa}')
        if details:
            edu_block.append(Paragraph(' | '.join(details), styles['EduDate']))

        elements.append(KeepTogether(edu_block))

    elements.append(Spacer(1, 2 * mm))
    return elements


def _build_skills(content, styles):
    """Build skills section — grouped by category."""
    skills = content.get('skills', {})
    if not skills:
        return []

    has_any = any(skills.get(cat) for cat in ('technical', 'tools', 'soft'))
    if not has_any:
        return []

    elements = [
        Paragraph('SKILLS', styles['SectionTitle']),
        HRFlowable(width='100%', thickness=0.3, color=COLOR_DIVIDER, spaceAfter=4),
    ]

    category_labels = {
        'technical': 'Technical Skills',
        'tools': 'Tools & Platforms',
        'soft': 'Soft Skills',
    }

    for cat_key, cat_label in category_labels.items():
        items = skills.get(cat_key, [])
        if items:
            skill_list = ', '.join([_safe(s) for s in items])
            elements.append(
                Paragraph(
                    f'<b>{_safe(cat_label)}:</b> {skill_list}',
                    styles['SkillList'],
                )
            )

    elements.append(Spacer(1, 2 * mm))
    return elements


def _build_certifications(content, styles):
    """Build certifications section."""
    certs = content.get('certifications', [])
    if not certs:
        return []

    elements = [
        Paragraph('CERTIFICATIONS', styles['SectionTitle']),
        HRFlowable(width='100%', thickness=0.3, color=COLOR_DIVIDER, spaceAfter=4),
    ]

    for cert in certs:
        name = _safe(cert.get('name', ''))
        issuer = _safe(cert.get('issuer', ''))
        year = _safe(cert.get('year', ''))

        parts = [name]
        if issuer:
            parts.append(f'— {issuer}')
        if year:
            parts.append(f'({year})')

        elements.append(Paragraph(' '.join(parts), styles['CertName']))

    elements.append(Spacer(1, 2 * mm))
    return elements


def _build_projects(content, styles):
    """Build projects section."""
    projects = content.get('projects', [])
    if not projects:
        return []

    elements = [
        Paragraph('PROJECTS', styles['SectionTitle']),
        HRFlowable(width='100%', thickness=0.3, color=COLOR_DIVIDER, spaceAfter=4),
    ]

    for proj in projects:
        name = _safe(proj.get('name', ''))
        desc = _safe(proj.get('description', ''))
        techs = proj.get('technologies', [])
        url = _safe(proj.get('url', ''))

        proj_block = []
        proj_block.append(Paragraph(name, styles['ProjectName']))
        if desc:
            proj_block.append(Paragraph(desc, styles['ProjectDesc']))
        if techs:
            tech_str = ', '.join([_safe(t) for t in techs])
            proj_block.append(
                Paragraph(f'<i>Technologies: {tech_str}</i>', styles['ProjectDesc'])
            )
        if url:
            proj_block.append(Paragraph(url, styles['ProjectDesc']))

        elements.append(KeepTogether(proj_block))

    elements.append(Spacer(1, 2 * mm))
    return elements


# ── Main renderer ────────────────────────────────────────────────────────

def render_resume_pdf(resume_content: dict) -> bytes:
    """
    Render structured resume JSON into an ATS-optimized PDF.

    Args:
        resume_content: Validated resume JSON from LLM rewrite.

    Returns:
        PDF bytes.
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title='Resume',
        author=resume_content.get('contact', {}).get('name', 'Candidate'),
    )

    styles = _build_styles()
    elements = []

    # Build all sections in order
    elements.extend(_build_contact(resume_content, styles))
    elements.extend(_build_summary(resume_content, styles))
    elements.extend(_build_experience(resume_content, styles))
    elements.extend(_build_education(resume_content, styles))
    elements.extend(_build_skills(resume_content, styles))
    elements.extend(_build_certifications(resume_content, styles))
    elements.extend(_build_projects(resume_content, styles))

    doc.build(elements)
    return buf.getvalue()
