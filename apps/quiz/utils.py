# file path: apps/quiz/utils.py

import json
import re

import google.generativeai as genai
from django.conf import settings


# Configure Gemini
genai.configure(api_key=settings.GEMINI_API_KEY)

model = genai.GenerativeModel(
    model_name="gemini-2.5-flash",
    generation_config={
        "temperature": 0.4,
        "top_p": 0.95,
        "max_output_tokens": 4096,
    },
)


def clean_json(text: str):
    """
    Remove markdown code fences and parse JSON safely.
    """

    text = text.strip()

    text = re.sub(r"^```json", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^```", "", text)
    text = re.sub(r"```$", "", text)

    return json.loads(text)


def generate_quiz_from_resume(resume_text: str):
    """
    Generate interview MCQs from resume text using Gemini.
    """

    prompt = f"""
You are an expert technical interviewer.

Read the following resume carefully.

Resume:

{resume_text}

Generate EXACTLY 10 interview multiple-choice questions.

Rules:

1. Questions MUST ONLY be about technologies mentioned in the resume.

2. Ask about:
   - Programming languages
   - Frameworks
   - Libraries
   - Databases
   - Projects
   - APIs
   - Tools
   - Cloud
   - Git
   - Software engineering concepts

3. Mix Easy, Medium and Hard questions.

4. Each question must contain exactly FOUR options.

5. Only ONE option must be correct.

6. Return ONLY JSON.

Format:

[
  {{
    "id": 1,
    "question": "Which framework is used to build REST APIs in this resume?",
    "options": [
      "Django REST Framework",
      "Laravel",
      "Spring Boot",
      "Express"
    ],
    "answer": "Django REST Framework"
  }}
]

DO NOT return markdown.

DO NOT return explanations.

ONLY JSON.
"""

    try:

        response = model.generate_content(prompt)

        questions = clean_json(response.text)

        if not isinstance(questions, list):
            raise Exception("Gemini returned invalid JSON.")

        return questions

    except Exception as e:

        print("Gemini Quiz Error:", e)

        return [
            {
                "id": 1,
                "question": "Unable to generate quiz.",
                "options": [
                    "Retry later",
                    "Gemini Error",
                    "Resume Missing",
                    "Unknown",
                ],
                "answer": "Retry later",
            }
        ]