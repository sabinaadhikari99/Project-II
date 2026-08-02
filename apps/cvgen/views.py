from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.clickjacking import xframe_options_sameorigin

from .cv_templates import get_template_list, get_template_meta, is_valid_template
from .forms import AdditionalInfoFormSet, JobSeekerProfileForm
from .models import JobSeekerProfile
from .pdf_builder import build_pdf_for_profile, _format_lines, _parse_entry_blocks, _skills_list


class CreateProfileView(LoginRequiredMixin, View):
    """Step 1: collect CV details. Saves the profile (plus any Additional
    Info sections), then hands off to template selection instead of
    generating a PDF immediately."""

    def get(self, request):
        form = JobSeekerProfileForm()
        formset = AdditionalInfoFormSet(instance=JobSeekerProfile(), prefix='additional')
        return render(request, 'cvgen/create_profile.html', {'form': form, 'formset': formset})

    def post(self, request):
        form = JobSeekerProfileForm(request.POST)
        # The formset is validated against an unsaved instance (it doesn't touch
        # the DB); once the profile itself is saved, we re-point the formset at
        # the real profile and save it.
        formset = AdditionalInfoFormSet(request.POST, instance=JobSeekerProfile(), prefix='additional')
        if form.is_valid() and formset.is_valid():
            profile = form.save()
            formset.instance = profile
            formset.save()
            return redirect('cvgen:choose_template', pk=profile.pk)
        return render(request, 'cvgen/create_profile.html', {'form': form, 'formset': formset})


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


@method_decorator(xframe_options_sameorigin, name='dispatch')
class PreviewTemplateView(LoginRequiredMixin, View):
    """Renders the user's real CV data inside a given template's layout, for
    display inside the gallery's preview iframe/modal. This is HTML, not a
    PDF, so switching templates is instant and never regenerates data.

    The xframe_options_sameorigin decorator explicitly allows this specific
    view to be framed by pages on the same site, even if the project's
    global X_FRAME_OPTIONS setting is "DENY" (which would otherwise block
    the preview iframe with a "refused to connect" error)."""

    def get(self, request, pk, template_id):
        profile = get_object_or_404(JobSeekerProfile, pk=pk)
        if not is_valid_template(template_id):
            raise Http404('Unknown template')

        additional_info = [
            {'title': entry.title, 'details': _format_lines(entry.details)}
            for entry in profile.additional_info.all()
        ]

        context = {
            'profile': profile,
            'template_id': template_id,
            'meta': get_template_meta(template_id),
            'skills': _skills_list(profile.skills),
            'education': _format_lines(profile.education),
            'work_experience': _format_lines(profile.work_experience),
            'projects': _parse_entry_blocks(profile.projects),
            'certifications': _format_lines(profile.certifications),
            'additional_info': additional_info,
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