# file path: apps/shared/vector_db.py
import pickle
from pathlib import Path

import numpy as np
from django.conf import settings

from .constants import VECTOR_DIMENSION

try:
    import faiss
except Exception:  # pragma: no cover - optional local dependency fallback
    faiss = None


class FAISSManager:
    def __init__(self):
        self.store_dir = Path(settings.VECTOR_STORE_DIR)
        self.index_path = self.store_dir / "faiss_index.bin"
        self.map_path = self.store_dir / "id_map.pkl"
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self.id_map: list[str] = []
        self.index = self._load_index()

    def _load_index(self):
        if faiss and self.index_path.exists():
            self.id_map = self._load_map()
            return faiss.read_index(str(self.index_path))
        if faiss:
            return faiss.IndexFlatIP(VECTOR_DIMENSION)
        self.id_map = self._load_map()
        return self._load_numpy_index()

    def _load_map(self) -> list[str]:
        if self.map_path.exists():
            with self.map_path.open("rb") as handle:
                return pickle.load(handle)
        return []

    def _load_numpy_index(self):
        npy_path = self.store_dir / "fallback_vectors.npy"
        if npy_path.exists():
            return np.load(npy_path).astype("float32")
        return np.empty((0, VECTOR_DIMENSION), dtype="float32")

    def _save(self):
        with self.map_path.open("wb") as handle:
            pickle.dump(self.id_map, handle)
        if faiss:
            faiss.write_index(self.index, str(self.index_path))
        else:
            np.save(self.store_dir / "fallback_vectors.npy", self.index)

    def _normalize(self, embedding: list[float]) -> np.ndarray:
        array = np.array([embedding], dtype="float32")
        norm = np.linalg.norm(array, axis=1, keepdims=True)
        norm[norm == 0] = 1
        return array / norm

    def add_embedding(self, object_id: str, embedding: list[float]):
        if object_id in self.id_map:
            return self.update_embedding(object_id, embedding)
        vector = self._normalize(embedding)
        self.id_map.append(object_id)
        if faiss:
            self.index.add(vector)
        else:
            self.index = np.vstack([self.index, vector])
        self._save()

    def update_embedding(self, object_id: str, embedding: list[float]):
        if object_id not in self.id_map:
            return self.add_embedding(object_id, embedding)
        vectors = self._all_vectors()
        vectors[self.id_map.index(object_id)] = self._normalize(embedding)[0]
        self._rebuild(vectors)

    def _all_vectors(self):
        if not faiss:
            return self.index.copy()
        return np.vstack([self.index.reconstruct(i) for i in range(self.index.ntotal)]).astype("float32")

    def _rebuild(self, vectors):
        if faiss:
            self.index = faiss.IndexFlatIP(VECTOR_DIMENSION)
            if len(vectors):
                self.index.add(vectors)
        else:
            self.index = vectors.astype("float32")
        self._save()

    def search_similar(self, embedding: list[float], top_k: int = 5, prefix: str | None = None):
        if len(self.id_map) == 0:
            return []
        query = self._normalize(embedding)
        if faiss:
            scores, indices = self.index.search(query, min(top_k * 3, len(self.id_map)))
            pairs = [(self.id_map[idx], float(score)) for idx, score in zip(indices[0], scores[0]) if idx >= 0]
        else:
            scores = self.index @ query[0]
            ordered = np.argsort(-scores)[: top_k * 3]
            pairs = [(self.id_map[idx], float(scores[idx])) for idx in ordered]
        if prefix:
            pairs = [pair for pair in pairs if pair[0].startswith(prefix)]
        return pairs[:top_k]


def get_vector_manager() -> FAISSManager:
    return FAISSManager()
