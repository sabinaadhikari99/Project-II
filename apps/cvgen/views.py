import io
import re
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse
from django.views import View
from .models import JobSeekerProfile
from .forms import JobSeekerProfileForm
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle, HRFlowable


def _build_pdf_for_profile(profile):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
    styles = getSampleStyleSheet()

    name_style = ParagraphStyle(
        name='NameStyle',
        parent=styles['Heading1'],
        fontSize=24,
        leading=28,
        spaceAfter=6,
        textColor=colors.HexColor('#0a3d62'),
    )
    contact_style = ParagraphStyle(
        name='ContactStyle',
        parent=styles['Normal'],
        fontSize=9.5,
        leading=12,
        textColor=colors.HexColor('#555555'),
        spaceAfter=10,
    )
    section_title_style = ParagraphStyle(
        name='SectionTitle',
        parent=styles['Heading2'],
        fontSize=12,
        leading=14,
        spaceBefore=10,
        spaceAfter=6,
        textColor=colors.HexColor('#10316b'),
    )
    normal_style = ParagraphStyle(
        name='NormalText',
        parent=styles['BodyText'],
        fontSize=10.5,
        leading=14,
        spaceAfter=4,
    )
    bullet_style = ParagraphStyle(
        name='BulletText',
        parent=normal_style,
        leftIndent=12,
        bulletIndent=0,
        spaceAfter=2,
    )

    story = [Paragraph(profile.full_name or 'Job Seeker', name_style)]

    contact_parts = []
    if profile.email:
        contact_parts.append(profile.email)
    if profile.phone_number:
        contact_parts.append(profile.phone_number)
    if profile.address:
        contact_parts.append(profile.address)
    if profile.linkedin_url:
        contact_parts.append(profile.linkedin_url)
    if profile.github_url:
        contact_parts.append(profile.github_url)

    if contact_parts:
        story.append(Paragraph(' | '.join(contact_parts), contact_style))

    story.append(HRFlowable(width='100%', thickness=1, color=colors.HexColor('#cccccc')))
    story.append(Spacer(1, 12))

    def _format_lines(raw_text):
        return [line.strip() for line in re.split(r'[\r\n]+', raw_text) if line.strip()]

    def _section_bullets(title, raw_text):
        items = _format_lines(raw_text)
        if not items:
            return []
        section = [Paragraph(title, section_title_style)]
        for item in items:
            section.append(Paragraph(f'<bullet>&bull;</bullet> {item}', bullet_style))
        return section

    summary_text = 'Professional job seeker with a strong focus on delivering value in every role.'
    if profile.skills:
        skills_list = [skill.strip() for skill in re.split(r'[\n,]+', profile.skills) if skill.strip()]
        if skills_list:
            summary_text = f"Experienced professional with skills in {skills_list[0]} and a strong record of accomplishment."

    story.append(Paragraph('Professional Summary', section_title_style))
    story.append(Paragraph(summary_text, normal_style))

    skills = [skill.strip() for skill in re.split(r'[\n,]+', profile.skills) if skill.strip()]
    if skills:
        story.append(Paragraph('Skills', section_title_style))
        story.append(Paragraph(', '.join(skills), normal_style))

    story.extend(_section_bullets('Work Experience', profile.work_experience))
    story.extend(_section_bullets('Education', profile.education))
    story.extend(_section_bullets('Projects', profile.projects))
    story.extend(_section_bullets('Certifications', profile.certifications))

    doc.build(story)
    buffer.seek(0)
    return buffer


class CreateProfileView(View):
    def get(self, request):
        form = JobSeekerProfileForm()
        return render(request, 'cvgen/create_profile.html', {'form': form})

    def post(self, request):
        form = JobSeekerProfileForm(request.POST, request.FILES)
        if form.is_valid():
            profile = form.save()
            pdf_buffer = _build_pdf_for_profile(profile)
            response = HttpResponse(pdf_buffer, content_type='application/pdf')
            filename = f"{profile.full_name.replace(' ', '_') if profile.full_name else 'job_seeker'}_cv.pdf"
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            return response
        return render(request, 'cvgen/create_profile.html', {'form': form})


class GenerateCvView(View):
    def get(self, request, pk):
        profile = get_object_or_404(JobSeekerProfile, pk=pk)
        pdf_buffer = _build_pdf_for_profile(profile)
        response = HttpResponse(pdf_buffer, content_type='application/pdf')
        filename = f"{profile.full_name.replace(' ', '_') if profile.full_name else 'job_seeker'}_cv.pdf"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response