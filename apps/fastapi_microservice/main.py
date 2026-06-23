# file path: apps/fastapi_microservice/main.py
import hashlib
from functools import lru_cache

import numpy as np
from fastapi import FastAPI
from pydantic import BaseModel

VECTOR_DIMENSION = 384
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

app = FastAPI(title="SkillSync AI Embedding Service")


class EmbedRequest(BaseModel):
    text: str


class EmbedResponse(BaseModel):
    embedding: list[float]


@lru_cache(maxsize=1)
def get_model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(MODEL_NAME)


def fallback_embedding(text: str) -> list[float]:
    vector = np.zeros(VECTOR_DIMENSION, dtype="float32")
    for token in (text or "").lower().split():
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        vector[int.from_bytes(digest[:4], "little") % VECTOR_DIMENSION] += 1.0
    norm = np.linalg.norm(vector)
    if norm:
        vector = vector / norm
    return vector.tolist()


@app.post("/embed/", response_model=EmbedResponse)
def embed(payload: EmbedRequest):
    try:
        embedding = get_model().encode(payload.text or "", normalize_embeddings=True)
        return {"embedding": embedding.astype("float32").tolist()}
    except Exception:
        return {"embedding": fallback_embedding(payload.text)}
