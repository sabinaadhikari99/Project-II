# file path: apps/state/signals.py
"""Cache invalidation for persistent state.

Writes made outside the service layer (admin edits, cascading deletes, data
migrations) must not leave a stale cached copy behind, so invalidation is
attached to the models themselves rather than only to the services.
"""

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import AnalysisSession, QuizSession, UIState
from .services import AnalysisSessionService, QuizSessionService, UIStateService


@receiver([post_save, post_delete], sender=AnalysisSession)
def _invalidate_analysis(sender, instance, **kwargs):
    AnalysisSessionService.invalidate(instance.user_id)


@receiver([post_save, post_delete], sender=UIState)
def _invalidate_ui_state(sender, instance, **kwargs):
    UIStateService.invalidate(instance.user_id)


@receiver([post_save, post_delete], sender=QuizSession)
def _invalidate_quiz(sender, instance, **kwargs):
    QuizSessionService.invalidate(instance.user_id)
