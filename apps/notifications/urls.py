from django.urls import path

from .views import NotificationListAPIView, NotificationMarkReadAPIView

urlpatterns = [
    path("", NotificationListAPIView.as_view(), name="notifications-list"),
    path("<int:pk>/read/", NotificationMarkReadAPIView.as_view(), name="notifications-read"),
]
