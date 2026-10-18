import logging
import threading
from typing import List
from config import settings
from schemas.retrieval import RetrievedChunk

logger = logging.getLogger(__name__)


class CrossEncoderReranker:
    """
    Optional Cross-Encoder reranker.
    Disabled by default to avoid heavy resource usage.
    Can be enabled via RERANKING_ENABLED=true in .env or settings.
    """

    def __init__(
        self,
        enabled: bool = settings.RERANKING_ENABLED,
        model_name: str = settings.RERANKER_MODEL_NAME
    ):
        self.enabled = enabled
        self.model_name = model_name
        self._model = None
        self._lock = threading.Lock()

    def _get_model(self):
        if not self.enabled:
            return None
        if self._model is None:
            with self._lock:
                if self._model is None:
                    from sentence_transformers import CrossEncoder
                    logger.info(f"Loading cross-encoder reranker '{self.model_name}' on CPU...")
                    self._model = CrossEncoder(self.model_name, device="cpu")
                    logger.info("Cross-encoder reranker loaded.")
        return self._model

    def rerank(
        self,
        query: str,
        candidates: List[RetrievedChunk],
        top_k: int = settings.TOP_K_FINAL
    ) -> List[RetrievedChunk]:
        """
        Rerank retrieved chunks using cross-encoder scores if enabled; otherwise return top_k candidates.
        """
        if not candidates:
            return []

        if not self.enabled:
            return candidates[:top_k]

        try:
            model = self._get_model()
            if model is None:
                return candidates[:top_k]

            pairs = [[query, c.text] for c in candidates]
            scores = model.predict(pairs)

            # Pair candidates with their cross-encoder score
            reranked = []
            for candidate, score in zip(candidates, scores):
                # Update candidate score with cross-encoder score
                updated = candidate.model_copy(update={
                    "score": float(score),
                    "retrieval_method": "hybrid_reranked"
                })
                reranked.append(updated)

            reranked.sort(key=lambda x: x.score, reverse=True)
            return reranked[:top_k]

        except Exception as e:
            logger.warning(f"Reranking failed: {e}. Falling back to default ranking.")
            return candidates[:top_k]

