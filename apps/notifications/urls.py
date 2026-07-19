from django.urls import path

from .views import (
    NotificationDeleteAllAPIView,
    NotificationDeleteAPIView,
    NotificationListAPIView,
    NotificationMarkAllReadAPIView,
    NotificationMarkReadAPIView,
    NotificationTypesAPIView,
    UnreadCountAPIView,
)

urlpatterns = [
    path("", NotificationListAPIView.as_view(), name="notifications-list"),
    path("unread-count/", UnreadCountAPIView.as_view(), name="notifications-unread-count"),
    path("types/", NotificationTypesAPIView.as_view(), name="notifications-types"),
    path("<int:pk>/read/", NotificationMarkReadAPIView.as_view(), name="notifications-read"),
    path("mark-all-read/", NotificationMarkAllReadAPIView.as_view(), name="notifications-mark-all-read"),
    path("<int:pk>/delete/", NotificationDeleteAPIView.as_view(), name="notifications-delete"),
    path("delete-all/", NotificationDeleteAllAPIView.as_view(), name="notifications-delete-all"),
]
