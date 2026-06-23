# file path: apps/chatbot/services.py
from django.conf import settings


def career_chat(message: str) -> str:
    text = (message or "").lower()
    if "resume" in text:
        return "Lead with measurable impact, tailor skills to the job, and keep your resume to the most relevant experience."
    if "interview" in text:
        return "Use the STAR method: situation, task, action, result. Practice concise stories for your top projects."
    if "skill" in text:
        return "Compare your profile skills with target jobs, then build one portfolio project for each major gap."
    if settings.GEMINI_API_KEY:
        try:
            import google.generativeai as genai

            genai.configure(api_key=settings.GEMINI_API_KEY)
            model = genai.GenerativeModel("gemini-pro")
            return model.generate_content(message).text
        except Exception:
            pass
    return "I can help with resumes, interview prep, skill gaps, and job search strategy. What role are you targeting?"


def interview_questions(role: str) -> list[str]:
    role = role or "software engineer"
    return [
        f"Tell me about a project that proves you are ready for a {role} role.",
        "Describe a time you resolved ambiguity with data.",
        "How do you prioritize when deadlines conflict?",
        "What technical skill are you actively improving, and how are you measuring progress?",
        "Why is this opportunity a strong fit for your career direction?",
    ]
