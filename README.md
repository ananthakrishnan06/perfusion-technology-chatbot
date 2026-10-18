# PerfusionGPT — RAG Backend for Perfusion Technology

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com)
[![Groq SDK](https://img.shields.io/badge/Groq-Official%20SDK-F55036.svg)](https://groq.com)
[![FAISS](https://img.shields.io/badge/FAISS-CPU%20Vector%20Store-007ACC.svg)](https://github.com/facebookresearch/faiss)
[![Tests](https://img.shields.io/badge/tests-29%20passed-brightgreen.svg)]()

A modular, reliable, evidence-grounded Retrieval-Augmented Generation (RAG) backend engineered specifically for **Perfusion Technology** education.

PerfusionGPT retrieves authentic passages from uploaded medical textbooks, clinical guidelines, and lecture notes, combining dense semantic search (FAISS) with sparse keyword retrieval (BM25) via Reciprocal Rank Fusion (RRF), and generates evidence-backed answers with verifiable page-level citations using the Groq API.

> [!NOTE]
> **Backend Only:** This project is strictly a headless REST API service. The user interface will be developed separately using Google Stitch and integrated via these REST endpoints.

---

## Architecture Pipeline

```
PDF Upload (Multipart)
        ↓
PDF Validation & Integrity Check (%PDF- header, size, structure)
        ↓
PyMuPDF Text Extraction & Layout Inspection
        ↓
Text Cleaning & Confident Header/Footer Removal
        ↓
Structure-Aware Chunking (Preserving 1-based authentic PDF page numbers)
        ↓
Embedding Generation (BAAI/bge-small-en-v1.5, L2-normalized)
        ↓
Dual Indexing:
  ├── FAISS Dense Vector Store (Cosine Similarity / IndexFlatIP)
  └── BM25 Okapi Sparse Keyword Index (Perfusion Terminology & Acronyms)
        ↓
Reciprocal Rank Fusion (RRF) Hybrid Retrieval
        ↓
Optional Cross-Encoder Reranking
        ↓
Relevant Evidence Selection & Prompt Construction
        ↓
Groq API (llama-3.3-70b-versatile)
        ↓
Evidence-Grounded Answer + Programmatic Source Citations
        ↓
JSON REST API Response
```

---

## Key Features

1. **Robust PDF Ingestion & OCR Detection:**
   - Accepts multiple PDF files via multipart form data.
   - Enforces strict validation: file extensions, magic bytes (`%PDF-`), and configurable file size limits (`MAX_UPLOAD_SIZE_MB`).
   - Automatically flags scanned documents or image-only PDFs that require OCR.
   - Cleans line-wrap hyphens (e.g. `perfu-\nsion` → `perfusion`) and removes repeated headers/footers without corrupting clinical terminology.

2. **Structure-Aware Chunking & Verifiable Citations:**
   - Chunks text at natural paragraph, heading, and sentence boundaries.
   - Strictly preserves authentic **1-based original PDF page numbers** in every chunk metadata payload.
   - Prevents LLMs from hallucinating page numbers by extracting and deduplicating citations programmatically.

3. **Hybrid Retrieval (Dense + Sparse):**
   - **Semantic Search:** FAISS (`IndexFlatIP` with L2-normalized vectors) powered by `BAAI/bge-small-en-v1.5`.
   - **Keyword Search:** `rank-bm25` (BM25Okapi) with a perfusion-aware tokenizer that preserves technical acronyms (`CPB`, `ECMO`, `ACT`, `PaO2`, `SvO2`), hyphens (`acid-base`), and decimals (`7.40`).
   - **Rank Fusion:** Reciprocal Rank Fusion (RRF, $k=60$) combining semantic and keyword rankings safely.
   - **Document Filtering:** Allows scoping queries to specific document IDs.

4. **Evidence-Grounded Answering via Groq:**
   - Powered by official `groq` SDK with `llama-3.3-70b-versatile` (or configurable model).
   - Dedicated educational system prompt instructing the model to base answers exclusively on retrieved passages.
   - Explicit fallback response when evidence is insufficient:
     > *"I could not find sufficient supporting information in the indexed Perfusion Technology documents to answer this question reliably."*

5. **Study Multiple-Choice Question (MCQ) Generator:**
   - Generates 4-option multiple-choice practice questions grounded in retrieved textbook evidence with correct answer explanations and citations.

6. **Google Stitch Frontend Readiness:**
   - Strict CORS middleware with configurable origins.
   - Standardized, consistent JSON schemas across all endpoints.
   - Interactive OpenAPI documentation available at `/docs`.

---

## Directory Structure

```
PerfusionGPT/
│
├── main.py                     # FastAPI application setup, lifespan, CORS, and error handlers
├── config.py                   # Centralized Pydantic BaseSettings configuration
├── requirements.txt            # Dependency specification
├── pytest.ini                  # Pytest configuration
├── .env.example                # Template environment variables
├── .gitignore                  # Git ignore rules
├── README.md                   # Project documentation
│
├── api/                        # REST API layer
│   ├── __init__.py
│   ├── dependencies.py         # Dependency injection container
│   ├── routes_health.py        # Health check endpoint
│   ├── routes_documents.py     # PDF upload, listing, details, and deletion
│   ├── routes_retrieval.py     # Source search and index rebuild
│   ├── routes_chat.py          # Evidence-grounded Q&A chat endpoint
│   └── routes_study.py         # MCQ generation endpoint
│
├── ingestion/                  # PDF extraction & text processing
│   ├── __init__.py
│   ├── pdf_loader.py           # PyMuPDF extraction, validation, and OCR detection
│   ├── text_cleaner.py         # Whitespace, hyphenation, and header/footer cleaner
│   └── chunker.py              # Structure-aware passage chunker
│
├── retrieval/                  # Search & ranking engines
│   ├── __init__.py
│   ├── embeddings.py           # BAAI/bge-small-en-v1.5 sentence-transformer wrapper
│   ├── vector_store.py         # FAISS IndexFlatIP vector database manager
│   ├── keyword_search.py       # BM25Okapi keyword search engine
│   ├── hybrid_search.py        # Reciprocal Rank Fusion (RRF) hybrid retriever
│   └── reranker.py             # Optional Cross-Encoder reranker
│
├── generation/                 # Groq LLM integration
│   ├── __init__.py
│   ├── groq_client.py          # Groq SDK wrapper with error and timeout handling
│   ├── prompts.py              # PerfusionGPT system prompts and message builders
│   └── answer_generator.py     # Answer synthesis and citation extraction
│
├── services/                   # Business logic orchestration
│   ├── __init__.py
│   ├── document_service.py     # Ingestion, storage, and index synchronization
│   ├── retrieval_service.py    # Standalone retrieval search
│   └── chat_service.py         # Chat Q&A and MCQ generation service
│
├── schemas/                    # Pydantic v2 data models
│   ├── __init__.py
│   ├── document.py             # Document & chunk models
│   ├── retrieval.py            # Search query & response models
│   └── chat.py                 # Chat & MCQ request/response models
│
├── storage/                    # Persistent metadata store
│   ├── __init__.py
│   └── metadata_store.py       # Thread-safe JSON store with atomic file writes
│
├── data/                       # Local data storage (documents, indices, metadata)
│   ├── documents/              # Stored PDF files (named with internal UUIDs)
│   └── indices/                # FAISS binary index and ID mapping
│
└── tests/                      # Automated test suite
    ├── conftest.py             # In-memory PDF fixtures and test container
    ├── test_pdf_loader.py      # PDF extraction, validation, and OCR tests
    ├── test_chunker.py         # Chunking and page-preservation tests
    ├── test_retrieval.py       # FAISS, BM25, and RRF tests
    ├── test_citations.py       # Citation mapping and deduplication tests
    ├── test_document_management.py # Upload, deduplication, deletion, and rebuild tests
    └── test_api.py             # FastAPI TestClient API integration tests
```

---

## Installation & Setup

### Prerequisites

- Python 3.10, 3.11, or 3.12 (Python 3.12 recommended)
- A Groq API key from [console.groq.com](https://console.groq.com)

### 1. Clone & Setup Virtual Environment

```bash
cd "d:/pt chatbot"
python -m venv venv

# Windows (PowerShell):
.\venv\Scripts\Activate.ps1

# Linux / macOS:
source venv/bin/activate
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Environment Variables

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

Edit `.env` and provide your Groq API key:

```env
GROQ_API_KEY=gsk_your_actual_groq_api_key_here
GROQ_MODEL=llama-3.3-70b-versatile
GROQ_TEMPERATURE=0.2
GROQ_MAX_TOKENS=2048

EMBEDDING_MODEL_NAME=BAAI/bge-small-en-v1.5
EMBEDDING_DEVICE=cpu

CHUNK_SIZE=500
CHUNK_OVERLAP=80
MAX_UPLOAD_SIZE_MB=50

CORS_ORIGINS=["*"]
```

---

## Running the Application

Start the FastAPI development server:

```bash
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Once running:
- **Base API URL:** `http://127.0.0.1:8000`
- **Interactive OpenAPI Documentation (Swagger UI):** `http://127.0.0.1:8000/docs`
- **Alternative ReDoc UI:** `http://127.0.0.1:8000/redoc`

---

## API Reference & Examples

### 1. Health Check
`GET /health`

**Response:**
```json
{
  "status": "ok",
  "service": "PerfusionGPT",
  "version": "1.0.0"
}
```

---

### 2. Upload PDF Documents
`POST /api/v1/documents/upload` (Multipart Form Data)

Upload one or more PDF files under the `files` field.

**Example `curl` request:**
```bash
curl -X POST "http://127.0.0.1:8000/api/v1/documents/upload" \
  -F "files=@perfusion_textbook.pdf"
```

**Response:**
```json
{
  "results": [
    {
      "document_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
      "original_filename": "perfusion_textbook.pdf",
      "processing_status": "indexed",
      "page_count": 45,
      "chunk_count": 82,
      "ocr_warning": null,
      "error_details": null
    }
  ],
  "total_uploaded": 1,
  "total_failed": 0
}
```

---

### 3. List Indexed Documents
`GET /api/v1/documents`

**Response:**
```json
{
  "documents": [
    {
      "document_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
      "filename": "perfusion_textbook.pdf",
      "file_hash": "a4f5...b12",
      "file_size_bytes": 1048576,
      "total_pages": 45,
      "total_chunks": 82,
      "low_text_pages": [],
      "ocr_needed": false,
      "ocr_warning": null,
      "uploaded_at": "2026-10-16T18:40:00Z",
      "status": "indexed"
    }
  ],
  "total_documents": 1
}
```

---

### 4. Delete a Document
`DELETE /api/v1/documents/{document_id}`

Completely removes the document, deletes the stored file, and rebuilds the FAISS and BM25 indices to guarantee its passages are excluded from future searches.

**Response:**
```json
{
  "status": "success",
  "message": "Document '9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d' successfully removed from knowledge base and indices.",
  "document_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d"
}
```

---

### 5. Search Sources (Without LLM Call)
`POST /api/v1/retrieval/search`

Useful for inspecting retrieval ranking and testing search independently of Groq.

**Request:**
```json
{
  "query": "How do centrifugal pumps compare to roller pumps in CPB?",
  "document_ids": [],
  "top_k": 3
}
```

**Response:**
```json
{
  "query": "How do centrifugal pumps compare to roller pumps in CPB?",
  "retrieved_chunks": [
    {
      "chunk_id": "9b1deb4d_p1_c0",
      "document_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
      "source": "perfusion_textbook.pdf",
      "page": 1,
      "chunk_index": 0,
      "text": "Roller pumps are positive-displacement and occlusive, whereas centrifugal pumps are non-occlusive and afterload-dependent...",
      "score": 0.032258,
      "semantic_rank": 1,
      "bm25_rank": 1,
      "retrieval_method": "hybrid_rrf"
    }
  ],
  "total_retrieved": 1,
  "retrieval_method": "hybrid_rrf"
}
```

---

### 6. Ask an Evidence-Grounded Question
`POST /api/v1/chat/ask`

**Request:**
```json
{
  "question": "What is the Activated Clotting Time (ACT) requirement before initiating cardiopulmonary bypass?",
  "document_ids": [],
  "top_k": 5,
  "conversation_history": [
    {"role": "user", "content": "Hello, I am studying perfusion anticoagulation."},
    {"role": "assistant", "content": "Welcome. I am ready to assist with evidence from your perfusion documents."}
  ]
}
```

**Response:**
```json
{
  "answer": "### Anticoagulation & ACT Monitoring\n\nBefore initiating cardiopulmonary bypass (CPB), the target Activated Clotting Time (ACT) must exceed **400 to 480 seconds**.\n\n- Baseline ACT is typically **100 to 130 seconds**.\n- Unfractionated porcine heparin is administered at an initial loading dose of **300 to 400 units/kg**.\n- Following termination of bypass, protamine sulfate is administered at approximately 1 mg per 100 units of initial heparin to reverse anticoagulation.",
  "grounded": true,
  "insufficient_evidence": false,
  "citations": [
    {
      "source": "perfusion_textbook.pdf",
      "page": 3,
      "chunk_id": "9b1deb4d_p3_c0",
      "excerpt": "The Activated Clotting Time (ACT) is the gold standard point-of-care test for monitoring heparin effect. A baseline ACT is typically 100 to 130 seconds. Before initiating cardiopulmonary bypass, the target ACT must exceed 400 to 480 seconds."
    }
  ],
  "retrieval": {
    "method": "hybrid_rrf",
    "retrieved_chunks": 3
  }
}
```

If the documents do not contain the answer:
```json
{
  "answer": "I could not find sufficient supporting information in the indexed Perfusion Technology documents to answer this question reliably.",
  "grounded": false,
  "insufficient_evidence": true,
  "citations": [],
  "retrieval": {
    "method": "hybrid",
    "retrieved_chunks": 0
  }
}
```

---

### 7. Study Question Generation (MCQ)
`POST /api/v1/study/mcq`

**Request:**
```json
{
  "topic": "Membrane oxygenator gas exchange",
  "num_questions": 2,
  "difficulty": "intermediate"
}
```

**Response:**
```json
{
  "topic": "Membrane oxygenator gas exchange",
  "questions": [
    {
      "question": "Which parameter directly regulates carbon dioxide elimination in a membrane oxygenator?",
      "options": [
        {"key": "A", "text": "Fraction of delivered oxygen (FiO2)"},
        {"key": "B", "text": "Sweep gas flow rate"},
        {"key": "C", "text": "Arterial line filtration pore size"},
        {"key": "D", "text": "Venous reservoir level"}
      ],
      "correct_answer": "B",
      "explanation": "Carbon dioxide removal is governed directly by sweep gas flow rate through the hollow-fiber lumens, while oxygenation is regulated by FiO2.",
      "citations": [
        {
          "source": "perfusion_textbook.pdf",
          "page": 2,
          "chunk_id": "9b1deb4d_p2_c0",
          "excerpt": "Carbon dioxide removal (PaCO2) is directly regulated by adjusting the sweep gas flow rate."
        }
      ]
    }
  ],
  "total_questions": 1,
  "insufficient_evidence": false,
  "citations": [...]
}
```

---

### 8. Rebuild Vector and Keyword Index
`POST /api/v1/index/rebuild`

Recomputes FAISS embeddings and rebuilds the BM25 index from scratch using all documents in the metadata store.

**Response:**
```json
{
  "status": "success",
  "total_chunks_indexed": 82,
  "total_documents": 1
}
```

---

## Running the Automated Test Suite

PerfusionGPT includes comprehensive unit, integration, and API tests using `pytest` and `FastAPI TestClient`. Groq API calls are mocked in automated tests so they run quickly and offline without API charges.

Execute all tests:

```bash
python -m pytest -v
```

### Running with a Live Groq API Key

To run the optional live Groq integration test against Groq's cloud infrastructure, ensure `GROQ_API_KEY` is exported in your environment and run:

```bash
$env:GROQ_API_KEY="gsk_your_actual_key"   # PowerShell
python -m pytest -v -k "test_live_groq_integration"
```

---

## Educational & Clinical Reliability Disclaimer

> [!CAUTION]
> **Educational Use Only:**
> PerfusionGPT is engineered strictly as an educational study assistant for Perfusion Technology students and academic inquiry. It is **not** a certified medical device, does not possess clinical validation or regulatory clearance, and must **never** be used as a substitute for institutional clinical protocols, operating room checklists, or the real-time judgment of certified clinical perfusionists and attending physicians.

