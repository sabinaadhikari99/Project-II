import logging
import pickle
from pathlib import Path

import numpy as np
from django.conf import settings

from .constants import VECTOR_DIMENSION

try:
    import faiss
except Exception:
    faiss = None

logger = logging.getLogger(__name__)


class FAISSManager:
    def __init__(self):
        self.store_dir = Path(settings.VECTOR_STORE_DIR)
        self.index_path = self.store_dir / "faiss_index.bin"
        self.map_path = self.store_dir / "id_map.pkl"
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self.id_map: list[str] = []
        self.index = self._load_index()
        self._validate_sync()

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

    def _validate_sync(self):
        vector_count = self.index.ntotal if faiss else len(self.index)
        map_count = len(self.id_map)
        if vector_count != map_count:
            logger.warning(
                "Vector store desync detected: id_map has %d entries but index has %d vectors. "
                "Truncating id_map to match.",
                map_count, vector_count,
            )
            if map_count > vector_count:
                self.id_map = self.id_map[:vector_count]
                self._save()
            elif vector_count > map_count and map_count == 0:
                self._rebuild_from_scratch()

    def _rebuild_from_scratch(self):
        logger.info("Rebuilding vector store from scratch due to desync.")
        if faiss:
            self.index = faiss.IndexFlatIP(VECTOR_DIMENSION)
        else:
            self.index = np.empty((0, VECTOR_DIMENSION), dtype="float32")
        self.id_map = []
        self._save()

    def _vector_count(self):
        return self.index.ntotal if faiss else len(self.index)

    def add_embedding(self, object_id: str, embedding: list[float]):
        if object_id in self.id_map:
            return self.update_embedding(object_id, embedding)
        if len(embedding) != VECTOR_DIMENSION:
            logger.error("add_embedding: expected dimension %d, got %d", VECTOR_DIMENSION, len(embedding))
            return
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
        if len(embedding) != VECTOR_DIMENSION:
            logger.error("update_embedding: expected dimension %d, got %d", VECTOR_DIMENSION, len(embedding))
            return
        self._validate_sync()
        try:
            idx = self.id_map.index(object_id)
            if idx >= self._vector_count():
                logger.warning("update_embedding: index %d out of bounds (count %d), skipping", idx, self._vector_count())
                return
            vectors = self._all_vectors()
            vectors[idx] = self._normalize(embedding)[0]
            self._rebuild(vectors)
        except (IndexError, ValueError) as e:
            logger.error("update_embedding failed for %s: %s", object_id, e)

    def _all_vectors(self):
        if not faiss:
            return self.index.copy()
        n = self.index.ntotal
        if n == 0:
            return np.empty((0, VECTOR_DIMENSION), dtype="float32")
        return np.vstack([self.index.reconstruct(i) for i in range(n)]).astype("float32")

    def _rebuild(self, vectors):
        if faiss:
            self.index = faiss.IndexFlatIP(VECTOR_DIMENSION)
            if len(vectors):
                self.index.add(vectors)
        else:
            self.index = vectors.astype("float32")
        self._save()

    def search_similar(self, embedding: list[float], top_k: int = 5, prefix: str | None = None):
        if len(self.id_map) == 0 or self._vector_count() == 0:
            return []
        if len(embedding) != VECTOR_DIMENSION:
            logger.error("search_similar: expected dimension %d, got %d", VECTOR_DIMENSION, len(embedding))
            return []
        self._validate_sync()
        query = self._normalize(embedding)
        n = self._vector_count()
        try:
            if faiss:
                scores, indices = self.index.search(query, min(top_k * 3, n))
                pairs = []
                for idx, score in zip(indices[0], scores[0]):
                    if idx < 0 or idx >= len(self.id_map):
                        continue
                    pairs.append((self.id_map[idx], float(score)))
            else:
                scores = self.index @ query[0]
                ordered = np.argsort(-scores)[: min(top_k * 3, n)]
                pairs = [(self.id_map[idx], float(scores[idx])) for idx in ordered if idx < len(self.id_map)]
        except Exception as e:
            logger.error("search_similar failed: %s", e, exc_info=True)
            return []
        if prefix:
            pairs = [pair for pair in pairs if pair[0].startswith(prefix)]
        return pairs[:top_k]


def get_vector_manager() -> FAISSManager:
    return FAISSManager()
