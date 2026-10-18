import logging
import threading
from typing import List, Optional
import numpy as np
from config import settings

logger = logging.getLogger(__name__)


class EmbeddingManager:
    """
    Thread-safe, cached embedding manager for BAAI/bge-small-en-v1.5 (or configured model).
    Encodes text into L2-normalized embeddings for fast cosine similarity via FAISS IndexFlatIP.
    """

    _instance: Optional["EmbeddingManager"] = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(EmbeddingManager, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, model_name: str = settings.EMBEDDING_MODEL_NAME, device: str = settings.EMBEDDING_DEVICE):
        if getattr(self, "_initialized", False):
            return

        self.model_name = model_name
        self.device = device
        self._model = None
        self._model_lock = threading.Lock()
        self._initialized = True

    def _get_model(self):
        """Load sentence transformer model efficiently using local cache when available."""
        if self._model is None:
            with self._model_lock:
                if self._model is None:
                    import os
                    import torch
                    from sentence_transformers import SentenceTransformer

                    # Optimize PyTorch CPU thread count for fast inference
                    try:
                        cpu_count = os.cpu_count() or 4
                        torch.set_num_threads(min(4, cpu_count))
                    except Exception:
                        pass

                    logger.info(f"Loading embedding model '{self.model_name}' on device '{self.device}'...")
                    try:
                        # Try loading from local HuggingFace cache first for instant sub-second startup
                        self._model = SentenceTransformer(self.model_name, device=self.device, local_files_only=True)
                    except Exception:
                        # Fallback to online fetch if model is not yet in local cache
                        self._model = SentenceTransformer(self.model_name, device=self.device)

                    logger.info("Embedding model loaded successfully.")
        return self._model

    def warmup(self) -> None:
        """Pre-warm the embedding model and PyTorch kernels so user queries execute in <15ms."""
        try:
            model = self._get_model()
            model.encode(["Perfusion technology warmup query"], normalize_embeddings=True, show_progress_bar=False)
            logger.info("Embedding manager pre-warmed successfully.")
        except Exception as e:
            logger.warning(f"Embedding manager warmup note: {e}")

    def embed_texts(self, texts: List[str], batch_size: int = settings.EMBEDDING_BATCH_SIZE) -> np.ndarray:
        """
        Compute L2-normalized dense embeddings for a list of passage texts.
        Returns a float32 numpy array of shape (N, dimension).
        """
        if not texts:
            return np.empty((0, settings.EMBEDDING_DIMENSION), dtype=np.float32)

        # Handle empty or whitespace-only texts safely
        sanitized_texts = [t if (t and t.strip()) else "empty" for t in texts]

        model = self._get_model()
        embeddings = model.encode(
            sanitized_texts,
            batch_size=batch_size,
            show_progress_bar=False,
            normalize_embeddings=True,
            convert_to_numpy=True
        )

        return embeddings.astype(np.float32)

    def embed_query(self, query: str) -> np.ndarray:
        """
        Compute L2-normalized dense embedding for a single query.
        Returns a float32 numpy array of shape (1, dimension).
        """
        if not query or not query.strip():
            query = "empty"

        model = self._get_model()
        # BGE models benefit from instruction prefix if available, but bge-small-en-v1.5 handles direct queries well
        embedding = model.encode(
            [query],
            show_progress_bar=False,
            normalize_embeddings=True,
            convert_to_numpy=True
        )

        return embedding.astype(np.float32)

