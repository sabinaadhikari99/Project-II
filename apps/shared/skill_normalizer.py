import re

SKILL_ALIASES = {
    "js": "javascript",
    "ts": "typescript",
    "drf": "djangorestframework",
}

CANONICAL_NAMES = {
    "nextjs": "Next.js",
    "reactjs": "React.js",
    "nodejs": "Node.js",
    "expressjs": "Express.js",
    "vuejs": "Vue.js",
    "javascript": "JavaScript",
    "typescript": "TypeScript",
    "postgresql": "PostgreSQL",
    "mongodb": "MongoDB",
    "djangorestframework": "Django REST Framework",
    "machinelearning": "Machine Learning",
    "deeplearning": "Deep Learning",
    "tailwindcss": "Tailwind CSS",
    "springboot": "Spring Boot",
    "scikitlearn": "Scikit-learn",
    "powerbi": "Power BI",
    "cplusplus": "C++",
    "csharp": "C#",
}


def normalize_skill(skill):
    if not skill or not isinstance(skill, str):
        return ""
    s = skill.strip().lower()
    s = re.sub(r'[\s._-]+', '', s)
    return SKILL_ALIASES.get(s, s)


def normalize_skill_set(skills):
    return {normalize_skill(s) for s in (skills or []) if isinstance(s, str) and s.strip()}


def display_name(skill):
    if not skill or not isinstance(skill, str):
        return ""
    normalized = normalize_skill(skill)
    return CANONICAL_NAMES.get(normalized, skill.strip())
