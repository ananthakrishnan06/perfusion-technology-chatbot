import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Set, Tuple
from config import settings
from schemas.retrieval import RetrievedChunk
from storage.metadata_store import MetadataStore
from retrieval.embeddings import EmbeddingManager
from retrieval.vector_store import FAISSVectorStore
from retrieval.keyword_search import BM25KeywordSearch
from retrieval.reranker import CrossEncoderReranker

logger = logging.getLogger(__name__)


class HybridRetriever:
    """
    Combines dense FAISS semantic search and sparse BM25 keyword search using
    Reciprocal Rank Fusion (RRF), followed by optional Cross-Encoder reranking.
    """

    def __init__(
        self,
        metadata_store: MetadataStore,
        vector_store: FAISSVectorStore,
        keyword_search: BM25KeywordSearch,
        embedding_manager: Optional[EmbeddingManager] = None,
        reranker: Optional[CrossEncoderReranker] = None,
        rrf_k: int = settings.RRF_K,
        dense_weight: float = 1.5,
        bm25_weight: float = 1.0
    ):
        self.metadata_store = metadata_store
        self.vector_store = vector_store
        self.keyword_search = keyword_search
        self.embedding_manager = embedding_manager or EmbeddingManager()
        self.reranker = reranker or CrossEncoderReranker()
        self.rrf_k = rrf_k
        self.dense_weight = dense_weight
        self.bm25_weight = bm25_weight

    def retrieve(
        self,
        query: str,
        document_ids: Optional[List[str]] = None,
        top_k: int = settings.TOP_K_FINAL,
        top_k_semantic: int = settings.TOP_K_SEMANTIC,
        top_k_bm25: int = settings.TOP_K_BM25
    ) -> List[RetrievedChunk]:
        """
        Perform hybrid retrieval combining FAISS and BM25 via Reciprocal Rank Fusion (RRF).
        
        Args:
            query: The search question or topic.
            document_ids: Optional filter to restrict search to specific documents.
            top_k: Final number of chunks to return.
            top_k_semantic: Candidate count from FAISS.
            top_k_bm25: Candidate count from BM25.
            
        Returns:
            List of RetrievedChunk sorted by relevance score.
        """
        # Determine allowed chunk IDs if document filter is provided
        allowed_chunk_ids: Optional[Set[str]] = None
        if document_ids:
            allowed_chunks = self.metadata_store.get_all_chunks(document_ids=document_ids)
            allowed_chunk_ids = {c.chunk_id for c in allowed_chunks}
            if not allowed_chunk_ids:
                # Filter matched no chunks
                return []

        # Dynamically scale candidate pools for deep exam queries to ensure maximum precision & recall
        actual_semantic_k = max(top_k_semantic, top_k * 2)
        actual_bm25_k = max(top_k_bm25, top_k * 2)

        # 1 & 2. Concurrently execute Dense Semantic Search (FAISS) and Sparse Keyword Search (BM25)
        def _execute_semantic() -> List[Tuple[str, float]]:
            try:
                query_vector = self.embedding_manager.embed_query(query)
                return self.vector_store.search(
                    query_vector=query_vector,
                    top_k=actual_semantic_k,
                    allowed_chunk_ids=allowed_chunk_ids
                )
            except Exception as e:
                logger.error(f"Semantic search failed: {e}")
                return []

        def _execute_bm25() -> List[Tuple[str, float]]:
            try:
                return self.keyword_search.search(
                    query=query,
                    top_k=actual_bm25_k,
                    allowed_chunk_ids=allowed_chunk_ids
                )
            except Exception as e:
                logger.error(f"BM25 search failed: {e}")
                return []

        with ThreadPoolExecutor(max_workers=2) as executor:
            future_sem = executor.submit(_execute_semantic)
            future_bm = executor.submit(_execute_bm25)
            semantic_results = future_sem.result()
            bm25_results = future_bm.result()

        # If both engines yielded nothing, return empty
        if not semantic_results and not bm25_results:
            return []

        # 3. Reciprocal Rank Fusion (RRF)
        # Record ranks (1-based)
        semantic_ranks: Dict[str, int] = {cid: idx + 1 for idx, (cid, _) in enumerate(semantic_results)}
        bm25_ranks: Dict[str, int] = {cid: idx + 1 for idx, (cid, _) in enumerate(bm25_results)}

        all_candidate_ids = set(semantic_ranks.keys()).union(set(bm25_ranks.keys()))
        rrf_scores: Dict[str, float] = {}

        for cid in all_candidate_ids:
            score = 0.0
            if cid in semantic_ranks:
                score += self.dense_weight / (self.rrf_k + semantic_ranks[cid])
            if cid in bm25_ranks:
                score += self.bm25_weight / (self.rrf_k + bm25_ranks[cid])
            rrf_scores[cid] = score

        # Sort candidate IDs by RRF score descending
        sorted_candidates = sorted(all_candidate_ids, key=lambda cid: rrf_scores[cid], reverse=True)

        # 4. Construct RetrievedChunk objects, filtering out sub-threshold candidates
        retrieved_list: List[RetrievedChunk] = []
        for cid in sorted_candidates:
            if rrf_scores[cid] < settings.MIN_RRF_SCORE_THRESHOLD:
                continue
            chunk = self.metadata_store.get_chunk(cid)
            if not chunk:
                continue

            retrieved_chunk = RetrievedChunk(
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                source=chunk.source,
                page=chunk.page,
                chunk_index=chunk.chunk_index,
                text=chunk.text,
                score=round(rrf_scores[cid], 6),
                semantic_rank=semantic_ranks.get(cid),
                bm25_rank=bm25_ranks.get(cid),
                retrieval_method="hybrid_rrf"
            )
            retrieved_list.append(retrieved_chunk)

        # 5. Apply Optional Cross-Encoder Reranking
        candidates_to_rerank = retrieved_list[: max(top_k * 2, 10)]
        final_results = self.reranker.rerank(query=query, candidates=candidates_to_rerank, top_k=top_k)

        return final_results

