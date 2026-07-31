"""
PDF generation for job seeker CVs.

Generation is split into "layouts" (currently single-column and
sidebar/two-column). Each template in cv_templates.TEMPLATE_REGISTRY
picks a layout + an accent color, so new templates almost never need
new PDF code - they just reuse one of the existing layout builders.
"""
import io
import re

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import (
    Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle, HRFlowable,
)

from .cv_templates import get_template_meta


def _format_lines(raw_text):
    return [line.strip() for line in re.split(r'[\r\n]+', raw_text or '') if line.strip()]


def _skills_list(raw_text):
    return [skill.strip() for skill in re.split(r'[\n,]+', raw_text or '') if skill.strip()]


def _summary_text(profile):
    summary_text = 'Professional job seeker with a strong focus on delivering value in every role.'
    skills_list = _skills_list(profile.skills)
    if skills_list:
        summary_text = (
            f"Experienced professional with skills in {skills_list[0]} "
            f"and a strong record of accomplishment."
        )
    return summary_text


def _build_styles(accent_hex):
    styles = getSampleStyleSheet()
    accent = colors.HexColor(accent_hex)
    return {
        'name': ParagraphStyle(
            'NameStyle', parent=styles['Heading1'], fontSize=24, leading=28,
            spaceAfter=6, textColor=accent,
        ),
        'contact': ParagraphStyle(
            'ContactStyle', parent=styles['Normal'], fontSize=9.5, leading=12,
            textColor=colors.HexColor('#555555'), spaceAfter=10,
        ),
        'section': ParagraphStyle(
            'SectionTitle', parent=styles['Heading2'], fontSize=12, leading=14,
            spaceBefore=10, spaceAfter=6, textColor=accent,
        ),
        'normal': ParagraphStyle(
            'NormalText', parent=styles['BodyText'], fontSize=10.5, leading=14,
            spaceAfter=4,
        ),
        'bullet': ParagraphStyle(
            'BulletText', parent=styles['BodyText'], fontSize=10.5, leading=14,
            leftIndent=12, spaceAfter=2,
        ),
        'sidebar_title': ParagraphStyle(
            'SidebarTitle', parent=styles['Heading3'], fontSize=11, leading=13,
            textColor=colors.white, spaceBefore=10, spaceAfter=4,
        ),
        'sidebar_text': ParagraphStyle(
            'SidebarText', parent=styles['Normal'], fontSize=9.5, leading=13,
            textColor=colors.white, spaceAfter=4,
        ),
    }


def _section_bullets(title, raw_text, section_style, bullet_style):
    items = _format_lines(raw_text)
    if not items:
        return []
    block = [Paragraph(title, section_style)]
    for item in items:
        block.append(Paragraph(f'<bullet>&bull;</bullet> {item}', bullet_style))
    return block


def _build_single_column_pdf(profile, accent_hex):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter,
        rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40,
    )
    s = _build_styles(accent_hex)

    story = [Paragraph(profile.full_name or 'Job Seeker', s['name'])]

    contact_parts = [p for p in [
        profile.email, profile.phone_number, profile.address,
        profile.linkedin_url, profile.github_url,
    ] if p]
    if contact_parts:
        story.append(Paragraph(' | '.join(contact_parts), s['contact']))

    story.append(HRFlowable(width='100%', thickness=1, color=colors.HexColor('#cccccc')))
    story.append(Spacer(1, 12))

    story.append(Paragraph('Professional Summary', s['section']))
    story.append(Paragraph(_summary_text(profile), s['normal']))

    skills = _skills_list(profile.skills)
    if skills:
        story.append(Paragraph('Skills', s['section']))
        story.append(Paragraph(', '.join(skills), s['normal']))

    story.extend(_section_bullets('Work Experience', profile.work_experience, s['section'], s['bullet']))
    story.extend(_section_bullets('Education', profile.education, s['section'], s['bullet']))
    story.extend(_section_bullets('Projects', profile.projects, s['section'], s['bullet']))
    story.extend(_section_bullets('Certifications', profile.certifications, s['section'], s['bullet']))

    doc.build(story)
    buffer.seek(0)
    return buffer


def _build_sidebar_pdf(profile, accent_hex):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter,
        rightMargin=0, leftMargin=0, topMargin=0, bottomMargin=0,
    )
    s = _build_styles(accent_hex)
    accent = colors.HexColor(accent_hex)

    sidebar_name_style = ParagraphStyle(
        'SBName', parent=s['sidebar_title'], fontSize=15, spaceBefore=0, spaceAfter=10,
    )
    sidebar_flow = [Paragraph(profile.full_name or 'Job Seeker', sidebar_name_style)]

    contact_lines = [p for p in [
        profile.email, profile.phone_number, profile.address,
        profile.linkedin_url, profile.github_url,
    ] if p]
    if contact_lines:
        sidebar_flow.append(Paragraph('Contact', s['sidebar_title']))
        for line in contact_lines:
            sidebar_flow.append(Paragraph(line, s['sidebar_text']))

    skills = _skills_list(profile.skills)
    if skills:
        sidebar_flow.append(Paragraph('Skills', s['sidebar_title']))
        for skill in skills:
            sidebar_flow.append(Paragraph(f'• {skill}', s['sidebar_text']))

    education_items = _format_lines(profile.education)
    if education_items:
        sidebar_flow.append(Paragraph('Education', s['sidebar_title']))
        for item in education_items:
            sidebar_flow.append(Paragraph(item, s['sidebar_text']))

    certification_items = _format_lines(profile.certifications)
    if certification_items:
        sidebar_flow.append(Paragraph('Certifications', s['sidebar_title']))
        for item in certification_items:
            sidebar_flow.append(Paragraph(item, s['sidebar_text']))

    main_flow = [
        Paragraph('Professional Summary', s['section']),
        Paragraph(_summary_text(profile), s['normal']),
    ]
    main_flow.extend(_section_bullets('Work Experience', profile.work_experience, s['section'], s['bullet']))
    main_flow.extend(_section_bullets('Projects', profile.projects, s['section'], s['bullet']))

    table = Table([[sidebar_flow, main_flow]], colWidths=[180, 432])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, 0), accent),
        ('LEFTPADDING', (0, 0), (0, 0), 18),
        ('RIGHTPADDING', (0, 0), (0, 0), 18),
        ('LEFTPADDING', (1, 0), (1, 0), 30),
        ('RIGHTPADDING', (1, 0), (1, 0), 30),
        ('TOPPADDING', (0, 0), (-1, -1), 30),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 30),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))

    doc.build([table])
    buffer.seek(0)
    return buffer


# Maps a template's "layout" value to the function that renders it.
# Add a new layout here only if a genuinely new structure is needed -
# most new templates should just reuse "single" or "sidebar".
LAYOUT_BUILDERS = {
    'single': _build_single_column_pdf,
    'sidebar': _build_sidebar_pdf,
}


def build_pdf_for_profile(profile, template_id):
    """Build a PDF buffer for the given profile, styled per the given template id."""
    meta = get_template_meta(template_id)
    builder = LAYOUT_BUILDERS.get(meta['layout'], _build_single_column_pdf)
    return builder(profile, meta['accent'])