from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from .cv_templates import get_template_list, get_template_meta, is_valid_template
from .forms import JobSeekerProfileForm
from .models import JobSeekerProfile
from .pdf_builder import build_pdf_for_profile, _format_lines, _skills_list


class CreateProfileView(LoginRequiredMixin, View):
    """Step 1: collect CV details. Saves the profile, then hands off to
    template selection instead of generating a PDF immediately."""

    def get(self, request):
        form = JobSeekerProfileForm()
        return render(request, 'cvgen/create_profile.html', {'form': form})

    def post(self, request):
        form = JobSeekerProfileForm(request.POST)
        if form.is_valid():
            profile = form.save()
            return redirect('cvgen:choose_template', pk=profile.pk)
        return render(request, 'cvgen/create_profile.html', {'form': form})


class ChooseTemplateView(LoginRequiredMixin, View):
    """Step 2: template gallery. Lets the user preview each template with
    their own data before picking one."""

    def get(self, request, pk):
        profile = get_object_or_404(JobSeekerProfile, pk=pk)
        return render(request, 'cvgen/choose_template.html', {
            'profile': profile,
            'templates': get_template_list(),
            'selected_template': profile.selected_template,
        })


class PreviewTemplateView(LoginRequiredMixin, View):
    """Renders the user's real CV data inside a given template's layout, for
    display inside the gallery's preview iframe/modal. This is HTML, not a
    PDF, so switching templates is instant and never regenerates data."""

    def get(self, request, pk, template_id):
        profile = get_object_or_404(JobSeekerProfile, pk=pk)
        if not is_valid_template(template_id):
            raise Http404('Unknown template')

        context = {
            'profile': profile,
            'template_id': template_id,
            'meta': get_template_meta(template_id),
            'skills': _skills_list(profile.skills),
            'education': _format_lines(profile.education),
            'work_experience': _format_lines(profile.work_experience),
            'projects': _format_lines(profile.projects),
            'certifications': _format_lines(profile.certifications),
        }
        return render(request, 'cvgen/cv_preview.html', context)


class GenerateCvView(LoginRequiredMixin, View):
    """Step 3: generate the final PDF using the selected template only."""

    def get(self, request, pk, template_id=None):
        profile = get_object_or_404(JobSeekerProfile, pk=pk)
        template_id = template_id or profile.selected_template

        if not is_valid_template(template_id):
            raise Http404('Unknown template')

        if profile.selected_template != template_id:
            profile.selected_template = template_id
            profile.save(update_fields=['selected_template'])

        pdf_buffer = build_pdf_for_profile(profile, template_id)
        response = HttpResponse(pdf_buffer, content_type='application/pdf')
        filename = f"{profile.full_name.replace(' ', '_') if profile.full_name else 'job_seeker'}_cv.pdf"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response