# file path: config/urls.py
from django.conf import settings
from django.contrib import admin
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.urls import include, path
from django.views.generic import TemplateView

from apps.accounts.views import GlobalSearchAPIView, LinkedInConflictPageView, LinkedInRoleSelectPageView

from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView


class DashboardTemplateView(LoginRequiredMixin, TemplateView):
    login_url = settings.LOGIN_URL
    redirect_field_name = "next"


class AuthPageTemplateView(TemplateView):
    pass


urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("", TemplateView.as_view(template_name="accounts/landingpage.html"), name="landing-page"),
    path("login/", AuthPageTemplateView.as_view(template_name="accounts/login.html"), name="login"),
    path("register/", AuthPageTemplateView.as_view(template_name="accounts/register.html"), name="register"),
    path("profile/settings/", DashboardTemplateView.as_view(template_name="accounts/profile_settings.html"), name="profile-settings"),
    path("company-profile/", DashboardTemplateView.as_view(template_name="accounts/company_profile.html"), name="company-profile"),
    path("profile/", DashboardTemplateView.as_view(template_name="accounts/profile.html"), name="profile"),
    path("settings/", DashboardTemplateView.as_view(template_name="accounts/settings.html"), name="settings"),
    path("dashboard/seeker/", DashboardTemplateView.as_view(template_name="dashboard/seeker.html"), name="seeker-dashboard"),
    path("dashboard/recruiter/", DashboardTemplateView.as_view(template_name="dashboard/recruiter.html"), name="recruiter-dashboard"),
    path("dashboard/recruiter/post-job/", DashboardTemplateView.as_view(template_name="dashboard/recruiter_post_job.html"), name="recruiter-post-job"),
    path("dashboard/admin/", DashboardTemplateView.as_view(template_name="dashboard/admin.html"), name="admin-dashboard"),
    path("jobs/", DashboardTemplateView.as_view(template_name="jobs.html"), name="jobs"),
    path("job-recommendation/", DashboardTemplateView.as_view(template_name="recommendations.html"), name="job-recommendation"),
    path("ai-match/", DashboardTemplateView.as_view(template_name="recommendations.html"), name="ai-match"),
    path("skillgap/", DashboardTemplateView.as_view(template_name="skillgap.html"), name="skillgap"),
    path("notifications/", DashboardTemplateView.as_view(template_name="notifications.html"), name="notifications"),
    path("chat/", DashboardTemplateView.as_view(template_name="chat.html"), name="chat"),
    path("quiz/", DashboardTemplateView.as_view(template_name="quiz.html"), name="quiz"),
    path("linkedin/", DashboardTemplateView.as_view(template_name="linkedin.html"), name="linkedin"),
    path("linkedin/success/", TemplateView.as_view(template_name="accounts/linkedin_success.html"), name="linkedin-success"),
    path("linkedin/role-select/", LinkedInRoleSelectPageView.as_view(), name="linkedin-role-select"),
    path("linkedin/conflict/", LinkedInConflictPageView.as_view(), name="linkedin-conflict"),
    path("api/auth/", include("apps.accounts.urls")),
    path("api/jobs/", include("apps.jobs.urls")),
    path("api/skillgap/", include("apps.skillgap.urls")),
    path("api/recruiter/", include("apps.recruiters.urls")),
    path("api/admin/", include("apps.admin_panel.urls")),
    path("api/chatbot/", include("apps.chatbot.urls")),
    path("api/quiz/", include("apps.quiz.urls")),
    path("api/external/", include("apps.external.urls")),
    path("api/search/", GlobalSearchAPIView.as_view(), name="global-search"),
    path("api/notifications/", include("apps.notifications.urls")),
    path('cvgen/', include('apps.cvgen.urls', namespace='cvgen')),

    path('schema/', SpectacularAPIView.as_view(), name='schema'),
    path('swagger/', SpectacularSwaggerView.as_view(url_name='schema')),

]

admin.site.site_header = "SkillSync AI Admin"


