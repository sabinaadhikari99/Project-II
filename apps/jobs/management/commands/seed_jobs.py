"""Seed JobPosting records with 100 realistic, profession-specific job postings.

The command is deterministic (same input -> same output across runs) and
idempotent: jobs that already exist for a seeded recruiter are skipped.

Usage:
    python manage.py seed_jobs
    python manage.py seed_jobs --jobs 200
    python manage.py seed_jobs --recruiters 20
    python manage.py seed_jobs --with-embeddings
    python manage.py seed_jobs --reset

Generated data is suitable for testing AI Job Match, Skill Gap Analysis,
Recommended Courses and Learning Roadmap, because:
  * job_category is always one of the 17 taxonomy professions used by the
    profession classifier, so job pools line up with candidate professions;
  * required_skills are profession-specific and aligned with the course
    catalog, so skill gaps produce course recommendations;
  * every description, responsibility list, qualification list and required
    skill list is unique.
"""

import random
from collections import Counter
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from faker import Faker

from apps.jobs.models import JobPosting
from apps.shared.constants import ROLE_RECRUITER

User = get_user_model()

SEED_DOMAIN = "seedjobs.example"
SEED_PASSWORD = "Seed@Recruiter123"
DEFAULT_JOB_COUNT = 100
DEFAULT_RECRUITER_POOL = 12
RNG_SEED = 20260731

WORK_MODES = ("remote", "remote", "remote", "hybrid", "hybrid", "onsite")
EMPLOYMENT_TYPES = ("Full-time", "Full-time", "Full-time", "Contract", "Part-time")
TEAMS = (
    "Product", "Platform", "Data", "Design", "Infrastructure",
    "Security", "Mobile", "Quality", "Engineering", "Customer Experience",
)
SOFT_SKILLS = (
    "Communication", "Collaboration", "Problem Solving", "Critical Thinking",
    "Teamwork", "Time Management", "Adaptability", "Leadership",
)
BENEFITS = (
    "Comprehensive health, dental and vision insurance",
    "401(k) matching up to 5% of base salary",
    "Flexible working hours and remote-friendly setup",
    "Annual learning and development budget of $2,000",
    "20 days of paid time off plus public holidays",
    "Stock options for eligible employees",
    "Mental health and wellness support program",
    "Paid parental leave of 16 weeks",
    "Company-wide hackathons and innovation days",
    "Home office equipment stipend of $1,000",
    "Monthly team socials and quarterly offsites",
    "Professional certification sponsorship",
    "Performance-based annual bonus",
    "Free access to gym memberships and fitness classes",
)

# role -> (taxonomy category, salary band (low, high), core skills, alternate skills, duties, qualifications)
ROLE_SPECS = {
    "Frontend Developer": ("Frontend Developer", 60000, 115000, [
        "JavaScript", "TypeScript", "React", "CSS", "HTML", "Redux",
        "REST APIs", "Git", "Tailwind CSS", "Unit Testing",
    ], ["Next.js", "GraphQL", "SCSS", "Vue.js"], [
        "Build responsive, accessible UI components with React and Tailwind CSS",
        "Integrate REST APIs and manage application state with Redux",
        "Optimize page performance and Core Web Vitals across the product",
        "Collaborate with designers to translate Figma mockups into pixel-perfect interfaces",
        "Write unit and integration tests to protect core user flows",
    ], [
        "3+ years of professional frontend development experience",
        "Strong command of modern JavaScript, TypeScript and CSS",
        "Experience with component testing and code review workflows",
        "Portfolio of production web applications you can walk through",
    ]),

    "Backend Developer": ("Backend Developer", 65000, 120000, [
        "Python", "Django", "PostgreSQL", "Docker", "Redis", "REST APIs",
        "Celery", "Git", "Microservices",
    ], ["FastAPI", "Kafka", "RabbitMQ", "MySQL"], [
        "Design and build scalable REST APIs with Django and DRF",
        "Model relational data in PostgreSQL and tune query performance",
        "Run background jobs and scheduled tasks with Celery and Redis",
        "Containerize services with Docker and deploy to cloud infrastructure",
        "Participate in API design reviews and maintain integration tests",
    ], [
        "3+ years building backend services in Python with Django",
        "Solid understanding of relational databases and data modeling",
        "Experience with message queues and distributed systems",
        "Ability to write clean, tested, well-documented code",
    ]),

    "Full Stack Developer": ("Full Stack Developer", 65000, 120000, [
        "JavaScript", "React", "Node.js", "Express", "MongoDB", "REST APIs",
        "Docker", "Git", "HTML", "CSS",
    ], ["TypeScript", "GraphQL", "PostgreSQL", "Redis"], [
        "Ship end-to-end features spanning React frontends and Node.js APIs",
        "Design document schemas in MongoDB and optimize common queries",
        "Build reusable frontend components and shared API contracts",
        "Containerize the application stack with Docker for consistent deploys",
        "Own features from technical design through deployment and monitoring",
    ], [
        "4+ years of full stack development across React and Node.js",
        "Experience designing REST APIs and data schemas",
        "Comfortable working across the entire development lifecycle",
        "Strong debugging skills across browser, server and database layers",
    ]),

    "Python Developer": ("Backend Developer", 65000, 115000, [
        "Python", "Django", "Django REST Framework", "PostgreSQL", "Docker",
        "Redis", "Git", "Celery", "REST APIs",
    ], ["FastAPI", "Flask", "SQLAlchemy", "Pandas"], [
        "Develop backend services and internal tools in Python",
        "Expose and document HTTP APIs used by internal and external clients",
        "Automate data processing workflows and background jobs",
        "Write unit tests and participate in regular code reviews",
        "Maintain service documentation and API versioning strategy",
    ], [
        "3+ years of professional Python development",
        "Experience with Django or a comparable web framework",
        "Familiarity with PostgreSQL and asynchronous task queues",
        "Commitment to code quality, testing and documentation",
    ]),

    "Django Developer": ("Backend Developer", 65000, 115000, [
        "Python", "Django", "Django REST Framework", "PostgreSQL", "Docker",
        "Redis", "Celery", "Git", "REST APIs", "Unit Testing",
    ], ["FastAPI", "MySQL", "GraphQL", "RabbitMQ"], [
        "Build and maintain Django applications serving millions of requests",
        "Implement REST endpoints with DRF and enforce authentication policies",
        "Design database migrations and optimize hot query paths",
        "Schedule and monitor Celery tasks processing high-volume workloads",
        "Conduct code reviews and mentor junior developers on Django patterns",
    ], [
        "3+ years of experience with Django in production",
        "Deep knowledge of DRF, ORM optimization and migrations",
        "Experience deploying Django with Gunicorn, Nginx and Docker",
        "Strong testing discipline using pytest or Django TestCase",
    ]),

    "React Developer": ("Frontend Developer", 60000, 110000, [
        "React", "JavaScript", "TypeScript", "Redux", "Next.js",
        "Tailwind CSS", "CSS", "Git", "Unit Testing",
    ], ["GraphQL", "Vite", "SCSS", "Vue.js"], [
        "Develop complex product features with React and TypeScript",
        "Implement state management with Redux Toolkit and RTK Query",
        "Build SEO-friendly pages and routing with Next.js",
        "Improve render performance and bundle size of critical screens",
        "Maintain a component library with reusable, typed components",
    ], [
        "3+ years of professional React development",
        "Expertise in hooks, context and modern React patterns",
        "Experience with Next.js and server-side rendering",
        "Familiarity with accessibility standards and responsive design",
    ]),

    "Angular Developer": ("Frontend Developer", 60000, 110000, [
        "Angular", "TypeScript", "JavaScript", "SCSS", "HTML", "CSS",
        "REST APIs", "Git", "Unit Testing",
    ], ["RxJS", "NgRx", "Tailwind CSS", "Redux"], [
        "Build enterprise-grade applications with Angular and TypeScript",
        "Implement reactive state flows with RxJS and NgRx",
        "Create reusable directives, pipes and component libraries",
        "Optimize change detection and lazy-loaded module boundaries",
        "Write Jasmine and Karma unit tests for critical components",
    ], [
        "3+ years of Angular development in production",
        "Strong TypeScript and RxJS knowledge",
        "Experience with Angular CLI and build tooling",
        "Understanding of web accessibility and performance budgets",
    ]),

    "Vue Developer": ("Frontend Developer", 55000, 105000, [
        "Vue.js", "JavaScript", "TypeScript", "Vite", "CSS", "HTML",
        "REST APIs", "Git", "Unit Testing",
    ], ["Pinia", "Nuxt", "Tailwind CSS", "SCSS"], [
        "Build interactive interfaces with Vue 3 Composition API",
        "Manage application state with Pinia stores",
        "Develop server-rendered experiences with Nuxt",
        "Design reusable component systems and shared utilities",
        "Contribute to frontend tooling built on Vite",
    ], [
        "2+ years of Vue.js development experience",
        "Comfortable with TypeScript and modern tooling",
        "Experience shipping responsive, accessible interfaces",
        "Collaborative mindset with strong attention to detail",
    ]),

    "Flutter Developer": ("Mobile Developer", 65000, 125000, [
        "Flutter", "Dart", "Firebase", "REST APIs", "Riverpod", "Provider",
        "Git", "SQLite", "Clean Architecture",
    ], ["Flutter Testing", "Flutter Deployment", "GraphQL", "Mobile Testing"], [
        "Develop cross-platform mobile apps with Flutter and Dart",
        "Integrate Firebase services including Auth, Firestore and Push",
        "Architect features with Riverpod and clean architecture patterns",
        "Ship to the App Store and Google Play with automated build pipelines",
        "Profile app performance and fix platform-specific issues",
    ], [
        "3+ years of Flutter development with shipped apps",
        "Deep understanding of Dart, widgets and state management",
        "Experience with Firebase and mobile CI/CD pipelines",
        "Knowledge of offline storage and local database patterns",
    ]),

    "Android Developer": ("Mobile Developer", 65000, 120000, [
        "Kotlin", "Android", "Firebase", "REST APIs", "Git", "Clean Architecture",
        "Unit Testing", "SQLite", "Material Design",
    ], ["Jetpack Compose", "Coroutines", "Flutter", "Mobile Testing"], [
        "Build native Android applications with Kotlin and Jetpack Compose",
        "Implement offline-first experiences with Room and WorkManager",
        "Integrate Firebase Analytics, Crashlytics and Remote Config",
        "Publish releases to Google Play with staged rollouts",
        "Optimize startup time, memory usage and battery consumption",
    ], [
        "3+ years of native Android development with Kotlin",
        "Strong grasp of Material Design and accessibility guidelines",
        "Experience with coroutines, Flow and dependency injection",
        "Familiarity with Play Console release management",
    ]),

    "iOS Developer": ("Mobile Developer", 70000, 125000, [
        "Swift", "SwiftUI", "UIKit", "Firebase", "REST APIs", "Git",
        "Clean Architecture", "Unit Testing", "App Store",
    ], ["Core Data", "Combine", "Flutter", "Mobile Testing"], [
        "Build native iOS applications with Swift and SwiftUI",
        "Design data persistence layers with Core Data or SwiftData",
        "Implement async flows with Combine and structured concurrency",
        "Manage App Store submissions, TestFlight builds and review cycles",
        "Profile performance and memory usage with Instruments",
    ], [
        "3+ years of iOS development with shipped apps",
        "Proficiency in Swift, SwiftUI and UIKit",
        "Experience with Combine, async/await and concurrency",
        "Knowledge of App Store guidelines and release tooling",
    ]),

    "Java Developer": ("Backend Developer", 65000, 120000, [
        "Java", "Spring Boot", "PostgreSQL", "Docker", "REST APIs",
        "Microservices", "Kafka", "Git", "Redis",
    ], ["MySQL", "RabbitMQ", "Kubernetes", "MongoDB"], [
        "Develop backend services with Java 17 and Spring Boot",
        "Design event-driven components with Kafka and Redis",
        "Refactor monolith boundaries into maintainable microservices",
        "Write integration tests with Testcontainers and JUnit",
        "Contribute to shared libraries and API contracts",
    ], [
        "4+ years of Java development experience",
        "Strong Spring Boot and Spring Data expertise",
        "Experience with event streaming and caching technologies",
        "Solid understanding of REST design and API versioning",
    ]),

    "Spring Boot Developer": ("Backend Developer", 65000, 120000, [
        "Java", "Spring Boot", "Microservices", "PostgreSQL", "Docker",
        "Kafka", "REST APIs", "Git", "Redis", "Unit Testing",
    ], ["Kubernetes", "RabbitMQ", "MySQL", "MongoDB"], [
        "Build and operate Spring Boot services in production",
        "Implement resilience patterns including retries, timeouts and circuit breakers",
        "Design event producers and consumers on Kafka",
        "Containerize services and own deployment manifests",
        "Automate integration tests and contract tests for service boundaries",
    ], [
        "4+ years of Spring Boot experience in production",
        "Deep knowledge of Spring Security, Data JPA and Actuator",
        "Experience operating distributed systems",
        "Strong debugging and observability skills",
    ]),

    "Node.js Developer": ("Backend Developer", 65000, 115000, [
        "Node.js", "Express", "MongoDB", "JavaScript", "REST APIs", "Docker",
        "Redis", "Git", "Unit Testing",
    ], ["TypeScript", "GraphQL", "PostgreSQL", "RabbitMQ"], [
        "Develop high-throughput APIs with Node.js and Express",
        "Model and query data in MongoDB with effective indexes",
        "Implement caching layers and rate limiting with Redis",
        "Build real-time features with WebSocket and event streams",
        "Maintain test coverage for critical API paths",
    ], [
        "3+ years of Node.js backend development",
        "Strong JavaScript and async programming skills",
        "Experience with MongoDB and Redis in production",
        "Familiarity with Docker-based development workflows",
    ]),

    "Laravel Developer": ("Backend Developer", 55000, 105000, [
        "PHP", "Laravel", "MySQL", "REST APIs", "Docker", "Redis",
        "Git", "Unit Testing", "Vue.js",
    ], ["PostgreSQL", "Tailwind CSS", "Livewire", "Alpine.js"], [
        "Build web applications with Laravel and Eloquent",
        "Design REST APIs and queue-driven background jobs",
        "Create admin panels and dashboards with Livewire",
        "Optimize database queries and caching with Redis",
        "Deploy Laravel applications with Forge or containerized pipelines",
    ], [
        "3+ years of PHP and Laravel development",
        "Strong knowledge of Eloquent, migrations and seeders",
        "Experience with queues, events and scheduling",
        "Familiarity with TDD and Pest or PHPUnit",
    ]),

    "PHP Developer": ("Backend Developer", 50000, 95000, [
        "PHP", "Laravel", "MySQL", "JavaScript", "HTML", "CSS",
        "REST APIs", "Git", "Docker",
    ], ["PostgreSQL", "Vue.js", "WordPress", "Bootstrap"], [
        "Develop and maintain PHP applications and integrations",
        "Build features across backend logic and frontend templates",
        "Integrate third-party services via REST APIs",
        "Maintain database schemas and write data migration scripts",
        "Support production deployments and fix reported issues",
    ], [
        "2+ years of professional PHP development",
        "Working knowledge of MySQL and SQL",
        "Comfortable with Git-based collaboration",
        "Good sense of code maintainability and security basics",
    ]),

    ".NET Developer": ("Backend Developer", 65000, 115000, [
        "C#", "ASP.NET Core", "SQL", "REST APIs", "Docker", "Git",
        "Microservices", "Unit Testing", "Redis",
    ], ["Azure", "MongoDB", "RabbitMQ", "Kubernetes"], [
        "Develop backend services with C# and ASP.NET Core",
        "Design REST APIs and gRPC contracts for internal services",
        "Write unit and integration tests with xUnit",
        "Deploy services to Azure and monitor with Application Insights",
        "Refactor legacy codebases toward modern .NET patterns",
    ], [
        "3+ years of .NET development with C#",
        "Experience with ASP.NET Core and EF Core",
        "Familiarity with Azure services and CI/CD pipelines",
        "Solid testing and code review habits",
    ]),

    "DevOps Engineer": ("DevOps Engineer", 75000, 140000, [
        "Docker", "Kubernetes", "CI/CD", "AWS", "Terraform", "Linux",
        "Jenkins", "Git", "Ansible", "Prometheus",
    ], ["Grafana", "Azure", "GCP", "Helm"], [
        "Design and maintain CI/CD pipelines for multiple product teams",
        "Operate Kubernetes clusters and tune autoscaling policies",
        "Manage infrastructure as code with Terraform and Ansible",
        "Build monitoring and alerting with Prometheus and Grafana",
        "Drive incident response and post-mortem processes",
    ], [
        "4+ years of DevOps or SRE experience",
        "Hands-on Kubernetes and Terraform expertise",
        "Strong Linux administration and scripting skills",
        "Experience with cloud providers and cost optimization",
    ]),

    "Cloud Engineer": ("DevOps Engineer", 75000, 135000, [
        "AWS", "Azure", "GCP", "Docker", "Kubernetes", "Terraform",
        "Linux", "CI/CD", "Python", "Helm",
    ], ["Ansible", "Shell Scripting", "YAML", "BigQuery"], [
        "Architect and operate multi-cloud infrastructure",
        "Build repeatable infrastructure with Terraform modules",
        "Implement landing zones with networking and security guardrails",
        "Automate cloud cost governance and resource tagging policies",
        "Support teams with cloud migration and modernization paths",
    ], [
        "4+ years of cloud engineering experience",
        "Certification in at least one major cloud platform",
        "Strong Terraform and infrastructure-as-code background",
        "Experience with Kubernetes and container platforms",
    ]),

    "AWS Engineer": ("DevOps Engineer", 80000, 140000, [
        "AWS", "Terraform", "Docker", "Kubernetes", "CI/CD", "Linux",
        "Python", "YAML", "Shell Scripting",
    ], ["Ansible", "GCP", "Grafana", "Helm"], [
        "Design AWS architectures with high availability and disaster recovery",
        "Manage EKS clusters, IAM policies and VPC networking",
        "Automate provisioning with Terraform and CloudFormation",
        "Optimize AWS spend with right-sizing and savings plans",
        "Implement security best practices with AWS Config and GuardDuty",
    ], [
        "4+ years of AWS engineering experience",
        "Strong AWS certification track record",
        "Deep Terraform and Linux experience",
        "Experience running production Kubernetes workloads",
    ]),

    "Azure Engineer": ("DevOps Engineer", 80000, 140000, [
        "Azure", "Docker", "Kubernetes", "Terraform", "CI/CD", "Linux",
        "YAML", "Shell Scripting", "Helm",
    ], ["Ansible", "AWS", "Grafana", "Python"], [
        "Design Azure solutions including AKS, App Service and Azure SQL",
        "Automate deployments with Azure DevOps and Terraform",
        "Manage Entra ID identities and role-based access control",
        "Monitor workloads with Log Analytics and Defender for Cloud",
        "Drive Azure governance, policy and cost management",
    ], [
        "4+ years of Azure engineering experience",
        "Azure certifications in architecture or DevOps",
        "Strong Terraform and infrastructure-as-code skills",
        "Experience with Kubernetes and containerized workloads",
    ]),

    "GCP Engineer": ("DevOps Engineer", 80000, 140000, [
        "GCP", "Docker", "Kubernetes", "Terraform", "CI/CD", "BigQuery",
        "Linux", "Python", "YAML",
    ], ["AWS", "Ansible", "Grafana", "Helm"], [
        "Architect GCP solutions with GKE, Cloud Run and BigQuery",
        "Implement infrastructure as code with Terraform",
        "Build data pipelines and analytics on BigQuery",
        "Enforce GCP IAM, org policies and VPC service controls",
        "Automate CI/CD with Cloud Build and Artifact Registry",
    ], [
        "4+ years of GCP engineering experience",
        "Google Cloud certification in cloud architecture",
        "Strong Terraform and Kubernetes expertise",
        "Experience with data platforms and serverless computing",
    ]),

    "Cybersecurity Engineer": ("Cybersecurity Engineer", 75000, 140000, [
        "SIEM", "Firewall", "Network Security", "Penetration Testing",
        "Ethical Hacking", "Linux", "IDS/IPS", "Cryptography", "Risk Assessment",
    ], ["ELK Stack", "Security Auditing", "CISSP", "Shell Scripting"], [
        "Monitor and triage security events across SIEM platforms",
        "Conduct penetration tests and coordinate vulnerability remediation",
        "Harden network perimeters with firewalls and IDS/IPS controls",
        "Lead incident response and digital forensics investigations",
        "Maintain security policies aligned with ISO 27001 and NIST",
    ], [
        "4+ years of cybersecurity engineering experience",
        "Hands-on SIEM, firewall and threat detection expertise",
        "Penetration testing experience and relevant certifications",
        "Strong Linux, networking and scripting fundamentals",
    ]),

    "Network Engineer": ("Cybersecurity Engineer", 65000, 120000, [
        "Network Security", "Firewall", "IDS/IPS", "Linux", "ELK Stack",
        "Shell Scripting", "SIEM", "Networking", "Cryptography",
    ], ["Penetration Testing", "Risk Assessment", "CISSP", "Security Auditing"], [
        "Design and operate enterprise LAN, WAN and SD-WAN networks",
        "Manage firewall rulesets and VPN infrastructure",
        "Monitor network health with ELK Stack dashboards",
        "Troubleshoot routing, switching and load-balancing issues",
        "Enforce segmentation policies to protect critical assets",
    ], [
        "4+ years of network engineering experience",
        "Deep routing and switching knowledge (BGP, OSPF, VLANs)",
        "Experience with firewalls, VPNs and network monitoring",
        "CCNP or equivalent practical expertise",
    ]),

    "QA Engineer": ("Software Engineer", 50000, 95000, [
        "Unit Testing", "Test Driven Development", "Jira", "Postman",
        "CI/CD", "Git", "Debugging", "Communication", "Teamwork",
    ], ["Python", "Selenium", "Docker", "Mobile Testing"], [
        "Design test strategies covering functional, regression and E2E paths",
        "Execute manual and automated test suites across releases",
        "Track defects in Jira and drive resolution with developers",
        "Build API test collections with Postman",
        "Report quality metrics and risk signals to stakeholders",
    ], [
        "3+ years of QA engineering experience",
        "Strong knowledge of test design and defect lifecycle",
        "Experience with API testing and CI-integrated test runs",
        "Excellent attention to detail and communication skills",
    ]),

    "Automation Tester": ("Software Engineer", 50000, 95000, [
        "Python", "Unit Testing", "Test Driven Development", "Postman",
        "CI/CD", "Git", "Jenkins", "Docker", "Debugging",
    ], ["Selenium", "Jira", "JavaScript", "Mobile Testing"], [
        "Build and maintain automated test frameworks in Python",
        "Automate regression suites running in CI pipelines",
        "Develop API and contract tests with Postman and pytest",
        "Analyze flaky tests and stabilize suite execution time",
        "Pair with developers to embed quality gates into delivery",
    ], [
        "3+ years of test automation experience",
        "Strong Python or JavaScript automation skills",
        "Experience with Selenium, Playwright or similar tools",
        "Familiarity with CI/CD platforms such as Jenkins",
    ]),

    "Data Analyst": ("Data Analyst", 55000, 95000, [
        "SQL", "Excel", "Power BI", "Tableau", "Statistics", "Data Visualization",
        "Python", "Pandas", "Reporting", "Data Cleaning",
    ], ["Google Analytics", "Looker", "R", "Data Analysis"], [
        "Extract and clean data from warehouses and business systems",
        "Build dashboards in Power BI and Tableau for leadership",
        "Run statistical analyses to answer business questions",
        "Automate recurring reports with Python and SQL",
        "Partner with product and finance teams on metrics definitions",
    ], [
        "3+ years of data analysis experience",
        "Advanced SQL and strong Excel skills",
        "Experience with Power BI or Tableau dashboards",
        "Solid grasp of statistics and experiment design",
    ]),

    "Data Engineer": ("Data Engineer", 80000, 145000, [
        "SQL", "Python", "Spark", "Airflow", "Kafka", "Data Pipelines",
        "ETL", "Snowflake", "BigQuery", "Data Warehousing",
    ], ["Hadoop", "AWS", "Redshift", "Docker"], [
        "Design and maintain batch and streaming data pipelines",
        "Orchestrate workflows with Airflow and monitor DAG health",
        "Model warehouse schemas in Snowflake and BigQuery",
        "Build streaming consumers with Kafka for real-time analytics",
        "Implement data quality checks and lineage tracking",
    ], [
        "4+ years of data engineering experience",
        "Expert SQL and strong Python skills",
        "Experience with Spark, Airflow and streaming platforms",
        "Deep knowledge of cloud data warehouses",
    ]),

    "Data Scientist": ("Data Scientist", 80000, 150000, [
        "Python", "Pandas", "NumPy", "TensorFlow", "Scikit-learn", "SQL",
        "Power BI", "Statistics", "Machine Learning", "Matplotlib",
    ], ["PyTorch", "Keras", "Seaborn", "R"], [
        "Build predictive models on large customer and product datasets",
        "Design A/B tests and evaluate causal impact of product changes",
        "Communicate findings with clear visualizations and narratives",
        "Develop model monitoring and retraining processes",
        "Collaborate with engineering to deploy models to production",
    ], [
        "4+ years of data science experience",
        "Strong statistics and machine learning fundamentals",
        "Proficiency in Python, Pandas and Scikit-learn",
        "Experience shipping models that drive business decisions",
    ]),

    "Machine Learning Engineer": ("Machine Learning Engineer", 90000, 160000, [
        "Python", "TensorFlow", "PyTorch", "Scikit-learn", "Machine Learning",
        "MLOps", "Docker", "Model Deployment", "AWS", "Keras",
    ], ["Kubernetes", "Kafka", "SQL", "FastAPI"], [
        "Train and fine-tune deep learning models at scale",
        "Build ML training and inference pipelines on AWS",
        "Operationalize models with monitoring, retraining and drift detection",
        "Optimize inference latency and serving costs",
        "Establish MLOps standards for the data science team",
    ], [
        "4+ years of machine learning engineering experience",
        "Expertise in PyTorch or TensorFlow",
        "Experience deploying models in production environments",
        "Strong software engineering fundamentals and Python skills",
    ]),

    "AI Engineer": ("Machine Learning Engineer", 90000, 160000, [
        "Python", "PyTorch", "TensorFlow", "Deep Learning", "NLP",
        "Machine Learning", "MLOps", "Model Deployment", "Docker",
    ], ["Keras", "AWS", "FastAPI", "Kubernetes"], [
        "Design and train AI models for production use cases",
        "Integrate LLM-based features with retrieval pipelines",
        "Build evaluation harnesses to measure model quality",
        "Deploy AI services with strict latency and cost budgets",
        "Stay current on research and translate it into product value",
    ], [
        "4+ years of applied AI engineering experience",
        "Strong deep learning and NLP background",
        "Experience deploying and monitoring AI services",
        "Solid Python and production software engineering skills",
    ]),

    "NLP Engineer": ("Machine Learning Engineer", 90000, 160000, [
        "Python", "NLP", "PyTorch", "TensorFlow", "Machine Learning",
        "Deep Learning", "MLOps", "Model Deployment", "Docker",
    ], ["Keras", "AWS", "FastAPI", "Scikit-learn"], [
        "Build and fine-tune language models for classification and extraction",
        "Develop entity recognition and text classification pipelines",
        "Evaluate models with domain-specific metrics and human review",
        "Optimize inference for token and cost efficiency",
        "Publish language model evaluations to product stakeholders",
    ], [
        "4+ years of NLP engineering experience",
        "Deep understanding of transformer architectures",
        "Experience with PyTorch and Hugging Face ecosystem",
        "Strong Python and data engineering skills",
    ]),

    "Computer Vision Engineer": ("Machine Learning Engineer", 90000, 160000, [
        "Python", "Computer Vision", "PyTorch", "TensorFlow", "Deep Learning",
        "Machine Learning", "Model Deployment", "Docker", "Algorithms",
    ], ["C++", "AWS", "Keras", "Kubernetes"], [
        "Build object detection and segmentation models for production",
        "Curate and augment large image datasets",
        "Optimize models for edge and low-latency inference",
        "Deploy vision services with automated evaluation pipelines",
        "Research novel architectures and benchmark them rigorously",
    ], [
        "4+ years of computer vision experience",
        "Strong deep learning and image processing expertise",
        "Experience deploying vision models at scale",
        "Proficiency in PyTorch and Python",
    ]),

    "Database Administrator": ("Software Engineer", 65000, 115000, [
        "SQL", "PostgreSQL", "MySQL", "MongoDB", "Data Modeling",
        "Performance Optimization", "Data Warehousing", "Linux", "Shell Scripting",
    ], ["Redis", "Kafka", "AWS", "Snowflake"], [
        "Administer PostgreSQL, MySQL and MongoDB clusters",
        "Tune queries, indexes and configuration for performance",
        "Design backup, recovery and failover strategies",
        "Manage schema changes and data migrations across environments",
        "Monitor database health and capacity trends",
    ], [
        "4+ years of database administration experience",
        "Expert SQL and deep PostgreSQL knowledge",
        "Experience with replication, clustering and high availability",
        "Strong Linux and scripting fundamentals",
    ]),

    "UI/UX Designer": ("UI/UX Designer", 55000, 105000, [
        "Figma", "User Research", "Wireframing", "Prototyping",
        "Usability Testing", "UI Design", "Interaction Design",
        "Design Systems", "User Flows", "Responsive Design",
    ], ["Sketch", "Visual Design", "Information Architecture", "Personas"], [
        "Lead end-to-end design from research to high-fidelity UI",
        "Conduct user interviews and usability testing sessions",
        "Build and maintain design systems in Figma",
        "Create wireframes, prototypes and interaction specs",
        "Partner with engineering to ensure pixel-perfect delivery",
    ], [
        "3+ years of UI/UX design experience",
        "Strong portfolio demonstrating shipped products",
        "Expert Figma and prototyping skills",
        "Experience with user research and testing methods",
    ]),

    "Graphic Designer": ("Graphic Designer", 45000, 85000, [
        "Photoshop", "Illustrator", "Adobe XD", "Branding", "Typography",
        "Color Theory", "Layout", "Logo Design", "Print Design", "Canva",
    ], ["InDesign", "Motion Graphics", "Sketch", "Visual Design"], [
        "Design brand identities, logos and visual guidelines",
        "Create marketing assets for digital and print channels",
        "Produce social media and campaign creative",
        "Build pitch decks and presentation templates",
        "Collaborate with content teams on visual storytelling",
    ], [
        "3+ years of graphic design experience",
        "Strong portfolio across branding and marketing",
        "Expertise in Adobe Creative Suite",
        "Excellent typography and layout skills",
    ]),

    "Product Designer": ("UI/UX Designer", 60000, 110000, [
        "Figma", "Prototyping", "User Research", "Wireframing",
        "Design Systems", "Interaction Design", "UI Design",
        "Usability Testing", "User Flows", "Product Metrics",
    ], ["Sketch", "Information Architecture", "Visual Design", "Personas"], [
        "Own product design across web and mobile surfaces",
        "Translate product goals into tested, high-quality flows",
        "Run discovery sessions and usability testing with users",
        "Maintain scalable design systems and component libraries",
        "Measure design impact using product metrics",
    ], [
        "4+ years of product design experience",
        "Portfolio of complex, shipped digital products",
        "Strong systems thinking and interaction design skills",
        "Experience collaborating directly with product managers",
    ]),

    "Product Manager": ("Product Manager", 80000, 140000, [
        "Product Strategy", "Roadmapping", "Market Research", "Product Metrics",
        "Stakeholder Management", "Agile", "Jira", "User Research",
        "Data Analysis", "Communication",
    ], ["Scrum", "A/B Testing", "Google Analytics", "SQL"], [
        "Own the product roadmap from discovery to delivery",
        "Conduct market and competitive research to shape strategy",
        "Define success metrics and track product performance",
        "Prioritize backlog with stakeholders across the business",
        "Run discovery interviews and validate solutions with users",
    ], [
        "4+ years of product management experience",
        "Track record of shipping successful products",
        "Strong data analysis and prioritization skills",
        "Excellent stakeholder communication abilities",
    ]),

    "Business Analyst": ("Product Manager", 65000, 115000, [
        "Data Analysis", "Stakeholder Management", "SQL", "Excel", "Jira",
        "Reporting", "Agile", "Critical Thinking", "Communication", "Collaboration",
    ], ["Power BI", "Scrum", "Confluence", "Process Mapping"], [
        "Gather and document requirements across business units",
        "Model business processes and identify improvement opportunities",
        "Translate requirements into user stories and acceptance criteria",
        "Analyze data to support decision-making and reporting",
        "Facilitate workshops and manage stakeholder expectations",
    ], [
        "3+ years of business analysis experience",
        "Strong requirements gathering and documentation skills",
        "Working knowledge of SQL and data analysis",
        "Experience with Agile delivery frameworks",
    ]),

    "Scrum Master": ("Product Manager", 70000, 120000, [
        "Scrum", "Agile", "Jira", "Confluence", "Stakeholder Management",
        "Project Management", "Leadership", "Communication", "Teamwork",
        "Emotional Intelligence",
    ], ["Kanban", "Coaching", "Risk Assessment", "Reporting"], [
        "Coach teams on Scrum practices and continuous improvement",
        "Facilitate sprint planning, reviews and retrospectives",
        "Remove impediments and shield teams from distractions",
        "Track delivery metrics and report progress to leadership",
        "Champion agile transformation across multiple squads",
    ], [
        "3+ years of Scrum Master experience",
        "Certified Scrum Master or equivalent",
        "Strong facilitation and conflict resolution skills",
        "Experience scaling agile across multiple teams",
    ]),

    "Project Manager": ("Product Manager", 70000, 120000, [
        "Project Management", "Agile", "Scrum", "Jira", "Stakeholder Management",
        "Risk Assessment", "Leadership", "Communication", "Reporting", "Critical Thinking",
    ], ["Confluence", "Excel", "Waterfall", "Product Metrics"], [
        "Plan and execute projects from initiation to closure",
        "Manage budgets, timelines and resource allocation",
        "Identify risks and drive mitigation plans",
        "Communicate status and decisions to stakeholders",
        "Run retrospectives and institutionalize lessons learned",
    ], [
        "4+ years of project management experience",
        "PMP or equivalent project management certification",
        "Strong budget and schedule management skills",
        "Excellent stakeholder communication abilities",
    ]),

    "Blockchain Developer": ("Software Engineer", 80000, 140000, [
        "JavaScript", "TypeScript", "Node.js", "Cryptography", "Git",
        "REST APIs", "Docker", "Unit Testing", "Algorithms",
    ], ["Python", "Go", "Rust", "PostgreSQL"], [
        "Design and implement blockchain-based applications",
        "Write secure smart contract logic and integration layers",
        "Build wallet integrations and transaction signing flows",
        "Audit code for security and gas-efficiency issues",
        "Integrate blockchain services with conventional backends",
    ], [
        "3+ years of software development experience",
        "Strong cryptography and consensus mechanism knowledge",
        "Experience with blockchain platforms and tooling",
        "Solid security mindset and testing discipline",
    ]),

    "Game Developer": ("Software Engineer", 55000, 105000, [
        "C#", "C++", "OOP", "Algorithms", "Data Structures", "Debugging",
        "Performance Optimization", "Design Patterns", "Git",
    ], ["Python", "Rust", "JavaScript", "Linux"], [
        "Implement core gameplay systems and mechanics",
        "Optimize rendering and physics performance",
        "Build editor tools that speed up content creation",
        "Integrate audio, animation and VFX pipelines",
        "Profile and fix memory and frame-time issues",
    ], [
        "3+ years of game development experience",
        "Strong C# or C++ skills",
        "Experience with game engines and real-time systems",
        "Portfolio of playable games or prototypes",
    ]),

    "Embedded Engineer": ("Software Engineer", 65000, 115000, [
        "C++", "C", "Linux", "OOP", "Shell Scripting", "Debugging",
        "Git", "Networking", "Algorithms",
    ], ["Python", "Rust", "C#", "YAML"], [
        "Develop firmware for embedded and IoT devices",
        "Implement device drivers and board support packages",
        "Optimize code for memory and power constraints",
        "Build test harnesses for hardware-in-the-loop testing",
        "Integrate devices with cloud IoT platforms",
    ], [
        "4+ years of embedded software development",
        "Strong C and C++ expertise",
        "Experience with RTOS and bare-metal development",
        "Knowledge of communication protocols and debugging tools",
    ]),
}

EDUCATION_FIELDS = {
    "Frontend Developer": "Computer Science",
    "Backend Developer": "Computer Science",
    "Full Stack Developer": "Computer Science",
    "Software Engineer": "Computer Science or related engineering field",
    "DevOps Engineer": "Computer Science",
    "Data Scientist": "Data Science",
    "Machine Learning Engineer": "Machine Learning",
    "Data Engineer": "Data Engineering",
    "Data Analyst": "Statistics",
    "Graphic Designer": "Graphic Design",
    "UI/UX Designer": "Design",
    "Product Manager": "Business Administration",
    "Marketing Manager": "Marketing",
    "Accountant": "Accounting",
    "Human Resources Manager": "Human Resources",
    "Cybersecurity Engineer": "Cybersecurity",
    "Mobile Developer": "Computer Science",
}

INSTANCE_TITLES = (
    ("{role}", (1, 3)),
    ("Senior {role}", (6, 9)),
    ("{role}", (3, 5)),
)


def _rounded_salary(value):
    return int(round(value / 5000.0) * 5000)


class Command(BaseCommand):
    help = (
        "Seed JobPosting records with 100 realistic, profession-specific jobs "
        "suitable for AI Job Match, Skill Gap Analysis, Recommended Courses and "
        "Learning Roadmap testing."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--jobs", type=int, default=DEFAULT_JOB_COUNT,
            help=f"Number of jobs to seed (default: {DEFAULT_JOB_COUNT}).",
        )
        parser.add_argument(
            "--recruiters", type=int, default=DEFAULT_RECRUITER_POOL,
            help=f"Number of recruiter accounts to create (default: {DEFAULT_RECRUITER_POOL}).",
        )
        parser.add_argument(
            "--reset", action="store_true",
            help="Delete all jobs created by this command before reseeding.",
        )
        parser.add_argument(
            "--with-embeddings", action="store_true",
            help="Also compute and store job embeddings via create_job_with_embedding().",
        )

    def handle(self, *args, **options):
        job_count = options["jobs"]
        pool_size = options["recruiters"]
        if job_count < 1:
            raise CommandError("--jobs must be at least 1")
        if pool_size < 1:
            raise CommandError("--recruiters must be at least 1")

        rng = random.Random(RNG_SEED)
        Faker.seed(RNG_SEED)
        fake = Faker("en_US")

        if options["reset"]:
            deleted, _ = JobPosting.objects.filter(
                recruiter__email__endswith=f"@{SEED_DOMAIN}"
            ).delete()
            self.stdout.write(f"Reset: deleted {deleted} previously seeded job(s).")

        recruiters = self._get_recruiters(pool_size)
        specs = self._generate_specs(job_count, rng, fake)

        created = 0
        skipped = 0
        created_jobs = []
        for spec in specs:
            recruiter = recruiters[spec["index"] % len(recruiters)]
            if JobPosting.objects.filter(
                recruiter=recruiter, title=spec["title"], company=spec["company"]
            ).exists():
                skipped += 1
                continue
            job = self._create_job(recruiter, spec, options["with_embeddings"])
            created_jobs.append(job)
            created += 1

        self._assert_unique("description", [job.description for job in created_jobs])
        self._assert_unique(
            "required_skills",
            [", ".join(job.required_skills) for job in created_jobs],
        )

        self._print_summary(
            created, skipped, created_jobs, job_count, recruiters,
            with_embeddings=options["with_embeddings"],
        )

    def _get_recruiters(self, pool_size):
        recruiters = []
        for i in range(pool_size):
            email = f"recruiter{i + 1:02d}@{SEED_DOMAIN}"
            username = f"recruiter_seed_{i + 1:02d}"
            recruiter, was_created = User.objects.get_or_create(
                email=email,
                defaults={"username": username, "role": ROLE_RECRUITER},
            )
            if was_created:
                recruiter.set_password(SEED_PASSWORD)
                recruiter.save()
            recruiters.append(recruiter)
        return recruiters

    def _generate_specs(self, job_count, rng, fake):
        role_names = list(ROLE_SPECS)
        companies = self._unique_values(fake.company, job_count)
        locations = self._unique_values(
            lambda: f"{fake.city()}, {fake.country()}", job_count
        )
        specs = []
        for i in range(job_count):
            role = role_names[i % len(role_names)]
            instance = i // len(role_names)
            title_template, exp_range = INSTANCE_TITLES[instance]
            spec = self._build_spec(
                index=i,
                role=role,
                title=title_template.format(role=role),
                exp_range=exp_range,
                company=companies[i],
                location=locations[i],
                rng=rng,
                fake=fake,
            )
            specs.append(spec)
        return specs

    def _build_spec(self, index, role, title, exp_range, company, location, rng, fake):
        category, band_low, band_high, core_skills, alternates, duties, quals = ROLE_SPECS[role]
        exp_required = round(rng.uniform(*exp_range), 1)
        work_mode = rng.choice(WORK_MODES)
        employment = rng.choice(EMPLOYMENT_TYPES)

        instance = index // len(ROLE_SPECS)
        required = self._unique_required_skills(core_skills, alternates, instance, rng)
        preferred = [
            skill for skill in alternates if skill not in required
        ][:2] + list(rng.sample(SOFT_SKILLS, 1))

        seniority = "junior" if exp_required < 2 else ("senior" if exp_required >= 6 else "mid")
        salary_mid = rng.uniform(band_low, band_high)
        salary_mid *= {"junior": 0.85, "mid": 1.0, "senior": 1.25}[seniority]
        salary_mid = _rounded_salary(salary_mid)
        salary_range = f"${salary_mid * 0.9:,.0f} - ${salary_mid * 1.15:,.0f}"

        apply_by = (date.today() + timedelta(days=rng.randint(21, 45))).isoformat()
        description = self._build_description(
            rng=rng,
            role=title,
            company=company,
            location=location,
            work_mode=work_mode,
            employment=employment,
            salary_range=salary_range,
            duties=duties,
            quals=quals,
            preferred=preferred,
            apply_by=apply_by,
            category=category,
            seniority=seniority,
            fake=fake,
        )
        education = self._education_for(category, seniority, rng)

        return {
            "index": index,
            "title": title,
            "company": company,
            "company_logo": "",
            "location": location,
            "work_mode": work_mode,
            "description": description,
            "required_skills": required,
            "experience_required": exp_required,
            "education_required": education,
            "salary_range": salary_range,
            "job_category": category,
            "is_active": True,
        }

    def _unique_required_skills(self, core_skills, alternates, instance, rng):
        skills = list(core_skills)
        if alternates:
            start = instance % len(alternates)
            chosen = (alternates[start:start + 2]
                      if start + 2 <= len(alternates)
                      else alternates[start:] + alternates[:2 - (len(alternates) - start)])
            for offset, alt in enumerate(chosen):
                skills[(offset + 1 + instance) % len(skills)] = alt
        rng.shuffle(skills)
        return skills

    def _build_description(self, rng, role, company, location, work_mode, employment,
                           salary_range, duties, quals, preferred, apply_by,
                           category, seniority, fake):
        duties = list(duties)
        quals = list(quals)
        rng.shuffle(duties)
        rng.shuffle(quals)
        benefits = rng.sample(BENEFITS, 5)

        parts = [
            f"{company} is hiring a {role} to join the {rng.choice(TEAMS)} team in {location}.",
            f"This {employment.lower()} position offers {salary_range} per year and follows a {work_mode} work arrangement.",
            f"The ideal candidate will strengthen our {category} capability while working closely with product, engineering and design stakeholders.",
            "",
            "Responsibilities:",
        ]
        parts.extend(f"- {duty}." for duty in duties[:4])
        parts.extend([
            "",
            "Qualifications:",
        ])
        parts.extend(f"- {qual}." for qual in quals[:3])
        parts.extend([
            "",
            f"Preferred skills: {', '.join(preferred)}.",
            "",
            "Benefits:",
        ])
        parts.extend(f"- {benefit}." for benefit in benefits)
        parts.extend([
            "",
            f"Employment type: {employment}",
            f"Work mode: {work_mode.capitalize()}",
            f"Applications close {apply_by}.",
        ])
        return "\n".join(parts)

    def _education_for(self, category, seniority, rng):
        field = EDUCATION_FIELDS.get(category, "")
        if not field:
            return ""
        if category in ("Data Scientist", "Machine Learning Engineer") and rng.random() < 0.6:
            return f"Master's Degree in {field}"
        if seniority == "junior" and rng.random() < 0.3:
            return ""
        return f"Bachelor's Degree in {field}"

    def _create_job(self, recruiter, spec, with_embeddings):
        data = {key: value for key, value in spec.items() if key != "index"}
        if with_embeddings:
            from apps.jobs.services import create_job_with_embedding
            return create_job_with_embedding(recruiter, data)
        return JobPosting.objects.create(recruiter=recruiter, **data)

    def _unique_values(self, generator, count):
        values = []
        seen = set()
        while len(values) < count:
            value = generator()
            if value not in seen:
                seen.add(value)
                values.append(value)
        return values

    def _assert_unique(self, label, values):
        seen = set()
        duplicates = []
        for value in values:
            if value in seen:
                duplicates.append(value)
            seen.add(value)
        if duplicates:
            raise CommandError(
                f"Generated {label} values are not unique ({len(duplicates)} duplicate(s)). "
                "Rerun with --reset to regenerate cleanly."
            )

    def _print_summary(self, created, skipped, created_jobs, job_count, recruiters,
                       with_embeddings=False):
        self.stdout.write(self.style.SUCCESS(
            f"Jobs: {created} created, {skipped} already existed (target: {job_count})."
        ))
        if created_jobs:
            spread = Counter(job.job_category for job in created_jobs)
            self.stdout.write("Category spread (created jobs):")
            for category, count in sorted(spread.items(), key=lambda item: -item[1]):
                self.stdout.write(f"  {category}: {count}")
            self.stdout.write("Sample:")
            for job in created_jobs[:5]:
                self.stdout.write(
                    f"  - {job.title} @ {job.company} ({job.job_category}, {job.work_mode}, {job.salary_range})"
                )
        self.stdout.write(
            f"Recruiters: {len(recruiters)} seeded accounts "
            f"(recruiter01@{SEED_DOMAIN} .. recruiter{len(recruiters):02d}@{SEED_DOMAIN}, "
            f"password: {SEED_PASSWORD})."
        )
        if not with_embeddings:
            self.stdout.write(self.style.WARNING(
                "Note: embeddings were not computed. Run with --with-embeddings "
                "when the embedding service is available to populate the vector store."
            ))
