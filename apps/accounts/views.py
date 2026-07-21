# file path: apps/accounts/views.py
import os
import urllib.parse

import requests
from django.conf import settings
from django.contrib.auth import login
from django.shortcuts import redirect, render
from rest_framework import generics, parsers, permissions, response, status, views
from rest_framework.authentication import SessionAuthentication
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.tokens import RefreshToken

from apps.shared.pdf_utils import extract_pdf_text
from .models import User, UserProfile
from .serializers import LoginSerializer, ProfileUpdateSerializer, RegisterSerializer, UserSerializer


class RegisterAPIView(generics.CreateAPIView):
    queryset = User.objects.all()
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]


class LoginAPIView(views.APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        login(request, serializer.user)
        return response.Response(serializer.validated_data)


class GetTokenAPIView(views.APIView):
    """
    Get or refresh JWT tokens for an authenticated user.
    Used when user is authenticated via Django session but needs JWT tokens for API calls.
    """
    authentication_classes = [SessionAuthentication, JWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        """Generate fresh JWT tokens for the authenticated user."""
        if not request.user.is_authenticated:
            return response.Response(
                {"detail": "User is not authenticated."},
                status=401
            )
        
        refresh = RefreshToken.for_user(request.user)
        return response.Response({
            "user": UserSerializer(request.user).data,
            "access": str(refresh.access_token),
            "refresh": str(refresh),
        })


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


class LogoutAPIView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        try:
            refresh_token = request.data.get("refresh")
            if refresh_token:
                token = RefreshToken(refresh_token)
                token.blacklist()
        except Exception:
            pass
        return response.Response({"detail": "Logged out successfully"})


LINKEDIN_SCOPES = "openid profile email"


class LinkedInLoginAPIView(views.APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        role = request.GET.get("role")
        if role and role not in ("job_seeker", "recruiter"):
            return response.Response(
                {"detail": "Invalid role specified."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        stored_role = role or "job_seeker"

        client_id = settings.LINKEDIN_CLIENT_ID
        redirect_uri = settings.LINKEDIN_REDIRECT_URI
        state = os.urandom(16).hex()

        request.session["linkedin_oauth_state"] = state
        request.session["linkedin_oauth_role"] = stored_role

        params = urllib.parse.urlencode({
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": LINKEDIN_SCOPES,
            "state": state,
        })
        auth_url = f"https://www.linkedin.com/oauth/v2/authorization?{params}"
        return response.Response({"auth_url": auth_url})


class LinkedInCallbackAPIView(views.APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        code = request.GET.get("code")
        state = request.GET.get("state")
        error = request.GET.get("error")
        stored_state = request.session.pop("linkedin_oauth_state", None)
        role = request.session.pop("linkedin_oauth_role", "job_seeker")

        if error:
            return redirect(f"/login/?error=linkedin_{error}")

        if not code or not state or state != stored_state:
            return redirect("/login/?error=linkedin_invalid_state")

        token_data = self._exchange_code(code)
        if "error" in token_data:
            return redirect("/login/?error=linkedin_token_exchange_failed")

        access_token = token_data["access_token"]

        profile = self._fetch_profile(access_token)
        if not profile or not profile.get("email"):
            return redirect("/login/?error=linkedin_no_email")

        email = profile["email"]
        name = profile.get("name", email.split("@")[0])
        picture = profile.get("picture", "")

        try:
            user = User.objects.get(email=email)
            if user.role == role:
                refresh = RefreshToken.for_user(user)
                return redirect(
                    f"/linkedin/success/?access={str(refresh.access_token)}&refresh={str(refresh)}"
                )
            else:
                request.session["linkedin_conflict_data"] = {
                    "email": email,
                    "existing_role": user.role,
                    "requested_role": role,
                    "name": name,
                    "profile_picture": picture,
                }
                return redirect("/linkedin/conflict/")
        except User.DoesNotExist:
            base_username = name.replace(" ", "_").lower()[:30]
            username = base_username
            counter = 1
            while User.objects.filter(username=username).exists():
                username = f"{base_username}_{counter}"
                counter += 1

            user = User.objects.create_user(
                email=email,
                username=username,
                password=os.urandom(32).hex(),
                role=role,
                profile_picture=picture,
            )
            UserProfile.objects.create(user=user)

            refresh = RefreshToken.for_user(user)
            return redirect(
                f"/linkedin/success/?access={str(refresh.access_token)}&refresh={str(refresh)}"
            )

    def _exchange_code(self, code):
        try:
            resp = requests.post(
                "https://www.linkedin.com/oauth/v2/accessToken",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "client_id": settings.LINKEDIN_CLIENT_ID,
                    "client_secret": settings.LINKEDIN_CLIENT_SECRET,
                    "redirect_uri": settings.LINKEDIN_REDIRECT_URI,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=15,
            )
            return resp.json()
        except requests.RequestException:
            return {"error": "request_failed"}

    def _fetch_profile(self, access_token):
        try:
            resp = requests.get(
                "https://api.linkedin.com/v2/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=15,
            )
            if resp.status_code == 200:
                return resp.json()
            return None
        except requests.RequestException:
            return None


class LinkedInRoleSelectPageView(views.APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        linkedin_data = request.session.get("linkedin_data")
        if not linkedin_data:
            return redirect("/register/")
        return render(request, "accounts/linkedin_role_select.html", {
            "linkedin_email": linkedin_data.get("email", ""),
            "linkedin_name": linkedin_data.get("name", ""),
            "linkedin_picture": linkedin_data.get("profile_picture", ""),
        })


class LinkedInRoleSelectAPIView(views.APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        linkedin_data = request.session.pop("linkedin_data", None)
        if not linkedin_data:
            return response.Response(
                {"detail": "No LinkedIn session data found. Please sign in with LinkedIn again."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        role = request.data.get("role")
        if role not in ("job_seeker", "recruiter"):
            return response.Response(
                {"detail": "Please select a valid role."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        email = linkedin_data["email"]
        try:
            user = User.objects.get(email=email, role=role)
            refresh = RefreshToken.for_user(user)
            return response.Response({
                "user": UserSerializer(user).data,
                "access": str(refresh.access_token),
                "refresh": str(refresh),
            })
        except User.DoesNotExist:
            if User.objects.filter(email=email).exists():
                return response.Response(
                    {"detail": "This LinkedIn account is already associated with a different profile on SkillSync AI."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        base_username = linkedin_data.get("username", email.split("@")[0])
        username = base_username
        counter = 1
        while User.objects.filter(username=username).exists():
            username = f"{base_username}_{counter}"
            counter += 1

        user = User.objects.create_user(
            email=email,
            username=username,
            password=os.urandom(32).hex(),
            role=role,
            profile_picture=linkedin_data.get("profile_picture", ""),
        )
        UserProfile.objects.create(user=user)

        refresh = RefreshToken.for_user(user)
        return response.Response({
            "user": UserSerializer(user).data,
            "access": str(refresh.access_token),
            "refresh": str(refresh),
        })


class LinkedInConflictPageView(views.APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        conflict_data = request.session.get("linkedin_conflict_data")
        if not conflict_data:
            return redirect("/login/")
        labels = {"job_seeker": "Job Seeker", "recruiter": "Recruiter", "admin": "Admin"}
        return render(request, "accounts/linkedin_conflict.html", {
            "conflict_email": conflict_data.get("email", ""),
            "existing_role": conflict_data.get("existing_role", ""),
            "existing_role_label": labels.get(conflict_data.get("existing_role", ""), "User"),
            "requested_role": conflict_data.get("requested_role", ""),
            "requested_role_label": labels.get(conflict_data.get("requested_role", ""), "User"),
            "linkedin_name": conflict_data.get("name", ""),
            "linkedin_picture": conflict_data.get("profile_picture", ""),
        })


class LinkedInConflictResolveAPIView(views.APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        conflict_data = request.session.pop("linkedin_conflict_data", None)
        if not conflict_data:
            return response.Response(
                {"detail": "No conflict data found. Please sign in with LinkedIn again."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        email = conflict_data.get("email")
        try:
            user = User.objects.get(email=email)
            refresh = RefreshToken.for_user(user)
            return response.Response({
                "user": UserSerializer(user).data,
                "access": str(refresh.access_token),
                "refresh": str(refresh),
            })
        except User.DoesNotExist:
            return response.Response(
                {"detail": "Account not found."},
                status=status.HTTP_404_NOT_FOUND,
            )


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