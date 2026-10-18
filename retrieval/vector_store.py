import json
import logging
import os
import threading
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
import faiss
import numpy as np
from config import settings

logger = logging.getLogger(__name__)


class FAISSVectorStore:
    """
    FAISS-based vector index managing chunk embeddings using Inner Product (cosine similarity).
    Persists index binary and chunk ID mapping safely without unsafe serialization.
    """

    def __init__(
        self,
        dimension: int = settings.EMBEDDING_DIMENSION,
        index_dir: Path = settings.INDICES_DIR
    ):
        self.dimension = dimension
        self.index_dir = index_dir
        self.index_path = self.index_dir / "faiss.index"
        self.id_map_path = self.index_dir / "faiss_id_map.json"
        self._lock = threading.RLock()

        self.index: faiss.IndexFlatIP = faiss.IndexFlatIP(self.dimension)
        self.chunk_ids: List[str] = []
        self.chunk_id_set: Set[str] = set()

        self.load_from_disk()

    @property
    def total_vectors(self) -> int:
        with self._lock:
            return self.index.ntotal

    def add_vectors(self, new_chunk_ids: List[str], vectors: np.ndarray) -> None:
        """
        Incrementally add new chunk embeddings to the index.
        Ignores chunk IDs that are already present.
        """
        with self._lock:
            if len(new_chunk_ids) == 0 or vectors.shape[0] == 0:
                return

            if vectors.shape[1] != self.dimension:
                raise ValueError(
                    f"Vector dimension mismatch: expected {self.dimension}, got {vectors.shape[1]}"
                )

            # Filter out any chunk IDs already indexed
            unique_ids = []
            unique_indices = []
            for i, cid in enumerate(new_chunk_ids):
                if cid not in self.chunk_id_set:
                    unique_ids.append(cid)
                    unique_indices.append(i)

            if not unique_ids:
                return

            filtered_vectors = vectors[unique_indices].astype(np.float32)
            self.index.add(filtered_vectors)
            self.chunk_ids.extend(unique_ids)
            self.chunk_id_set.update(unique_ids)

            self.save_to_disk()
            logger.info(f"Added {len(unique_ids)} vectors to FAISS index. Total: {self.index.ntotal}")

    def search(
        self,
        query_vector: np.ndarray,
        top_k: int = settings.TOP_K_SEMANTIC,
        allowed_chunk_ids: Optional[Set[str]] = None
    ) -> List[Tuple[str, float]]:
        """
        Search the index for the most similar chunks.
        Returns list of (chunk_id, similarity_score).
        """
        with self._lock:
            if self.index.ntotal == 0 or len(self.chunk_ids) == 0:
                return []

            # If filtered, retrieve more candidates to account for filtering
            search_k = min(self.index.ntotal, top_k * 5 if allowed_chunk_ids else top_k)
            distances, indices = self.index.search(query_vector.astype(np.float32), search_k)

            results: List[Tuple[str, float]] = []
            for dist, idx in zip(distances[0], indices[0]):
                if idx < 0 or idx >= len(self.chunk_ids):
                    continue

                cid = self.chunk_ids[idx]
                if allowed_chunk_ids is not None and cid not in allowed_chunk_ids:
                    continue

                results.append((cid, float(dist)))
                if len(results) >= top_k:
                    break

            return results

    def rebuild(self, chunk_ids: List[str], vectors: np.ndarray) -> None:
        """
        Rebuild the FAISS index from scratch with the provided vectors and chunk IDs.
        """
        with self._lock:
            self.index = faiss.IndexFlatIP(self.dimension)
            self.chunk_ids = []
            self.chunk_id_set = set()

            if len(chunk_ids) > 0 and vectors.shape[0] > 0:
                if vectors.shape[1] != self.dimension:
                    raise ValueError(
                        f"Vector dimension mismatch: expected {self.dimension}, got {vectors.shape[1]}"
                    )
                self.index.add(vectors.astype(np.float32))
                self.chunk_ids = list(chunk_ids)
                self.chunk_id_set = set(chunk_ids)

            self.save_to_disk()
            logger.info(f"Rebuilt FAISS index with {self.index.ntotal} vectors.")

    def clear(self) -> None:
        """Clear all vectors from the index."""
        with self._lock:
            self.index = faiss.IndexFlatIP(self.dimension)
            self.chunk_ids = []
            self.chunk_id_set = set()
            self.save_to_disk()

    def save_to_disk(self) -> None:
        """Persist FAISS index binary and ID map safely."""
        with self._lock:
            self.index_dir.mkdir(parents=True, exist_ok=True)
            tmp_index = self.index_path.with_suffix(".tmp")
            tmp_id_map = self.id_map_path.with_suffix(".tmp")

            try:
                faiss.write_index(self.index, str(tmp_index))
                with open(tmp_id_map, "w", encoding="utf-8") as f:
                    json.dump(self.chunk_ids, f)

                if tmp_index.exists():
                    os.replace(tmp_index, self.index_path)
                if tmp_id_map.exists():
                    os.replace(tmp_id_map, self.id_map_path)
            except Exception as e:
                logger.error(f"Failed to persist FAISS vector store: {e}")
                if tmp_index.exists():
                    try:
                        tmp_index.unlink()
                    except OSError:
                        pass
                if tmp_id_map.exists():
                    try:
                        tmp_id_map.unlink()
                    except OSError:
                        pass
                raise

    def load_from_disk(self) -> None:
        """Load and validate persisted FAISS index and chunk ID map."""
        with self._lock:
            if not self.index_path.exists() or not self.id_map_path.exists():
                logger.info("No existing FAISS index found on disk. Initializing empty index.")
                return

            try:
                loaded_index = faiss.read_index(str(self.index_path))
                with open(self.id_map_path, "r", encoding="utf-8") as f:
                    loaded_ids = json.load(f)

                # Validate consistency between binary index and ID mapping
                if loaded_index.ntotal != len(loaded_ids):
                    logger.warning(
                        f"FAISS index consistency error: index contains {loaded_index.ntotal} vectors "
                        f"but ID map contains {len(loaded_ids)} IDs. Reinitializing empty index."
                    )
                    self.index = faiss.IndexFlatIP(self.dimension)
                    self.chunk_ids = []
                    self.chunk_id_set = set()
                    return

                self.index = loaded_index
                self.chunk_ids = loaded_ids
                self.chunk_id_set = set(loaded_ids)
                logger.info(f"Loaded FAISS index with {self.index.ntotal} vectors from {self.index_path}")

            except Exception as e:
                logger.error(f"Failed to load FAISS index from disk: {e}. Starting with empty index.")
                self.index = faiss.IndexFlatIP(self.dimension)
                self.chunk_ids = []
                self.chunk_id_set = set()

