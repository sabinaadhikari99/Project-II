"""Fine-grained specialisations layered on top of PROFESSION_CONFIGS.

Why this module exists
----------------------
`profession_classifier.PROFESSION_CONFIGS` holds 17 coarse professions, and
every `JobPosting.job_category` in the database is one of those 17 values. That
coarse layer is what job filtering runs on, so it must not change.

But "Mobile Developer" is far too blunt to drive a skill-gap analysis: a Flutter
CV and a native iOS CV land in the same bucket and therefore used to receive the
same missing skills, the same courses and the same roadmap.

This module adds a second, finer tier *without touching the database*:

    CV  ->  specialisation ("Flutter Developer")
            parent         ("Mobile Developer")   <- still used for job filtering

The specialisation drives everything that should be CV-specific (skill gaps,
courses, roadmap, insights, summary) and re-ranks jobs inside the parent
category. The parent keeps job filtering, `classify_job()` and the existing
API contracts working exactly as before.

Each entry declares:
    parent       coarse profession, MUST be a key of PROFESSION_CONFIGS
    titles       title phrases that identify the specialisation
    signals      weighted skills used to detect it from a CV
    core_skills  the canonical skill set for this specialisation; this is what
                 makes gap analysis profession-correct rather than pool-wide
    adjacent     parent categories acceptable as "related roles" in the
                 semantic fallback when the parent has too few postings
"""

from apps.shared.skill_normalizer import normalize_skill

# --------------------------------------------------------------------------
# Specialisation catalogue
# --------------------------------------------------------------------------

SPECIALIZATIONS = {
    # ---------------------------------------------------------------- mobile
    "Flutter Developer": {
        "parent": "Mobile Developer",
        "titles": {"flutter developer", "flutter engineer", "flutter app developer",
                   "cross platform developer", "cross-platform developer",
                   "dart developer", "flutter mobile developer"},
        "signals": {"Flutter": 12, "Dart": 12, "Riverpod": 9, "Provider": 6,
                    "BLoC": 9, "GetX": 7, "Firebase": 6, "Mobile UI": 4},
        "core_skills": ["Dart", "Flutter", "State Management", "Riverpod", "BLoC",
                        "Firebase", "REST APIs", "Flutter Testing",
                        "Mobile Architecture", "Play Store Deployment",
                        "Push Notifications", "SQLite"],
        "adjacent": ["Mobile Developer"],
    },
    "Android Developer": {
        "parent": "Mobile Developer",
        "titles": {"android developer", "android engineer", "android app developer",
                   "kotlin developer", "native android developer"},
        "signals": {"Kotlin": 12, "Android": 12, "Jetpack Compose": 10,
                    "Coroutines": 8, "Material Design": 6, "Java": 5, "Firebase": 4},
        "core_skills": ["Kotlin", "Android SDK", "Jetpack Compose", "Coroutines",
                        "Material Design", "Room", "Dagger/Hilt", "REST APIs",
                        "Android Testing", "Play Store Deployment"],
        "adjacent": ["Mobile Developer"],
    },
    "iOS Developer": {
        "parent": "Mobile Developer",
        "titles": {"ios developer", "ios engineer", "ios app developer",
                   "swift developer", "native ios developer"},
        "signals": {"Swift": 12, "SwiftUI": 11, "UIKit": 10, "iOS": 11,
                    "Xcode": 7, "Combine": 7, "Core Data": 6},
        "core_skills": ["Swift", "SwiftUI", "UIKit", "Combine", "Core Data",
                        "REST APIs", "XCTest", "App Store Deployment",
                        "iOS Architecture"],
        "adjacent": ["Mobile Developer"],
    },
    "React Native Developer": {
        "parent": "Mobile Developer",
        "titles": {"react native developer", "react native engineer"},
        "signals": {"React Native": 12, "JavaScript": 5, "TypeScript": 6,
                    "Redux": 6, "Expo": 8},
        "core_skills": ["React Native", "TypeScript", "Redux", "React Navigation",
                        "Expo", "REST APIs", "Jest", "Mobile Architecture"],
        "adjacent": ["Mobile Developer", "Frontend Developer"],
    },

    # -------------------------------------------------------------- frontend
    "React Developer": {
        "parent": "Frontend Developer",
        "titles": {"react developer", "react engineer", "react.js developer",
                   "reactjs developer"},
        "signals": {"React": 12, "Redux": 9, "Next.js": 9, "TypeScript": 7,
                    "JavaScript": 5},
        "core_skills": ["React", "TypeScript", "Redux", "Next.js", "React Testing Library",
                        "Tailwind CSS", "Responsive Design", "REST APIs", "Webpack"],
        "adjacent": ["Frontend Developer", "Full Stack Developer"],
    },
    "Angular Developer": {
        "parent": "Frontend Developer",
        "titles": {"angular developer", "angular engineer"},
        "signals": {"Angular": 12, "RxJS": 10, "NgRx": 10, "TypeScript": 8},
        "core_skills": ["Angular", "TypeScript", "RxJS", "NgRx", "Jasmine",
                        "Karma", "Responsive Design", "REST APIs"],
        "adjacent": ["Frontend Developer", "Full Stack Developer"],
    },
    "Vue Developer": {
        "parent": "Frontend Developer",
        "titles": {"vue developer", "vue.js developer", "vuejs developer"},
        "signals": {"Vue.js": 12, "Vuex": 10, "Nuxt.js": 9, "TypeScript": 6},
        "core_skills": ["Vue.js", "Vuex", "Nuxt.js", "TypeScript", "Vitest",
                        "Responsive Design", "REST APIs"],
        "adjacent": ["Frontend Developer", "Full Stack Developer"],
    },
    "Frontend Developer": {
        "parent": "Frontend Developer",
        "titles": {"frontend developer", "front end developer", "frontend engineer",
                   "front-end developer", "ui developer", "web developer"},
        "signals": {"JavaScript": 8, "HTML": 4, "CSS": 4, "TypeScript": 7,
                    "Tailwind CSS": 6, "Bootstrap": 4},
        "core_skills": ["JavaScript", "TypeScript", "React", "Responsive Design",
                        "Tailwind CSS", "Webpack", "Accessibility", "REST APIs",
                        "Unit Testing"],
        "adjacent": ["Frontend Developer", "Full Stack Developer"],
    },

    # --------------------------------------------------------------- backend
    "Python/Django Developer": {
        "parent": "Backend Developer",
        "titles": {"django developer", "python developer", "python backend developer"},
        "signals": {"Django": 12, "Django REST Framework": 11, "Python": 8,
                    "Celery": 7, "FastAPI": 6, "Flask": 5},
        "core_skills": ["Python", "Django", "Django REST Framework", "PostgreSQL",
                        "Celery", "Redis", "REST APIs", "Pytest", "Docker",
                        "API Design"],
        "adjacent": ["Backend Developer", "Full Stack Developer"],
    },
    "Node.js Developer": {
        "parent": "Backend Developer",
        "titles": {"node.js developer", "node developer", "nodejs developer",
                   "express developer"},
        "signals": {"Node.js": 12, "Express": 10, "NestJS": 9, "TypeScript": 7,
                    "MongoDB": 6},
        "core_skills": ["Node.js", "Express", "TypeScript", "MongoDB", "PostgreSQL",
                        "REST APIs", "Jest", "Docker", "API Design"],
        "adjacent": ["Backend Developer", "Full Stack Developer"],
    },
    "Java Developer": {
        "parent": "Backend Developer",
        "titles": {"java developer", "java engineer", "spring boot developer",
                   "java backend developer"},
        "signals": {"Java": 12, "Spring Boot": 12, "Hibernate": 9, "Maven": 6,
                    "JUnit": 7},
        "core_skills": ["Java", "Spring Boot", "Hibernate", "PostgreSQL", "JUnit",
                        "Maven", "REST APIs", "Microservices", "Docker"],
        "adjacent": ["Backend Developer", "Software Engineer"],
    },
    ".NET Developer": {
        "parent": "Backend Developer",
        "titles": {".net developer", "dotnet developer", "c# developer",
                   "asp.net developer"},
        "signals": {"C#": 12, ".NET": 12, "ASP.NET": 11, "Entity Framework": 9},
        "core_skills": ["C#", ".NET", "ASP.NET Core", "Entity Framework",
                        "SQL Server", "REST APIs", "xUnit", "Azure"],
        "adjacent": ["Backend Developer", "Software Engineer"],
    },
    "PHP Developer": {
        "parent": "Backend Developer",
        "titles": {"php developer", "laravel developer", "wordpress developer"},
        "signals": {"PHP": 12, "Laravel": 11, "Symfony": 8, "MySQL": 6},
        "core_skills": ["PHP", "Laravel", "MySQL", "REST APIs", "Composer",
                        "PHPUnit", "Docker"],
        "adjacent": ["Backend Developer", "Full Stack Developer"],
    },
    "Go Developer": {
        "parent": "Backend Developer",
        "titles": {"go developer", "golang developer", "go engineer"},
        "signals": {"Go": 12, "Gin": 8, "gRPC": 8},
        "core_skills": ["Go", "gRPC", "PostgreSQL", "REST APIs", "Docker",
                        "Kubernetes", "Microservices"],
        "adjacent": ["Backend Developer", "DevOps Engineer"],
    },
    "Backend Developer": {
        "parent": "Backend Developer",
        "titles": {"backend developer", "back end developer", "backend engineer",
                   "back-end developer", "api developer", "server side developer"},
        "signals": {"REST APIs": 8, "SQL": 6, "Microservices": 7, "API Design": 7},
        "core_skills": ["REST APIs", "API Design", "SQL", "PostgreSQL", "Redis",
                        "Microservices", "Docker", "Unit Testing", "Caching"],
        "adjacent": ["Backend Developer", "Full Stack Developer"],
    },

    # ------------------------------------------------------------ full stack
    "Full Stack Developer": {
        "parent": "Full Stack Developer",
        "titles": {"full stack developer", "fullstack developer", "full-stack developer",
                   "mern stack developer", "mean stack developer",
                   "full stack engineer"},
        "signals": {"React": 7, "Node.js": 7, "Django": 7, "MongoDB": 6,
                    "PostgreSQL": 6, "TypeScript": 6},
        "core_skills": ["React", "TypeScript", "Node.js", "REST APIs", "PostgreSQL",
                        "MongoDB", "Docker", "CI/CD", "Unit Testing", "System Design"],
        "adjacent": ["Full Stack Developer", "Frontend Developer", "Backend Developer"],
    },

    # ------------------------------------------------------ software / other
    "Software Engineer": {
        "parent": "Software Engineer",
        "titles": {"software engineer", "software developer", "programmer", "sde"},
        "signals": {"Data Structures": 9, "Algorithms": 9, "System Design": 8,
                    "OOP": 7, "Design Patterns": 7},
        "core_skills": ["Data Structures", "Algorithms", "System Design", "OOP",
                        "Design Patterns", "Git", "Unit Testing", "CI/CD", "Docker"],
        "adjacent": ["Software Engineer", "Backend Developer"],
    },
    "Game Developer": {
        "parent": "Software Engineer",
        "titles": {"game developer", "game programmer", "unity developer",
                   "unreal developer", "gameplay engineer"},
        "signals": {"Unity": 12, "Unreal Engine": 12, "C#": 7, "C++": 7,
                    "Game Physics": 9, "Blender": 5},
        "core_skills": ["Unity", "C#", "Game Physics", "3D Mathematics",
                        "Shader Programming", "Animation Systems",
                        "Performance Optimization", "Multiplayer Networking"],
        "adjacent": ["Software Engineer"],
    },
    "Embedded Systems Engineer": {
        "parent": "Software Engineer",
        "titles": {"embedded engineer", "embedded systems engineer",
                   "firmware engineer", "iot engineer"},
        "signals": {"C": 9, "C++": 9, "RTOS": 12, "Microcontrollers": 12,
                    "Embedded C": 12, "ARM": 8, "Arduino": 6},
        "core_skills": ["Embedded C", "RTOS", "Microcontrollers", "ARM Cortex",
                        "I2C/SPI/UART", "Device Drivers", "Hardware Debugging",
                        "Low Power Design"],
        "adjacent": ["Software Engineer"],
    },
    "QA Engineer": {
        "parent": "Software Engineer",
        "titles": {"qa engineer", "quality assurance engineer", "software tester",
                   "test engineer", "automation tester", "sdet",
                   "qa automation engineer"},
        "signals": {"Selenium": 12, "Cypress": 11, "Playwright": 11,
                    "Test Automation": 12, "JUnit": 6, "Postman": 6, "JIRA": 5},
        "core_skills": ["Test Automation", "Selenium", "Cypress", "API Testing",
                        "Postman", "Test Planning", "Performance Testing",
                        "CI/CD", "Bug Tracking"],
        "adjacent": ["Software Engineer"],
    },

    # ------------------------------------------------------- devops / cloud
    "DevOps Engineer": {
        "parent": "DevOps Engineer",
        "titles": {"devops engineer", "dev ops engineer", "platform engineer",
                   "site reliability engineer", "sre"},
        "signals": {"Docker": 10, "Kubernetes": 12, "Terraform": 11, "Jenkins": 9,
                    "CI/CD": 10, "Ansible": 9},
        "core_skills": ["Docker", "Kubernetes", "Terraform", "CI/CD", "Jenkins",
                        "Ansible", "Linux", "Prometheus", "Grafana", "Shell Scripting"],
        "adjacent": ["DevOps Engineer"],
    },
    "Cloud Engineer": {
        "parent": "DevOps Engineer",
        "titles": {"cloud engineer", "cloud architect", "aws engineer",
                   "azure engineer", "gcp engineer", "cloud solutions architect"},
        "signals": {"AWS": 12, "Azure": 11, "GCP": 11, "CloudFormation": 9,
                    "Terraform": 8, "Lambda": 8},
        "core_skills": ["AWS", "Terraform", "CloudFormation", "Serverless",
                        "VPC Networking", "IAM", "Cost Optimization",
                        "Kubernetes", "Cloud Security"],
        "adjacent": ["DevOps Engineer"],
    },
    "Network Engineer": {
        "parent": "DevOps Engineer",
        "titles": {"network engineer", "network administrator",
                   "network architect", "noc engineer"},
        "signals": {"Cisco": 12, "CCNA": 12, "Routing": 10, "Switching": 10,
                    "BGP": 10, "TCP/IP": 8, "Firewall": 7},
        "core_skills": ["TCP/IP", "Routing & Switching", "BGP", "OSPF", "Cisco IOS",
                        "Firewall Configuration", "VPN", "Network Monitoring",
                        "Load Balancing"],
        "adjacent": ["DevOps Engineer", "Cybersecurity Engineer"],
    },

    # ------------------------------------------------------------ data / AI
    "Data Analyst": {
        "parent": "Data Analyst",
        "titles": {"data analyst", "junior data analyst", "reporting analyst"},
        "signals": {"SQL": 11, "Excel": 10, "Power BI": 11, "Tableau": 11,
                    "Data Visualization": 9, "Statistics": 8},
        "core_skills": ["Advanced SQL", "Excel", "Power BI", "Tableau", "Statistics",
                        "Python", "Pandas", "Data Cleaning", "Dashboarding",
                        "A/B Testing"],
        "adjacent": ["Data Analyst", "Data Scientist"],
    },
    "Business Intelligence Analyst": {
        "parent": "Data Analyst",
        "titles": {"business intelligence analyst", "bi analyst", "bi developer",
                   "business intelligence developer"},
        "signals": {"Power BI": 12, "Tableau": 12, "Looker": 10, "DAX": 11,
                    "SQL": 9, "Data Warehouse": 8},
        "core_skills": ["Power BI", "DAX", "Tableau", "Advanced SQL",
                        "Data Warehouse", "ETL", "Data Modeling", "Looker",
                        "Dashboarding"],
        "adjacent": ["Data Analyst", "Data Engineer"],
    },
    "Business Analyst": {
        "parent": "Data Analyst",
        "titles": {"business analyst", "systems analyst", "functional analyst"},
        "signals": {"Requirements Gathering": 12, "BPMN": 10, "UML": 9,
                    "Stakeholder Management": 9, "JIRA": 7, "SQL": 6},
        "core_skills": ["Requirements Gathering", "Process Modeling", "BPMN",
                        "Stakeholder Management", "SQL", "User Stories",
                        "Gap Analysis", "UAT", "Documentation"],
        "adjacent": ["Data Analyst", "Product Manager"],
    },
    "Data Scientist": {
        "parent": "Data Scientist",
        "titles": {"data scientist", "research scientist", "applied scientist"},
        "signals": {"Machine Learning": 11, "Statistics": 10, "Scikit-learn": 9,
                    "Pandas": 8, "Feature Engineering": 9},
        "core_skills": ["Python", "Statistics", "Machine Learning", "Scikit-learn",
                        "Pandas", "Feature Engineering", "A/B Testing",
                        "Data Visualization", "SQL", "Model Evaluation"],
        "adjacent": ["Data Scientist", "Machine Learning Engineer"],
    },
    "AI Engineer": {
        "parent": "Data Scientist",
        "titles": {"ai engineer", "ai developer", "generative ai engineer",
                   "llm engineer"},
        "signals": {"LLM": 12, "LangChain": 12, "Transformers": 11, "RAG": 12,
                    "Prompt Engineering": 10, "Vector Database": 10},
        "core_skills": ["LLM Integration", "LangChain", "RAG Pipelines",
                        "Vector Databases", "Prompt Engineering", "Transformers",
                        "Model Deployment", "Python", "FastAPI"],
        "adjacent": ["Data Scientist", "Machine Learning Engineer"],
    },
    "Machine Learning Engineer": {
        "parent": "Machine Learning Engineer",
        "titles": {"machine learning engineer", "ml engineer", "mlops engineer",
                   "deep learning engineer"},
        "signals": {"TensorFlow": 11, "PyTorch": 11, "MLOps": 12,
                    "Model Deployment": 11, "Deep Learning": 10},
        "core_skills": ["PyTorch", "TensorFlow", "MLOps", "Model Deployment",
                        "Feature Engineering", "Docker", "Kubernetes",
                        "Model Monitoring", "CI/CD"],
        "adjacent": ["Machine Learning Engineer", "Data Scientist"],
    },
    "NLP Engineer": {
        "parent": "Machine Learning Engineer",
        "titles": {"nlp engineer", "natural language processing engineer"},
        "signals": {"NLP": 12, "Transformers": 11, "spaCy": 10, "BERT": 10,
                    "Hugging Face": 10},
        "core_skills": ["NLP", "Transformers", "Hugging Face", "spaCy",
                        "Text Classification", "Named Entity Recognition",
                        "Embeddings", "Model Deployment"],
        "adjacent": ["Machine Learning Engineer", "Data Scientist"],
    },
    "Computer Vision Engineer": {
        "parent": "Machine Learning Engineer",
        "titles": {"computer vision engineer", "cv engineer",
                   "image processing engineer"},
        "signals": {"Computer Vision": 12, "OpenCV": 12, "YOLO": 10, "CNN": 10},
        "core_skills": ["Computer Vision", "OpenCV", "CNNs", "Object Detection",
                        "Image Segmentation", "PyTorch", "Model Deployment"],
        "adjacent": ["Machine Learning Engineer", "Data Scientist"],
    },
    "Data Engineer": {
        "parent": "Data Engineer",
        "titles": {"data engineer", "analytics engineer", "big data engineer",
                   "data pipeline engineer"},
        "signals": {"ETL": 12, "Airflow": 12, "Spark": 11, "Kafka": 10,
                    "Data Warehouse": 9},
        "core_skills": ["Python", "Advanced SQL", "ETL", "Airflow", "Spark",
                        "Kafka", "Data Modeling", "Snowflake", "dbt",
                        "Data Quality"],
        "adjacent": ["Data Engineer", "Data Analyst"],
    },
    "Database Administrator": {
        "parent": "Data Engineer",
        "titles": {"database administrator", "dba", "database engineer",
                   "sql dba"},
        "signals": {"PostgreSQL": 10, "MySQL": 10, "Oracle": 11, "SQL Server": 11,
                    "Database Tuning": 12, "Replication": 10},
        "core_skills": ["Advanced SQL", "Query Optimization", "Indexing Strategy",
                        "Backup & Recovery", "Replication", "High Availability",
                        "Database Security", "Performance Tuning"],
        "adjacent": ["Data Engineer", "Backend Developer"],
    },

    # -------------------------------------------------------------- security
    "Cybersecurity Engineer": {
        "parent": "Cybersecurity Engineer",
        "titles": {"cybersecurity engineer", "security engineer",
                   "information security engineer", "security architect"},
        "signals": {"Network Security": 11, "SIEM": 11, "Firewall": 9,
                    "Risk Assessment": 9, "Compliance": 8},
        "core_skills": ["Network Security", "SIEM", "Incident Response",
                        "Vulnerability Management", "Risk Assessment",
                        "Cryptography", "Compliance", "Linux Hardening"],
        "adjacent": ["Cybersecurity Engineer", "DevOps Engineer"],
    },
    "Penetration Tester": {
        "parent": "Cybersecurity Engineer",
        "titles": {"penetration tester", "ethical hacker", "red team engineer",
                   "offensive security engineer"},
        "signals": {"Penetration Testing": 12, "Ethical Hacking": 12,
                    "Metasploit": 11, "Burp Suite": 11, "OSCP": 11, "Nmap": 9},
        "core_skills": ["Penetration Testing", "Burp Suite", "Metasploit",
                        "OWASP Top 10", "Exploit Development", "Nmap",
                        "Report Writing", "Web Application Security"],
        "adjacent": ["Cybersecurity Engineer"],
    },
    "SOC Analyst": {
        "parent": "Cybersecurity Engineer",
        "titles": {"soc analyst", "security analyst", "security operations analyst",
                   "threat analyst"},
        "signals": {"SIEM": 12, "Splunk": 11, "Incident Response": 11,
                    "Threat Intelligence": 10, "IDS/IPS": 9},
        "core_skills": ["SIEM", "Splunk", "Incident Response", "Threat Hunting",
                        "Log Analysis", "IDS/IPS", "Malware Analysis",
                        "Security Monitoring"],
        "adjacent": ["Cybersecurity Engineer"],
    },

    # ---------------------------------------------------------------- design
    "UI Designer": {
        "parent": "UI/UX Designer",
        "titles": {"ui designer", "user interface designer", "visual ui designer"},
        "signals": {"Figma": 11, "Design Systems": 11, "Adobe XD": 9,
                    "Prototyping": 8, "Typography": 7},
        "core_skills": ["Figma", "Design Systems", "Component Libraries",
                        "Prototyping", "Typography", "Color Theory",
                        "Responsive Design", "Accessibility", "Handoff"],
        "adjacent": ["UI/UX Designer", "Graphic Designer"],
    },
    "UX Designer": {
        "parent": "UI/UX Designer",
        "titles": {"ux designer", "user experience designer", "ux researcher",
                   "interaction designer", "product designer"},
        "signals": {"User Research": 12, "Usability Testing": 12, "Wireframing": 10,
                    "Personas": 9, "Information Architecture": 10},
        "core_skills": ["User Research", "Usability Testing", "Wireframing",
                        "Information Architecture", "User Flows", "Personas",
                        "Journey Mapping", "Prototyping", "Figma"],
        "adjacent": ["UI/UX Designer", "Product Manager"],
    },
    "Graphic Designer": {
        "parent": "Graphic Designer",
        "titles": {"graphic designer", "visual designer", "brand designer",
                   "creative designer", "graphic artist"},
        "signals": {"Photoshop": 12, "Illustrator": 12, "InDesign": 11,
                    "Branding": 11, "Typography": 10, "Color Theory": 9},
        "core_skills": ["Adobe Illustrator", "Adobe Photoshop", "Adobe InDesign",
                        "Branding", "Typography", "Color Theory", "Layout Design",
                        "Print Production", "Logo Design", "Figma"],
        "adjacent": ["Graphic Designer", "UI/UX Designer"],
    },
    "Motion Designer": {
        "parent": "Graphic Designer",
        "titles": {"motion designer", "motion graphics designer", "animator",
                   "video editor"},
        "signals": {"After Effects": 12, "Premiere Pro": 11, "Cinema 4D": 11,
                    "Motion Graphics": 12, "Animation": 10},
        "core_skills": ["After Effects", "Motion Graphics", "Premiere Pro",
                        "Cinema 4D", "Animation Principles", "Storyboarding",
                        "Color Grading", "Sound Design"],
        "adjacent": ["Graphic Designer"],
    },

    # ------------------------------------------------------------- non-tech
    "Product Manager": {
        "parent": "Product Manager",
        "titles": {"product manager", "product owner", "technical product manager"},
        "signals": {"Product Strategy": 11, "Roadmapping": 11, "Agile": 8,
                    "Product Metrics": 10},
        "core_skills": ["Product Strategy", "Roadmapping", "User Research",
                        "Product Metrics", "A/B Testing", "SQL", "Agile",
                        "Stakeholder Management", "Prioritisation"],
        "adjacent": ["Product Manager", "Data Analyst"],
    },
    "Marketing Manager": {
        "parent": "Marketing Manager",
        "titles": {"marketing manager", "digital marketing manager",
                   "growth marketer", "brand manager"},
        "signals": {"Digital Marketing": 11, "SEO": 10, "Google Analytics": 9},
        "core_skills": ["Digital Marketing", "SEO", "SEM", "Google Analytics",
                        "Content Strategy", "Email Marketing", "Campaign Management",
                        "Marketing Automation"],
        "adjacent": ["Marketing Manager", "Product Manager"],
    },
    "Accountant": {
        "parent": "Accountant",
        "titles": {"accountant", "staff accountant", "financial accountant",
                   "chartered accountant"},
        "signals": {"Accounting": 11, "GAAP": 11, "Financial Reporting": 10},
        "core_skills": ["Financial Reporting", "GAAP", "Bookkeeping", "Auditing",
                        "Tax Preparation", "Excel", "QuickBooks",
                        "Financial Analysis"],
        "adjacent": ["Accountant"],
    },
    "Human Resources Manager": {
        "parent": "Human Resources Manager",
        "titles": {"hr manager", "human resources manager", "hr generalist",
                   "talent acquisition specialist", "recruiter"},
        "signals": {"Recruiting": 11, "HR Policies": 11, "Talent Acquisition": 10},
        "core_skills": ["Talent Acquisition", "Employee Relations", "HR Policies",
                        "Performance Management", "Onboarding", "HRIS",
                        "Labor Laws", "Compensation & Benefits"],
        "adjacent": ["Human Resources Manager"],
    },
}


# --------------------------------------------------------------------------
# Derived lookups (built once at import)
# --------------------------------------------------------------------------

#: parent profession -> list of specialisation names underneath it
SPECIALIZATIONS_BY_PARENT = {}
for _name, _cfg in SPECIALIZATIONS.items():
    SPECIALIZATIONS_BY_PARENT.setdefault(_cfg["parent"], []).append(_name)

#: normalised signal skill -> {specialisation: weight}
_SIGNAL_INDEX = {}
for _name, _cfg in SPECIALIZATIONS.items():
    for _skill, _weight in _cfg["signals"].items():
        _SIGNAL_INDEX.setdefault(normalize_skill(_skill), {})[_name] = _weight

#: a signal skill is "distinctive" when very few specialisations claim it.
#: Distinctive hits are what separate Flutter from React Native, not "Python".
_DISTINCTIVENESS = {
    _key: 1.0 if len(_owners) == 1 else (0.6 if len(_owners) <= 3 else 0.3)
    for _key, _owners in _SIGNAL_INDEX.items()
}


def get_specialization(name):
    return SPECIALIZATIONS.get(name)


def get_parent_profession(name):
    """Coarse profession for a specialisation; falls back to the name itself so
    callers can pass either tier without branching."""
    cfg = SPECIALIZATIONS.get(name)
    return cfg["parent"] if cfg else name


def get_core_skills(name):
    """Canonical skill set for a specialisation. This is the profession-correct
    basis for gap analysis - it is what stops a Flutter CV being told to learn
    React."""
    cfg = SPECIALIZATIONS.get(name)
    return list(cfg["core_skills"]) if cfg else []


def get_adjacent_parents(name):
    """Parent categories acceptable as 'related roles' in the semantic
    fallback. Deliberately narrow: never crosses field boundaries."""
    cfg = SPECIALIZATIONS.get(name)
    if cfg:
        return list(cfg["adjacent"])
    return [name] if name else []


def _title_score(title_lower, cfg):
    if not title_lower:
        return 0.0
    for phrase in cfg["titles"]:
        if phrase in title_lower:
            # Longer phrases are more specific: "flutter developer" should beat
            # the generic "developer" fragment of another entry.
            return 1.0 + len(phrase.split()) / 20.0
    return 0.0


def detect_specialization(resume_text, extracted_skills, parent_profession, sections=None):
    """Pick the best specialisation for a CV.

    Restricted to specialisations under `parent_profession` so the fine tier can
    never contradict the coarse profession the rest of the system filters on.

    Returns (specialisation_name, confidence 0-100). Falls back to the parent's
    own same-named entry, then to the parent itself, so the caller always gets a
    usable value.
    """
    candidates = SPECIALIZATIONS_BY_PARENT.get(parent_profession, [])
    if not candidates:
        return parent_profession, 0

    skills_norm = {normalize_skill(s) for s in (extracted_skills or [])}
    text_lower = (resume_text or "").lower()

    title_lower = ""
    if sections:
        title_lower = (sections.get("title") or "").lower()

    scores = {}
    for name in candidates:
        cfg = SPECIALIZATIONS[name]

        # Signal skills, weighted by how distinctive each one is.
        signal = 0.0
        possible = 0.0
        for skill, weight in cfg["signals"].items():
            key = normalize_skill(skill)
            factor = _DISTINCTIVENESS.get(key, 0.5)
            possible += weight * factor
            if key in skills_norm:
                signal += weight * factor
        signal_pct = (signal / possible) if possible else 0.0

        # An explicit title in the CV is the strongest single evidence.
        title = _title_score(title_lower, cfg)
        if not title:
            # Titles also appear in experience/summary prose.
            for phrase in cfg["titles"]:
                if phrase in text_lower:
                    title = 0.6
                    break

        scores[name] = signal_pct * 0.6 + min(title, 1.5) * 0.4

    best = max(scores, key=scores.get)
    best_score = scores[best]

    if best_score <= 0:
        # No fine-grained evidence at all - stay at the parent tier rather than
        # inventing a specialisation.
        return (parent_profession if parent_profession in SPECIALIZATIONS
                else parent_profession), 0

    return best, min(100, round(best_score * 100))