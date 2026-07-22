import logging
import threading
import traceback

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.db import transaction
from django.template.loader import render_to_string

from apps.jobs.models import Application, JobPosting
from apps.shared.constants import ROLE_ADMIN, ROLE_RECRUITER

from .models import Notification

logger = logging.getLogger(__name__)
User = get_user_model()

AI_MATCH_THRESHOLD = getattr(settings, "AI_MATCH_THRESHOLD", 80)


def _send_email_async(subject, text_message, from_email, recipient_list, html_message=None):
    def _send():
        try:
            send_mail(
                subject,
                text_message,
                from_email,
                recipient_list,
                html_message=html_message,
                fail_silently=False,
            )
            logger.info("Email sent to %s: %s", recipient_list, subject)
        except Exception as e:
            logger.error("Email delivery FAILED to %s (subject=%s): %s", recipient_list, subject, e)
    thread = threading.Thread(target=_send, daemon=True)
    thread.start()


def create_notification(
    user,
    title,
    message,
    notification_type=Notification.NotificationType.SYSTEM,
    sender=None,
    job=None,
    match_percentage=0,
    priority=Notification.Priority.MEDIUM,
    metadata=None,
):
    notification = Notification.objects.create(
        user=user,
        sender=sender,
        recruiter=sender if sender and getattr(sender, "role", None) == ROLE_RECRUITER else None,
        job=job,
        match_percentage=match_percentage,
        notification_type=notification_type,
        title=title,
        message=message,
        priority=priority,
        metadata=metadata or {},
    )
    logger.info("Notification created: [%s] %s -> %s", notification_type, title, user.email)
    return notification


def send_email_notification(user, subject, template_name, context):
    try:
        html_message = render_to_string(template_name, context)
    except Exception as e:
        logger.warning("Email template render failed for %s: %s", template_name, e)
        html_message = None
    text_message = f"Subject: {subject}\n\n{context.get('message', '')}"
    _send_email_async(subject, text_message, settings.DEFAULT_FROM_EMAIL, [user.email], html_message)


def notify_applicant_confirmation(application):
    applicant = application.applicant
    job = application.job
    if not applicant or not job:
        return
    title = "Application Submitted Successfully"
    message = f"Your application for {job.title} at {job.company} has been submitted successfully."
    create_notification(
        user=applicant,
        title=title,
        message=message,
        notification_type=Notification.NotificationType.APPLICATION,
        job=job,
        priority=Notification.Priority.HIGH,
    )


def notify_new_application(application):
    job = application.job
    if not job:
        logger.warning("notify_new_application skipped: job is None (application %s)", application.id)
        return
    recruiter = job.recruiter
    if not recruiter:
        logger.warning("notify_new_application skipped: recruiter is None (job %s)", job.id)
        return
    applicant = application.applicant
    title = f"New Application: {job.title}"
    message = f"{applicant.username or applicant.email} applied for {job.title} at {job.company}."
    create_notification(
        user=recruiter,
        sender=applicant,
        title=title,
        message=message,
        notification_type=Notification.NotificationType.APPLICATION,
        job=job,
        priority=Notification.Priority.HIGH,
    )
    send_email_notification(
        recruiter,
        f"New Application Received: {job.title}",
        "notifications/email/recruiter_new_application.html",
        {
            "recruiter": recruiter,
            "applicant": applicant,
            "job": job,
            "message": message,
        },
    )


def notify_applicant_status_change(application):
    applicant = application.applicant
    job = application.job
    if not applicant or not job:
        logger.warning("notify_applicant_status_change skipped: missing applicant/job")
        return
    status_display = dict(Application.STATUS_CHOICES).get(application.status, application.status)
    title = f"Application {status_display}"
    message = f"Your application for {job.title} at {job.company} has been {status_display.lower()}."
    create_notification(
        user=applicant,
        sender=job.recruiter,
        title=title,
        message=message,
        notification_type=Notification.NotificationType.APPLICATION,
        job=job,
        priority=Notification.Priority.HIGH,
    )
    send_email_notification(
        applicant,
        f"Application {status_display}: {job.title}",
        "notifications/email/applicant_status_change.html",
        {
            "applicant": applicant,
            "job": job,
            "status": status_display,
            "message": message,
        },
    )


def notify_job_matched_candidates(job):
    from apps.jobs.services import match_candidates_for_job

    matches = match_candidates_for_job(job, limit=20)
    if not matches:
        logger.info("No AI candidates matched for job %s", job.id)
        return

    notifications = []
    for match_data in matches:
        candidate = match_data["candidate"]
        score = match_data["score"]
        match_percentage = round(score * 100) if score <= 1.0 else round(min(score, 100))
        if match_percentage < AI_MATCH_THRESHOLD:
            continue
        title = f"{match_percentage}% Match: {job.title}"
        message = (
            f"A new job '{job.title}' at {job.company} matches your profile "
            f"with {match_percentage}% compatibility."
        )
        notifications.append(Notification(
            user=candidate,
            sender=job.recruiter,
            recruiter=job.recruiter,
            job=job,
            match_percentage=match_percentage,
            notification_type=Notification.NotificationType.JOB_MATCH,
            title=title,
            message=message,
            priority=Notification.Priority.HIGH,
            metadata={"required_skills": job.required_skills},
        ))

    if notifications:
        batch = Notification.objects.bulk_create(notifications, ignore_conflicts=True)
        logger.info("AI match: %d notifications created for job %s", len(batch), job.id)
        for n in batch:
            send_email_notification(
                n.user,
                f"SkillSync AI job match: {job.title}",
                "notifications/email/job_match.html",
                {
                    "user": n.user,
                    "job": job,
                    "match_percentage": n.match_percentage,
                    "required_skills": job.required_skills or [],
                    "message": n.message,
                },
            )


def notify_new_job_posting(job):
    from apps.shared.constants import ROLE_JOB_SEEKER

    seekers = User.objects.filter(role=ROLE_JOB_SEEKER, is_active=True).only("id", "email")
    if not seekers.exists():
        logger.info("No active job seekers to notify about new job %s", job.id)
        return

    notifications = []
    for seeker in seekers:
        notifications.append(Notification(
            user=seeker,
            sender=job.recruiter,
            recruiter=job.recruiter,
            job=job,
            notification_type=Notification.NotificationType.JOB_MATCH,
            title=f"New Job: {job.title} at {job.company}",
            message=(
                f"A new position '{job.title}' has been posted at {job.company}. "
                f"{'Location: ' + job.location + '. ' if job.location else ''}"
                f"{'Skills: ' + ', '.join(job.required_skills or []) + '.' if job.required_skills else ''}"
            ),
            priority=Notification.Priority.MEDIUM,
            metadata={"required_skills": job.required_skills or []},
        ))

    batch = Notification.objects.bulk_create(notifications, ignore_conflicts=True)
    logger.info("New job posting: %d notifications created for job %s", len(batch), job.id)


def notify_job_match(user, job, match_percentage, required_skills, message=None):
    recruiter_name = job.recruiter.username or job.recruiter.email
    title = f"{match_percentage}% match: {job.title}"
    if not message:
        message = (
            f"{recruiter_name} from {job.company} posted {job.title}. "
            f"Your resume matches this role at {match_percentage}%."
        )
    notification, created = Notification.objects.get_or_create(
        user=user,
        job=job,
        notification_type=Notification.NotificationType.JOB_MATCH,
        defaults={
            "sender": job.recruiter,
            "recruiter": job.recruiter,
            "match_percentage": match_percentage,
            "title": title,
            "message": message,
            "priority": Notification.Priority.HIGH,
            "metadata": {"required_skills": required_skills},
        },
    )
    if not created and match_percentage > notification.match_percentage:
        notification.match_percentage = match_percentage
        notification.title = title
        notification.message = message
        notification.recruiter = job.recruiter
        notification.sender = job.recruiter
        notification.save(update_fields=["match_percentage", "title", "message", "recruiter", "sender"])

    if created:
        logger.info("Individual job match notification created for %s on %s", user.email, job.title)
        send_email_notification(
            user,
            f"SkillSync AI job match: {job.title}",
            "notifications/email/job_match.html",
            {
                "user": user,
                "job": job,
                "match_percentage": match_percentage,
                "required_skills": required_skills or [],
                "message": message,
            },
        )


def notify_candidate_withdrew(job, candidate):
    if not job or not candidate:
        logger.warning("notify_candidate_withdrew skipped: job or candidate is None")
        return
    title = f"Candidate Withdrew: {job.title}"
    message = f"{candidate.username or candidate.email} withdrew their application for {job.title}."
    create_notification(
        user=job.recruiter,
        sender=candidate,
        title=title,
        message=message,
        notification_type=Notification.NotificationType.APPLICATION,
        job=job,
        priority=Notification.Priority.MEDIUM,
    )


def notify_interview_scheduled(application, interview_date):
    applicant = application.applicant
    job = application.job
    if not applicant or not job:
        logger.warning("notify_interview_scheduled skipped: missing applicant/job")
        return
    title = f"Interview Scheduled: {job.title}"
    message = f"An interview has been scheduled for {job.title} at {job.company} on {interview_date}."
    create_notification(
        user=applicant,
        sender=job.recruiter,
        title=title,
        message=message,
        notification_type=Notification.NotificationType.INTERVIEW,
        job=job,
        priority=Notification.Priority.HIGH,
        metadata={"interview_date": str(interview_date)},
    )
    send_email_notification(
        applicant,
        f"Interview Invitation: {job.title}",
        "notifications/email/interview_scheduled.html",
        {
            "applicant": applicant,
            "job": job,
            "interview_date": interview_date,
            "message": message,
        },
    )


def notify_recruiter_interview_response(application, accepted):
    job = application.job
    applicant = application.applicant
    if not job or not applicant:
        logger.warning("notify_recruiter_interview_response skipped: missing job/applicant")
        return
    action = "accepted" if accepted else "rejected"
    title = f"Interview {action.title()} by {applicant.username or applicant.email}"
    message = f"{applicant.username or applicant.email} has {action} the interview for {job.title}."
    create_notification(
        user=job.recruiter,
        sender=applicant,
        title=title,
        message=message,
        notification_type=Notification.NotificationType.INTERVIEW,
        job=job,
        priority=Notification.Priority.HIGH,
        metadata={"interview_accepted": accepted},
    )


def notify_resume_uploaded(user):
    if not user:
        return
    title = "Resume Uploaded Successfully"
    message = "Your resume has been uploaded and is being processed for AI analysis."
    create_notification(
        user=user,
        title=title,
        message=message,
        notification_type=Notification.NotificationType.RESUME,
        priority=Notification.Priority.MEDIUM,
    )


def notify_resume_analysis_complete(user, match_percentage=0):
    if not user:
        return
    title = "Resume AI Analysis Complete"
    message = f"Your resume has been analyzed. Top match score: {match_percentage}%."
    create_notification(
        user=user,
        title=title,
        message=message,
        notification_type=Notification.NotificationType.AI_MATCH,
        priority=Notification.Priority.HIGH,
        metadata={"match_percentage": match_percentage},
    )


def notify_skill_gap_complete(user):
    if not user:
        return
    title = "Skill Gap Analysis Complete"
    message = "Your skill gap analysis has been completed. View recommendations to improve your profile."
    create_notification(
        user=user,
        title=title,
        message=message,
        notification_type=Notification.NotificationType.SKILL_GAP,
        priority=Notification.Priority.MEDIUM,
    )


def notify_new_jobs_match_cv(user, matched_jobs_count):
    if not user:
        return
    title = f"{matched_jobs_count} New Job{'s' if matched_jobs_count != 1 else ''} Match Your CV"
    message = f"We found {matched_jobs_count} new job{'s' if matched_jobs_count != 1 else ''} matching your profile."
    create_notification(
        user=user,
        title=title,
        message=message,
        notification_type=Notification.NotificationType.JOB_MATCH,
        priority=Notification.Priority.HIGH,
        metadata={"matched_jobs_count": matched_jobs_count},
    )


def notify_better_ai_match_found(user, job, new_match_percentage, old_match_percentage):
    if not user or not job:
        return
    title = f"Better AI Match Found: {new_match_percentage}%"
    message = (
        f"A better match found for '{job.title}' at {job.company}: "
        f"{new_match_percentage}% (was {old_match_percentage}%)."
    )
    notify_job_match(user, job, new_match_percentage, job.required_skills, message)


def notify_profile_viewed(viewed_user, viewed_by):
    if not viewed_user or not viewed_by:
        return
    title = "Profile Viewed"
    message = f"{viewed_by.username or viewed_by.email} viewed your profile."
    create_notification(
        user=viewed_user,
        sender=viewed_by,
        title=title,
        message=message,
        notification_type=Notification.NotificationType.PROFILE,
        priority=Notification.Priority.LOW,
    )


def notify_shortlisted(application):
    applicant = application.applicant
    job = application.job
    if not applicant or not job:
        logger.warning("notify_shortlisted skipped: missing applicant/job")
        return
    title = f"Application Shortlisted: {job.title}"
    message = f"Congratulations! Your application for {job.title} at {job.company} has been shortlisted."
    create_notification(
        user=applicant,
        sender=job.recruiter,
        title=title,
        message=message,
        notification_type=Notification.NotificationType.APPLICATION,
        job=job,
        priority=Notification.Priority.HIGH,
    )
    send_email_notification(
        applicant,
        f"Application Shortlisted: {job.title}",
        "notifications/email/applicant_shortlisted.html",
        {
            "applicant": applicant,
            "job": job,
            "message": message,
        },
    )


def notify_new_message(recipient, sender_user, message_preview=""):
    if not recipient or not sender_user:
        return
    title = f"New Message from {sender_user.username or sender_user.email}"
    message = message_preview or f"You have a new message from {sender_user.username or sender_user.email}."
    create_notification(
        user=recipient,
        sender=sender_user,
        title=title,
        message=message,
        notification_type=Notification.NotificationType.MESSAGE,
        priority=Notification.Priority.MEDIUM,
    )


def notify_job_expired(job):
    if not job:
        return
    title = f"Job Expired: {job.title}"
    message = f"Your job posting '{job.title}' at {job.company} has expired."
    create_notification(
        user=job.recruiter,
        sender=job.recruiter,
        title=title,
        message=message,
        notification_type=Notification.NotificationType.RECRUITER,
        job=job,
        priority=Notification.Priority.MEDIUM,
    )


def notify_job_expiring_soon(job, days_left):
    if not job:
        return
    title = f"Job Expiring Soon: {job.title}"
    message = f"Your job '{job.title}' at {job.company} will expire in {days_left} day{'s' if days_left != 1 else ''}."
    create_notification(
        user=job.recruiter,
        sender=job.recruiter,
        title=title,
        message=message,
        notification_type=Notification.NotificationType.RECRUITER,
        job=job,
        priority=Notification.Priority.LOW,
    )


def notify_admin_new_user(new_user, description, action_type="REGISTRATION", related_job=None):
    admins = User.objects.filter(role=ROLE_ADMIN, is_active=True)
    if not admins.exists():
        logger.debug("No admin users found to notify about %s", description)
        return
    for admin in admins:
        title = f"New {'Job Posting' if related_job else 'User Registration'}"
        create_notification(
            user=admin,
            sender=new_user,
            title=title,
            message=description,
            notification_type=Notification.NotificationType.ADMIN,
            job=related_job,
            priority=Notification.Priority.MEDIUM if not related_job else Notification.Priority.HIGH,
            metadata={"action_type": action_type, "user_id": new_user.id},
        )


def notify_admin_system_error(admin_user, error_message):
    if not admin_user:
        return
    title = "Critical System Error"
    message = error_message
    create_notification(
        user=admin_user,
        title=title,
        message=message,
        notification_type=Notification.NotificationType.SYSTEM,
        priority=Notification.Priority.CRITICAL,
    )


def notify_admin_suspicious_activity(admin_user, description):
    if not admin_user:
        return
    title = "Suspicious Activity Detected"
    message = description
    create_notification(
        user=admin_user,
        title=title,
        message=message,
        notification_type=Notification.NotificationType.SECURITY,
        priority=Notification.Priority.HIGH,
    )


def notify_company_verification_request(admin_user, company_name):
    if not admin_user:
        return
    title = "Company Verification Request"
    message = f"A verification request has been submitted for {company_name}."
    create_notification(
        user=admin_user,
        title=title,
        message=message,
        notification_type=Notification.NotificationType.VERIFICATION,
        priority=Notification.Priority.MEDIUM,
    )


def notify_profile_completion_reminder(user):
    if not user:
        return
    title = "Complete Your Profile"
    message = "Your profile is incomplete. Add your skills and experience to get better job matches."
    Notification.objects.get_or_create(
        user=user,
        notification_type=Notification.NotificationType.PROFILE,
        title=title,
        defaults={
            "message": message,
            "priority": Notification.Priority.LOW,
        },
    )


def notify_job_approved(recruiter, job):
    if not recruiter or not job:
        return
    title = f"Job Approved: {job.title}"
    message = f"Your job posting '{job.title}' at {job.company} has been approved by the admin."
    create_notification(
        user=recruiter,
        sender=recruiter,
        title=title,
        message=message,
        notification_type=Notification.NotificationType.RECRUITER,
        job=job,
        priority=Notification.Priority.HIGH,
    )


def notify_job_rejected(recruiter, job, reason=""):
    if not recruiter or not job:
        return
    title = f"Job Rejected: {job.title}"
    message = f"Your job posting '{job.title}' has been rejected.{' Reason: ' + reason if reason else ''}"
    create_notification(
        user=recruiter,
        sender=recruiter,
        title=title,
        message=message,
        notification_type=Notification.NotificationType.RECRUITER,
        job=job,
        priority=Notification.Priority.HIGH,
    )


def notify_account_deleted(admin_user, deleted_user_email, role):
    if not admin_user:
        return
    title = "Account Deleted"
    message = f"User {deleted_user_email} ({role}) has been deleted."
    create_notification(
        user=admin_user,
        title=title,
        message=message,
        notification_type=Notification.NotificationType.ADMIN,
        priority=Notification.Priority.MEDIUM,
        metadata={"deleted_user_email": deleted_user_email, "role": role},
    )


def notify_email_delivery_failure(admin_user, failed_email, error_detail=""):
    if not admin_user:
        return
    title = "Email Delivery Failure"
    message = f"Failed to send email to {failed_email}.{' Error: ' + error_detail if error_detail else ''}"
    create_notification(
        user=admin_user,
        title=title,
        message=message,
        notification_type=Notification.NotificationType.SYSTEM,
        priority=Notification.Priority.HIGH,
        metadata={"failed_email": failed_email},
    )


def send_application_email(application):
    if not application or not application.applicant or not application.job:
        logger.warning("send_application_email skipped: missing data")
        return
    send_email_notification(
        application.applicant,
        f"Application received: {application.job.title}",
        "notifications/email/applicant_status_change.html",
        {
            "applicant": application.applicant,
            "job": application.job,
            "status": "Submitted",
            "message": f"Your application for {application.job.title} at {application.job.company} was submitted.",
        },
    )


def send_and_mark_notification(notification_id):
    try:
        notification = Notification.objects.get(id=notification_id, is_email_sent=False)
        notification.is_email_sent = True
        notification.save(update_fields=["is_email_sent"])
        logger.info("Notification %d marked as email sent", notification_id)
    except Notification.DoesNotExist:
        logger.debug("send_and_mark_notification: notification %s not found or already sent", notification_id)
