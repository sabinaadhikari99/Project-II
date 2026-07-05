# file path: config/urls.py
from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView

from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    path("django-admin/", admin.site.urls),
    # Default landing page
    path("", TemplateView.as_view(template_name="accounts/landingpage.html"), name="landing-page"),
    path("login/", TemplateView.as_view(template_name="accounts/login.html"), name="login"),
    path("register/", TemplateView.as_view(template_name="accounts/register.html"), name="register"),
    path("profile/settings/", TemplateView.as_view(template_name="accounts/profile_settings.html"), name="profile-settings"),
    path("dashboard/seeker/", TemplateView.as_view(template_name="dashboard/seeker.html"), name="seeker-dashboard"),
    path("dashboard/recruiter/", TemplateView.as_view(template_name="dashboard/recruiter.html"), name="recruiter-dashboard"),
    path("dashboard/admin/", TemplateView.as_view(template_name="dashboard/admin.html"), name="admin-dashboard"),
    path("jobs/", TemplateView.as_view(template_name="jobs.html"), name="jobs"),
    path("job-recommendation/", TemplateView.as_view(template_name="recommendations.html"), name="job-recommendation"),
    path("ai-match/", TemplateView.as_view(template_name="recommendations.html"), name="ai-match"),
    path("skillgap/", TemplateView.as_view(template_name="skillgap.html"), name="skillgap"),
    path("notifications/", TemplateView.as_view(template_name="notifications.html"), name="notifications"),
    path("chat/", TemplateView.as_view(template_name="chat.html"), name="chat"),
    path("quiz/", TemplateView.as_view(template_name="quiz.html"), name="quiz"),
    path("linkedin/", TemplateView.as_view(template_name="linkedin.html"), name="linkedin"),
    path("api/auth/", include("apps.accounts.urls")),
    path("api/jobs/", include("apps.jobs.urls")),
    path("api/skillgap/", include("apps.skillgap.urls")),
    path("api/recruiter/", include("apps.recruiters.urls")),
    path("api/admin/", include("apps.admin_panel.urls")),
    path("api/chatbot/", include("apps.chatbot.urls")),
    path("api/quiz/", include("apps.quiz.urls")),
    path("api/external/", include("apps.external.urls")),
    path("api/notifications/", include("apps.notifications.urls")),
    path('cvgen/', include('apps.cvgen.urls', namespace='cvgen')),

    path('schema/', SpectacularAPIView.as_view(), name='schema'),
    path('swagger/', SpectacularSwaggerView.as_view(url_name='schema')),

]

admin.site.site_header = "SkillSync AI Admin"


