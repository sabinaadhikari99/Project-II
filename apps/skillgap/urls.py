# file path: apps/skillgap/urls.py
from django.urls import path

from .views import SkillGapAPIView

urlpatterns = [path("", SkillGapAPIView.as_view())]
