import logging

from channels.layers import get_channel_layer
from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver
from asgiref.sync import async_to_sync

from apps.jobs.models import Application, JobPosting

from .models import Notification
from .services import (
    notify_admin_new_user,
    notify_applicant_confirmation,
    notify_applicant_status_change,
    notify_job_matched_candidates,
    notify_new_application,
    notify_new_job_posting,
)

logger = logging.getLogger(__name__)
User = get_user_model()


@receiver(post_save, sender=Notification)
def broadcast_notification_realtime(sender, instance, created, **kwargs):
    if not created:
        return
    try:
        channel_layer = get_channel_layer()
        if channel_layer is None:
            logger.warning("Channel layer not configured, skipping real-time broadcast")
            return
        group_name = f"notifications_{instance.user_id}"
        from .serializers import NotificationSerializer
        data = NotificationSerializer(instance).data
        async_to_sync(channel_layer.group_send)(
            group_name,
            {
                "type": "notification_message",
                "data": data,
            },
        )
    except Exception as e:
        logger.error("Real-time broadcast failed for notification %d: %s", instance.id, e)


@receiver(post_save, sender=JobPosting)
def handle_job_posting_notifications(sender, instance, created, **kwargs):
    if not created:
        return
    try:
        notify_new_job_posting(instance)
        notify_job_matched_candidates(instance)
        notify_admin_new_user(
            instance.recruiter,
            f"New job posted: {instance.title} at {instance.company}",
            "RECRUITER",
            related_job=instance,
        )
        logger.info("Notifications sent for new job posting: %s", instance.title)
    except Exception as e:
        logger.error("Failed to send job posting notifications for %s: %s", instance.id, e)


@receiver(post_save, sender=Application)
def handle_application_notifications(sender, instance, created, **kwargs):
    try:
        if created:
            notify_new_application(instance)
            notify_applicant_confirmation(instance)
            logger.info("New application notification sent for %s -> %s",
                        instance.applicant_id, instance.job_id)
        else:
            if not kwargs.get("update_fields") or "status" in (kwargs.get("update_fields") or []):
                notify_applicant_status_change(instance)
                logger.info("Application status change notification sent for %s (%s)",
                            instance.id, instance.status)
    except Exception as e:
        logger.error("Failed to send application notification for %s: %s", instance.id, e)


@receiver(post_save, sender=User)
def handle_user_registration_notification(sender, instance, created, **kwargs):
    if not created:
        return
    try:
        from apps.shared.constants import USER_ROLES
        role_map = dict(USER_ROLES)
        role_label = role_map.get(instance.role, instance.role)
        notify_admin_new_user(
            instance,
            f"New {role_label} registered: {instance.email}",
            "REGISTRATION",
        )
        logger.info("Admin notified of new user registration: %s", instance.email)
    except Exception as e:
        logger.error("Failed to notify admins about new user %s: %s", instance.id, e)
