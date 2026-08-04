# file path: apps/chatbot/role_profiles.py
"""Role-specific interview material.

The AI writes the question bank whenever Gemini is reachable. This module is
what the feature falls back to when it is not - and the point of it is that the
fallback is still *role-specific*. A Flutter candidate is asked about the widget
lifecycle, a Django candidate about the ORM, a designer about typography. The
old behaviour, one static list of five questions for every role on the platform,
is exactly what this replaces.

Each profile also feeds the AI path: `topics` and `system_design_applicable`
are passed into the prompt so the model knows what the role is actually about
and whether a system-design round makes sense for it.

Adding a role means appending one `RoleProfile` - no other file changes.
"""

import re
from dataclasses import dataclass, field

# Question categories. `SYSTEM_DESIGN` is only ever used for roles whose profile
# declares it applicable - a graphic designer does not get a system design round.
TECHNICAL = "technical"
BEHAVIORAL = "behavioral"
HR = "hr"
SCENARIO = "scenario"
PROBLEM_SOLVING = "problem_solving"
SYSTEM_DESIGN = "system_design"

CATEGORIES = (TECHNICAL, BEHAVIORAL, HR, SCENARIO, PROBLEM_SOLVING, SYSTEM_DESIGN)

CATEGORY_LABELS = {
    TECHNICAL: "Technical",
    BEHAVIORAL: "Behavioral",
    HR: "HR",
    SCENARIO: "Scenario-Based",
    PROBLEM_SOLVING: "Problem Solving",
    SYSTEM_DESIGN: "System Design",
}

BEGINNER = "beginner"
INTERMEDIATE = "intermediate"
ADVANCED = "advanced"
LEVELS = (BEGINNER, INTERMEDIATE, ADVANCED)

LEVEL_LABELS = {
    BEGINNER: "Beginner",
    INTERMEDIATE: "Intermediate",
    ADVANCED: "Advanced",
}


@dataclass(frozen=True)
class RoleProfile:
    key: str
    label: str
    #: Matched against the target role and the user's analysed specialization.
    keywords: tuple
    #: Handed to the AI prompt so generated questions stay on-subject.
    topics: tuple
    #: Technical questions per difficulty level.
    technical: dict
    scenario: tuple = field(default_factory=tuple)
    problem_solving: tuple = field(default_factory=tuple)
    #: Empty for roles where a system design round makes no sense.
    system_design: tuple = field(default_factory=tuple)
    certifications: tuple = field(default_factory=tuple)

    @property
    def system_design_applicable(self):
        return bool(self.system_design)


PROFILES = (
    RoleProfile(
        key="flutter",
        label="Flutter / Mobile Developer",
        keywords=("flutter", "dart", "mobile", "android", "ios", "react native", "kotlin", "swift"),
        topics=("widget lifecycle", "state management", "platform channels", "app performance",
                "offline storage", "release builds", "testing"),
        technical={
            BEGINNER: (
                "Explain the Flutter widget lifecycle.",
                "What is the difference between a StatefulWidget and a StatelessWidget?",
                "What is the widget tree, and what causes Flutter to rebuild part of it?",
                "How do you handle navigation and routing between screens?",
            ),
            INTERMEDIATE: (
                "How would you optimize the performance of a Flutter list rendering thousands of items?",
                "Compare setState with a state management solution such as Provider, Bloc or Riverpod.",
                "Explain Flutter's build, layout and paint phases.",
                "How do you call native platform code from Flutter, and when do you need to?",
            ),
            ADVANCED: (
                "How would you diagnose and fix jank in a Flutter animation?",
                "Explain the relationship between the Flutter engine, the framework and platform channels.",
                "How would you architect an offline-first Flutter app that syncs when connectivity returns?",
                "How do you structure widget, unit and integration tests for a large Flutter codebase?",
            ),
        },
        scenario=(
            "Your app's cold start time regressed by 800ms after a release. Walk me through your investigation.",
            "A crash only reproduces on low-end Android devices. How do you track it down?",
        ),
        problem_solving=(
            "A screen rebuilds on every keystroke and the UI stutters. How do you find and fix the cause?",
        ),
        system_design=(
            "Design the offline caching and sync layer for a Flutter e-commerce app.",
        ),
        certifications=("Google Associate Android Developer", "Flutter Development Bootcamp certification"),
    ),
    RoleProfile(
        key="django",
        label="Python / Django Developer",
        keywords=("django", "python", "drf", "backend", "flask", "fastapi", "rest api", "server"),
        topics=("Django ORM", "REST API design", "authentication", "signals", "query optimisation",
                "caching", "testing", "deployment"),
        technical={
            BEGINNER: (
                "Explain the Django ORM and when a QuerySet is actually evaluated.",
                "What is the difference between a Django project and a Django app?",
                "How does Django's MTV pattern map onto MVC?",
                "How do migrations work, and what happens when two branches both add one?",
            ),
            INTERMEDIATE: (
                "How does JWT authentication work, and how would you implement it in Django REST Framework?",
                "Explain Django signals, and describe a case where you would deliberately avoid them.",
                "How do you design REST API resource URLs and choose the right status codes?",
                "Explain select_related versus prefetch_related and when each is the wrong choice.",
            ),
            ADVANCED: (
                "How would you find and fix an N+1 query problem in a Django view?",
                "How would you scale a Django application to handle ten times its current traffic?",
                "How do you keep a long-running task off the request/response cycle, and what breaks if you don't?",
                "Explain how you would add caching to a read-heavy endpoint without serving stale data.",
            ),
        },
        scenario=(
            "An endpoint that used to respond in 200ms now takes four seconds under load. How do you find the cause?",
            "A deployment introduced a data-corrupting migration. What do you do first?",
        ),
        problem_solving=(
            "Users report intermittent 500s that you cannot reproduce locally. How do you approach it?",
        ),
        system_design=(
            "Design a multi-tenant SaaS backend in Django, covering data isolation and billing.",
        ),
        certifications=("AWS Certified Developer – Associate", "Python Institute PCPP"),
    ),
    RoleProfile(
        key="data_analyst",
        label="Data Analyst",
        keywords=("data analyst", "analyst", "power bi", "tableau", "sql", "excel",
                  "business intelligence", "reporting", "dashboard"),
        topics=("SQL", "data cleaning", "dashboard design", "Power BI", "statistics",
                "stakeholder reporting", "KPI definition"),
        technical={
            BEGINNER: (
                "Explain the different types of SQL joins and when you would use each.",
                "How do you handle missing and duplicate values when cleaning a dataset?",
                "What is the difference between a fact table and a dimension table?",
                "Which chart type would you use for a trend over time, and why not a pie chart?",
            ),
            INTERMEDIATE: (
                "How would you design a Power BI dashboard for an executive audience?",
                "Explain SQL window functions with a concrete example.",
                "How do you decide which metrics belong on a dashboard and which are noise?",
                "Explain the difference between correlation and causation using an example from your work.",
            ),
            ADVANCED: (
                "How would you investigate a sudden 30% drop in a key business metric?",
                "How do you build a pipeline that keeps a dashboard refreshed hourly and alerts on failure?",
                "How do you validate that a dataset is trustworthy before you report on it?",
                "How would you design an A/B test and decide when the result is conclusive?",
            ),
        },
        scenario=(
            "A stakeholder insists a number in your dashboard is wrong. How do you resolve the disagreement?",
            "You are handed an undocumented dataset and asked for insights by tomorrow. What do you do?",
        ),
        problem_solving=(
            "Two reports built by different teams disagree on revenue. How do you reconcile them?",
        ),
        system_design=(
            "Design the data model for a sales analytics warehouse.",
        ),
        certifications=("Microsoft Certified: Power BI Data Analyst Associate", "Google Data Analytics Certificate"),
    ),
    RoleProfile(
        key="graphic_designer",
        label="Graphic Designer",
        keywords=("graphic design", "designer", "visual design", "branding", "illustrator",
                  "photoshop", "figma", "typography", "creative"),
        topics=("design process", "typography", "branding", "colour theory", "Figma workflow",
                "design systems", "print and digital output"),
        technical={
            BEGINNER: (
                "Walk me through your design process from brief to final delivery.",
                "Which typography principles do you apply when setting a layout, and why?",
                "How do you choose a colour palette for a brand?",
                "What is the difference between raster and vector, and when does it matter?",
            ),
            INTERMEDIATE: (
                "How do you structure a Figma file so that a team can work in it without breaking things?",
                "How do you keep a brand identity consistent across print, web and social?",
                "How do you check a design for accessibility, particularly colour contrast?",
                "How do you present and defend design work to a non-design stakeholder?",
            ),
            ADVANCED: (
                "How would you rebrand a product without losing existing brand recognition?",
                "How do you build and maintain a design system that other designers actually use?",
                "How do you measure whether a design succeeded?",
                "How do you art-direct and give useful critique to a junior designer?",
            ),
        },
        scenario=(
            "A client rejects three rounds of concepts without clear feedback. How do you get the project moving?",
            "You are asked to ship a campaign in two days with no brief. What do you do first?",
        ),
        problem_solving=(
            "A layout that works on desktop falls apart on mobile. How do you rework it?",
        ),
        # No system design round - it does not apply to this role.
        certifications=("Adobe Certified Professional", "Google UX Design Certificate"),
    ),
    RoleProfile(
        key="frontend",
        label="Frontend Developer",
        keywords=("frontend", "front-end", "react", "vue", "angular", "javascript",
                  "typescript", "next.js", "web developer", "ui developer"),
        topics=("component design", "state management", "rendering performance", "accessibility",
                "bundling", "browser APIs", "testing"),
        technical={
            BEGINNER: (
                "Explain the difference between props and state in a component framework.",
                "What is the virtual DOM and what problem does it solve?",
                "Explain event bubbling and how you would stop it.",
                "What is the difference between let, const and var?",
            ),
            INTERMEDIATE: (
                "Explain the rules of hooks and why they exist.",
                "How do you prevent unnecessary re-renders in a large component tree?",
                "How do you make a custom interactive component keyboard accessible?",
                "Explain the difference between server-side rendering, static generation and client rendering.",
            ),
            ADVANCED: (
                "How would you diagnose a slow initial page load, from request to first interaction?",
                "Explain hydration and the ways it fails in server-rendered apps.",
                "How would you structure state in an application with dozens of screens?",
                "How do you keep a JavaScript bundle small as a codebase grows?",
            ),
        },
        scenario=(
            "A page scores badly on Core Web Vitals in production but looks fine locally. What do you check?",
            "A form silently loses user input on slow connections. How do you debug it?",
        ),
        problem_solving=(
            "A memory leak makes a single-page app slow down the longer it is open. How do you find it?",
        ),
        system_design=(
            "Design the frontend architecture for a dashboard with real-time updates.",
        ),
        certifications=("Meta Front-End Developer Certificate", "JavaScript Algorithms and Data Structures (freeCodeCamp)"),
    ),
    RoleProfile(
        key="data_science",
        label="Data Scientist / ML Engineer",
        keywords=("data scien", "machine learning", "ml engineer", "deep learning", "ai engineer",
                  "nlp", "computer vision", "pytorch", "tensorflow"),
        topics=("model selection", "feature engineering", "evaluation metrics", "overfitting",
                "deployment", "data drift", "experiment design"),
        technical={
            BEGINNER: (
                "Explain the bias-variance tradeoff.",
                "What is the difference between supervised and unsupervised learning?",
                "Why do you split data into train, validation and test sets?",
                "Explain precision and recall, and when you would favour one over the other.",
            ),
            INTERMEDIATE: (
                "How do you handle a severely imbalanced classification dataset?",
                "Explain cross-validation and when a simple split is not enough.",
                "How do you decide which features to engineer, and how do you tell if they helped?",
                "How do you choose an evaluation metric that matches the business problem?",
            ),
            ADVANCED: (
                "How would you detect and respond to data drift in a production model?",
                "How do you decide a model is ready to ship, and what do you monitor afterwards?",
                "Explain how you would debug a model that performs well offline but poorly in production.",
                "How would you design an experiment to prove your model creates business value?",
            ),
        },
        scenario=(
            "Your model's accuracy drops sharply three months after launch. What is your process?",
            "A stakeholder asks you to explain a prediction the model made about one customer. How do you answer?",
        ),
        problem_solving=(
            "You have a promising model but the training data may be leaking the target. How do you check?",
        ),
        system_design=(
            "Design an end-to-end ML pipeline from raw data to a served, monitored model.",
        ),
        certifications=("AWS Certified Machine Learning – Specialty", "TensorFlow Developer Certificate"),
    ),
    RoleProfile(
        key="devops",
        label="DevOps / Cloud Engineer",
        keywords=("devops", "sre", "cloud", "kubernetes", "docker", "aws", "azure", "gcp",
                  "infrastructure", "platform engineer", "ci/cd"),
        topics=("containers", "CI/CD", "infrastructure as code", "observability",
                "incident response", "scaling", "cost control"),
        technical={
            BEGINNER: (
                "Explain the difference between a container and a virtual machine.",
                "What is infrastructure as code, and what does it buy you?",
                "Walk me through what happens when a CI pipeline runs on a pull request.",
                "What is the difference between a container image and a running container?",
            ),
            INTERMEDIATE: (
                "Explain a blue-green deployment and how it differs from a canary release.",
                "How would you design a CI/CD pipeline for a service that deploys several times a day?",
                "How do you debug a pod stuck in CrashLoopBackOff?",
                "What do you monitor to know a service is healthy, beyond CPU and memory?",
            ),
            ADVANCED: (
                "How would you design infrastructure to survive the loss of an availability zone?",
                "How do you manage secrets across environments without leaking them into logs or images?",
                "Walk me through how you would run and then write up a production incident.",
                "How would you reduce a cloud bill by 30% without degrading reliability?",
            ),
        },
        scenario=(
            "Deploys succeed but error rates spike ten minutes later, every time. How do you investigate?",
            "You are paged at 3am for a service you have never worked on. What are your first five minutes?",
        ),
        problem_solving=(
            "A nightly job intermittently fails with no useful logs. How do you make it debuggable?",
        ),
        system_design=(
            "Design a deployment and rollback strategy for a high-traffic API.",
        ),
        certifications=("AWS Certified Solutions Architect – Associate", "Certified Kubernetes Administrator (CKA)"),
    ),
    RoleProfile(
        key="qa",
        label="QA / Test Engineer",
        keywords=("qa", "quality assurance", "test engineer", "sdet", "automation test", "tester"),
        topics=("test strategy", "automation", "regression", "API testing", "bug reporting"),
        technical={
            BEGINNER: (
                "What is the difference between smoke, sanity and regression testing?",
                "What makes a bug report useful to a developer?",
                "Explain the test pyramid.",
                "What is the difference between verification and validation?",
            ),
            INTERMEDIATE: (
                "How do you decide which tests to automate and which to leave manual?",
                "How would you test an API with no documentation?",
                "How do you write test cases from an ambiguous requirement?",
                "How do you deal with a flaky automated test?",
            ),
            ADVANCED: (
                "How would you build a test strategy for a product releasing weekly?",
                "How do you measure whether your test suite is actually effective?",
                "How would you test a feature that depends on a third-party service you cannot control?",
                "How do you performance-test a system and decide what 'good' looks like?",
            ),
        },
        scenario=(
            "A critical bug reached production despite passing tests. How do you respond?",
            "Developers say your bug reports are not actionable. How do you fix that?",
        ),
        problem_solving=(
            "A regression suite takes four hours and blocks releases. How do you cut it down safely?",
        ),
        certifications=("ISTQB Certified Tester Foundation Level",),
    ),
    RoleProfile(
        key="ui_ux",
        label="UI/UX Designer",
        # Multi-word keywords are deliberate: "UX Designer" would otherwise be
        # captured by the graphic designer profile's shorter "designer".
        keywords=("ux designer", "ui designer", "ux design", "ui/ux", "product designer",
                  "user experience", "interaction design", "usability", "wireframe",
                  "prototyp", "ux"),
        topics=("user research", "information architecture", "prototyping", "usability testing",
                "design systems", "accessibility"),
        technical={
            BEGINNER: (
                "What is the difference between UX and UI?",
                "Walk me through how you run a usability test.",
                "What is information architecture and how do you decide on it?",
                "How do you go from a wireframe to a high-fidelity prototype?",
            ),
            INTERMEDIATE: (
                "How do you turn research findings into concrete design decisions?",
                "How do you design for accessibility beyond colour contrast?",
                "How do you decide between following a convention and inventing something new?",
                "How do you work with engineers so designs survive implementation?",
            ),
            ADVANCED: (
                "How would you build and govern a design system across several product teams?",
                "How do you measure whether a redesign improved the user experience?",
                "How do you handle a case where user research contradicts what leadership wants?",
                "How do you prioritise UX debt against new feature work?",
            ),
        },
        scenario=(
            "Analytics show users abandoning a flow at step three. How do you diagnose and fix it?",
            "You have one week and no budget for research. How do you de-risk a major design decision?",
        ),
        problem_solving=(
            "A feature tests well with users but fails after launch. How do you find out why?",
        ),
        certifications=("Google UX Design Certificate", "Nielsen Norman Group UX Certification"),
    ),
)

#: Used when a target role matches nothing above. Still role-named, so the
#: questions read as though they were written for the role the user typed.
GENERIC = RoleProfile(
    key="generic",
    label="General",
    keywords=(),
    topics=("core responsibilities", "tools of the trade", "collaboration", "quality of work"),
    technical={
        BEGINNER: (
            "Which tools and technologies do you use day to day as a {role}, and why those?",
            "Walk me through the core responsibilities of a {role} as you understand them.",
            "What does a good piece of work look like in this role?",
        ),
        INTERMEDIATE: (
            "Walk me through the most technically demanding piece of work you have delivered as a {role}.",
            "How do you keep your skills current in this field?",
            "How do you decide between doing something quickly and doing it thoroughly?",
        ),
        ADVANCED: (
            "How would you improve the way a {role} team works, if you joined tomorrow?",
            "What is the hardest trade-off you have had to make in this role, and how did you decide?",
            "How would you mentor someone junior into this role?",
        ),
    },
    scenario=(
        "You are given a deadline you believe is unrealistic. What do you do?",
        "A project you own is failing and you spotted it first. How do you handle it?",
    ),
    problem_solving=(
        "Describe how you break down a problem you have never seen before.",
    ),
)

#: Behavioral and HR questions apply to every role, so they live here rather
#: than being duplicated into each profile. `{role}` is filled in per session.
BEHAVIORAL_QUESTIONS = {
    BEGINNER: (
        "Tell me about a project you are proud of and what your specific contribution was.",
        "Describe a time you had to learn something new quickly.",
        "Tell me about a time you received difficult feedback. What did you do with it?",
    ),
    INTERMEDIATE: (
        "Describe a time you disagreed with a teammate about a technical decision. How was it resolved?",
        "Tell me about a deadline you missed. What happened, and what changed afterwards?",
        "Describe a time you resolved ambiguity with data rather than opinion.",
    ),
    ADVANCED: (
        "Tell me about a time you influenced a decision without having authority over it.",
        "Describe the largest failure you owned, and what you changed as a result.",
        "Tell me about a time you had to deliver bad news to a stakeholder.",
    ),
}

HR_QUESTIONS = {
    BEGINNER: (
        "Tell me about yourself and why you are applying for this {role} role.",
        "What attracted you to this position?",
        "What are your greatest strengths as a {role}?",
    ),
    INTERMEDIATE: (
        "Why are you leaving your current role?",
        "Where do you see your career as a {role} in three years?",
        "What kind of team and management style do you work best with?",
    ),
    ADVANCED: (
        "What are your salary expectations, and how did you arrive at that number?",
        "What would make you turn down an offer from us?",
        "What is the one thing you would want your first 90 days here to achieve?",
    ),
}


def _normalise(text):
    return re.sub(r"[^a-z0-9+#/ ]+", " ", (text or "").lower())


def match_profile(*texts):
    """Pick the profile whose keywords best match the role (and CV specialization).

    The target role is what the user typed, so it is matched first; the analysed
    specialization is a fallback for when the role box is left empty.
    """
    haystack = " ".join(_normalise(t) for t in texts if t)
    if not haystack.strip():
        return GENERIC

    best, best_score = GENERIC, 0
    for profile in PROFILES:
        # Longer keyword matches are stronger evidence than short ones, so a
        # role of "Data Analyst" is not out-voted by an incidental "sql".
        score = sum(len(kw) for kw in profile.keywords if kw in haystack)
        if score > best_score:
            best, best_score = profile, score
    return best


def profile_for_key(key):
    for profile in PROFILES:
        if profile.key == key:
            return profile
    return GENERIC


def available_categories(profile):
    """Categories worth offering for this role - system design only where it fits."""
    return tuple(
        category for category in CATEGORIES
        if category != SYSTEM_DESIGN or profile.system_design_applicable
    )
