# file path: apps/notifications/services.py
from django.conf import settings
from django.core.mail import send_mail

from .models import Notification


def send_application_email(application):
    subject = f"Application received: {application.job.title}"
    message = (
        f"Hi {application.applicant.username},\n\n"
        f"Your application for {application.job.title} at {application.job.company} was submitted."
    )
    send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [application.applicant.email], fail_silently=True)


def notify_job_match(user, job, match_percentage, required_skills, application_link):
    title = f"{match_percentage}% match: {job.title}"
    recruiter_name = job.recruiter.username or job.recruiter.email
    contact = job.recruiter.email
    message = (
        f"{recruiter_name} from {job.company} posted {job.title}. "
        f"Your resume matches this role at {match_percentage}%."
    )
    notification, created = Notification.objects.get_or_create(
        user=user,
        job=job,
        defaults={
            "recruiter": job.recruiter,
            "match_percentage": match_percentage,
            "title": title,
            "message": message,
        },
    )
    if not created and match_percentage > notification.match_percentage:
        notification.match_percentage = match_percentage
        notification.title = title
        notification.message = message
        notification.recruiter = job.recruiter
        notification.save(update_fields=["match_percentage", "title", "message", "recruiter"])

    if created:
        email_message = (
            f"Hi {user.username},\n\n"
            f"You have a strong SkillSync AI job match.\n\n"
            f"Recruiter Name: {recruiter_name}\n"
            f"Company Name: {job.company}\n"
            f"Job Title: {job.title}\n"
            f"Match Percentage: {match_percentage}%\n"
            f"Required Skills: {', '.join(required_skills) or 'Not listed'}\n"
            f"Apply Link: {application_link}\n"
            f"Contact Information: {contact}\n"
        )
        send_mail(
            f"SkillSync AI job match: {job.title}",
            email_message,
            job.recruiter.email or settings.DEFAULT_FROM_EMAIL,
            [user.email],
            fail_silently=True,
        )
