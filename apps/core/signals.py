# file path: apps/core/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.accounts.models import UserProfile
from apps.shared.constants import PROFILE_VECTOR_PREFIX
from apps.shared.embedding_client import get_embedding
from apps.shared.vector_db import get_vector_manager


@receiver(post_save, sender=UserProfile)
def update_profile_embedding(sender, instance: UserProfile, **kwargs):
    text = " ".join([
        instance.user.get_full_name() or instance.user.username,
        " ".join(instance.skills or []),
        instance.resume_text or "",
        instance.education or "",
        str(instance.experience_years or 0),
    ])
    embedding = get_embedding(text)
    get_vector_manager().update_embedding(f"{PROFILE_VECTOR_PREFIX}:{instance.user_id}", embedding)
