"""
PDF generation for job seeker CVs.

Generation is split into "layouts" (single, sidebar, banded - see
cv_templates.py for what each means). Each layout is further shaped by
font family and heading style, so templates that share a layout still
look meaningfully different. New templates almost never need new PDF
code - they just combine an existing layout with a font/heading style.
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

FONT_FAMILIES = {
    'sans': {'normal': 'Helvetica', 'bold': 'Helvetica-Bold'},
    'serif': {'normal': 'Times-Roman', 'bold': 'Times-Bold'},
}


def _format_lines(raw_text):
    return [line.strip() for line in re.split(r'[\r\n]+', raw_text or '') if line.strip()]


def _parse_entry_blocks(raw_text):
    """Split text into blocks separated by a blank line. Each block's first
    line becomes a bold sub-title; the remaining lines become bullet points
    under it. Used for the Projects field, so multiple projects can each
    have their own bold title within a single "Projects" section."""
    blocks = re.split(r'\n\s*\n', (raw_text or '').strip())
    entries = []
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        entries.append({'title': lines[0], 'details': lines[1:]})
    return entries


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


def _contact_parts(profile):
    return [p for p in [
        profile.email, profile.phone_number, profile.address,
        profile.linkedin_url, profile.github_url,
    ] if p]


def _build_styles(accent_hex, font_key, text_color=None):
    """Build the base paragraph styles for a given accent color + font family."""
    fonts = FONT_FAMILIES.get(font_key, FONT_FAMILIES['sans'])
    styles = getSampleStyleSheet()
    accent = colors.HexColor(accent_hex)
    body_color = text_color or colors.HexColor('#1f2937')

    return {
        'accent': accent,
        'fonts': fonts,
        'name': ParagraphStyle(
            'NameStyle', parent=styles['Heading1'], fontName=fonts['bold'],
            fontSize=24, leading=28, spaceAfter=6, textColor=accent,
        ),
        'contact': ParagraphStyle(
            'ContactStyle', parent=styles['Normal'], fontName=fonts['normal'],
            fontSize=9.5, leading=12, textColor=colors.HexColor('#555555'), spaceAfter=10,
        ),
        'section': ParagraphStyle(
            'SectionTitle', parent=styles['Heading2'], fontName=fonts['bold'],
            fontSize=12, leading=14, spaceBefore=12, spaceAfter=4, textColor=accent,
        ),
        'normal': ParagraphStyle(
            'NormalText', parent=styles['BodyText'], fontName=fonts['normal'],
            fontSize=10.5, leading=14, spaceAfter=4, textColor=body_color,
        ),
        'bullet': ParagraphStyle(
            'BulletText', parent=styles['BodyText'], fontName=fonts['normal'],
            fontSize=10.5, leading=14, leftIndent=12, spaceAfter=2, textColor=body_color,
        ),
        'entry_title': ParagraphStyle(
            'EntryTitle', parent=styles['BodyText'], fontName=fonts['bold'],
            fontSize=10.5, leading=14, spaceBefore=8, spaceAfter=2, textColor=body_color,
        ),
        'sidebar_title': ParagraphStyle(
            'SidebarTitle', parent=styles['Heading3'], fontName=fonts['bold'],
            fontSize=11, leading=13, textColor=colors.white, spaceBefore=12, spaceAfter=4,
        ),
        'sidebar_text': ParagraphStyle(
            'SidebarText', parent=styles['Normal'], fontName=fonts['normal'],
            fontSize=9.5, leading=13, textColor=colors.white, spaceAfter=4,
        ),
    }


def _heading_flowables(title, heading_style, s):
    """Render a section heading as a list of flowables, styled per heading_style.
    Keeps the three visual "families" (underline / block / plain caps) distinct
    across every template that uses them, regardless of layout."""
    if heading_style == 'block':
        chip_style = ParagraphStyle(
            'Chip', fontName=s['fonts']['bold'], fontSize=9.5,
            leading=12, textColor=colors.white,
        )
        chip = Table([[Paragraph(title.upper(), chip_style)]], colWidths=[170])
        chip.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), s['accent']),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        return [Spacer(1, 8), chip, Spacer(1, 4)]

    if heading_style == 'plain_caps':
        return [Paragraph(title.upper(), s['section'])]

    # default: underline
    return [
        Paragraph(title, s['section']),
        HRFlowable(width='100%', thickness=1, color=s['accent'], spaceAfter=4),
    ]


def _section_bullets(title, raw_text, heading_style, s):
    items = _format_lines(raw_text)
    if not items:
        return []
    block = _heading_flowables(title, heading_style, s)
    for item in items:
        block.append(Paragraph(f'<bullet>&bull;</bullet> {item}', s['bullet']))
    return block


def _project_entries_flowables(title, raw_text, heading_style, s):
    """Renders the Projects section with each project's title in bold,
    followed by its own bullet points - unlike other sections, which are a
    single flat bullet list."""
    entries = _parse_entry_blocks(raw_text)
    if not entries:
        return []
    block = _heading_flowables(title, heading_style, s)
    for entry in entries:
        block.append(Paragraph(entry['title'], s['entry_title']))
        for line in entry['details']:
            block.append(Paragraph(f'<bullet>&bull;</bullet> {line}', s['bullet']))
    return block


def _additional_info_flowables(profile, heading_style, s):
    """Renders every user-defined Additional Info entry as its own section
    (entry.title as the heading, entry.details as bullet points) so people
    can add as many custom sections - Achievements, Publications, whatever
    they like - as they want."""
    flow = []
    for entry in profile.additional_info.all():
        flow.extend(_section_bullets(entry.title, entry.details, heading_style, s))
    return flow


# ──────────────────────────────────────────────────────────────
# Layout 1: single column (top header, full-width body)
# ──────────────────────────────────────────────────────────────
def _build_single_column_pdf(profile, meta):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter,
        rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40,
    )
    s = _build_styles(meta['accent'], meta['font'])

    story = [Paragraph(profile.full_name or 'Job Seeker', s['name'])]

    contact_parts = _contact_parts(profile)
    if contact_parts:
        story.append(Paragraph(' | '.join(contact_parts), s['contact']))

    if meta.get('divider', True):
        story.append(HRFlowable(width='100%', thickness=1, color=colors.HexColor('#cccccc')))
        story.append(Spacer(1, 10))

    heading_style = meta['heading_style']
    story.extend(_heading_flowables('Professional Summary', heading_style, s))
    story.append(Paragraph(_summary_text(profile), s['normal']))

    skills = _skills_list(profile.skills)
    if skills:
        story.extend(_heading_flowables('Skills', heading_style, s))
        story.append(Paragraph(', '.join(skills), s['normal']))

    story.extend(_section_bullets('Work Experience', profile.work_experience, heading_style, s))
    story.extend(_section_bullets('Education', profile.education, heading_style, s))
    story.extend(_project_entries_flowables('Projects', profile.projects, heading_style, s))
    story.extend(_section_bullets('Certifications', profile.certifications, heading_style, s))
    story.extend(_additional_info_flowables(profile, heading_style, s))

    doc.build(story)
    buffer.seek(0)
    return buffer


# ──────────────────────────────────────────────────────────────
# Layout 2: sidebar (full-height colored column + white main column)
# ──────────────────────────────────────────────────────────────
def _build_sidebar_pdf(profile, meta):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter,
        rightMargin=0, leftMargin=0, topMargin=0, bottomMargin=0,
    )
    s = _build_styles(meta['accent'], meta['font'])
    accent = s['accent']

    sidebar_name_style = ParagraphStyle(
        'SBName', parent=s['sidebar_title'], fontSize=15, spaceBefore=0, spaceAfter=10,
    )
    sidebar_flow = [Paragraph(profile.full_name or 'Job Seeker', sidebar_name_style)]

    contact_lines = _contact_parts(profile)
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

    heading_style = meta['heading_style']
    main_flow = _heading_flowables('Professional Summary', heading_style, s)
    main_flow.append(Paragraph(_summary_text(profile), s['normal']))
    main_flow.extend(_section_bullets('Work Experience', profile.work_experience, heading_style, s))
    main_flow.extend(_project_entries_flowables('Projects', profile.projects, heading_style, s))
    main_flow.extend(_additional_info_flowables(profile, heading_style, s))

    sidebar_col = (180, sidebar_flow)
    main_col = (432, main_flow)
    columns = [sidebar_col, main_col] if meta.get('sidebar_side', 'left') == 'left' else [main_col, sidebar_col]
    col_widths = [c[0] for c in columns]
    col_content = [c[1] for c in columns]
    sidebar_index = 0 if meta.get('sidebar_side', 'left') == 'left' else 1
    main_index = 1 - sidebar_index

    table = Table([col_content], colWidths=col_widths)
    table.setStyle(TableStyle([
        ('BACKGROUND', (sidebar_index, 0), (sidebar_index, 0), accent),
        ('LEFTPADDING', (sidebar_index, 0), (sidebar_index, 0), 18),
        ('RIGHTPADDING', (sidebar_index, 0), (sidebar_index, 0), 18),
        ('LEFTPADDING', (main_index, 0), (main_index, 0), 30),
        ('RIGHTPADDING', (main_index, 0), (main_index, 0), 30),
        ('TOPPADDING', (0, 0), (-1, -1), 30),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 30),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))

    doc.build([table])
    buffer.seek(0)
    return buffer


# ──────────────────────────────────────────────────────────────
# Layout 3: banded (full-width colored header bar, plain 2-col body below)
# ──────────────────────────────────────────────────────────────
def _build_banded_pdf(profile, meta):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter,
        rightMargin=0, leftMargin=0, topMargin=0, bottomMargin=0,
    )
    s = _build_styles(meta['accent'], meta['font'])
    accent = s['accent']
    fonts = s['fonts']

    band_name_style = ParagraphStyle(
        'BandName', fontName=fonts['bold'], fontSize=22, leading=26, textColor=colors.white,
    )
    band_contact_style = ParagraphStyle(
        'BandContact', fontName=fonts['normal'], fontSize=9.5, leading=12,
        textColor=colors.whitesmoke, spaceBefore=4,
    )

    band_content = [Paragraph(profile.full_name or 'Job Seeker', band_name_style)]
    contact_parts = _contact_parts(profile)
    if contact_parts:
        band_content.append(Paragraph(' | '.join(contact_parts), band_contact_style))

    band = Table([[band_content]], colWidths=[612])
    band.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), accent),
        ('LEFTPADDING', (0, 0), (-1, -1), 40),
        ('RIGHTPADDING', (0, 0), (-1, -1), 40),
        ('TOPPADDING', (0, 0), (-1, -1), 28),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 28),
    ]))

    heading_style = meta['heading_style']
    main_flow = _heading_flowables('Professional Summary', heading_style, s)
    main_flow.append(Paragraph(_summary_text(profile), s['normal']))
    main_flow.extend(_section_bullets('Work Experience', profile.work_experience, heading_style, s))
    main_flow.extend(_project_entries_flowables('Projects', profile.projects, heading_style, s))

    side_flow = []
    skills = _skills_list(profile.skills)
    if skills:
        side_flow.extend(_heading_flowables('Skills', heading_style, s))
        side_flow.append(Paragraph(', '.join(skills), s['normal']))
    side_flow.extend(_section_bullets('Education', profile.education, heading_style, s))
    side_flow.extend(_section_bullets('Certifications', profile.certifications, heading_style, s))
    side_flow.extend(_additional_info_flowables(profile, heading_style, s))

    body = Table([[main_flow, side_flow]], colWidths=[370, 242])
    body.setStyle(TableStyle([
        ('LEFTPADDING', (0, 0), (0, 0), 40),
        ('RIGHTPADDING', (0, 0), (0, 0), 20),
        ('LEFTPADDING', (1, 0), (1, 0), 20),
        ('RIGHTPADDING', (1, 0), (1, 0), 40),
        ('TOPPADDING', (0, 0), (-1, -1), 24),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))

    doc.build([band, body])
    buffer.seek(0)
    return buffer


# Maps a template's "layout" value to the function that renders it.
LAYOUT_BUILDERS = {
    'single': _build_single_column_pdf,
    'sidebar': _build_sidebar_pdf,
    'banded': _build_banded_pdf,
}


def build_pdf_for_profile(profile, template_id):
    """Build a PDF buffer for the given profile, styled per the given template id."""
    meta = get_template_meta(template_id)
    builder = LAYOUT_BUILDERS.get(meta['layout'], _build_single_column_pdf)
    return builder(profile, meta)