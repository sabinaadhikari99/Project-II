import re

SKILL_ALIASES = {
    "js": "javascript",
    "ts": "typescript",
    "py": "python",
    "drf": "djangorestframework",
    "reactjs": "react",
    "react.js": "react",
    "reactnative": "reactnative",
    "react native": "reactnative",
    "nodejs": "node.js",
    "node.js": "node.js",
    "expressjs": "express",
    "express.js": "express",
    "vuejs": "vue.js",
    "vue.js": "vue.js",
    "nextjs": "next.js",
    "next.js": "next.js",
    "angularjs": "angular",
    "springboot": "springboot",
    "spring boot": "springboot",
    "tailwindcss": "tailwindcss",
    "tailwind css": "tailwindcss",
    "scikitlearn": "scikitlearn",
    "scikit learn": "scikitlearn",
    "sklearn": "scikitlearn",
    "powerbi": "powerbi",
    "power bi": "powerbi",
    "postgresql": "postgresql",
    "postgres": "postgresql",
    "mongodb": "mongodb",
    "mongo": "mongodb",
    "django rest framework": "djangorestframework",
    "django rest": "djangorestframework",
    "machinelearning": "machinelearning",
    "machine learning": "machinelearning",
    "deeplearning": "deeplearning",
    "deep learning": "deeplearning",
    "tensorflow": "tensorflow",
    "tensor flow": "tensorflow",
    "tf": "tensorflow",
    "pytorch": "pytorch",
    "torch": "pytorch",
    "kubernetes": "kubernetes",
    "k8s": "kubernetes",
    "aws": "aws",
    "amazon web services": "aws",
    "gcp": "gcp",
    "google cloud": "gcp",
    "gcloud": "gcp",
    "cplusplus": "cplusplus",
    "c++": "cplusplus",
    "csharp": "csharp",
    "c#": "csharp",
    "flutter sdk": "flutter",
    "flutter": "flutter",
    "dart": "dart",
    "html5": "html",
    "css3": "css",
    "scss": "scss",
    "sass": "scss",
    "cicd": "cicd",
    "ci/cd": "cicd",
    "ci cd": "cicd",
    "nlp": "nlp",
    "natural language processing": "nlp",
    "computer vision": "computervision",
    "artificial intelligence": "ai",
    "large language model": "llm",
    "large language models": "llm",
}

CANONICAL_NAMES = {
    "next.js": "Next.js",
    "react": "React",
    "reactnative": "React Native",
    "node.js": "Node.js",
    "express": "Express",
    "vue.js": "Vue.js",
    "angular": "Angular",
    "javascript": "JavaScript",
    "typescript": "TypeScript",
    "python": "Python",
    "java": "Java",
    "cplusplus": "C++",
    "csharp": "C#",
    "postgresql": "PostgreSQL",
    "mongodb": "MongoDB",
    "djangorestframework": "Django REST Framework",
    "machinelearning": "Machine Learning",
    "deeplearning": "Deep Learning",
    "tensorflow": "TensorFlow",
    "pytorch": "PyTorch",
    "scikitlearn": "Scikit-learn",
    "kubernetes": "Kubernetes",
    "tailwindcss": "Tailwind CSS",
    "powerbi": "Power BI",
    "springboot": "Spring Boot",
    "cicd": "CI/CD",
    "computervision": "Computer Vision",
    "llm": "LLM",
    "ai": "AI",
    "flutter": "Flutter",
    "swift": "Swift",
    "kotlin": "Kotlin",
    "scss": "SCSS",
    "html": "HTML",
    "css": "CSS",
}


def normalize_skill(skill):
    if not skill or not isinstance(skill, str):
        return ""
    s = skill.strip().lower()
    direct_key = re.sub(r'[\s._-]+', '', s)
    result = SKILL_ALIASES.get(direct_key)
    if result:
        return result
    result = SKILL_ALIASES.get(s)
    if result:
        return result
    return direct_key


def normalize_skill_set(skills):
    return {normalize_skill(s) for s in (skills or []) if isinstance(s, str) and s.strip()}


def display_name(skill):
    if not skill or not isinstance(skill, str):
        return ""
    normalized = normalize_skill(skill)
    return CANONICAL_NAMES.get(normalized, skill.strip())
