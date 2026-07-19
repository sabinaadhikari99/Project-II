import logging

from django.db.models import Count
from rest_framework import generics, response, status, views
from rest_framework.pagination import PageNumberPagination

from .models import Notification
from .serializers import NotificationSerializer

logger = logging.getLogger(__name__)


class NotificationPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class NotificationListAPIView(generics.ListAPIView):
    serializer_class = NotificationSerializer
    pagination_class = NotificationPagination

    def get_queryset(self):
        qs = Notification.objects.filter(user=self.request.user).select_related(
            "sender", "recruiter", "job"
        )
        notification_type = self.request.query_params.get("type")
        is_read = self.request.query_params.get("is_read")
        if notification_type:
            qs = qs.filter(notification_type=notification_type)
        if is_read is not None:
            qs = qs.filter(is_read=is_read.lower() == "true")
        return qs


class NotificationMarkReadAPIView(views.APIView):
    def post(self, request, pk):
        notification = generics.get_object_or_404(Notification, pk=pk, user=request.user)
        from django.utils import timezone
        notification.is_read = True
        notification.read_at = timezone.now()
        notification.save(update_fields=["is_read", "read_at"])
        return response.Response(NotificationSerializer(notification).data)


class NotificationMarkAllReadAPIView(views.APIView):
    def post(self, request):
        from django.utils import timezone
        updated = Notification.objects.filter(user=request.user, is_read=False).update(
            is_read=True,
            read_at=timezone.now(),
        )
        logger.info("User %s marked %d notifications as read", request.user.id, updated)
        return response.Response({"marked_read": updated})


class NotificationDeleteAPIView(views.APIView):
    def delete(self, request, pk):
        notification = generics.get_object_or_404(Notification, pk=pk, user=request.user)
        notification.delete()
        return response.Response(status=status.HTTP_204_NO_CONTENT)


class NotificationDeleteAllAPIView(views.APIView):
    def delete(self, request):
        qs = Notification.objects.filter(user=request.user)
        notification_type = request.query_params.get("type")
        if notification_type:
            qs = qs.filter(notification_type=notification_type)
        count, _ = qs.delete()
        logger.info("User %s deleted %d notifications", request.user.id, count)
        return response.Response({"deleted": count})


class UnreadCountAPIView(views.APIView):
    def get(self, request):
        count = Notification.objects.filter(user=request.user, is_read=False).count()
        return response.Response({"count": count})


class NotificationTypesAPIView(views.APIView):
    def get(self, request):
        qs = Notification.objects.filter(user=request.user).values("notification_type").annotate(
            total=Count("id")
        ).order_by("-total")
        type_map = dict(Notification.NotificationType.choices)
        types = [
            {"code": item["notification_type"], "label": type_map.get(item["notification_type"], item["notification_type"]), "count": item["total"]}
            for item in qs
        ]
        return response.Response(types)
