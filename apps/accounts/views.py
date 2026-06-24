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
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user


class ResumeUploadAPIView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [parsers.MultiPartParser, parsers.FormParser]

    def post(self, request):
        resume = request.FILES.get("resume")

        if not resume:
            return response.Response(
                {"detail": "Resume PDF is required."},
                status=400
            )

        if not resume.name.lower().endswith(".pdf"):
            return response.Response(
                {"detail": "Only PDF files are allowed."},
                status=400
            )

        resume_text = extract_pdf_text(resume)

        if not resume_text or len(resume_text.strip()) < 80:
            return response.Response(
                {"detail": "The uploaded PDF text looks empty or unclear."},
                status=400
            )

        profile, _ = UserProfile.objects.get_or_create(user=request.user)

        profile.resume_text = resume_text

        extracted_skills = _extract_known_skills(resume_text)

        profile.skills = sorted(set(profile.skills or []) | set(extracted_skills))

        profile.save()

        return response.Response({
            "resume_text": resume_text,
            "extracted_skills": extracted_skills
        })


def _extract_known_skills(text):
    from apps.jobs.models import JobPosting

    known = set()

    jobs = JobPosting.objects.filter(is_active=True).values_list(
        "required_skills",
        flat=True
    )

    for skills in jobs:
        if skills:
            for skill in skills:
                if skill and skill.strip():
                    known.add(skill.strip())

    lowered = f" {text.lower()} "

    return sorted(
        skill for skill in known
        if skill.lower() in lowered
    )