import json
import logging
import os
import random

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.shared.profession_classifier import PROFESSION_CONFIGS

logger = logging.getLogger(__name__)

random.seed(42)

PROFESSION_NAMES = sorted(PROFESSION_CONFIGS.keys())

CAREER_LEVELS = ["Junior", "Mid", "Senior", "Lead"]

INDUSTRIES = [
    "Technology", "Data & Analytics", "Healthcare", "Finance", "E-commerce",
    "Consulting", "Education", "Media & Entertainment", "Manufacturing",
    "Real Estate", "Gaming", "Non-profit", "Telecommunications",
    "Automotive", "Energy", "Aerospace", "Biotechnology",
]

LOCATIONS = [
    "San Francisco, CA", "New York, NY", "Seattle, WA", "Austin, TX",
    "Boston, MA", "Chicago, IL", "Denver, CO", "Los Angeles, CA",
    "Portland, OR", "Atlanta, GA", "Dallas, TX", "Miami, FL",
    "Phoenix, AZ", "San Diego, CA", "Minneapolis, MN", "Raleigh, NC",
    "Remote", "Houston, TX", "Philadelphia, PA", "Charlotte, NC",
]

FIRST_NAMES = [
    "Alex", "Jordan", "Taylor", "Casey", "Riley", "Morgan", "Blake",
    "Avery", "Cameron", "Dakota", "Parker", "Quinn", "Harper", "Logan",
    "Sage", "Emerson", "Reese", "Finley", "Rowan", "Drew", "Liam",
    "Noah", "Oliver", "Elijah", "James", "William", "Henry", "Lucas",
    "Emma", "Olivia", "Ava", "Isabella", "Sophia", "Mia", "Charlotte",
    "Amelia", "Ethan", "Mason", "Lucas", "Evelyn", "Abigail", "Ella",
]

LAST_NAMES = [
    "Martinez", "Smith", "Wong", "Brown", "Johnson", "Davis", "Anderson",
    "Wilson", "Taylor", "Thomas", "Garcia", "Robinson", "Clark", "Lewis",
    "Lee", "Walker", "Hall", "Allen", "Young", "Hernandez", "King",
    "Wright", "Lopez", "Hill", "Scott", "Green", "Adams", "Baker",
    "Gonzalez", "Nelson", "Carter", "Mitchell", "Perez", "Roberts",
    "Turner", "Phillips", "Campbell", "Parker", "Evans", "Edwards",
    "Collins", "Stewart", "Morris", "Patel", "Kumar", "Chen", "Gupta",
]

COMPANY_ADJECTIVES = [
    "Global", "Digital", "Dynamic", "Core", "Peak", "Next", "First",
    "Premium", "Elite", "Prime", "Apex", "Quantum", "Nova", "Fusion",
    "Vertex", "Pulse", "Nexus", "Horizon", "Summit", "Pinnacle",
]

COMPANY_NOUNS = [
    "Tech", "Systems", "Solutions", "Labs", "Works", "Group", "Corp",
    "Inc", "Analytics", "Software", "Digital", "Data", "Cloud", "Net",
    "Dynamics", "Ventures", "Partners", "Media", "Health", "Finance",
]

COMPANY_SUFFIXES = ["Inc", "Corp", "LLC", "Group", "Technologies", "Solutions"]


def generate_company_name():
    adj = random.choice(COMPANY_ADJECTIVES)
    noun = random.choice(COMPANY_NOUNS)
    suffix = random.choice(COMPANY_SUFFIXES)
    return f"{adj}{noun} {suffix}"


def make_email(first, last, domain=None):
    if domain:
        return f"{first.lower()}.{last.lower()}@{domain}"
    domains = ["gmail.com", "outlook.com", "yahoo.com", "protonmail.com", "icloud.com"]
    return f"{first.lower()}.{last.lower()}@{random.choice(domains)}"


def generate_companies(count=100):
    seen = set()
    companies = []
    existing = [
        {"name": "TechCorp Global", "industry": "Technology", "description": "Enterprise SaaS platform provider serving Fortune 500 clients worldwide.", "location": "San Francisco, CA"},
        {"name": "InnoVista Systems", "industry": "Technology", "description": "Cloud infrastructure and DevOps consulting firm specializing in AWS and GCP migrations.", "location": "Seattle, WA"},
        {"name": "CloudPeak Technologies", "industry": "Technology", "description": "Next-gen cloud-native application development company.", "location": "Austin, TX"},
        {"name": "DataForge Analytics", "industry": "Data & Analytics", "description": "Big data and machine learning solutions for healthcare and finance.", "location": "New York, NY"},
        {"name": "Appcraft Studios", "industry": "Technology", "description": "Mobile-first application development studio building cross-platform apps.", "location": "Portland, OR"},
        {"name": "NexGen Software", "industry": "Technology", "description": "Custom software development firm specializing in enterprise microservices architecture.", "location": "Boston, MA"},
        {"name": "ByteBridge Solutions", "industry": "Technology", "description": "Full-service IT consulting and digital transformation partner.", "location": "Denver, CO"},
        {"name": "QuantumStack Inc", "industry": "Technology", "description": "Cloud-native infrastructure and platform engineering company.", "location": "San Francisco, CA"},
        {"name": "SilverOak Financial", "industry": "Finance", "description": "Wealth management and financial advisory services for high-net-worth individuals.", "location": "New York, NY"},
        {"name": "Pulse Media Group", "industry": "Media & Entertainment", "description": "Digital media and advertising agency with a focus on brand storytelling.", "location": "Los Angeles, CA"},
        {"name": "ShopNova", "industry": "E-commerce", "description": "Direct-to-consumer e-commerce platform for emerging lifestyle brands.", "location": "Austin, TX"},
        {"name": "MedCore Health", "industry": "Healthcare", "description": "Healthcare technology company building EHR and telemedicine platforms.", "location": "Boston, MA"},
        {"name": "Apex Manufacturing Corp", "industry": "Manufacturing", "description": "Industrial automation and smart manufacturing solutions provider.", "location": "Detroit, MI"},
        {"name": "StratEdge Consulting", "industry": "Consulting", "description": "Management and technology consulting firm serving mid-market enterprises.", "location": "Chicago, IL"},
        {"name": "LearnSphere Education", "industry": "Education", "description": "EdTech platform offering personalized learning paths and professional certifications.", "location": "Raleigh, NC"},
        {"name": "GreenLeaf Nonprofit", "industry": "Non-profit", "description": "Environmental conservation nonprofit leveraging technology for climate action.", "location": "Portland, OR"},
        {"name": "NexaGen Gaming", "industry": "Gaming", "description": "Indie game studio focused on cross-platform multiplayer experiences.", "location": "Los Angeles, CA"},
        {"name": "CrestView Realty", "industry": "Real Estate", "description": "Commercial real estate technology and property management platform.", "location": "Miami, FL"},
        {"name": "SkyNet Telecom", "industry": "Telecommunications", "description": "Telecommunications infrastructure and 5G network solutions provider.", "location": "Atlanta, GA"},
        {"name": "BioSync Labs", "industry": "Biotechnology", "description": "Biotech research company using AI for drug discovery and genomic analysis.", "location": "San Diego, CA"},
        {"name": "Titan Aerospace", "industry": "Aerospace", "description": "Aerospace engineering and satellite technology company.", "location": "Seattle, WA"},
    ]
    for c in existing:
        name = c["name"]
        seen.add(name.lower())
        companies.append({**c, "size": random.choice(["50-200", "200-500", "500-1000", "1000-5000", "5000+"])})

    while len(companies) < count:
        name = generate_company_name()
        if name.lower() in seen:
            continue
        seen.add(name.lower())
        industry = random.choice(INDUSTRIES)
        location = random.choice(LOCATIONS)
        adj = random.choice(["Leading", "Innovative", "Fast-growing", "Premier", "Award-winning"])
        size = random.choice(["10-50", "50-200", "200-500", "500-1000", "1000-5000", "5000+"])
        companies.append({
            "name": name,
            "industry": industry,
            "description": f"{adj} {industry.lower()} company specializing in innovative solutions.",
            "location": location,
            "size": size,
        })
    return companies[:count]


_global_usernames = set()


def generate_recruiters(companies, count=100):
    recruiters = []
    recruiter_emails = set()

    existing = [
        {"email": "sarah.chen@techcorp.com", "username": "Sarah Chen", "company_name": "TechCorp Global"},
        {"email": "james.wilson@innovista.com", "username": "James Wilson", "company_name": "InnoVista Systems"},
        {"email": "priya.patel@cloudpeak.com", "username": "Priya Patel", "company_name": "CloudPeak Technologies"},
        {"email": "michael.ross@dataforge.com", "username": "Michael Ross", "company_name": "DataForge Analytics"},
        {"email": "emma.torres@appcraft.com", "username": "Emma Torres", "company_name": "Appcraft Studios"},
        {"email": "david.kim@nexgen.com", "username": "David Kim", "company_name": "NexGen Software"},
        {"email": "lisa.anderson@bytebridge.com", "username": "Lisa Anderson", "company_name": "ByteBridge Solutions"},
        {"email": "raj.mehta@quantumstack.com", "username": "Raj Mehta", "company_name": "QuantumStack Inc"},
        {"email": "jennifer.lee@silveroak.com", "username": "Jennifer Lee", "company_name": "SilverOak Financial"},
        {"email": "nathan.wright@pulsemedia.com", "username": "Nathan Wright", "company_name": "Pulse Media Group"},
        {"email": "sophia.nguyen@shopnova.com", "username": "Sophia Nguyen", "company_name": "ShopNova"},
        {"email": "amanda.johnson@medcore.com", "username": "Amanda Johnson", "company_name": "MedCore Health"},
        {"email": "rachel.hernandez@apexmfg.com", "username": "Rachel Hernandez", "company_name": "Apex Manufacturing Corp"},
        {"email": "kevin.thompson@stratedge.com", "username": "Kevin Thompson", "company_name": "StratEdge Consulting"},
        {"email": "melissa.garcia@learnsphere.com", "username": "Melissa Garcia", "company_name": "LearnSphere Education"},
        {"email": "chris.patton@greenleaf.org", "username": "Chris Patton", "company_name": "GreenLeaf Nonprofit"},
        {"email": "alex.reed@nexagen.com", "username": "Alex Reed", "company_name": "NexaGen Gaming"},
        {"email": "maria.santos@crestview.com", "username": "Maria Santos", "company_name": "CrestView Realty"},
        {"email": "tom.fisher@skynet.com", "username": "Tom Fisher", "company_name": "SkyNet Telecom"},
        {"email": "priya.sharma@biosync.com", "username": "Priya Sharma", "company_name": "BioSync Labs"},
        {"email": "ryan.cooper@titan.aero", "username": "Ryan Cooper", "company_name": "Titan Aerospace"},
    ]
    for r in existing:
        recruiters.append({**r, "password": "RecruitPass1!", "company_logo": ""})
        recruiter_emails.add(r["email"])
        _global_usernames.add(r["username"])

    for i, company in enumerate(companies):
        if len(recruiters) >= count:
            break
        name_lower = company["name"].lower()
        domain = name_lower.replace(" ", "").replace(",", "").replace(".", "") + ".com"
        first = random.choice(FIRST_NAMES)
        last = random.choice(LAST_NAMES)
        full_name = f"{first} {last}"
        while full_name in _global_usernames:
            last = random.choice(LAST_NAMES)
            full_name = f"{first} {last}"
        email = make_email(first, last, domain)
        if email in recruiter_emails:
            continue
        recruiter_emails.add(email)
        _global_usernames.add(full_name)
        recruiters.append({
            "email": email,
            "username": full_name,
            "password": f"RecruitPass{len(recruiters) + 1}!",
            "company_name": company["name"],
            "company_logo": "",
        })

    return recruiters[:count]


def get_profession_skills(profession):
    config = PROFESSION_CONFIGS.get(profession, {})
    return sorted(config.get("skills", {}).keys(), key=lambda s: -config["skills"][s])


SAMPLE_PROJECTS = {
    "Frontend Developer": [
        "Built a responsive e-commerce dashboard with React and TypeScript, improving page load times by 40%.",
        "Developed a component library with Storybook documentation used by 5 product teams.",
        "Implemented server-side rendering with Next.js, reducing SEO bounce rate by 25%.",
    ],
    "Backend Developer": [
        "Designed and deployed a microservices architecture handling 10k+ requests per second.",
        "Built a RESTful API gateway with Django REST Framework serving 50k+ daily active users.",
        "Implemented a Celery-based task queue reducing background job processing time by 60%.",
    ],
    "Full Stack Developer": [
        "Architected and built a full-stack SaaS platform serving 500+ business customers.",
        "Developed a real-time collaboration feature using WebSockets and Django Channels.",
        "Built an e-commerce platform with payment integration processing $2M+ in monthly transactions.",
    ],
    "Software Engineer": [
        "Designed a distributed caching layer reducing database load by 70%.",
        "Implemented a CI/CD pipeline reducing deployment time from 2 hours to 15 minutes.",
        "Built a real-time data processing system handling 1M+ events per day.",
    ],
    "DevOps Engineer": [
        "Designed and implemented a Kubernetes-based infrastructure serving 100+ microservices.",
        "Built a comprehensive monitoring stack with Prometheus and Grafana covering 200+ services.",
        "Automated infrastructure provisioning with Terraform across 3 cloud providers.",
    ],
    "Data Scientist": [
        "Developed a churn prediction model achieving 94% accuracy, reducing customer churn by 18%.",
        "Built a recommendation system using collaborative filtering, increasing engagement by 35%.",
        "Designed an A/B testing framework that improved conversion rates by 22%.",
    ],
    "Machine Learning Engineer": [
        "Deployed a real-time NLP model serving 50k+ requests per day with sub-100ms latency.",
        "Built an MLOps pipeline automating model training, evaluation, and deployment cycles.",
        "Developed a computer vision model for defect detection achieving 99.2% precision.",
    ],
    "Data Engineer": [
        "Designed and built a data lake processing 10TB+ of daily data using Spark and Airflow.",
        "Implemented a real-time streaming pipeline with Kafka handling 100k+ events per second.",
        "Built a data warehouse migration from on-premise to Snowflake reducing query times by 80%.",
    ],
    "Data Analyst": [
        "Created executive dashboards in Tableau tracking 50+ KPIs across 5 business units.",
        "Conducted cohort analysis leading to a 15% improvement in customer retention.",
        "Built automated reporting pipelines reducing manual reporting effort by 30 hours per week.",
    ],
    "Graphic Designer": [
        "Designed a complete brand identity system for a fintech startup including logo, typography, and guidelines.",
        "Created visual assets for a marketing campaign that generated 500k+ impressions.",
        "Developed a unified design system used across web, mobile, and print materials.",
    ],
    "UI/UX Designer": [
        "Led user research for a healthcare app with 50+ interviews, resulting in a 40% usability improvement.",
        "Designed end-to-end user flows for a mobile banking app serving 100k+ users.",
        "Created a design system with 200+ components used across 3 product lines.",
    ],
    "Product Manager": [
        "Launched a B2B SaaS product that achieved $5M ARR within 18 months of launch.",
        "Led cross-functional team to deliver a mobile app with 500k+ downloads in first quarter.",
        "Defined product strategy resulting in 3x increase in user engagement metrics.",
    ],
    "Marketing Manager": [
        "Developed a content marketing strategy that increased organic traffic by 200% in 6 months.",
        "Managed $2M+ annual marketing budget across digital channels with 4x ROAS.",
        "Led a rebranding campaign that increased brand awareness by 45% in target markets.",
    ],
    "Accountant": [
        "Managed full-cycle accounting for a $50M revenue company with 200+ employees.",
        "Led a successful SOX compliance audit with zero material weaknesses identified.",
        "Implemented an automated accounts payable system reducing processing time by 60%.",
    ],
    "Human Resources Manager": [
        "Developed a talent acquisition strategy that reduced time-to-hire from 45 to 22 days.",
        "Implemented an employee engagement program that improved retention by 25%.",
        "Designed a performance management system used by 500+ employees across 3 locations.",
    ],
    "Cybersecurity Engineer": [
        "Led penetration testing engagements for 50+ enterprise clients identifying 200+ vulnerabilities.",
        "Implemented a SIEM solution processing 1M+ security events per day with automated incident response.",
        "Designed and implemented a zero-trust architecture for a 5000-employee organization.",
    ],
    "Mobile Developer": [
        "Built a cross-platform mobile app with Flutter that achieved 4.8 star rating with 100k+ downloads.",
        "Developed a React Native application with offline-first architecture for field service teams.",
        "Published 3 iOS apps on the App Store with combined 200k+ active users.",
    ],
}


def generate_resume(profession, level, skills, name, email, phone, location):
    level_num = {"Junior": 0, "Mid": 1, "Senior": 2, "Lead": 3}[level]
    exp_years = [1, 3, 6, 10][level_num]
    edu_map = {
        "Junior": "B.S. in Computer Science, University of California, Berkeley, 2024",
        "Mid": "B.S. in Computer Science, University of Michigan, 2021",
        "Senior": "M.S. in Computer Science, Stanford University, 2018",
        "Lead": "M.S. in Computer Science, Massachusetts Institute of Technology, 2014",
    }
    cert_map = {
        "Junior": None,
        "Mid": random.choice([None, "AWS Certified Cloud Practitioner", "CompTIA A+", "Google Analytics Individual Qualification"]),
        "Senior": random.choice(["AWS Certified Solutions Architect", "Certified Kubernetes Administrator", "Google Professional Data Engineer", "CISSP", "PMP"]),
        "Lead": random.choice(["AWS Certified Solutions Architect Professional", "Google Cloud Architect", "CISSP", "PMP", "TOGAF 9 Certified"]),
    }

    title_alias = random.choice(list(PROFESSION_CONFIGS[profession]["titles"])).title()
    headline = f"{level} {title_alias}"

    summary_templates = {
        "Junior": [
            f"Recent graduate with a strong foundation in {', '.join(skills[:4])}. "
            f"Completed multiple academic and personal projects demonstrating proficiency in {profession.lower()} development. "
            f"Eager to contribute to a dynamic engineering team and grow technical expertise in a professional environment.",
            f"Motivated and detail-oriented {profession.lower()} with hands-on project experience in "
            f"{', '.join(skills[:3])}. Passionate about building efficient and scalable solutions. "
            f"Seeking an opportunity to apply academic knowledge to real-world challenges.",
        ],
        "Mid": [
            f"Results-driven {profession.lower()} with {exp_years} years of experience building production-grade solutions "
            f"using {', '.join(skills[:5])}. Proven track record of delivering high-quality software on schedule. "
            f"Strong problem-solving skills and ability to work effectively in cross-functional teams.",
            f"Experienced {profession.lower()} with {exp_years}+ years developing and maintaining "
            f"applications using {', '.join(skills[:5])}. Committed to writing clean, maintainable code "
            f"and implementing best practices in software development.",
        ],
        "Senior": [
            f"Senior {profession.lower()} with {exp_years} years of experience designing and delivering "
            f"large-scale systems using {', '.join(skills[:6])}. Led multiple cross-functional teams "
            f"to successfully ship products serving millions of users. Expertise in architecture design, "
            f"performance optimization, and mentoring junior engineers.",
            f"Accomplished {profession.lower()} with {exp_years}+ years of experience architecting "
            f"and implementing complex systems. Deep expertise in {', '.join(skills[:6])}. "
            f"Passionate about technical leadership, code quality, and building high-performing teams.",
        ],
        "Lead": [
            f"Visionary {profession.lower()} leader with {exp_years}+ years driving technical strategy "
            f"and execution across multiple product lines. Expertise in {', '.join(skills[:6])} "
            f"with a proven track record of building and scaling engineering organizations. "
            f"Experienced in setting technical direction, mentoring teams, and delivering business impact.",
            f"Seasoned {profession.lower()} leader with {exp_years}+ years of experience architecting "
            f"enterprise-scale solutions. Deep technical expertise in {', '.join(skills[:6])} "
            f"combined with strong leadership and strategic planning abilities.",
        ],
    }

    resume = [
        f"{name}",
        f"{'=' * len(name)}",
        f"{headline}",
        f"{email} | {phone} | {location} | linkedin.com/in/{email.split('@')[0]}",
        "",
        "PROFESSIONAL SUMMARY",
        "-" * 50,
        random.choice(summary_templates[level]),
        "",
        "EXPERIENCE",
        "-" * 50,
    ]

    companies_list = ["TechCorp Global", "InnoVista Systems", "DataForge Analytics", "CloudPeak Technologies",
                       "ByteBridge Solutions", "ShopNova", "NexGen Software", "Pulse Media Group",
                       "Appcraft Studios", "QuantumStack Inc"]
    for i in range(level_num + 1):
        company = random.choice(companies_list)
        years_back = max(1, (level_num - i) * 2 + 1)
        start_year = 2026 - years_back
        end_year = 2026 - (level_num - i) * 2 if i > 0 else "Present"
        titles = [f"{lvl} {random.choice(list(PROFESSION_CONFIGS[profession]['titles'])).title()}" for lvl in
                   reversed(["Junior", "Mid", "Senior", "Lead"][:level_num + 1])]
        role_title = titles[i] if i < len(titles) else title_alias
        resume.append(f"\n{role_title}")
        resume.append(f"{company} | {random.choice(LOCATIONS)}")
        resume.append(f"{start_year} – {end_year}")
        for _ in range(random.randint(2, 3)):
            resume.append(f"  - {random.choice(SAMPLE_PROJECTS.get(profession, ['Delivered high-quality solutions.']))}")
        resume.append("")

    resume.extend([
        "PROJECTS",
        "-" * 50,
    ])
    for _ in range(2):
        proj = random.choice(SAMPLE_PROJECTS.get(profession, ["Built production-grade systems."]))
        techs = ", ".join(random.sample(skills, min(3, len(skills))))
        resume.append(f"  - {proj} (Technologies: {techs})")
    resume.append("")

    resume.extend([
        "SKILLS",
        "-" * 50,
        ", ".join(skills),
        "",
        "EDUCATION",
        "-" * 50,
    ])
    edu = edu_map[level]
    if "Computer Science" in edu or "Engineering" in edu:
        gpa = {1: "3.7 GPA", 3: "3.5 GPA", 6: "3.8 GPA", 10: "3.9 GPA"}
        resume.append(f"{edu} – {gpa[exp_years]}")
    else:
        resume.append(edu)
    resume.append("")

    cert = cert_map[level]
    if cert:
        resume.extend([
            "CERTIFICATIONS",
            "-" * 50,
            f"  - {cert}",
            "",
        ])

    return "\n".join(resume)


def generate_job_seekers_with_profiles(count=200):
    profiles_per_profession = count // len(PROFESSION_NAMES)
    remainder = count % len(PROFESSION_NAMES)
    seekers = []
    profiles = []
    used_emails = set()

    existing_emails = [f"seeker{i}@email.com" for i in range(1, 61)]
    existing_names = [f"User {i}" for i in range(1, 61)]
    for i, (email, name) in enumerate(zip(existing_emails, existing_names)):
        used_emails.add(email)
        _global_usernames.add(name)

    for pi, profession in enumerate(PROFESSION_NAMES):
        profession_count = profiles_per_profession + (1 if pi < remainder else 0)
        skills = get_profession_skills(profession)
        levels_per = profession_count // 4
        level_rem = profession_count % 4
        level_counts = {}
        for li, level in enumerate(CAREER_LEVELS):
            level_counts[level] = levels_per + (1 if li < level_rem else 0)

        for level in CAREER_LEVELS:
            for _ in range(level_counts[level]):
                first = random.choice(FIRST_NAMES)
                last = random.choice(LAST_NAMES)
                name = f"{first} {last}"
                while name in _global_usernames:
                    last = random.choice(LAST_NAMES)
                    name = f"{first} {last}"
                email = f"{first.lower()}.{last.lower()}{random.randint(1, 999)}@email.com"
                while email in used_emails:
                    email = f"{first.lower()}.{last.lower()}{random.randint(1, 999)}@email.com"
                used_emails.add(email)
                _global_usernames.add(name)
                phone = f"+1-555-{random.randint(1000, 9999)}"
                location = random.choice(LOCATIONS)
                bio_texts = {
                    "Junior": f"Recent graduate passionate about {profession.lower()}.",
                    "Mid": f"Experienced {profession.lower()} with a track record of delivering results.",
                    "Senior": f"Senior {profession.lower()} seeking challenging opportunities.",
                    "Lead": f"Technical leader with expertise in {profession.lower()} strategy and execution.",
                }
                resume_text = generate_resume(profession, level, skills, name, email, phone, location)

                seekers.append({
                    "email": email,
                    "username": name,
                    "password": f"SeekerPass{len(seekers) + 1}!",
                })
                bio = bio_texts.get(level, f"Professional {profession.lower()}")
                profiles.append({
                    "email": email,
                    "phone": phone,
                    "skills": skills,
                    "experience_years": {"Junior": 1, "Mid": 3, "Senior": 6, "Lead": 10}[level],
                    "profession": profession,
                    "level": level,
                    "education": {"Junior": "B.S. in Computer Science, University of California, Berkeley, 2024",
                                  "Mid": "B.S. in Computer Science, University of Michigan, 2021",
                                  "Senior": "M.S. in Computer Science, Stanford University, 2018",
                                  "Lead": "M.S. in Computer Science, Massachusetts Institute of Technology, 2014"}[level],
                    "location": location,
                    "bio": bio,
                    "headline": f"{level} {random.choice(list(PROFESSION_CONFIGS[profession]['titles'])).title()}",
                    "linkedin_url": f"https://linkedin.com/in/{email.split('@')[0]}",
                    "github_url": f"https://github.com/{email.split('@')[0]}",
                    "portfolio_url": f"https://{email.split('@')[0]}.dev",
                    "resume_text": resume_text,
                })

    return seekers[:count], profiles[:count]


def generate_jobs(recruiters, count=500):
    jobs_per_recruiter = count // len(recruiters)
    remainder = count % len(recruiters)
    jobs = []

    title_templates_by_profession = {}
    for profession in PROFESSION_NAMES:
        titles = list(PROFESSION_CONFIGS[profession]["titles"])
        levels = ["Junior", "Mid-Level", "Senior", "Lead"]
        templates = []
        for level in levels:
            for t in titles:
                templates.append(f"{level} {t.title()}")
        title_templates_by_profession[profession] = templates

    for ri, recruiter in enumerate(recruiters):
        rc = jobs_per_recruiter + (1 if ri < remainder else 0)
        company = recruiter["company_name"]
        professions_for_recruiter = random.choices(PROFESSION_NAMES, k=rc)
        for profession in professions_for_recruiter:
            title = random.choice(title_templates_by_profession[profession])
            skills = get_profession_skills(profession)
            required_skills = random.sample(skills, min(random.randint(4, 8), len(skills)))
            exp_req = random.choice([1, 2, 3, 5, 7])
            edu_req = random.choice(["High School", "Associate's", "Bachelor's", "Master's", "PhD"])
            salary_ranges = {
                1: "$60k-$85k", 2: "$75k-$100k", 3: "$90k-$130k",
                5: "$120k-$160k", 7: "$150k-$200k",
            }
            work_mode = random.choice(["remote", "hybrid", "onsite"])
            location = random.choice(LOCATIONS)
            prof_config = PROFESSION_CONFIGS.get(profession, {})
            prof_titles = list(prof_config.get("titles", set())) if prof_config else ["Professional"]
            adj = random.choice(["experienced", "talented", "motivated", "skilled", "passionate"])
            desc = f"We are looking for an {adj} {title} to join our team at {company}. " \
                   f"The ideal candidate has experience with {', '.join(required_skills[:4])}. " \
                   f"You will work on {random.choice(SAMPLE_PROJECTS.get(profession, ['challenging projects']))}"

            jobs.append({
                "recruiter_email": recruiter["email"],
                "title": title,
                "company": company,
                "company_logo": "",
                "location": location,
                "work_mode": work_mode,
                "description": desc,
                "required_skills": required_skills,
                "experience_required": exp_req,
                "education_required": edu_req,
                "salary_range": salary_ranges.get(exp_req, "$100k-$150k"),
                "is_active": True,
            })

    return jobs[:count]


def generate_applications(job_seekers, jobs, count=250):
    applications = []
    used_pairs = set()
    statuses = ["submitted", "submitted", "reviewing", "shortlisted", "hired", "rejected"]
    weights = [0.35, 0.20, 0.20, 0.10, 0.10, 0.05]

    for _ in range(count):
        seeker = random.choice(job_seekers)
        job = random.choice(jobs)
        pair_key = (seeker["email"], job["title"], job["company"])
        if pair_key in used_pairs:
            continue
        used_pairs.add(pair_key)
        cover_letter_templates = [
            f"I am writing to express my strong interest in the {job['title']} position at {job['company']}. "
            f"With my background in {', '.join(job['required_skills'][:3])}, I am confident I would be a strong addition to your team.",
            f"After researching {job['company']}, I was impressed by your innovative approach. "
            f"My experience with {', '.join(job['required_skills'][:3])} aligns perfectly with this role's requirements.",
            "",
        ]
        applications.append({
            "applicant_email": seeker["email"],
            "job_company": job["company"],
            "job_title": job["title"],
            "cover_letter": random.choice(cover_letter_templates),
            "status": random.choices(statuses, weights=weights, k=1)[0],
        })

    return applications[:count]


class Command(BaseCommand):
    help = "Generate expanded professional datasets for all 17 professions"

    def handle(self, *args, **options):
        data_dir = settings.DATA_DIR
        output_dir = data_dir / "generated"
        os.makedirs(output_dir, exist_ok=True)

        self.stdout.write("Generating 100 companies...")
        companies = generate_companies(100)
        (output_dir / "companies.json").write_text(
            json.dumps(companies, indent=2), encoding="utf-8"
        )
        self.stdout.write(self.style.SUCCESS(f"  {len(companies)} companies generated"))

        self.stdout.write("Generating 100 recruiters...")
        recruiters = generate_recruiters(companies, 100)
        (output_dir / "recruiters.json").write_text(
            json.dumps(recruiters, indent=2), encoding="utf-8"
        )
        self.stdout.write(self.style.SUCCESS(f"  {len(recruiters)} recruiters generated"))

        self.stdout.write("Generating 200 job seekers with ATS-friendly resumes...")
        seekers, profiles = generate_job_seekers_with_profiles(200)
        (output_dir / "job_seekers.json").write_text(
            json.dumps(seekers, indent=2), encoding="utf-8"
        )
        (output_dir / "user_profiles.json").write_text(
            json.dumps(profiles, indent=2), encoding="utf-8"
        )
        self.stdout.write(self.style.SUCCESS(f"  {len(seekers)} job seekers generated"))
        self.stdout.write(self.style.SUCCESS(f"  {len(profiles)} user profiles generated"))

        self.stdout.write("Generating 500 job postings...")
        jobs = generate_jobs(recruiters, 500)
        (output_dir / "jobs.json").write_text(
            json.dumps(jobs, indent=2), encoding="utf-8"
        )
        self.stdout.write(self.style.SUCCESS(f"  {len(jobs)} jobs generated"))

        self.stdout.write("Generating 250 applications...")
        apps = generate_applications(seekers, jobs, 250)
        (output_dir / "applications.json").write_text(
            json.dumps(apps, indent=2), encoding="utf-8"
        )
        self.stdout.write(self.style.SUCCESS(f"  {len(apps)} applications generated"))

        self.stdout.write(self.style.NOTICE("\nDataset Distribution:"))
        prof_counts = {}
        for p in profiles:
            for prof in PROFESSION_NAMES:
                skills = get_profession_skills(prof)
                if any(s in p.get("skills", []) for s in skills[:3]):
                    prof_counts[prof] = prof_counts.get(prof, 0) + 1
                    break
        for prof in PROFESSION_NAMES:
            self.stdout.write(f"  {prof}: {prof_counts.get(prof, 0)} profiles")
