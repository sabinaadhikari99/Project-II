"""
Run in: python manage.py shell
Then:   exec(open('diagnose_cv.py').read())
"""
from apps.accounts.models import User

email = input("Enter the candidate's email: ").strip()
u = User.objects.get(email=email)
p = getattr(u, "profile", None)

print("=" * 60)
if p is None:
    print("FAIL: this user has no UserProfile row at all.")
else:
    print("resume_text length:", len(p.resume_text or ""))
    print("resume_file field :", repr(p.resume_file))
    print("resume_file name  :", p.resume_file.name if p.resume_file else None)
    print("cv_url            :", repr(p.cv_url))
    if p.resume_file:
        try:
            print("resume_file.url   :", p.resume_file.url)
        except Exception as e:
            print("resume_file.url   : ERROR ->", e)
print("=" * 60)