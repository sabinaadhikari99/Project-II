# file path: apps/accounts/views.py
from rest_framework import generics, parsers, permissions, response, views

from apps.shared.pdf_utils import extract_pdf_text

from .models import User, UserProfile
from .serializers import LoginSerializer, ProfileUpdateSerializer, RegisterSerializer


class RegisterAPIView(generics.CreateAPIView):
    queryset = User.objects.all()
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]


class LoginAPIView(views.APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return response.Response(serializer.validated_data)


class ProfileAPIView(generics.RetrieveUpdateAPIView):
    serializer_class = ProfileUpdateSerializer

    def get_object(self):
        return self.request.user


class ResumeUploadAPIView(views.APIView):
    parser_classes = [parsers.MultiPartParser, parsers.FormParser]

    def post(self, request):
        resume = request.FILES.get("resume")
        if not resume:
            return response.Response({"detail": "Resume PDF is required."}, status=400)

        resume_text = extract_pdf_text(resume)
        if len(resume_text.strip()) < 80:
            return response.Response({"detail": "The uploaded PDF text looks empty or unclear."}, status=400)

        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        profile.resume_text = resume_text
        extracted_skills = _extract_known_skills(resume_text)
        profile.skills = sorted(set(profile.skills or []) | set(extracted_skills))
        profile.save()
        return response.Response({"resume_text": resume_text, "extracted_skills": extracted_skills})


def _extract_known_skills(text):
    from apps.jobs.models import JobPosting

    known = set()
    for job in JobPosting.objects.filter(is_active=True).only("required_skills")[:100]:
        known.update(skill.strip() for skill in (job.required_skills or []) if skill.strip())

    lowered = f" {text.lower()} "
    return sorted(skill for skill in known if f" {skill.lower()} " in lowered or skill.lower() in lowered)
