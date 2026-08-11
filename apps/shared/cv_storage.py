# file path: apps/shared/cv_storage.py
"""Saves the actual uploaded CV file (not just its extracted text).

Both CV upload entry points (apps.accounts.views.ResumeUploadAPIView and
apps.jobs.services.analyze_resume_match) need to do this identically, so it
lives here once rather than being duplicated - a fix or a storage backend
change only has to happen in one place.
"""


def save_resume_file(profile, resume_file, request=None):
    """Save `resume_file` onto `profile.resume_file` and sync `profile.cv_url`.

    `resume_file` is a Django UploadedFile (e.g. from request.FILES). Its
    read position may already be at EOF if something upstream (like
    apps.shared.pdf_utils.extract_pdf_text) already consumed it to extract
    text - seek(0) first so the full file is actually written to storage,
    not an empty remainder.

    Does NOT call profile.save() - the caller is expected to save the
    profile once, after this and any other field assignments, to avoid
    multiple redundant writes.
    """
    try:
        resume_file.seek(0)
    except (AttributeError, ValueError):
        pass

    profile.resume_file.save(resume_file.name, resume_file, save=False)

    file_url = profile.resume_file.url
    if request is not None:
        file_url = request.build_absolute_uri(file_url)
    profile.cv_url = file_url

    return profile.cv_url