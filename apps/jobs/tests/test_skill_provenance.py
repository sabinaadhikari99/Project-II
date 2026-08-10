"""The match score must move in BOTH directions with the CV's keywords.

Two defects made it one-way. `analyze_resume_match` unioned the CV's skills into
`UserProfile.skills` and scored the union, so a deleted skill was still counted;
and the extractor scans the whole document, so deleting a keyword from the
SKILLS section changed nothing while the same word survived in a bullet.

These tests pin the corrected behaviour: removing a required skill lowers the
score, adding one raises it, and a declared skill outscores a merely mentioned
one.
"""

import os

from django.test import TestCase

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from apps.accounts.models import User, UserProfile
from apps.jobs.models import JobPosting
from apps.jobs.services import (
    compute_match_score,
    extract_resume_skills,
    locate_resume_skills,
    skill_confidence_map,
)
from apps.shared.constants import ROLE_RECRUITER
from apps.shared.cv_signals import extract_cv_signals, extract_skills_section

BASE_CV = """Mobile App Developer

Professional Summary
Mobile app developer with 4 years of experience building cross-platform apps.

Skills
{skills}

Experience
Mobile App Developer, TechStartup Inc. 2019 - 2023
- {experience}
- Reduced crash rate by 40% across 3 shipped products

Education
Bachelor of Engineering in Computer Science

Contact
jane@example.com  +977 9800000000
github.com/example
"""


def build_cv(skills, experience="Shipped several production applications"):
    return BASE_CV.format(skills=skills, experience=experience)


class SkillsSectionExtractionTests(TestCase):
    """The SKILLS block has to be found before provenance can mean anything."""

    def test_heading_on_its_own_line(self):
        body = extract_skills_section(build_cv("Flutter, Dart, Firebase"))
        self.assertIn("Flutter", body)
        self.assertIn("Firebase", body)
        self.assertNotIn("Reduced crash rate", body,
                         "the section must stop at the next heading")

    def test_inline_heading(self):
        body = extract_skills_section("Skills: Python, Django, React\n\nEXPERIENCE\nStuff\n")
        self.assertIn("Python", body)
        self.assertNotIn("Stuff", body)

    def test_title_case_rows_are_not_mistaken_for_headings(self):
        """Real skills lists look like 'Docker Advanced' - that is content."""
        body = extract_skills_section(
            "SKILLS\nDocker Advanced\nKubernetes Intermediate\nAnsible Basic\nLANGUAGES\nEnglish\n"
        )
        self.assertIn("Docker", body)
        self.assertIn("Ansible", body)
        self.assertNotIn("English", body)

    def test_missing_section_returns_empty(self):
        self.assertEqual(extract_skills_section("Just some prose about Python."), "")


class SkillProvenanceTests(TestCase):
    """Where a skill appears decides what it is worth."""

    def test_declared_skill_outranks_a_prose_mention(self):
        declared = locate_resume_skills(
            build_cv("Flutter, Dart, Firebase"), ["flutter"])
        mentioned = locate_resume_skills(
            build_cv("Dart, Firebase", experience="Built apps with Flutter"), ["flutter"])
        self.assertEqual(declared["flutter"]["sources"], ["skills_section"])
        self.assertGreater(declared["flutter"]["confidence"],
                           mentioned["flutter"]["confidence"])

    def test_multiword_skills_are_located_by_their_real_spelling(self):
        """Extraction yields normalised keys ('restapis'), never CV wording."""
        located = locate_resume_skills(
            build_cv("Flutter, REST APIs, CI/CD"), ["restapis", "cicd"])
        self.assertEqual(located["restapis"]["sources"], ["skills_section"])
        self.assertEqual(located["cicd"]["sources"], ["skills_section"])

    def test_confidence_map_is_keyed_by_normalised_skill(self):
        located = locate_resume_skills(build_cv("Flutter, Dart"), ["flutter"])
        self.assertEqual(skill_confidence_map(located), {"flutter": 1.0})

    def test_empty_inputs_are_safe(self):
        self.assertEqual(locate_resume_skills("", ["flutter"]), {})
        self.assertEqual(locate_resume_skills("text", []), {})


class BidirectionalScoreTests(TestCase):
    """Adding a required skill must raise the score; removing one must lower it."""

    @classmethod
    def setUpTestData(cls):
        cls.recruiter = User.objects.create_user(
            username="rec-prov", email="rec-prov@example.com",
            password="x", role=ROLE_RECRUITER,
        )
        cls.job = JobPosting.objects.create(
            recruiter=cls.recruiter, title="Flutter Developer", company="Acme",
            description="Mobile role.",
            required_skills=["Flutter", "Dart", "Firebase", "REST APIs"],
            experience_required=0, education_required="",
            job_category="Mobile Developer",
        )
        cls.profile = UserProfile(experience_years=0, education="")

    def _score(self, cv_text):
        """Score a CV exactly as analyze_resume_match now does."""
        skills = extract_resume_skills(cv_text)
        confidence = skill_confidence_map(locate_resume_skills(cv_text, skills))
        return compute_match_score(
            user_skills=skills, user_profession="Mobile Developer",
            profile=self.profile, job=self.job, vector_score=0.5,
            cv_signals=extract_cv_signals(cv_text),
            specialization="Flutter Developer",
            skill_confidence=confidence,
        )

    def test_removing_a_required_skill_lowers_the_score(self):
        full = self._score(build_cv("Flutter, Dart, Firebase, REST APIs"))
        stripped = self._score(build_cv("Firebase, REST APIs"))
        self.assertLess(stripped["final_score"], full["final_score"])
        self.assertLess(stripped["skills_score"], full["skills_score"])
        self.assertGreater(stripped["total_deduction"], full["total_deduction"])

    def test_adding_a_required_skill_raises_the_score(self):
        partial = self._score(build_cv("Flutter, Dart"))
        complete = self._score(build_cv("Flutter, Dart, Firebase, REST APIs"))
        self.assertGreater(complete["final_score"], partial["final_score"])

    def test_declaring_a_skill_beats_only_mentioning_it(self):
        """The Darnell case: same skill, moved out of the SKILLS section."""
        declared = self._score(build_cv("Flutter, Dart, Firebase, REST APIs"))
        mentioned = self._score(build_cv(
            "Flutter, Dart, Firebase",
            experience="Integrated REST APIs across three products",
        ))
        self.assertLessEqual(mentioned["skills_score"], declared["skills_score"])
        self.assertLessEqual(mentioned["final_score"], declared["final_score"])

    def test_a_prose_mention_still_counts_as_matched(self):
        """Discounted, not discredited - it must not become a missing skill."""
        result = self._score(build_cv(
            "Flutter, Dart, Firebase",
            experience="Integrated REST APIs across three products",
        ))
        charged = {d["item"].lower() for d in result["deductions"]}
        self.assertNotIn("rest apis", charged)

    def test_omitting_confidence_preserves_the_previous_behaviour(self):
        """Skill Gap Analysis calls compute_match_score without provenance."""
        cv = build_cv("Flutter, Dart, Firebase, REST APIs")
        skills = extract_resume_skills(cv)
        without = compute_match_score(
            user_skills=skills, user_profession="Mobile Developer",
            profile=self.profile, job=self.job, vector_score=0.5,
            cv_signals=extract_cv_signals(cv),
        )
        self.assertEqual(without["skills_score"], 100,
                         "no confidence map means every match counts fully")
