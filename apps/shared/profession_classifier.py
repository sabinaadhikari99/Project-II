import logging
import re

from django.conf import settings

logger = logging.getLogger(__name__)

SKILL_SYNONYMS = {
    "adobe photoshop": "Photoshop",
    "adobe illustrator": "Illustrator",
    "adobe indesign": "InDesign",
    "adobe creative suite": "Adobe Creative Suite",
    "figma": "Figma",
    "sketch": "Sketch",
    "js": "JavaScript",
    "javascript": "JavaScript",
    "ts": "TypeScript",
    "typescript": "TypeScript",
    "react": "React",
    "reactjs": "React",
    "react.js": "React",
    "react native": "React Native",
    "reactnative": "React Native",
    "node": "Node.js",
    "nodejs": "Node.js",
    "node.js": "Node.js",
    "expressjs": "Express",
    "express.js": "Express",
    "express": "Express",
    "tf": "TensorFlow",
    "tensor flow": "TensorFlow",
    "tensorflow": "TensorFlow",
    "torch": "PyTorch",
    "pytorch": "PyTorch",
    "sklearn": "Scikit-learn",
    "scikit learn": "Scikit-learn",
    "scikit-learn": "Scikit-learn",
    "keras": "Keras",
    "pandas": "Pandas",
    "numpy": "NumPy",
    "matplotlib": "Matplotlib",
    "seaborn": "Seaborn",
    "django": "Django",
    "drf": "Django REST Framework",
    "django rest": "Django REST Framework",
    "django rest framework": "Django REST Framework",
    "fastapi": "FastAPI",
    "flask": "Flask",
    "python": "Python",
    "java": "Java",
    "c++": "C++",
    "c#": "C#",
    "html": "HTML",
    "html5": "HTML",
    "css": "CSS",
    "css3": "CSS",
    "springboot": "Spring Boot",
    "spring boot": "Spring Boot",
    "tailwind": "Tailwind CSS",
    "tailwind css": "Tailwind CSS",
    "tailwindcss": "Tailwind CSS",
    "next": "Next.js",
    "nextjs": "Next.js",
    "next.js": "Next.js",
    "vue": "Vue.js",
    "vuejs": "Vue.js",
    "vue.js": "Vue.js",
    "angular": "Angular",
    "angularjs": "Angular",
    "svelte": "Svelte",
    "bootstrap": "Bootstrap",
    "scss": "SCSS",
    "sass": "SCSS",
    "postgres": "PostgreSQL",
    "postgresql": "PostgreSQL",
    "mysql": "MySQL",
    "sqlite": "SQLite",
    "mongo": "MongoDB",
    "mongodb": "MongoDB",
    "redis": "Redis",
    "docker": "Docker",
    "kubernetes": "Kubernetes",
    "k8s": "Kubernetes",
    "aws": "AWS",
    "amazon web services": "AWS",
    "azure": "Azure",
    "gcp": "GCP",
    "gcloud": "GCP",
    "google cloud": "GCP",
    "terraform": "Terraform",
    "ansible": "Ansible",
    "jenkins": "Jenkins",
    "ml": "Machine Learning",
    "machine learning": "Machine Learning",
    "deep learning": "Deep Learning",
    "dl": "Deep Learning",
    "nlp": "NLP",
    "natural language processing": "NLP",
    "cv": "Computer Vision",
    "computer vision": "Computer Vision",
    "ai": "Artificial Intelligence",
    "artificial intelligence": "Artificial Intelligence",
    "llm": "LLM",
    "large language model": "LLM",
    "large language models": "LLM",
    "rag": "RAG",
    "faiss": "FAISS",
    "mlops": "MLOps",
    "ci/cd": "CI/CD",
    "cicd": "CI/CD",
    "etl": "ETL",
    "airflow": "Airflow",
    "spark": "Spark",
    "apache spark": "Spark",
    "kafka": "Kafka",
    "tableau": "Tableau",
    "power bi": "Power BI",
    "powerbi": "Power BI",
    "sql": "SQL",
    "nosql": "NoSQL",
    "git": "Git",
    "github actions": "GitHub Actions",
    "gitlab ci": "GitLab CI",
    "jira": "JIRA",
    "confluence": "Confluence",
    "adobe xd": "Adobe XD",
    "invision": "InVision",
    "zeplin": "Zeplin",
    "branding": "Branding",
    "typography": "Typography",
    "wireframing": "Wireframing",
    "prototyping": "Prototyping",
    "ux research": "User Research",
    "user research": "User Research",
    "ui design": "UI Design",
    "ux design": "UX Design",
    "responsive design": "Responsive Design",
    "photography": "Photography",
    "canva": "Canva",
    "print design": "Print Design",
    "layout design": "Layout",
    "quickbooks": "QuickBooks",
    "xero": "Xero",
    "crm": "CRM",
    "hubspot": "HubSpot",
    "seo": "SEO",
    "sem": "SEM",
    "kotlin": "Kotlin",
    "swift": "Swift",
    "flutter": "Flutter",
    "flutter sdk": "Flutter",
    "react native": "React Native",
    "android": "Android",
    "ios": "iOS",
    "go": "Go",
    "rust": "Rust",
    "ruby": "Ruby",
    "scala": "Scala",
    "php": "PHP",
    "swiftui": "SwiftUI",
    "ui kit": "UIKit",
    "dart": "Dart",
    "py": "Python",
}

SECTION_PATTERNS = {
    "title": re.compile(
        r"(?:^|\n)\s*(?:resume|curriculum vitae|cv|career|profile)\s*[:\-]?\s*(.+?)(?=\n\s*\n|\n(?=[A-Z]))",
        re.IGNORECASE,
    ),
    "summary": re.compile(
        r"(?:professional\s+summary|summary|profile\s+summary|career\s+objective|objective|about\s+me)\s*[:\-]?\s*(.+?)(?=\n\s*\n|\n(?=[A-Z]))",
        re.IGNORECASE | re.DOTALL,
    ),
    "experience": re.compile(
        r"(?:experience|work\s+experience|professional\s+experience|employment|work\s+history)\s*[:\-]?\s*(.+?)(?=\n\s*\n(?:education|skills|projects|certifications|$))",
        re.IGNORECASE | re.DOTALL,
    ),
    "education": re.compile(
        r"(?:education|academic\s+background|qualifications)\s*[:\-]?\s*(.+?)(?=\n\s*\n(?:skills|projects|certifications|experience|$))",
        re.IGNORECASE | re.DOTALL,
    ),
    "projects": re.compile(
        r"(?:projects|project\s+experience|key\s+projects|personal\s+projects)\s*[:\-]?\s*(.+?)(?=\n\s*\n(?:education|skills|certifications|experience|$))",
        re.IGNORECASE | re.DOTALL,
    ),
    "certifications": re.compile(
        r"(?:certifications|certificates|licenses|credentials)\s*[:\-]?\s*(.+?)(?=\n\s*\n(?:skills|education|projects|experience|$))",
        re.IGNORECASE | re.DOTALL,
    ),
}

GENERIC_TITLE_WORDS = {
    "developer", "engineer", "manager", "designer", "analyst", "scientist",
    "intern", "junior", "senior", "lead", "staff", "principal", "associate",
    "specialist", "consultant", "architect", "administrator", "coordinator",
    "officer", "head", "director", "vp", "vice", "president", "executive",
    "trainee", "apprentice", "freelance", "contract", "full-time", "part-time",
}

PROFESSION_CONFIGS = {
    "Frontend Developer": {
        "titles": {
            "frontend developer", "front end developer", "frontend engineer",
            "front end engineer", "ui developer", "ui engineer",
            "react developer", "vue developer", "angular developer",
            "web developer", "frontend", "web ui developer",
            "javascript developer", "typescript developer",
            "front-end developer", "front-end engineer",
        },
        "skills": {
            "React": 10, "Next.js": 10, "Vue.js": 10, "Angular": 10, "Svelte": 8,
            "TypeScript": 10, "JavaScript": 8, "HTML": 2, "CSS": 2,
            "SCSS": 4, "Tailwind CSS": 8, "Bootstrap": 5,
            "Webpack": 6, "Vite": 6, "Redux": 8, "GraphQL": 7,
            "Figma": 3, "Responsive Design": 6,
        },
    },
    "Backend Developer": {
        "titles": {
            "backend developer", "back end developer", "backend engineer",
            "back end engineer", "python developer", "django developer",
            "api developer", "server side developer", "backend",
            "back-end developer", "back-end engineer", "node.js developer",
            "node developer", "java developer", "spring boot developer",
            "go developer", "ruby developer", "php developer",
        },
        "skills": {
            "Python": 10, "Django": 10, "Django REST Framework": 9, "FastAPI": 9,
            "Flask": 7, "Node.js": 8, "Express": 7, "Spring Boot": 8,
            "Java": 8, "Go": 8, "PostgreSQL": 8, "MySQL": 7, "MongoDB": 7,
            "Redis": 6, "SQL": 8, "REST APIs": 8, "Microservices": 7,
            "API Design": 7, "Celery": 6, "RabbitMQ": 5, "Kafka": 6,
        },
    },
    "Full Stack Developer": {
        "titles": {
            "full stack developer", "full stack engineer", "fullstack developer",
            "full stack", "fullstack", "full-stack developer",
            "full-stack engineer", "mean stack developer",
            "mern stack developer", "full stack web developer",
        },
        "skills": {
            "React": 8, "Next.js": 7, "Vue.js": 7, "Angular": 7,
            "JavaScript": 8, "TypeScript": 8, "HTML": 3, "CSS": 3,
            "Tailwind CSS": 5, "Bootstrap": 4,
            "Python": 8, "Django": 8, "Django REST Framework": 7, "FastAPI": 7,
            "Node.js": 7, "Express": 6, "PostgreSQL": 7, "MySQL": 6,
            "MongoDB": 6, "SQL": 7, "REST APIs": 7, "Git": 4, "Docker": 5,
        },
    },
    "Software Engineer": {
        "titles": {
            "software engineer", "software developer", "programmer",
            "software engineer intern", "software developer intern",
            "software engineering", "sde", "sde intern",
        },
        "skills": {
            "Python": 8, "Java": 9, "C++": 9, "C#": 8, "Go": 8, "Rust": 7,
            "Ruby": 6, "Scala": 6, "Kotlin": 7,
            "Data Structures": 9, "Algorithms": 9, "System Design": 8,
            "OOP": 7, "Microservices": 6, "REST APIs": 7, "API Design": 6,
            "Design Patterns": 7, "TDD": 6, "CI/CD": 5,
            "Git": 6, "Docker": 6, "Kubernetes": 5, "AWS": 6, "Azure": 5, "GCP": 5,
        },
    },
    "DevOps Engineer": {
        "titles": {
            "devops engineer", "dev ops engineer", "site reliability engineer",
            "sre", "platform engineer", "cloud engineer", "infrastructure engineer",
            "devops", "cloud architect", "infrastructure architect",
        },
        "skills": {
            "Docker": 10, "Kubernetes": 10, "AWS": 9, "Azure": 8, "GCP": 8,
            "Terraform": 9, "Ansible": 8, "Jenkins": 8, "CI/CD": 9,
            "Linux": 8, "Git": 6, "Helm": 7,
            "Prometheus": 7, "Grafana": 7, "ELK Stack": 6, "Shell Scripting": 7, "YAML": 5,
        },
    },
    "Data Scientist": {
        "titles": {
            "data scientist", "data science", "ai engineer", "ai scientist",
            "machine learning scientist", "research scientist", "data science intern",
            "data science engineer",
        },
        "skills": {
            "Machine Learning": 10, "Deep Learning": 9, "NLP": 9, "Computer Vision": 8,
            "Python": 9, "Pandas": 8, "NumPy": 8, "Scikit-learn": 8,
            "TensorFlow": 9, "PyTorch": 9, "Keras": 7,
            "SQL": 5, "Statistics": 9, "Probability": 8,
            "Data Visualization": 7, "Matplotlib": 6, "Seaborn": 6, "Tableau": 5,
            "Power BI": 4, "Feature Engineering": 8, "A/B Testing": 7,
        },
    },
    "Machine Learning Engineer": {
        "titles": {
            "machine learning engineer", "ml engineer", "mlops engineer",
            "deep learning engineer", "nlp engineer", "ml engineering",
            "ai engineer", "ai ml engineer",
        },
        "skills": {
            "Python": 9, "TensorFlow": 10, "PyTorch": 10, "Keras": 7,
            "Machine Learning": 10, "Deep Learning": 10, "NLP": 9,
            "FAISS": 8, "MLOps": 8, "Docker": 7, "Kubernetes": 6,
            "AWS": 7, "Feature Engineering": 8, "Model Deployment": 9,
            "CI/CD": 6, "Pandas": 6, "NumPy": 6, "Scikit-learn": 7,
        },
    },
    "Data Engineer": {
        "titles": {
            "data engineer", "data pipeline engineer", "big data engineer",
            "data infrastructure engineer", "analytics engineer", "data engineering",
            "data architect", "data warehouse engineer",
        },
        "skills": {
            "Python": 9, "SQL": 9, "ETL": 10, "Spark": 9, "Hadoop": 7,
            "Airflow": 9, "Kafka": 8, "Pandas": 7, "NumPy": 6,
            "Data Modeling": 8, "Snowflake": 7, "BigQuery": 7,
            "Redshift": 7, "Data Pipeline": 9, "Data Warehouse": 8,
        },
    },
    "Data Analyst": {
        "titles": {
            "data analyst", "analytics", "business intelligence analyst",
            "data analyst intern", "junior data analyst", "business analyst",
            "data analyst",
        },
        "skills": {
            "SQL": 10, "Excel": 9, "Tableau": 8, "Power BI": 8,
            "Python": 7, "Pandas": 6, "Data Visualization": 9,
            "Statistics": 8, "A/B Testing": 7, "R": 6,
            "Looker": 6, "Data Cleaning": 8, "Dashboarding": 9, "Reporting": 7,
        },
    },
    "Graphic Designer": {
        "titles": {
            "graphic designer", "visual designer", "creative designer",
            "graphic design", "brand designer", "graphic design intern",
            "graphic artist", "graphics designer",
        },
        "skills": {
            "Photoshop": 10, "Illustrator": 10, "Figma": 5, "Sketch": 5,
            "InDesign": 8, "Branding": 9, "Typography": 9,
            "Color Theory": 8, "UI Design": 5, "UX Design": 4,
            "Wireframing": 4, "Visual Design": 9, "Logos": 8,
            "Canva": 5, "Print Design": 7, "Layout": 7,
        },
    },
    "UI/UX Designer": {
        "titles": {
            "ui designer", "ux designer", "ux researcher", "product designer",
            "interaction designer", "ui/ux designer", "user experience designer",
            "user interface designer", "ux engineer",
        },
        "skills": {
            "Figma": 10, "Sketch": 7, "Adobe XD": 8, "User Research": 10,
            "Wireframing": 9, "Prototyping": 10, "Usability Testing": 9,
            "Interaction Design": 9, "Information Architecture": 8,
            "Design Systems": 8, "Responsive Design": 7,
            "HTML": 3, "CSS": 3, "User Flows": 8, "Personas": 8,
        },
    },
    "Product Manager": {
        "titles": {
            "product manager", "product owner", "technical product manager",
            "product management", "associate product manager", "product lead",
            "product manager intern", "senior product manager",
        },
        "skills": {
            "Product Strategy": 10, "Roadmapping": 9, "User Research": 8,
            "A/B Testing": 8, "SQL": 5, "Data Analysis": 7,
            "Agile": 8, "Scrum": 8, "JIRA": 7, "Stakeholder Management": 8,
            "Market Research": 7, "Wireframing": 5, "APIs": 4, "Product Metrics": 9,
        },
    },
    "Marketing Manager": {
        "titles": {
            "marketing manager", "marketing", "digital marketing manager",
            "growth marketer", "brand manager", "content marketing manager",
            "marketing specialist", "marketing coordinator",
        },
        "skills": {
            "Digital Marketing": 10, "SEO": 9, "SEM": 8, "Content Strategy": 8,
            "Social Media": 8, "Google Analytics": 8, "Email Marketing": 7,
            "Marketing Automation": 7, "CRM": 6, "HubSpot": 6,
            "Growth Strategy": 8, "Campaign Management": 8, "Brand Strategy": 7,
        },
    },
    "Accountant": {
        "titles": {
            "accountant", "accounting", "staff accountant", "senior accountant",
            "financial accountant", "tax accountant", "accountant intern",
            "chartered accountant", "accounts payable", "accounts receivable",
        },
        "skills": {
            "Accounting": 10, "QuickBooks": 8, "Xero": 7, "Tax Preparation": 8,
            "Excel": 7, "Financial Reporting": 9, "GAAP": 9,
            "Auditing": 8, "Bookkeeping": 8, "ERP": 6,
            "SAP": 6, "Oracle Financials": 6, "Financial Analysis": 7,
        },
    },
    "Human Resources Manager": {
        "titles": {
            "hr manager", "human resources manager", "hr generalist",
            "talent acquisition", "recruiter", "people operations", "hr",
            "hr business partner", "hr specialist",
        },
        "skills": {
            "Recruiting": 9, "Onboarding": 8, "HR Policies": 9,
            "Employee Relations": 8, "Payroll": 7, "Benefits Administration": 7,
            "HRIS": 7, "Labor Laws": 8, "Performance Management": 8,
            "Talent Acquisition": 9, "ATS": 7,
        },
    },
    "Cybersecurity Engineer": {
        "titles": {
            "cybersecurity engineer", "security engineer", "security analyst",
            "penetration tester", "information security", "infosec",
            "cyber security", "security architect", "cybersecurity analyst",
        },
        "skills": {
            "Network Security": 9, "Penetration Testing": 9, "Ethical Hacking": 9,
            "SIEM": 8, "Firewall": 8, "IDS/IPS": 8, "Risk Assessment": 8,
            "Compliance": 7, "CISSP": 8, "Python": 6, "Linux": 7,
            "Security Auditing": 8, "Cryptography": 7,
        },
    },
    "Mobile Developer": {
        "titles": {
            "mobile developer", "android developer", "ios developer",
            "react native developer", "flutter developer", "mobile engineer",
            "mobile app developer", "android engineer", "ios engineer",
            "swift developer", "kotlin developer", "mobile application developer",
            "ios app developer", "android app developer",
        },
        "skills": {
            "Kotlin": 10, "Swift": 10, "React Native": 9, "Flutter": 9,
            "Dart": 6, "Android": 9, "iOS": 9, "Java": 7, "SwiftUI": 7, "UIKit": 7,
            "Mobile UI": 7, "App Store": 6, "Firebase": 7,
            "REST APIs": 6, "Mobile Architecture": 8,
        },
    },
}

RELATED_PROFESSIONS = {
    "Frontend Developer": {"Full Stack Developer", "UI/UX Designer", "Mobile Developer"},
    "Backend Developer": {"Full Stack Developer", "Software Engineer", "DevOps Engineer"},
    "Full Stack Developer": {"Frontend Developer", "Backend Developer", "Software Engineer"},
    "Software Engineer": {"Backend Developer", "Full Stack Developer", "DevOps Engineer"},
    "DevOps Engineer": {"Backend Developer", "Software Engineer", "Cybersecurity Engineer"},
    "Data Scientist": {"Machine Learning Engineer", "Data Engineer", "Data Analyst"},
    "Machine Learning Engineer": {"Data Scientist", "Data Engineer", "Software Engineer"},
    "Data Engineer": {"Data Scientist", "Data Analyst", "Software Engineer"},
    "Data Analyst": {"Data Scientist", "Data Engineer", "Product Manager"},
    "Graphic Designer": {"UI/UX Designer"},
    "UI/UX Designer": {"Graphic Designer", "Frontend Developer", "Product Manager"},
    "Product Manager": {"Data Analyst", "Marketing Manager"},
    "Marketing Manager": {"Product Manager"},
    "Accountant": set(),
    "Human Resources Manager": set(),
    "Cybersecurity Engineer": {"DevOps Engineer"},
    "Mobile Developer": {"Frontend Developer", "Full Stack Developer"},
}

SECTIONS_WEIGHTS = {
    "title": 50,
    "summary": 15,
    "experience": 15,
    "projects": 5,
    "skills": 15,
}


def normalize_skill(raw):
    raw_lower = str(raw).strip().lower()
    if raw_lower in SKILL_SYNONYMS:
        return SKILL_SYNONYMS[raw_lower]
    return str(raw).strip()


def _build_skill_pattern(skill_name):
    escaped = re.escape(skill_name.lower())
    return re.compile(r"(?<![a-z0-9+#.])" + escaped + r"(?![a-z0-9+#.])", re.IGNORECASE)


def extract_resume_sections(resume_text):
    sections = {"title": "", "summary": "", "experience": "", "projects": "", "skills": "", "certifications": ""}
    for key, pattern in SECTION_PATTERNS.items():
        match = pattern.search(resume_text)
        if match:
            sections[key] = match.group(1).strip()
    if not sections["title"]:
        first_lines = [l.strip() for l in resume_text.splitlines() if l.strip()][:3]
        sections["title"] = first_lines[0] if first_lines else ""
    return sections


def extract_skills_from_section(text):
    if not text:
        return []
    found = set()
    text_lower = text.lower()
    for synonym_key, canon in SKILL_SYNONYMS.items():
        pattern = _build_skill_pattern(synonym_key)
        if pattern.search(text):
            found.add(canon)
    all_skill_names = set()
    for config in PROFESSION_CONFIGS.values():
        all_skill_names.update(config["skills"].keys())
    for skill in sorted(all_skill_names, key=len, reverse=True):
        pattern = _build_skill_pattern(skill)
        if pattern.search(text):
            found.add(skill)
    return sorted(found, key=str.lower)


def _matches_profession_title(title_lower, pattern):
    return pattern in title_lower


def _has_unique_term_match(title_lower, pattern):
    title_words = set(title_lower.split())
    pattern_words = set(pattern.split())
    unique_pattern = pattern_words - GENERIC_TITLE_WORDS
    if not unique_pattern:
        return len(pattern_words & title_words) >= len(pattern_words) * 0.75
    matched_unique = unique_pattern & title_words
    if not matched_unique:
        return False
    overlap = len(pattern_words & title_words)
    return overlap >= len(pattern_words) * 0.6


def _score_title(resume_title, profession):
    if not resume_title:
        return 0, 0
    title_lower = resume_title.lower()
    config = PROFESSION_CONFIGS.get(profession, {})
    t = config.get("titles", set())
    for pattern in t:
        if _matches_profession_title(title_lower, pattern):
            return 100, 1.0
    for pattern in t:
        if _has_unique_term_match(title_lower, pattern):
            return 70, 0.7
    return 0, 0.0


def _count_skill_matches_in_text(text, profession):
    if not text:
        return 0, 0
    config = PROFESSION_CONFIGS.get(profession, {})
    skills = config.get("skills", {})
    if not skills:
        return 0, 0
    matches = 0
    for skill in skills:
        pattern = _build_skill_pattern(skill)
        if pattern.search(text):
            matches += 1
    return matches, len(skills)


def _score_summary(summary_text, profession):
    if not summary_text:
        return 0, 0
    summary_lower = summary_text.lower()
    config = PROFESSION_CONFIGS.get(profession, {})
    t = config.get("titles", set())
    for pattern in t:
        if pattern in summary_lower:
            return 100, 1.0
    matches, total = _count_skill_matches_in_text(summary_text, profession)
    if total == 0:
        return 0, 0
    ratio = matches / total
    scaled = min(100, round(ratio * 200))
    return scaled, ratio


def _score_experience(exp_text, profession):
    if not exp_text:
        return 0, 0
    exp_lower = exp_text.lower()
    config = PROFESSION_CONFIGS.get(profession, {})
    t = config.get("titles", set())
    for pattern in t:
        if pattern in exp_lower:
            return 100, 1.0
    matches, total = _count_skill_matches_in_text(exp_text, profession)
    if total == 0:
        return 0, 0
    ratio = matches / total
    scaled = min(100, round(ratio * 200))
    return scaled, ratio


def _score_projects(proj_text, profession):
    if not proj_text:
        return 0, 0
    matches, total = _count_skill_matches_in_text(proj_text, profession)
    if total == 0:
        return 0, 0
    ratio = matches / total
    scaled = min(100, round(ratio * 200))
    return scaled, ratio


def _score_skills(extracted_skills, profession):
    if not extracted_skills:
        return 0, 0
    config = PROFESSION_CONFIGS.get(profession, {})
    weighted_skills = config.get("skills", {})
    total_possible = sum(weighted_skills.values())
    if total_possible == 0:
        return 0, 0
    normalised = set()
    for s in extracted_skills:
        norm = normalize_skill(s)
        normalised.add(norm.lower())
    score = 0
    for skill_name, weight in weighted_skills.items():
        if skill_name.lower() in normalised:
            score += weight
    pct = round(score / total_possible * 100)
    return min(pct, 100), score / total_possible


def classify_profession_with_resume(resume_text, extracted_skills=None):
    sections = extract_resume_sections(resume_text)
    if extracted_skills is None:
        extracted_skills = extract_skills_from_section(resume_text)
    if not sections["title"] and not extracted_skills:
        return None, 0

    _log_debug("=" * 50)
    _log_debug("Resume Sections Extracted:")
    for key, val in sections.items():
        preview = val[:80].replace("\n", " ") if val else "(empty)"
        _log_debug(f"  {key}: {preview}")
    _log_debug(f"Extracted Skills ({len(extracted_skills)}): {extracted_skills}")

    profession_scores = {}
    for profession in PROFESSION_CONFIGS:
        title_score, title_raw = _score_title(sections["title"], profession)
        summary_score, summary_raw = _score_summary(sections["summary"], profession)
        exp_score, exp_raw = _score_experience(sections["experience"], profession)
        proj_score, proj_raw = _score_projects(sections["projects"], profession)
        skill_score, skill_raw = _score_skills(extracted_skills, profession)

        total = (
            title_score * SECTIONS_WEIGHTS["title"]
            + summary_score * SECTIONS_WEIGHTS["summary"]
            + exp_score * SECTIONS_WEIGHTS["experience"]
            + proj_score * SECTIONS_WEIGHTS["projects"]
            + skill_score * SECTIONS_WEIGHTS["skills"]
        )
        total_weight = sum(SECTIONS_WEIGHTS.values())
        final = total / total_weight if total_weight else 0
        profession_scores[profession] = {
            "final": final,
            "title": title_score,
            "summary": summary_score,
            "experience": exp_score,
            "projects": proj_score,
            "skills": skill_score,
            "breakdown": {
                "title_raw": title_raw,
                "summary_raw": summary_raw,
                "exp_raw": exp_raw,
                "proj_raw": proj_raw,
                "skill_raw": skill_raw,
            },
        }

    sorted_professions = sorted(
        profession_scores.items(), key=lambda x: x[1]["final"], reverse=True
    )
    best = sorted_professions[0]
    runner_up = sorted_professions[1] if len(sorted_professions) > 1 else (None, {})

    _log_debug(f"\nTop Profession: {best[0]} (score={best[1]['final']:.1f})")
    _log_debug(f"  Breakdown: title={best[1]['title']}, summary={best[1]['summary']}, "
               f"exp={best[1]['experience']}, proj={best[1]['projects']}, skills={best[1]['skills']}")
    if runner_up[0]:
        _log_debug(f"Runner-up: {runner_up[0]} (score={runner_up[1]['final']:.1f})")

    if best[1]["final"] < 15:
        _log_debug("Score too low, falling back to skill-only classification")
        return _fallback_skill_classify(extracted_skills)

    diff = best[1]["final"] - (runner_up[1]["final"] if runner_up[1] else 0)
    if diff < 10 and best[1]["final"] < 40:
        _log_debug("Close margin with low score, using title-weighted classification")
        return _title_weighted_classify(sections["title"], extracted_skills)

    return best[0], round(best[1]["final"])


def _fallback_skill_classify(extracted_skills):
    if not extracted_skills:
        return None, 0
    best_prof = None
    best_score = 0
    for profession, config in PROFESSION_CONFIGS.items():
        weighted = config.get("skills", {})
        total_possible = sum(weighted.values())
        if total_possible == 0:
            continue
        normalised = set()
        for s in extracted_skills:
            normalised.add(normalize_skill(s).lower())
        score = sum(w for s, w in weighted.items() if s.lower() in normalised)
        pct = round(score / total_possible * 100)
        if pct > best_score:
            best_score = pct
            best_prof = profession
    if best_prof and best_score >= 15:
        return best_prof, best_score
    return best_prof, best_score


def _title_weighted_classify(title, extracted_skills):
    if title:
        from_title = classify_profession_from_title(title)
        if from_title:
            skills_prof, skills_conf = _fallback_skill_classify(extracted_skills)
            title_weight = 60
            skills_weight = 40
            combined = {}
            all_profs = set()
            if from_title:
                match = PROFESSION_CONFIGS.get(from_title, {})
                score = 100
                combined[from_title] = score * title_weight / 100
                all_profs.add(from_title)
            if skills_prof:
                combined[skills_prof] = combined.get(skills_prof, 0) + skills_conf * skills_weight / 100
                all_profs.add(skills_prof)
            if combined:
                best = max(combined, key=combined.get)
                return best, round(combined[best])
    return _fallback_skill_classify(extracted_skills)


def classify_profession_from_skills(skills):
    best_prof = None
    best_score = 0
    for profession, config in PROFESSION_CONFIGS.items():
        weighted = config.get("skills", {})
        total_possible = sum(weighted.values())
        if total_possible == 0:
            continue
        normalised = set()
        for s in skills:
            normalised.add(normalize_skill(s).lower())
        score = sum(w for s, w in weighted.items() if s.lower() in normalised)
        if score > best_score:
            best_score = score
            best_prof = profession
    return best_prof


def classify_profession_from_title(title):
    if not title:
        return None
    title_lower = title.strip().lower()
    best = None
    best_score = 0
    for profession, config in PROFESSION_CONFIGS.items():
        t = config.get("titles", set())
        for pattern in t:
            if pattern in title_lower:
                pattern_unique = len(pattern.split())
                if pattern_unique > best_score:
                    best_score = pattern_unique
                    best = profession
    return best


def classify_job(job_title, required_skills=None):
    from_title = classify_profession_from_title(job_title)
    if from_title:
        return from_title
    if required_skills:
        from_skills = classify_profession_from_skills(required_skills)
        if from_skills:
            return from_skills
    return "Other"


def get_related_professions(profession):
    return RELATED_PROFESSIONS.get(profession, set())


def get_related_profession_titles(profession):
    result = {profession}
    result.update(get_related_professions(profession))
    return result


def get_profession_confidence(profession, score):
    if score >= 80:
        return "high"
    if score >= 50:
        return "medium"
    return "low"


def _log_debug(msg):
    if getattr(settings, "AI_MATCH_DEBUG", False):
        logger.info("[ProfessionClassifier] %s", msg)
