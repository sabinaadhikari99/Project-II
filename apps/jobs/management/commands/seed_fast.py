import hashlib
import json
import logging
import pickle
from pathlib import Path

import numpy as np
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db.models.signals import post_save

from apps.accounts.models import UserProfile
from apps.core.signals import update_profile_embedding
from apps.jobs.models import JobPosting
from apps.shared.constants import (
    ROLE_JOB_SEEKER,
    ROLE_RECRUITER,
    VECTOR_DIMENSION,
    JOB_VECTOR_PREFIX,
    PROFILE_VECTOR_PREFIX,
)
from apps.shared.profession_classifier import classify_job

logger = logging.getLogger(__name__)
User = get_user_model()


def _fast_embedding(text):
    vector = np.zeros(VECTOR_DIMENSION, dtype="float32")
    for token in (text or "").lower().split():
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        idx = int.from_bytes(digest[:4], "little") % VECTOR_DIMENSION
        vector[idx] += 1.0
    norm = np.linalg.norm(vector)
    if norm:
        vector = vector / norm
    return vector.tolist()


def _rebuild_vector_store(job_entries, profile_entries):
    import faiss
    store_dir = Path(settings.VECTOR_STORE_DIR)
    store_dir.mkdir(parents=True, exist_ok=True)

    vectors = []
    id_map = []

    for oid, text in job_entries:
        vec = _fast_embedding(text)
        normalized = np.array([vec], dtype="float32")
        norm = np.linalg.norm(normalized)
        if norm:
            normalized = normalized / norm
        vectors.append(normalized[0])
        id_map.append(oid)

    for oid, text in profile_entries:
        vec = _fast_embedding(text)
        normalized = np.array([vec], dtype="float32")
        norm = np.linalg.norm(normalized)
        if norm:
            normalized = normalized / norm
        vectors.append(normalized[0])
        id_map.append(oid)

    if not vectors:
        return

    vectors_np = np.vstack(vectors).astype("float32")
    index = faiss.IndexFlatIP(VECTOR_DIMENSION)
    index.add(vectors_np)

    faiss.write_index(index, str(store_dir / "faiss_index.bin"))
    with (store_dir / "id_map.pkl").open("wb") as f:
        pickle.dump(id_map, f)

    logger.info("Vector store rebuilt: %d vectors, %d ids", len(vectors), len(id_map))


class Command(BaseCommand):
    help = "Fast seed using batch FAISS rebuild (no per-embedding disk writes)"

    def add_arguments(self, parser):
        parser.add_argument("--skip-users", action="store_true", help="Skip user/profile seeding")
        parser.add_argument("--data-dir", type=str, default="generated", help="Subdirectory under data/")

    def handle(self, *args, **options):
        skip_users = options["skip_users"]
        data_subdir = options["data_dir"]
        data_dir = settings.DATA_DIR / data_subdir

        post_save.disconnect(update_profile_embedding, sender=UserProfile)
        self.stdout.write("Disconnected profile embedding signal.")

        try:
            if not skip_users:
                self._seed_users(data_dir)
            job_entries, profile_entries = self._seed_jobs(data_dir)
            self.stdout.write(f"Building vector store with {len(job_entries)} job + {len(profile_entries)} profile vectors...")
            _rebuild_vector_store(job_entries, profile_entries)
        finally:
            post_save.connect(update_profile_embedding, sender=UserProfile)
            self.stdout.write("Reconnected profile embedding signal.")

        self._verify()
        self.stdout.write(self.style.SUCCESS("Seed fast completed successfully."))

    def _seed_users(self, data_dir):
        self.stdout.write("Seeding users...")

        for fname, role in [("recruiters.json", ROLE_RECRUITER), ("job_seekers.json", ROLE_JOB_SEEKER)]:
            path = data_dir / fname
            if not path.exists():
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            created = 0
            for item in data:
                email = item["email"].strip().lower()
                user, was_created = User.objects.get_or_create(
                    email=email,
                    defaults={"username": item["username"].strip(), "role": role},
                )
                if was_created:
                    user.set_password(item["password"])
                    user.save()
                    if role == ROLE_JOB_SEEKER:
                        UserProfile.objects.create(user=user)
                    created += 1
            self.stdout.write(self.style.SUCCESS(f"  {fname}: {created} created"))

        profiles_path = data_dir / "user_profiles.json"
        if profiles_path.exists():
            data = json.loads(profiles_path.read_text(encoding="utf-8"))
            updated = 0
            for item in data:
                email = item["email"].strip().lower()
                try:
                    user = User.objects.get(email=email)
                except User.DoesNotExist:
                    continue
                profile, _ = UserProfile.objects.get_or_create(user=user)
                changed = False
                for field in ["skills", "resume_text", "experience_years", "education",
                              "location", "bio", "headline", "phone",
                              "linkedin_url", "github_url", "portfolio_url"]:
                    if field in item and str(getattr(profile, field, "")) != str(item[field]):
                        setattr(profile, field, item[field])
                        changed = True
                if changed:
                    profile.save()
                    updated += 1
            self.stdout.write(self.style.SUCCESS(f"  Profiles: {updated} updated"))

    def _seed_jobs(self, data_dir):
        self.stdout.write("Seeding jobs...")
        jobs_path = data_dir / "jobs.json"
        if not jobs_path.exists():
            raise CommandError(f"jobs.json not found at {jobs_path}")

        data = json.loads(jobs_path.read_text(encoding="utf-8"))
        created = 0
        skipped = 0
        job_entries = []
        profile_entries = []

        for item in data:
            email = item.get("recruiter_email", "").strip().lower()
            try:
                recruiter = User.objects.get(email=email)
            except User.DoesNotExist:
                continue
            title = item["title"]
            company = item["company"]
            if JobPosting.objects.filter(recruiter=recruiter, title=title, company=company).exists():
                skipped += 1
                continue

            job_category = classify_job(title, item.get("required_skills", []))
            job = JobPosting.objects.create(
                recruiter=recruiter, title=title, company=company,
                company_logo=item.get("company_logo", ""), location=item.get("location", ""),
                work_mode=item.get("work_mode", "onsite"), description=item["description"],
                required_skills=item.get("required_skills", []),
                experience_required=item.get("experience_required", 0),
                education_required=item.get("education_required", ""),
                salary_range=item.get("salary_range", ""),
                is_active=item.get("is_active", True),
                job_category=job_category,
            )
            job_entries.append((f"{JOB_VECTOR_PREFIX}:{job.id}", job.embedding_text))
            created += 1
            if created % 100 == 0:
                self.stdout.write(f"  ... {created} jobs created")

        profiles_path = data_dir / "user_profiles.json"
        if profiles_path.exists():
            profiles_data = json.loads(profiles_path.read_text(encoding="utf-8"))
            for item in profiles_data:
                email = item["email"].strip().lower()
                try:
                    user = User.objects.get(email=email)
                    profile = user.profile
                except (User.DoesNotExist, UserProfile.DoesNotExist):
                    continue
                parts = [
                    f"Skills: {', '.join(profile.skills or [])}",
                    f"Headline: {profile.headline or ''}",
                    f"Bio: {profile.bio or ''}",
                    f"Experience: {profile.experience_years or 0} years",
                    f"Education: {profile.education or ''}",
                    f"Resume: {profile.resume_text or ''}",
                ]
                profile_entries.append((f"{PROFILE_VECTOR_PREFIX}:{user.id}", " ".join(parts)))

        self.stdout.write(self.style.SUCCESS(f"  Jobs: {created} created, {skipped} skipped"))
        return job_entries, profile_entries

    def _verify(self):
        jobs = JobPosting.objects.count()
        import faiss
        from pathlib import Path
        store_dir = Path(settings.VECTOR_STORE_DIR)
        index_path = store_dir / "faiss_index.bin"
        map_path = store_dir / "id_map.pkl"
        if index_path.exists() and map_path.exists():
            idx = faiss.read_index(str(index_path))
            with map_path.open("rb") as f:
                id_map = pickle.load(f)
            job_count = sum(1 for oid in id_map if oid.startswith("job:"))
            prof_count = sum(1 for oid in id_map if oid.startswith("profile:"))
            self.stdout.write(f"\nVerification:")
            self.stdout.write(f"  Jobs in DB: {jobs}")
            self.stdout.write(f"  Vectors in FAISS: {idx.ntotal}")
            self.stdout.write(f"  Job vectors: {job_count}, Profile vectors: {prof_count}")
        else:
            self.stdout.write(self.style.WARNING("  Vector store files not found!"))
