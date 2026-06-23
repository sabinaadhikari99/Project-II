# file path: apps/shared/constants.py
ROLE_JOB_SEEKER = "job_seeker"
ROLE_RECRUITER = "recruiter"
ROLE_ADMIN = "admin"

USER_ROLES = (
    (ROLE_JOB_SEEKER, "Job Seeker"),
    (ROLE_RECRUITER, "Recruiter"),
    (ROLE_ADMIN, "Admin"),
)

VECTOR_DIMENSION = 384
PROFILE_VECTOR_PREFIX = "profile"
JOB_VECTOR_PREFIX = "job"
