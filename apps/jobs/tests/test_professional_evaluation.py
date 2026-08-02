import json
import unittest
from pathlib import Path

import django
from django.conf import settings
from django.test import TestCase

os = __import__("os")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from apps.shared.profession_classifier import (
    classify_profession_with_resume,
    classify_profession_from_skills,
    classify_profession_from_title,
    classify_job,
    extract_skills_from_section,
    extract_resume_sections,
    get_related_professions,
    get_related_profession_titles,
    normalize_skill,
)
from apps.shared.skill_normalizer import normalize_skill as norm_skill
from apps.shared.skill_normalizer import normalize_skill_set, display_name
from apps.jobs.services import _compute_weighted_score


SAMPLE_RESUMES = {
    "Flutter Developer": """
Resume: Flutter Developer
Professional Summary: Experienced mobile app developer with 4 years of experience building cross-platform applications using Flutter and Dart. Published multiple apps on both Google Play Store and Apple App Store.
Work Experience:
Mobile App Developer at TechStartup Inc. (2020-2024)
- Developed cross-platform mobile applications using Flutter SDK and Dart
- Integrated REST APIs and Firebase services
- Implemented state management with Provider and Bloc patterns
- Published and maintained apps on App Store and Google Play
Skills: Flutter, Dart, Firebase, REST APIs, Git, Provider, Bloc, Android, iOS
Projects:
- E-commerce mobile app built with Flutter reaching 50k+ downloads
- Real-time chat application using Firebase and Flutter
Education: B.S. Computer Science
""",
    "Graphic Designer": """
Resume: Graphic Designer
Professional Summary: Creative graphic designer with 5 years of experience in brand identity, print design, and digital media. Proficient in Adobe Creative Suite with a strong portfolio of branding projects.
Work Experience:
Senior Graphic Designer at Creative Agency (2019-2024)
- Designed brand identities for 20+ clients including logos, typography, and color schemes
- Created marketing materials including brochures, flyers, and social media graphics
- Collaborated with UI/UX team on web design projects
Skills: Photoshop, Illustrator, InDesign, Branding, Typography, Color Theory, Canva, Print Design
Projects:
- Complete brand redesign for a major retail chain
- Product packaging design line for organic food company
Education: BFA in Graphic Design
""",
    "Backend Developer": """
Resume: Backend Developer
Professional Summary: Python backend developer with 4 years of experience building RESTful APIs and microservices using Django and FastAPI. Strong database design skills with PostgreSQL and MongoDB.
Work Experience:
Backend Developer at TechCorp (2020-2024)
- Designed and implemented RESTful APIs using Django REST Framework
- Built microservices architecture with FastAPI and Celery
- Managed PostgreSQL databases and optimized query performance
- Implemented authentication and authorization systems
Skills: Python, Django, Django REST Framework, FastAPI, PostgreSQL, Redis, Docker, Git, Celery
Projects:
- E-commerce platform backend serving 100k+ users
- Real-time data processing pipeline using Celery and Redis
Education: B.S. Computer Science
""",
    "Data Scientist": """
Resume: Data Scientist
Professional Summary: Data scientist with 3 years of experience in machine learning, statistical analysis, and data visualization. Proficient in Python, TensorFlow, and scikit-learn with proven track record of delivering actionable insights.
Work Experience:
Data Scientist at AnalyticsPro (2021-2024)
- Developed ML models for customer churn prediction achieving 92% accuracy
- Performed exploratory data analysis and feature engineering on large datasets
- Created interactive dashboards using Tableau and Power BI
Skills: Python, Pandas, NumPy, Scikit-learn, TensorFlow, SQL, Statistics, Data Visualization, Tableau
Projects:
- Customer segmentation model using K-means clustering
- Predictive maintenance system for manufacturing equipment
Education: M.S. Data Science
""",
    "Accountant": """
Resume: Accountant
Professional Summary: Certified accountant with 6 years of experience in financial reporting, tax preparation, and auditing. Proficient in QuickBooks, GAAP standards, and financial analysis.
Work Experience:
Senior Accountant at FinanceCorp (2018-2024)
- Prepared monthly financial statements and quarterly reports
- Managed accounts payable and receivable for 500+ client accounts
- Conducted internal audits and ensured GAAP compliance
- Prepared tax returns and coordinated with external auditors
Skills: Accounting, QuickBooks, Xero, Tax Preparation, Excel, Financial Reporting, GAAP, Auditing
Projects:
- Implemented new ERP system for financial operations
- Automated monthly reconciliation process reducing errors by 40%
Education: B.S. Accounting, CPA Certification
""",
    "Frontend Developer": """
Resume: Frontend Developer
Professional Summary: Frontend developer with 4 years of experience building responsive web applications using React, TypeScript, and modern CSS frameworks. Strong focus on user experience and performance optimization.
Work Experience:
Frontend Developer at WebAgency (2020-2024)
- Built responsive single-page applications using React and TypeScript
- Implemented state management with Redux and context API
- Optimized web performance achieving 95+ Lighthouse scores
Skills: React, TypeScript, JavaScript, HTML, CSS, Tailwind CSS, Redux, Git, REST APIs
Projects:
- SaaS dashboard application serving 10k+ users
- E-commerce frontend with complex state management
Education: B.S. Computer Science
""",
    "DevOps Engineer": """
Resume: DevOps Engineer
Professional Summary: DevOps engineer with 5 years of experience in cloud infrastructure, CI/CD pipelines, and containerization. Expert in AWS, Docker, Kubernetes, and Terraform.
Work Experience:
DevOps Engineer at CloudPlatform (2019-2024)
- Managed AWS infrastructure serving 1M+ users across multiple regions
- Implemented CI/CD pipelines using Jenkins and GitHub Actions
- Containerized applications using Docker and orchestrated with Kubernetes
Skills: Docker, Kubernetes, AWS, Terraform, Ansible, Jenkins, CI/CD, Linux, Git
Projects:
- Migrated monolith to microservices on Kubernetes
- Automated infrastructure provisioning with Terraform
Education: B.S. Computer Science
""",
    "Mobile Developer": """
Resume: Mobile Developer (React Native)
Professional Summary: Mobile developer with 3 years of experience building cross-platform apps with React Native. Published apps on both iOS and Android platforms.
Work Experience:
Mobile Developer at AppStudio (2021-2024)
- Built cross-platform mobile apps using React Native
- Integrated push notifications and in-app purchases
- Optimized app performance and reduced crash rate by 60%
Skills: React Native, JavaScript, TypeScript, Redux, Firebase, iOS, Android, Git, REST APIs
Projects:
- Social media app with 100k+ downloads
- Fitness tracking app with real-time sync
Education: B.S. Computer Science
""",
    "Machine Learning Engineer": """
Resume: Machine Learning Engineer
Professional Summary: ML engineer with 4 years of experience in building and deploying deep learning models. Expertise in PyTorch, TensorFlow, and MLOps practices.
Work Experience:
ML Engineer at AITech (2020-2024)
- Designed and trained deep learning models for computer vision tasks
- Deployed ML models to production using Docker and AWS SageMaker
- Implemented MLOps pipelines for model monitoring and retraining
Skills: Python, TensorFlow, PyTorch, Machine Learning, Deep Learning, Docker, AWS, MLOps, CI/CD
Projects:
- Real-time object detection system achieving 98% accuracy
- NLP sentiment analysis pipeline for customer feedback
Education: M.S. Machine Learning
""",
    "Data Engineer": """
Resume: Data Engineer
Professional Summary: Data engineer with 4 years of experience building data pipelines and ETL processes. Proficient in Spark, Airflow, and cloud data warehouses.
Work Experience:
Data Engineer at DataPlatform (2020-2024)
- Built scalable ETL pipelines processing 10TB+ daily
- Managed data warehouse infrastructure on Snowflake and BigQuery
- Implemented real-time streaming with Kafka and Spark
Skills: Python, SQL, ETL, Spark, Airflow, Kafka, Snowflake, BigQuery, Data Modeling
Projects:
- Real-time data streaming pipeline processing millions of events
- Data warehouse migration from on-premise to cloud
Education: B.S. Computer Science
""",
    "Data Analyst": """
Resume: Data Analyst
Professional Summary: Data analyst with 3 years of experience in data visualization, statistical analysis, and business intelligence. Skilled in SQL, Tableau, and Python.
Work Experience:
Data Analyst at BusinessCo (2021-2024)
- Created interactive dashboards and reports using Tableau and Power BI
- Performed SQL queries to extract and analyze business data
- Conducted A/B testing and statistical analysis for product decisions
Skills: SQL, Excel, Tableau, Power BI, Python, Pandas, Statistics, Data Visualization, Reporting
Projects:
- Sales forecasting dashboard used by executive team
- Customer behavior analysis driving 15% revenue increase
Education: B.S. Statistics
""",
    "UI/UX Designer": """
Resume: UI/UX Designer
Professional Summary: User experience designer with 4 years of experience in product design, user research, and interaction design. Expert in Figma and design systems.
Work Experience:
UX Designer at DesignStudio (2020-2024)
- Conducted user research and usability testing for 10+ products
- Designed wireframes, prototypes, and high-fidelity mockups in Figma
- Created and maintained design systems used across multiple products
Skills: Figma, User Research, Wireframing, Prototyping, Usability Testing, Interaction Design
Projects:
- Complete redesign of mobile banking app improving UX score by 40%
- Design system implementation for SaaS platform
Education: B.S. Human-Computer Interaction
""",
    "Product Manager": """
Resume: Product Manager
Professional Summary: Product manager with 5 years of experience driving product strategy, roadmapping, and cross-functional execution. Data-driven decision maker with strong analytical skills.
Work Experience:
Product Manager at ProductCo (2019-2024)
- Defined product strategy and roadmap for B2B SaaS platform
- Led cross-functional teams through agile development process
- Analyzed product metrics and user feedback to prioritize features
Skills: Product Strategy, Roadmapping, Agile, Scrum, User Research, A/B Testing, SQL, Data Analysis
Projects:
- Launched new product line generating $2M annual revenue
- Improved user retention by 25% through feature optimization
Education: MBA
""",
    "Marketing Manager": """
Resume: Marketing Manager
Professional Summary: Marketing manager with 5 years of experience in digital marketing, brand strategy, and growth marketing. Expert in SEO, SEM, and content marketing.
Work Experience:
Marketing Manager at MarketCorp (2019-2024)
- Developed and executed comprehensive digital marketing strategies
- Managed SEO and SEM campaigns increasing organic traffic by 150%
- Led content marketing team producing 50+ pieces monthly
Skills: Digital Marketing, SEO, SEM, Content Strategy, Social Media, Google Analytics, CRM, HubSpot
Projects:
- Multi-channel campaign achieving 300% ROI
- Brand repositioning resulting in 40% increase in brand awareness
Education: B.S. Marketing
""",
    "Human Resources Manager": """
Resume: HR Manager
Professional Summary: HR professional with 6 years of experience in talent acquisition, employee relations, and HR operations. Certified HR professional with strong people management skills.
Work Experience:
HR Manager at HRServices (2018-2024)
- Managed full-cycle recruitment for 200+ positions annually
- Developed and implemented HR policies and procedures
- Handled employee relations, performance management, and onboarding
Skills: Recruiting, Onboarding, HR Policies, Employee Relations, Payroll, Talent Acquisition, ATS
Projects:
- Implemented new HRIS system streamlining operations
- Developed remote work policy adopted company-wide
Education: B.S. Human Resources Management, PHR Certification
""",
    "Cybersecurity Engineer": """
Resume: Cybersecurity Engineer
Professional Summary: Security engineer with 4 years of experience in penetration testing, network security, and security architecture. Certified CISSP with strong technical background.
Work Experience:
Security Engineer at SecureCorp (2020-2024)
- Conducted penetration testing and vulnerability assessments
- Implemented SIEM solutions and security monitoring systems
- Designed and maintained firewall and IDS/IPS infrastructure
Skills: Network Security, Penetration Testing, SIEM, Firewall, IDS/IPS, Risk Assessment, CISSP, Python
Projects:
- Security audit and remediation for financial services client
- Implemented company-wide security awareness training program
Education: B.S. Cybersecurity, CISSP Certification
""",
    "Software Engineer": """
Resume: Software Engineer
Professional Summary: Software engineer with 5 years of experience designing and building scalable systems. Strong foundation in data structures, algorithms, and system design.
Work Experience:
Software Engineer at TechGiant (2019-2024)
- Designed and implemented distributed systems handling millions of requests
- Optimized algorithm performance reducing latency by 40%
- Mentored junior engineers and conducted code reviews
Skills: Python, Java, C++, Data Structures, Algorithms, System Design, REST APIs, Design Patterns, Git
Projects:
- Distributed caching system improving response times by 60%
- Real-time data processing platform
Education: B.S. Computer Science, M.S. Computer Science
""",
    "Full Stack Developer": """
Resume: Full Stack Developer
Professional Summary: Full stack developer with 4 years of experience building web applications from frontend to backend. Proficient in React, Django, and PostgreSQL.
Work Experience:
Full Stack Developer at WebFullCo (2020-2024)
- Built full-stack web applications using React frontend and Django backend
- Designed and managed PostgreSQL database schemas
Skills: React, JavaScript, TypeScript, Python, Django, PostgreSQL, HTML, CSS, Git, REST APIs
Projects:
- Full-stack project management tool serving 5000+ users
- E-commerce platform with React frontend and Django backend
Education: B.S. Computer Science
""",
}


FALSE_POSITIVE_CASES = [
    {
        "resume_key": "Flutter Developer",
        "should_not_be": ["Accountant", "HR Manager", "Graphic Designer", "Backend Developer", "Data Scientist", "DevOps Engineer"],
    },
    {
        "resume_key": "Graphic Designer",
        "should_not_be": ["DevOps Engineer", "Backend Developer", "Accountant", "Data Scientist", "Cybersecurity Engineer"],
    },
    {
        "resume_key": "Accountant",
        "should_not_be": ["Frontend Developer", "DevOps Engineer", "Data Scientist", "Mobile Developer", "Graphic Designer"],
    },
    {
        "resume_key": "Backend Developer",
        "should_not_be": ["Graphic Designer", "HR Manager", "Marketing Manager", "Accountant"],
    },
    {
        "resume_key": "Data Scientist",
        "should_not_be": ["UI/UX Designer", "Marketing Manager", "Accountant", "Graphic Designer"],
    },
]


class TestProfessionClassifier(TestCase):
    def setUp(self):
        self.resumes = SAMPLE_RESUMES

    def _detect_profession(self, resume_key):
        resume_text = self.resumes[resume_key]
        profession, confidence = classify_profession_with_resume(resume_text)
        return profession, confidence

    def test_flutter_detected_as_mobile(self):
        prof, conf = self._detect_profession("Flutter Developer")
        self.assertEqual(prof, "Mobile Developer", f"Flutter resume classified as {prof}, expected Mobile Developer")
        self.assertGreaterEqual(conf, 50, f"Flutter confidence too low: {conf}")

    def test_flutter_not_frontend(self):
        prof, conf = self._detect_profession("Flutter Developer")
        self.assertNotEqual(prof, "Frontend Developer",
                            f"Flutter resume should NOT be classified as Frontend Developer")

    def test_graphic_designer_detected(self):
        prof, conf = self._detect_profession("Graphic Designer")
        self.assertEqual(prof, "Graphic Designer", f"Graphic Designer resume classified as {prof}")
        self.assertGreaterEqual(conf, 50, f"Graphic Designer confidence too low: {conf}")

    def test_graphic_designer_not_software(self):
        prof, conf = self._detect_profession("Graphic Designer")
        self.assertNotEqual(prof, "Software Engineer",
                            f"Graphic Designer resume should NOT be classified as Software Engineer")

    def test_backend_detected(self):
        prof, conf = self._detect_profession("Backend Developer")
        self.assertEqual(prof, "Backend Developer", f"Backend resume classified as {prof}")
        self.assertGreaterEqual(conf, 50, f"Backend confidence too low: {conf}")

    def test_backend_not_frontend(self):
        prof, conf = self._detect_profession("Backend Developer")
        self.assertNotEqual(prof, "Frontend Developer",
                            f"Backend resume should NOT be classified as Frontend Developer")

    def test_data_scientist_detected(self):
        prof, conf = self._detect_profession("Data Scientist")
        self.assertEqual(prof, "Data Scientist", f"Data Scientist resume classified as {prof}")
        self.assertGreaterEqual(conf, 50, f"Data Scientist confidence too low: {conf}")

    def test_accountant_detected(self):
        prof, conf = self._detect_profession("Accountant")
        self.assertEqual(prof, "Accountant", f"Accountant resume classified as {prof}")
        self.assertGreaterEqual(conf, 50, f"Accountant confidence too low: {conf}")

    def test_frontend_detected(self):
        prof, conf = self._detect_profession("Frontend Developer")
        self.assertEqual(prof, "Frontend Developer", f"Frontend resume classified as {prof}")
        self.assertGreaterEqual(conf, 50, f"Frontend confidence too low: {conf}")

    def test_devops_detected(self):
        prof, conf = self._detect_profession("DevOps Engineer")
        self.assertEqual(prof, "DevOps Engineer", f"DevOps resume classified as {prof}")
        self.assertGreaterEqual(conf, 50, f"DevOps confidence too low: {conf}")

    def test_mobile_detected(self):
        prof, conf = self._detect_profession("Mobile Developer")
        self.assertEqual(prof, "Mobile Developer", f"Mobile Developer resume classified as {prof}")
        self.assertGreaterEqual(conf, 50, f"Mobile Developer confidence too low: {conf}")

    def test_ml_engineer_detected(self):
        prof, conf = self._detect_profession("Machine Learning Engineer")
        self.assertEqual(prof, "Machine Learning Engineer", f"ML Engineer resume classified as {prof}")
        self.assertGreaterEqual(conf, 50, f"ML Engineer confidence too low: {conf}")

    def test_data_engineer_detected(self):
        prof, conf = self._detect_profession("Data Engineer")
        self.assertEqual(prof, "Data Engineer", f"Data Engineer resume classified as {prof}")
        self.assertGreaterEqual(conf, 50, f"Data Engineer confidence too low: {conf}")

    def test_data_analyst_detected(self):
        prof, conf = self._detect_profession("Data Analyst")
        self.assertEqual(prof, "Data Analyst", f"Data Analyst resume classified as {prof}")
        self.assertGreaterEqual(conf, 50, f"Data Analyst confidence too low: {conf}")

    def test_ui_ux_detected(self):
        prof, conf = self._detect_profession("UI/UX Designer")
        self.assertEqual(prof, "UI/UX Designer", f"UI/UX Designer resume classified as {prof}")
        self.assertGreaterEqual(conf, 50, f"UI/UX Designer confidence too low: {conf}")

    def test_product_manager_detected(self):
        prof, conf = self._detect_profession("Product Manager")
        self.assertEqual(prof, "Product Manager", f"Product Manager resume classified as {prof}")
        self.assertGreaterEqual(conf, 50, f"Product Manager confidence too low: {conf}")

    def test_marketing_manager_detected(self):
        prof, conf = self._detect_profession("Marketing Manager")
        self.assertEqual(prof, "Marketing Manager", f"Marketing Manager resume classified as {prof}")
        self.assertGreaterEqual(conf, 50, f"Marketing Manager confidence too low: {conf}")

    def test_hr_manager_detected(self):
        prof, conf = self._detect_profession("Human Resources Manager")
        self.assertEqual(prof, "Human Resources Manager", f"HR Manager resume classified as {prof}")
        self.assertGreaterEqual(conf, 50, f"HR Manager confidence too low: {conf}")

    def test_cybersecurity_detected(self):
        prof, conf = self._detect_profession("Cybersecurity Engineer")
        self.assertEqual(prof, "Cybersecurity Engineer", f"Cybersecurity resume classified as {prof}")
        self.assertGreaterEqual(conf, 50, f"Cybersecurity confidence too low: {conf}")

    def test_software_engineer_detected(self):
        prof, conf = self._detect_profession("Software Engineer")
        self.assertEqual(prof, "Software Engineer", f"Software Engineer resume classified as {prof}")
        self.assertGreaterEqual(conf, 50, f"Software Engineer confidence too low: {conf}")

    def test_fullstack_detected(self):
        prof, conf = self._detect_profession("Full Stack Developer")
        self.assertEqual(prof, "Full Stack Developer", f"Full Stack resume classified as {prof}")
        self.assertGreaterEqual(conf, 50, f"Full Stack confidence too low: {conf}")


class TestFalsePositives(TestCase):
    def setUp(self):
        self.resumes = SAMPLE_RESUMES

    def test_all_false_positive_cases(self):
        results = []
        for case in FALSE_POSITIVE_CASES:
            resume_key = case["resume_key"]
            forbidden = case["should_not_be"]
            resume_text = self.resumes[resume_key]
            prof, conf = classify_profession_with_resume(resume_text)
            self.assertNotIn(prof, forbidden,
                             f"FALSE POSITIVE: {resume_key} resume classified as {prof}")
            results.append({
                "resume": resume_key,
                "detected": prof,
                "confidence": conf,
                "forbidden": forbidden,
                "passed": prof not in forbidden,
            })

    def test_no_false_positives_report(self):
        report = []
        for case in FALSE_POSITIVE_CASES:
            resume_key = case["resume_key"]
            forbidden = case["should_not_be"]
            resume_text = self.resumes[resume_key]
            prof, conf = classify_profession_with_resume(resume_text)
            if prof in forbidden:
                report.append(f"FALSE POSITIVE: {resume_key} -> {prof} (confidence: {conf})")
        self.assertEqual(len(report), 0, f"False positives detected:\n" + "\n".join(report))


class TestTitleClassification(TestCase):
    def test_flutter_developer_title(self):
        prof = classify_profession_from_title("Flutter Developer")
        self.assertEqual(prof, "Mobile Developer", f"Flutter Developer title -> {prof}")

    def test_react_native_developer_title(self):
        prof = classify_profession_from_title("React Native Developer")
        self.assertEqual(prof, "Mobile Developer", f"React Native Developer title -> {prof}")

    def test_frontend_developer_title(self):
        prof = classify_profession_from_title("Frontend Developer")
        self.assertEqual(prof, "Frontend Developer")

    def test_backend_developer_title(self):
        prof = classify_profession_from_title("Backend Developer")
        self.assertEqual(prof, "Backend Developer")

    def test_graphic_designer_title(self):
        prof = classify_profession_from_title("Graphic Designer")
        self.assertEqual(prof, "Graphic Designer")

    def test_data_scientist_title(self):
        prof = classify_profession_from_title("Data Scientist")
        self.assertEqual(prof, "Data Scientist")


class TestJobClassification(TestCase):
    def test_job_classification(self):
        test_cases = [
            ("Flutter Developer", ["Flutter", "Dart"]),
            ("React Native Developer", ["React Native", "JavaScript"]),
            ("Backend Python Developer", ["Python", "Django"]),
            ("Graphic Designer", ["Photoshop", "Illustrator"]),
            ("Data Scientist", ["Python", "Machine Learning"]),
        ]
        for title, skills in test_cases:
            result = classify_job(title, skills)
            self.assertIsNotNone(result, f"Job classification failed for {title}")
            self.assertNotEqual(result, "Other", f"Job {title} classified as Other")


class TestSkillNormalization(TestCase):
    def test_normalize_skill_aliases(self):
        cases = [
            ("ReactJS", "React"),
            ("react.js", "React"),
            ("React.js", "React"),
            ("NodeJS", "Node.js"),
            ("Node.js", "Node.js"),
            ("JS", "JavaScript"),
            ("Py", "Python"),
            ("Scikit Learn", "Scikit-learn"),
            ("scikit-learn", "Scikit-learn"),
            ("sklearn", "Scikit-learn"),
            ("Flutter SDK", "Flutter"),
            ("Flutter", "Flutter"),
            ("Django REST Framework", "Django REST Framework"),
            ("DRF", "Django REST Framework"),
            ("django rest", "Django REST Framework"),
            ("TF", "TensorFlow"),
            ("tensor flow", "TensorFlow"),
            ("K8s", "Kubernetes"),
            ("C++", "C++"),
            ("C#", "C#"),
            ("HTML5", "HTML"),
            ("CSS3", "CSS"),
            ("Next.js", "Next.js"),
            ("nextjs", "Next.js"),
            ("Vue.js", "Vue.js"),
            ("AngularJS", "Angular"),
            ("Tailwind CSS", "Tailwind CSS"),
            ("ML", "Machine Learning"),
            ("NLP", "NLP"),
            ("AI", "Artificial Intelligence"),
        ]
        for raw, expected in cases:
            result = normalize_skill(raw)
            self.assertEqual(result, expected,
                             f"normalize_skill('{raw}') = '{result}', expected '{expected}'")

    def test_normalize_skill_set(self):
        raw = ["ReactJS", "Node.js", "Python", "Django REST Framework", "Unknown Skill"]
        result = normalize_skill_set(raw)
        self.assertIn("react", result)
        self.assertIn("node.js", result)
        self.assertIn("python", result)
        self.assertIn("djangorestframework", result)

    def test_norm_skill_consistency(self):
        cases = [
            ("ReactJS", "react"),
            ("react.js", "react"),
            ("NodeJS", "node.js"),
            ("Node.js", "node.js"),
            ("Python", "python"),
            ("Py", "python"),
            ("DRF", "djangorestframework"),
            ("Scikit Learn", "scikitlearn"),
            ("Flutter SDK", "flutter"),
            ("Flutter", "flutter"),
        ]
        for raw, expected in cases:
            result = norm_skill(raw)
            self.assertEqual(result, expected, f"norm_skill('{raw}') = '{result}', expected '{expected}'")

    def test_display_name(self):
        cases = [
            ("nextjs", "Next.js"),
            ("reactjs", "React"),
            ("nodejs", "Node.js"),
            ("javascript", "JavaScript"),
            ("djangorestframework", "Django REST Framework"),
            ("machinelearning", "Machine Learning"),
        ]
        for raw, expected in cases:
            result = display_name(raw)
            self.assertEqual(result, expected, f"display_name('{raw}') = '{result}', expected '{expected}'")


class TestSkillExtraction(TestCase):
    def test_flutter_skills(self):
        skills = extract_skills_from_section(SAMPLE_RESUMES["Flutter Developer"])
        skill_names = [s.lower() for s in skills]
        self.assertIn("flutter", skill_names, f"Flutter not found in skills: {skills}")
        self.assertIn("dart", [s.lower() for s in skills],
                      "Dart should be in Flutter developer skills")

    def test_graphic_designer_skills(self):
        skills = extract_skills_from_section(SAMPLE_RESUMES["Graphic Designer"])
        skill_names = [s.lower() for s in skills]
        self.assertIn("photoshop", skill_names, f"Photoshop not found in skills: {skills}")
        self.assertIn("illustrator", skill_names, f"Illustrator not found in skills: {skills}")

    def test_accountant_skills(self):
        skills = extract_skills_from_section(SAMPLE_RESUMES["Accountant"])
        skill_names = [s.lower() for s in skills]
        self.assertIn("quickbooks", skill_names, f"QuickBooks not found in skills: {skills}")
        self.assertIn("accounting", skill_names, f"Accounting not found in skills: {skills}")


class TestRelatedProfessions(TestCase):
    def test_mobile_developer_related(self):
        # Mobile is a field of its own. Frontend used to be listed here, and
        # because get_related_profession_titles() feeds the job-category filter
        # directly, that is what made Flutter CVs come back full of React roles.
        related = get_related_professions("Mobile Developer")
        self.assertNotIn("Frontend Developer", related)
        self.assertNotIn("Full Stack Developer", related)
        self.assertNotIn("Accountant", related)

    def test_designer_never_related_to_engineering(self):
        related = get_related_professions("UI/UX Designer")
        self.assertNotIn("Frontend Developer", related)
        self.assertIn("Graphic Designer", related)

    def test_graphic_designer_related(self):
        related = get_related_professions("Graphic Designer")
        self.assertIn("UI/UX Designer", related)
        self.assertNotIn("DevOps Engineer", related)

    def test_accountant_isolated(self):
        related = get_related_professions("Accountant")
        self.assertEqual(len(related), 0, f"Accountant should have no related professions, got {related}")

    def test_hr_isolated(self):
        related = get_related_professions("Human Resources Manager")
        self.assertEqual(len(related), 0, f"HR should have no related professions, got {related}")

    def test_backend_related(self):
        related = get_related_professions("Backend Developer")
        self.assertIn("Full Stack Developer", related)
        self.assertIn("Software Engineer", related)
        self.assertIn("DevOps Engineer", related)
        self.assertNotIn("Graphic Designer", related)


class TestEvaluationReport(TestCase):
    def test_generate_detection_report(self):
        results = []
        for resume_key in SAMPLE_RESUMES:
            prof, conf = classify_profession_with_resume(SAMPLE_RESUMES[resume_key])
            expected = resume_key
            results.append({
                "resume": resume_key,
                "detected": prof,
                "expected": expected,
                "confidence": conf,
                "correct": prof == expected if expected != "Flutter Developer" else prof == "Mobile Developer",
            })

        correct = sum(1 for r in results if r["correct"])
        total = len(results)
        accuracy = correct / total * 100
        avg_confidence = sum(r["confidence"] for r in results) / total

        print(f"\n=== PROFESSION DETECTION REPORT ===")
        print(f"Accuracy: {accuracy:.1f}% ({correct}/{total})")
        print(f"Avg Confidence: {avg_confidence:.1f}")
        for r in results:
            status = "PASS" if r["correct"] else "FAIL"
            print(f"  [{status}] {r['resume']:30s} -> {r['detected']:25s} (conf={r['confidence']})")

        self.assertGreaterEqual(accuracy, 80.0, f"Detection accuracy {accuracy:.1f}% is below 80%")

    def test_false_positive_report(self):
        print(f"\n=== FALSE POSITIVE REPORT ===")
        total_fps = 0
        for case in FALSE_POSITIVE_CASES:
            resume_key = case["resume_key"]
            forbidden = case["should_not_be"]
            resume_text = SAMPLE_RESUMES[resume_key]
            prof, conf = classify_profession_with_resume(resume_text)
            fps = []
            for fb in forbidden:
                if prof == fb:
                    fps.append(fb)
                    total_fps += 1
            if fps:
                print(f"  [FAIL] {resume_key} -> {', '.join(fps)}")
            else:
                print(f"  [PASS] {resume_key} -> no false positives")
        self.assertEqual(total_fps, 0, f"Total false positives: {total_fps}")


class TestResumeSectionExtraction(TestCase):
    def test_extract_title_from_resume(self):
        sections = extract_resume_sections(SAMPLE_RESUMES["Flutter Developer"])
        title = sections.get("title", "").lower()
        self.assertIn("flutter", title, f"Title should contain 'flutter': {title}")

    def test_extract_skills_section(self):
        skills = extract_skills_from_section(SAMPLE_RESUMES["Backend Developer"])
        self.assertTrue(len(skills) > 0, f"Skills should be extracted, got: {skills}")
        self.assertIn("Django", skills, f"Django should be in backend skills: {skills}")
        self.assertIn("Python", skills, f"Python should be in backend skills: {skills}")


class TestScoringCalibration(TestCase):
    def setUp(self):
        self.maxDiff = None

    def _make_mock_job(self, category, skills=None, exp=0, edu=""):
        from types import SimpleNamespace
        return SimpleNamespace(
            job_category=category,
            required_skills=skills or [],
            experience_required=exp,
            education_required=edu,
        )

    def _make_mock_profile(self, skills=None, exp=0, edu=""):
        from types import SimpleNamespace
        return SimpleNamespace(
            skills=skills or [],
            experience_years=exp,
            education=edu,
        )

    def test_exact_match_scores_high(self):
        result = _compute_weighted_score(
            user_skills=["Python", "Django", "PostgreSQL"],
            user_profession="Backend Developer",
            profile=self._make_mock_profile(skills=["Python", "Django", "PostgreSQL"], exp=3),
            job=self._make_mock_job("Backend Developer", ["Python", "Django"], exp=2),
            vector_score=0.8,
        )
        self.assertGreaterEqual(result["final_score"], 70)

    def test_wrong_profession_scores_low(self):
        result = _compute_weighted_score(
            user_skills=["Photoshop", "Illustrator", "Branding"],
            user_profession="Graphic Designer",
            profile=self._make_mock_profile(skills=["Photoshop", "Illustrator", "Branding"], exp=3),
            job=self._make_mock_job("Backend Developer", ["Python", "Django"], exp=2),
            vector_score=0.3,
        )
        self.assertLessEqual(result["final_score"], 50)

    def test_unrelated_profession_blocked(self):
        result = _compute_weighted_score(
            user_skills=["Python", "Django"],
            user_profession="Backend Developer",
            profile=self._make_mock_profile(skills=["Python", "Django"], exp=3),
            job=self._make_mock_job("Accountant", ["QuickBooks", "Excel"], exp=2),
            vector_score=0.2,
        )
        self.assertLessEqual(result["final_score"], 30,
                             f"Unrelated profession score too high: {result['final_score']}")

    def test_identical_skills_high_score(self):
        result = _compute_weighted_score(
            user_skills=["Python", "Django", "DRF", "PostgreSQL", "Docker"],
            user_profession="Backend Developer",
            profile=self._make_mock_profile(skills=["Python", "Django", "DRF", "PostgreSQL", "Docker"], exp=5),
            job=self._make_mock_job("Backend Developer", ["Python", "Django", "PostgreSQL"], exp=3),
            vector_score=0.9,
        )
        self.assertGreaterEqual(result["final_score"], 75)

    def test_related_profession_still_scores(self):
        result = _compute_weighted_score(
            user_skills=["React", "TypeScript", "JavaScript", "CSS"],
            user_profession="Frontend Developer",
            profile=self._make_mock_profile(skills=["React", "TypeScript", "JavaScript", "CSS"], exp=3),
            job=self._make_mock_job("Full Stack Developer", ["React", "JavaScript", "Python", "Django"], exp=2),
            vector_score=0.6,
        )
        self.assertGreaterEqual(result["final_score"], 40)
        self.assertLessEqual(result["final_score"], 95)
