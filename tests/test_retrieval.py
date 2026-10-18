import numpy as np
import pytest
from schemas.document import ChunkMetadata
from retrieval.embeddings import EmbeddingManager
from retrieval.vector_store import FAISSVectorStore
from retrieval.keyword_search import BM25KeywordSearch
from retrieval.hybrid_search import HybridRetriever
from storage.metadata_store import MetadataStore


@pytest.fixture
def sample_test_chunks():
    return [
        ChunkMetadata(
            chunk_id="chunk_cpb_pumps",
            document_id="doc_1",
            source="perfusion_tech.pdf",
            page=1,
            chunk_index=0,
            text="Centrifugal pumps utilize rotating cones to generate kinetic energy and are afterload-dependent.",
            char_count=98,
            estimated_tokens=20
        ),
        ChunkMetadata(
            chunk_id="chunk_oxygenator",
            document_id="doc_1",
            source="perfusion_tech.pdf",
            page=2,
            chunk_index=1,
            text="Membrane oxygenators control PaO2 via FiO2 and carbon dioxide elimination via sweep gas flow rate.",
            char_count=100,
            estimated_tokens=22
        ),
        ChunkMetadata(
            chunk_id="chunk_heparin_act",
            document_id="doc_2",
            source="anticoagulation.pdf",
            page=1,
            chunk_index=0,
            text="Unfractionated heparin at 300-400 units/kg is monitored using Activated Clotting Time (ACT target > 480 s).",
            char_count=108,
            estimated_tokens=24
        ),
    ]


def test_embedding_generation():
    """Test generating normalized embeddings with expected dimensionality."""
    mgr = EmbeddingManager()
    texts = ["Cardiopulmonary bypass circuit", "Extracorporeal membrane oxygenation"]
    embeddings = mgr.embed_texts(texts)

    assert embeddings.shape[0] == 2
    assert embeddings.shape[1] == 384
    # Verify L2 normalization (norm should be approximately 1.0)
    for row in embeddings:
        norm = np.linalg.norm(row)
        assert abs(norm - 1.0) < 1e-4

    # Test single query embedding
    q_emb = mgr.embed_query("What is an oxygenator?")
    assert q_emb.shape == (1, 384)
    assert abs(np.linalg.norm(q_emb[0]) - 1.0) < 1e-4


def test_faiss_vector_store(tmp_path):
    """Test adding vectors, searching by cosine similarity, and saving/loading."""
    vstore = FAISSVectorStore(dimension=384, index_dir=tmp_path)
    assert vstore.total_vectors == 0

    # Search on empty index
    dummy_q = np.random.randn(1, 384).astype(np.float32)
    dummy_q = dummy_q / np.linalg.norm(dummy_q)
    assert vstore.search(dummy_q, top_k=5) == []

    # Add 2 distinct unit vectors
    v1 = np.zeros((1, 384), dtype=np.float32)
    v1[0, 0] = 1.0  # along dimension 0
    v2 = np.zeros((1, 384), dtype=np.float32)
    v2[0, 1] = 1.0  # along dimension 1

    vstore.add_vectors(["id_dim0", "id_dim1"], np.vstack([v1, v2]))
    assert vstore.total_vectors == 2

    # Query matching dimension 0
    results = vstore.search(v1, top_k=2)
    assert len(results) == 2
    assert results[0][0] == "id_dim0"
    assert abs(results[0][1] - 1.0) < 1e-5

    # Reload from disk
    vstore2 = FAISSVectorStore(dimension=384, index_dir=tmp_path)
    assert vstore2.total_vectors == 2
    results_reloaded = vstore2.search(v1, top_k=1)
    assert results_reloaded[0][0] == "id_dim0"


def test_bm25_keyword_search(sample_test_chunks):
    """Test BM25 keyword search with medical terms and acronyms."""
    bm25 = BM25KeywordSearch()
    # Empty index
    assert bm25.search("heparin", top_k=5) == []

    bm25.index_chunks(sample_test_chunks)

    # Search exact technical acronym "ACT"
    results_act = bm25.search("ACT monitoring heparin", top_k=3)
    assert len(results_act) > 0
    assert results_act[0][0] == "chunk_heparin_act"

    # Search "sweep gas"
    results_gas = bm25.search("sweep gas carbon dioxide", top_k=3)
    assert len(results_gas) > 0
    assert results_gas[0][0] == "chunk_oxygenator"

    # Search with document filter
    filtered = bm25.search("heparin", top_k=3, allowed_chunk_ids={"chunk_cpb_pumps"})
    assert len(filtered) == 0


def test_hybrid_retrieval_rrf(temp_test_env, sample_test_chunks):
    """Test Reciprocal Rank Fusion hybrid retrieval combining FAISS and BM25."""
    container = temp_test_env["container"]
    meta_store = container.metadata_store
    vstore = container.vector_store
    bm25 = container.keyword_search
    retriever = container.hybrid_retriever

    # Add chunks to metadata store
    for c in sample_test_chunks:
        meta_store.chunks[c.chunk_id] = c
        if c.document_id not in meta_store.doc_to_chunk_ids:
            meta_store.doc_to_chunk_ids[c.document_id] = []
        meta_store.doc_to_chunk_ids[c.document_id].append(c.chunk_id)

    # Index in BM25
    bm25.index_chunks(sample_test_chunks)

    # Embed and index in FAISS
    emb_mgr = container.embedding_manager
    texts = [c.text for c in sample_test_chunks]
    c_ids = [c.chunk_id for c in sample_test_chunks]
    embeddings = emb_mgr.embed_texts(texts)
    vstore.add_vectors(c_ids, embeddings)

    # Perform hybrid search
    results = retriever.retrieve(query="What is the function of a membrane oxygenator sweep gas?", top_k=2)

    assert len(results) > 0
    # Top result should be the oxygenator chunk
    assert results[0].chunk_id == "chunk_oxygenator"
    assert results[0].source == "perfusion_tech.pdf"
    assert results[0].page == 2
    assert results[0].score > 0
    assert results[0].retrieval_method in ["hybrid_rrf", "hybrid_reranked"]

    # Test document filtering
    filtered_results = retriever.retrieve(
        query="heparin and ACT",
        document_ids=["doc_1"],  # doc_1 does NOT contain heparin
        top_k=2
    )
    for r in filtered_results:
        assert r.document_id == "doc_1"

