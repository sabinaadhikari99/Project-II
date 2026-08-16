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
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import (
    BaseDocTemplate, Frame, FrameBreak, KeepInFrame, NextPageTemplate, PageTemplate,
    Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle, HRFlowable,
)

from .cv_templates import get_template_meta

PAGE_WIDTH, PAGE_HEIGHT = letter

#: Vertical breathing room on every page of the full-bleed layouts. The
#: horizontal edges are deliberately left at zero so a colored sidebar or
#: header band reaches the paper edge.
BLEED_GUTTER = 30

#: The "block" heading chip, kept in step with the same chip in the HTML
#: preview (`templates/cvgen/cv_preview.html`, `.heading-block .section-title`).
#: Its 10px padding and 4px radius are scaled from the preview's 780px page to
#: this 612pt one, so the gallery and the download agree on what a chip is.
CHIP_PADDING = 8
CHIP_RADIUS = 3

FONT_FAMILIES = {
    'sans': {'normal': 'Helvetica', 'bold': 'Helvetica-Bold'},
    'serif': {'normal': 'Times-Roman', 'bold': 'Times-Bold'},
}


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


def _contact_parts(profile):
    return [p for p in [
        profile.email, profile.phone_number, profile.address,
        profile.linkedin_url, profile.github_url,
    ] if p]


def _column_frame(x, width, pad, top=PAGE_HEIGHT, frame_id='col'):
    """One column of a two-column page, running to the paper edge horizontally.

    `top` is where the column starts, which the banded layout lowers to sit
    below its header band.
    """
    bottom = BLEED_GUTTER
    return Frame(
        x, bottom, width, top - bottom, id=frame_id,
        leftPadding=pad, rightPadding=pad,
        topPadding=BLEED_GUTTER, bottomPadding=0,
    )


def _two_column_doc(buffer, page_one_frames, flowing_frame, on_first=None):
    """A document whose second and later pages carry only the flowing column.

    Both two-column layouts used to be a single Table row holding an entire
    column in each cell. A table row cannot break, so the moment someone's CV
    outgrew one page ReportLab raised LayoutError rather than continuing - the
    bug this replaces. Splitting inside the row is not a fix either: ReportLab
    fails to converge on content this size and never returns.

    Frames are the construct that actually flows. The narrow column is filled
    first and closed off with a FrameBreak, and continuation pages define only
    the wide column, so overflow can never land in the space the sidebar
    occupies.
    """
    doc = BaseDocTemplate(
        buffer, pagesize=letter,
        leftMargin=0, rightMargin=0, topMargin=0, bottomMargin=0,
    )
    doc.addPageTemplates([
        PageTemplate(id='first', frames=page_one_frames, onPage=on_first or _noop_page),
        PageTemplate(id='later', frames=[flowing_frame], onPage=on_first or _noop_page),
    ])
    return doc


def _noop_page(_canvas, _doc):
    pass


def _column_painter(x, width, color):
    """Paints a full-height block of color behind one column.

    Drawn onto the page rather than set as a table BACKGROUND so the color
    covers the whole sheet on every page. A table background only ever covers
    the height of its own content, which left the color stopping partway down.
    """
    def draw(canvas, _doc):
        canvas.saveState()
        canvas.setFillColor(color)
        canvas.rect(x, 0, width, PAGE_HEIGHT, stroke=0, fill=1)
        canvas.restoreState()
    return draw


def _fitted(flow, width, height, pad):
    """Content guaranteed not to escape its column.

    The narrow column is filled before the wide one, so anything it could not
    hold would spill into the main column and land on top of the layout.
    Shrinking is the lesser evil, and only bites on a genuinely overloaded CV.
    """
    return KeepInFrame(
        width - 2 * pad, height - BLEED_GUTTER,
        flow, mode='shrink',
    )


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
        'entry_subtitle': ParagraphStyle(
            'EntrySubtitle', parent=styles['BodyText'], fontName=fonts['normal'],
            fontSize=9.5, leading=13, spaceAfter=4, textColor=colors.HexColor('#6b7280'),
        ),
        'sidebar_title': ParagraphStyle(
            'SidebarTitle', parent=styles['Heading3'], fontName=fonts['bold'],
            fontSize=11, leading=13, textColor=colors.white, spaceBefore=12, spaceAfter=4,
        ),
        'sidebar_text': ParagraphStyle(
            'SidebarText', parent=styles['Normal'], fontName=fonts['normal'],
            fontSize=9.5, leading=13, textColor=colors.white, spaceAfter=4,
        ),
        'sidebar_entry_title': ParagraphStyle(
            'SidebarEntryTitle', parent=styles['Normal'], fontName=fonts['bold'],
            fontSize=9.5, leading=13, textColor=colors.white, spaceBefore=6, spaceAfter=1,
        ),
    }


def _heading_flowables(title, heading_style, s):
    """Render a section heading as a list of flowables, styled per heading_style.
    Keeps the three visual "families" (underline / block / plain caps) distinct
    across every template that uses them, regardless of layout."""
    if heading_style == 'block':
        label = title.upper()
        chip_style = ParagraphStyle(
            'Chip', fontName=s['fonts']['bold'], fontSize=9.5,
            leading=12, textColor=colors.white,
        )
        # Sized to its own text and pinned left, which is what the HTML preview
        # draws with `display: inline-block`. A fixed 170pt width turned every
        # heading into a wide bar, and a Table defaults to hAlign CENTER, so
        # each bar also sat in the middle of the page - neither of which is the
        # design the user picked from the gallery.
        width = stringWidth(label, chip_style.fontName, chip_style.fontSize) + 2 * CHIP_PADDING
        chip = Table(
            [[Paragraph(label, chip_style)]],
            colWidths=[width], hAlign='LEFT',
            cornerRadii=[CHIP_RADIUS] * 4,
        )
        chip.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), s['accent']),
            ('LEFTPADDING', (0, 0), (-1, -1), CHIP_PADDING),
            ('RIGHTPADDING', (0, 0), (-1, -1), CHIP_PADDING),
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


def _project_entries_flowables(title, profile, heading_style, s):
    """Renders the Projects section using each ProjectEntry's own Title
    (bold) and Details (bullet points) - no text parsing involved, so
    there's nothing for a user's formatting habits to trip up."""
    entries = list(profile.projects.all())
    if not entries:
        return []
    block = _heading_flowables(title, heading_style, s)
    for entry in entries:
        block.append(Paragraph(entry.title, s['entry_title']))
        for line in _format_lines(entry.details):
            block.append(Paragraph(f'<bullet>&bull;</bullet> {line}', s['bullet']))
    return block


def _education_entries_flowables(profile, s, dark=False):
    """Renders each EducationEntry as its degree (bold) followed by an
    'Institution • Year' line - no free-text parsing, since Degree,
    Institution, and Year are already separate fields. `dark=True` swaps in
    white-text styles for use inside a colored sidebar column."""
    title_style = s['sidebar_entry_title'] if dark else s['entry_title']
    subtitle_style = s['sidebar_text'] if dark else s['entry_subtitle']

    flow = []
    for entry in profile.education.all():
        flow.append(Paragraph(entry.degree, title_style))
        meta_parts = [p for p in [entry.institution, entry.year] if p]
        if meta_parts:
            flow.append(Paragraph(' • '.join(meta_parts), subtitle_style))
    return flow


def _education_section_flowables(title, profile, heading_style, s):
    """Education section for the single/banded layouts (white background):
    section heading (styled per heading_style) + the light-text entries."""
    entries_flow = _education_entries_flowables(profile, s, dark=False)
    if not entries_flow:
        return []
    return _heading_flowables(title, heading_style, s) + entries_flow


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
    story.extend(_education_section_flowables('Education', profile, heading_style, s))
    story.extend(_project_entries_flowables('Projects', profile, heading_style, s))
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

    education_flow = _education_entries_flowables(profile, s, dark=True)
    if education_flow:
        sidebar_flow.append(Paragraph('Education', s['sidebar_title']))
        sidebar_flow.extend(education_flow)

    certification_items = _format_lines(profile.certifications)
    if certification_items:
        sidebar_flow.append(Paragraph('Certifications', s['sidebar_title']))
        for item in certification_items:
            sidebar_flow.append(Paragraph(item, s['sidebar_text']))

    heading_style = meta['heading_style']
    main_flow = _heading_flowables('Professional Summary', heading_style, s)
    main_flow.append(Paragraph(_summary_text(profile), s['normal']))
    main_flow.extend(_section_bullets('Work Experience', profile.work_experience, heading_style, s))
    main_flow.extend(_project_entries_flowables('Projects', profile, heading_style, s))
    main_flow.extend(_additional_info_flowables(profile, heading_style, s))

    sidebar_width, main_width = 180, 432
    sidebar_pad, main_pad = 18, 30
    on_left = meta.get('sidebar_side', 'left') == 'left'
    sidebar_x = 0 if on_left else main_width
    main_x = sidebar_width if on_left else 0

    sidebar_frame = _column_frame(sidebar_x, sidebar_width, sidebar_pad, frame_id='sidebar')
    main_frame = _column_frame(main_x, main_width, main_pad, frame_id='main')

    # The sidebar is filled first, then closed off, so the main column starts in
    # its own frame and carries the overflow onto later pages by itself.
    doc = _two_column_doc(
        buffer,
        page_one_frames=[sidebar_frame, main_frame],
        flowing_frame=_column_frame(main_x, main_width, main_pad, frame_id='main'),
        on_first=_column_painter(sidebar_x, sidebar_width, accent),
    )

    doc.build([
        NextPageTemplate('later'),
        _fitted(sidebar_flow, sidebar_width, PAGE_HEIGHT, sidebar_pad),
        FrameBreak(),
        *main_flow,
    ])
    buffer.seek(0)
    return buffer


# ──────────────────────────────────────────────────────────────
# Layout 3: banded (full-width colored header bar, plain 2-col body below)
# ──────────────────────────────────────────────────────────────
def _build_banded_pdf(profile, meta):
    buffer = io.BytesIO()
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
    main_flow.extend(_project_entries_flowables('Projects', profile, heading_style, s))

    side_flow = []
    skills = _skills_list(profile.skills)
    if skills:
        side_flow.extend(_heading_flowables('Skills', heading_style, s))
        side_flow.append(Paragraph(', '.join(skills), s['normal']))
    side_flow.extend(_education_section_flowables('Education', profile, heading_style, s))
    side_flow.extend(_section_bullets('Certifications', profile.certifications, heading_style, s))
    side_flow.extend(_additional_info_flowables(profile, heading_style, s))

    # Frames rather than a two-cell table row, for the same reason as the
    # sidebar layout: a row cannot break, so this used to be one long CV away
    # from raising LayoutError.
    main_width, side_width = 370, 242
    main_pad, side_pad = 40, 20

    # The band is measured once and painted onto page one, so the columns below
    # can be positioned against a height that is already known.
    _, band_height = band.wrap(PAGE_WIDTH, PAGE_HEIGHT)
    columns_top = PAGE_HEIGHT - band_height

    def paint_band(canvas, doc):
        if doc.page == 1:
            band.drawOn(canvas, 0, columns_top)

    side_frame = _column_frame(main_width, side_width, side_pad, columns_top, 'side')
    main_frame = _column_frame(0, main_width, main_pad, columns_top, 'main')

    doc = _two_column_doc(
        buffer,
        # Listed side-first so the narrow column is filled and closed before the
        # main column begins; frame order is fill order, not left-to-right.
        page_one_frames=[side_frame, main_frame],
        flowing_frame=_column_frame(0, main_width, main_pad, frame_id='main'),
        on_first=paint_band,
    )

    doc.build([
        NextPageTemplate('later'),
        _fitted(side_flow, side_width, columns_top, side_pad),
        FrameBreak(),
        *main_flow,
    ])
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