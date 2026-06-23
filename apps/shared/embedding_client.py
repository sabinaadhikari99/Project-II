# file path: apps/shared/embedding_client.py
import hashlib
import logging

import numpy as np
import requests
from django.conf import settings

from .constants import VECTOR_DIMENSION

logger = logging.getLogger(__name__)


def _fallback_embedding(text: str) -> list[float]:
    """Deterministic local embedding for development when FastAPI is offline."""
    vector = np.zeros(VECTOR_DIMENSION, dtype="float32")
    for token in (text or "").lower().split():
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        idx = int.from_bytes(digest[:4], "little") % VECTOR_DIMENSION
        vector[idx] += 1.0
    norm = np.linalg.norm(vector)
    if norm:
        vector = vector / norm
    return vector.tolist()


def get_embedding(text: str) -> list[float]:
    payload = {"text": text or ""}
    try:
        response = requests.post(f"{settings.FASTAPI_URL}/embed/", json=payload, timeout=8)
        response.raise_for_status()
        embedding = response.json()["embedding"]
        if len(embedding) == VECTOR_DIMENSION:
            return embedding
    except Exception as exc:
        logger.warning("Embedding service unavailable, using fallback embedding: %s", exc)
    return _fallback_embedding(text)
