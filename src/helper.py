import os
from pathlib import Path
from textwrap import dedent

import fitz
import google.generativeai as genai
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()


def is_gemini_configured() -> bool:
    return bool(GEMINI_API_KEY)


def extract_text_from_pdf(uploaded_file) -> str:
    """Extract readable text from an uploaded PDF file."""
    with fitz.open(stream=uploaded_file.read(), filetype="pdf") as document:
        text = "\n".join(page.get_text("text") for page in document)
    return text.strip()


def build_resume_analysis_prompt(resume_text: str, location: str = "", domain: str = "") -> str:
    preferences = []
    if location:
        preferences.append(f"Location: {location}")
    if domain:
        preferences.append(f"Preferred field: {domain}")

    preference_text = "\n".join(preferences) if preferences else "No optional preferences provided."

    return dedent(
        f"""
        You are an expert AI Career Coach and Job Recommendation Engine.

        Your task is to analyze the user's uploaded resume text and provide highly accurate
        job recommendations, skill gap analysis, and career guidance.

        Important rules:
        - Treat the resume text as real candidate data.
        - Do not assume missing skills; only infer from the resume text.
        - If resume text is empty or unclear, politely ask for re-upload.
        - Be professional, precise, structured, and actionable.
        - Recommend entry, mid, or senior roles only based on evidence in the resume.
        - Consider current industry demand, but do not hallucinate skills not present in the resume.

        Optional preferences:
        {preference_text}

        Resume text:
        {resume_text}

        Output format:

        1. Candidate Summary:
        2. Extracted Skills:
        3. Recommended Job Roles:
        4. Skill Gap Analysis:
        5. Learning Roadmap:
        6. Resume Improvement Tips:
        7. Final Advice:
        """
    ).strip()


def build_job_keyword_prompt(analysis: str, resume_text: str) -> str:
    return dedent(
        f"""
        Extract the best LinkedIn job-search titles and keywords for this candidate.

        Return only comma-separated search terms. Do not include explanations.

        Career analysis:
        {analysis}

        Resume text:
        {resume_text}
        """
    ).strip()


def ask_gemini(prompt: str, max_tokens: int = 1200) -> str:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is missing in the .env file.")

    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel(GEMINI_MODEL)
    response = model.generate_content(
        prompt,
        generation_config={
            "temperature": 0.4,
            "max_output_tokens": max_tokens,
        },
    )
    return (getattr(response, "text", "") or "").strip()
