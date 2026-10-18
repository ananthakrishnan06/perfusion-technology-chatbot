import re
import threading
from typing import List, Optional, Set, Tuple
from rank_bm25 import BM25Okapi
from config import settings
from schemas.document import ChunkMetadata


class BM25KeywordSearch:
    """
    Keyword retrieval engine using BM25Okapi, optimized for Perfusion Technology
    abbreviations, hyphenated medical compounds, and numerical values.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self.chunk_ids: List[str] = []
        self.corpus_chunks: List[ChunkMetadata] = []
        self.bm25: Optional[BM25Okapi] = None

    @staticmethod
    def tokenize(text: str) -> List[str]:
        """
        Tokenize text preserving medical abbreviations, hyphenated terms, and numbers.
        Example: 'acid-base balance during CPB' -> ['acid-base', 'acid', 'base', 'balance', 'during', 'cpb']
        """
        if not text:
            return []

        # Find words including hyphenated words and alphanumeric sequences
        tokens = re.findall(r"[a-zA-Z0-9]+(?:-[a-zA-Z0-9]+)*", text.lower())

        expanded_tokens: List[str] = []
        for token in tokens:
            expanded_tokens.append(token)
            if "-" in token:
                # Add subcomponents of hyphenated term
                parts = token.split("-")
                expanded_tokens.extend([p for p in parts if p])

        return expanded_tokens

    def index_chunks(self, chunks: List[ChunkMetadata]) -> None:
        """
        Build or rebuild the BM25 index from a list of chunks.
        """
        with self._lock:
            self.corpus_chunks = list(chunks)
            self.chunk_ids = [c.chunk_id for c in chunks]

            if not chunks:
                self.bm25 = None
                return

            tokenized_corpus = [self.tokenize(c.text) for c in chunks]
            # Ensure no completely empty token lists to prevent BM25 divide-by-zero
            tokenized_corpus = [tokens if tokens else ["empty"] for tokens in tokenized_corpus]
            self.bm25 = BM25Okapi(tokenized_corpus)

    QUERY_STOPWORDS = {
        "what", "is", "the", "how", "are", "of", "and", "in", "to", "for", "with",
        "during", "does", "do", "explain", "compare", "between", "which", "by", "from",
        "an", "a", "can", "should", "could", "would", "about", "describe"
    }

    def search(
        self,
        query: str,
        top_k: int = settings.TOP_K_BM25,
        allowed_chunk_ids: Optional[Set[str]] = None
    ) -> List[Tuple[str, float]]:
        """
        Search indexed chunks for keyword relevance.
        Returns list of (chunk_id, score).
        """
        with self._lock:
            if self.bm25 is None or len(self.chunk_ids) == 0:
                return []

            tokens = self.tokenize(query)
            # Filter common question stopwords while preserving clinical tokens
            tokenized_query = [t for t in tokens if t not in self.QUERY_STOPWORDS]
            if not tokenized_query:
                tokenized_query = tokens

            raw_scores = self.bm25.get_scores(tokenized_query)

            # Collect results with score > 0
            scored_candidates: List[Tuple[str, float]] = []
            for idx, score in enumerate(raw_scores):
                if score <= 0:
                    continue

                cid = self.chunk_ids[idx]
                if allowed_chunk_ids is not None and cid not in allowed_chunk_ids:
                    continue

                scored_candidates.append((cid, float(score)))

            # Sort descending by score
            scored_candidates.sort(key=lambda x: x[1], reverse=True)
            return scored_candidates[:top_k]

    def clear(self) -> None:
        with self._lock:
            self.chunk_ids = []
            self.corpus_chunks = []
            self.bm25 = None

