import json
from collections import Counter

profiles = json.loads(open("data/generated/user_profiles.json", encoding="utf-8").read())
print(f"Total profiles: {len(profiles)}")
print(f"Keys in first profile: {list(profiles[0].keys())}")
print(f"First profile profession: {profiles[0].get('profession')}")
print(f"First profile level: {profiles[0].get('level')}")

prof_counts = Counter(p.get("profession") for p in profiles)
print(f"Profession distribution: {dict(prof_counts)}")

jobs = json.loads(open("data/generated/jobs.json", encoding="utf-8").read())
print(f"\nTotal jobs: {len(jobs)}")

from apps.shared.profession_classifier import PROFESSION_CONFIGS

job_profs = Counter()
for j in jobs:
    title = j["title"].lower()
    found = False
    for prof, config in PROFESSION_CONFIGS.items():
        for t in config.get("titles", set()):
            if t in title:
                job_profs[prof] += 1
                found = True
                break
        if found:
            break
    if not found:
        job_profs["Other"] += 1
print(f"Job distribution: {dict(job_profs)}")
