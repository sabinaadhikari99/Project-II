# file path: apps/chatbot/services.py
from django.conf import settings


def _local_chat_response(text: str) -> str:
    if any(greeting in text for greeting in ["hello", "hi", "hey", "hiya", "good morning", "good afternoon", "good evening", "greetings"]):
        return (
            "Hi there! I’m SkillSync AI, your career coach. "
            "I can help with resumes, interviews, skills, or career planning — what would you like to discuss today?"
        )
    if "resume" in text or "cv" in text or "cover letter" in text:
        return (
            "Focus your resume on measurable results, tailor it to the job, and keep the content concise "
            "by highlighting key achievements and relevant skills."
        )
    if "interview" in text or "mock" in text or "questions" in text:
        return (
            "Prepare concise stories using the STAR method, emphasize your impact, and practice clear, calm delivery "
            "for each example."
        )
    if "skill" in text or "gap" in text or "learning" in text or "upskill" in text:
        return (
            "Compare your current skills with your target roles, then build focused projects to fill the highest-priority gaps."
        )
    if "job" in text or "career" in text or "role" in text or "position" in text:
        return (
            "Define the next role you want, then match your resume and preparation to that target with concrete examples "
            "and a clear growth story."
        )
    if "linkedin" in text or "network" in text or "connections" in text:
        return (
            "Use LinkedIn to share accomplishments, engage with target companies, and reach out with a concise career summary."
        )
    if "salary" in text or "pay" in text or "compensation" in text:
        return (
            "Research market ranges for your role and location, then frame compensation conversations around the value you bring."
        )
    return (
        "That sounds interesting. Tell me a little more about what you want help with — for example, resume advice, interview prep, "
        "skill development, or career planning — and I’ll give you a practical answer."
    )


def career_chat(message: str) -> str:
    text = (message or "").strip()
    if not text:
        return "Please share your question or the area where you want career guidance."

    normalized = text.lower()
    if settings.GEMINI_API_KEY:
        try:
            import google.generativeai as genai

            genai.configure(api_key=settings.GEMINI_API_KEY)
            model = genai.GenerativeModel("gemini-pro")
            prompt = (
                "You are an expert AI career coach. Answer the user question directly and accurately, "
                "using only the information in the question. Focus on resumes, interviews, skill gaps, "
                "job search, and career planning. Do not provide unrelated advice.\n\n"
                f"User question: {text}\n\n"
                "Answer clearly and concisely."
            )
            result = model.generate_content(prompt)
            reply = getattr(result, "text", "") or ""
            if reply.strip():
                return reply.strip()
        except Exception:
            pass

    return _local_chat_response(normalized)


def interview_questions(role: str) -> list[str]:
    role = role or "software engineer"
    return [
        f"Tell me about a project that proves you are ready for a {role} role.",
        "Describe a time you resolved ambiguity with data.",
        "How do you prioritize when deadlines conflict?",
        "What technical skill are you actively improving, and how are you measuring progress?",
        "Why is this opportunity a strong fit for your career direction?",
    ]
