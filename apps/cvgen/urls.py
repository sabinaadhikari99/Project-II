from django.urls import path
from . import views

app_name = "cvgen"

urlpatterns = [
    path("", views.CreateProfileView.as_view(), name="cvgen_home"),
    path("create/", views.CreateProfileView.as_view(), name="create_profile"),

    # Step 2 of the flow: choose a template, previewing with real data.
    path("<int:pk>/templates/", views.ChooseTemplateView.as_view(), name="choose_template"),
    path("<int:pk>/preview/<str:template_id>/", views.PreviewTemplateView.as_view(), name="preview_template"),

    # Final PDF generation.
    path("<int:pk>/generate/", views.GenerateCvView.as_view(), name="generate_cv"),
    path("<int:pk>/generate/<str:template_id>/", views.GenerateCvView.as_view(), name="generate_cv_with_template"),
]