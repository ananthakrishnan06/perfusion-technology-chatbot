import io
import shutil
import tempfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

try:
    import pymupdf as fitz
except ImportError:
    import fitz

from config import Settings
from storage.metadata_store import MetadataStore
from retrieval.embeddings import EmbeddingManager
from retrieval.vector_store import FAISSVectorStore
from retrieval.keyword_search import BM25KeywordSearch
from retrieval.reranker import CrossEncoderReranker
from retrieval.hybrid_search import HybridRetriever
from generation.groq_client import GroqClientWrapper
from generation.answer_generator import AnswerGenerator
from services.document_service import DocumentService
from services.retrieval_service import RetrievalService
from services.chat_service import ChatService
import api.dependencies as deps
from main import app


@pytest.fixture
def sample_perfusion_pdf_bytes() -> bytes:
    """Create a realistic in-memory multi-page Perfusion Technology PDF."""
    doc = fitz.open()

    # Page 1: Cardiopulmonary Bypass Circuit & Pumps
    p1 = doc.new_page()
    p1_text = (
        "PRINCIPLES OF CARDIOPULMONARY BYPASS\n\n"
        "Chapter 1: The Extracorporeal Circuit and Mechanical Pumps\n\n"
        "Cardiopulmonary bypass (CPB) temporarily takes over the mechanical function of the heart and lungs "
        "during open cardiac surgery. The essential components of a CPB circuit include venous cannulae, a venous "
        "reservoir, a blood pump, an oxygenator, a heat exchanger, and an arterial filter.\n\n"
        "Two principal pump designs are utilized: positive-displacement roller pumps and centrifugal pumps. "
        "Roller pumps operate by occluding tubing and deliver volume output that is proportional to pump RPM "
        "regardless of afterload. In contrast, centrifugal pumps utilize rotating cones or impellers that generate "
        "kinetic energy. Centrifugal pumps are afterload-dependent and non-occlusive, reducing the risk of circuit "
        "rupture and gross air embolization if an outflow obstruction occurs."
    )
    rect = fitz.Rect(50, 50, 550, 750)
    p1.insert_textbox(rect, p1_text, fontsize=11)

    # Page 2: Membrane Oxygenator & Gas Exchange
    p2 = doc.new_page()
    p2_text = (
        "PRINCIPLES OF CARDIOPULMONARY BYPASS\n\n"
        "Chapter 2: Membrane Oxygenators and Gas Transfer\n\n"
        "Modern CPB oxygenators utilize hollow-fiber microporous polypropylene or polymethylpentene (PMP) membranes. "
        "Blood flows over the exterior surface of the hollow fibers while sweep gas (oxygen and air mixture) passes "
        "through the interior lumens of the fibers.\n\n"
        "Oxygenation (PaO2) is controlled primarily by adjusting the fraction of delivered oxygen (FiO2). "
        "Carbon dioxide removal (PaCO2) is directly regulated by adjusting the sweep gas flow rate. "
        "Increasing sweep gas flow eliminates more carbon dioxide from the blood stream via diffusion gradient."
    )
    p2.insert_textbox(rect, p2_text, fontsize=11)

    # Page 3: Anticoagulation & Heparin Management
    p3 = doc.new_page()
    p3_text = (
        "PRINCIPLES OF CARDIOPULMONARY BYPASS\n\n"
        "Chapter 3: Anticoagulation and Heparin Monitoring\n\n"
        "Extracorporeal circulation requires systemic anticoagulation to prevent massive thrombotic occlusion "
        "of the bypass circuit upon blood-foreign surface contact. Unfractionated porcine heparin is the standard anticoagulant, "
        "administered at an initial loading dose of 300 to 400 units per kilogram of body weight.\n\n"
        "The Activated Clotting Time (ACT) is the gold standard point-of-care test for monitoring heparin effect. "
        "A baseline ACT is typically 100 to 130 seconds. Before initiating cardiopulmonary bypass, the target ACT must exceed "
        "400 to 480 seconds. Following termination of bypass, protamine sulfate is administered at approximately 1 mg per 100 units "
        "of initial heparin to titrate and reverse anticoagulation."
    )
    p3.insert_textbox(rect, p3_text, fontsize=11)

    pdf_bytes = doc.write()
    doc.close()
    return pdf_bytes


@pytest.fixture
def sample_scanned_pdf_bytes() -> bytes:
    """Create a scanned-like PDF with minimal or no extractable text."""
    doc = fitz.open()
    # Create pages with blank text or single punctuation marks
    p1 = doc.new_page()
    p1.insert_text((50, 50), "   ", fontsize=10)
    p2 = doc.new_page()
    p2.insert_text((50, 50), ".", fontsize=10)
    pdf_bytes = doc.write()
    doc.close()
    return pdf_bytes


@pytest.fixture
def temp_test_env(monkeypatch):
    """Provide an isolated temporary storage directory for tests."""
    temp_dir = tempfile.mkdtemp()
    temp_path = Path(temp_dir)
    data_dir = temp_path / "data"
    docs_dir = data_dir / "documents"
    indices_dir = data_dir / "indices"
    meta_file = data_dir / "metadata.json"

    docs_dir.mkdir(parents=True, exist_ok=True)
    indices_dir.mkdir(parents=True, exist_ok=True)

    test_settings = Settings(
        BASE_DATA_DIR=data_dir,
        DOCUMENTS_DIR=docs_dir,
        INDICES_DIR=indices_dir,
        METADATA_FILE=meta_file,
        GROQ_API_KEY="test_mock_key"
    )

    # Instantiate isolated app container
    container = deps.AppContainer()
    container.metadata_store = MetadataStore(metadata_path=meta_file)
    container.vector_store = FAISSVectorStore(dimension=384, index_dir=indices_dir)
    container.keyword_search = BM25KeywordSearch()
    container.hybrid_retriever = HybridRetriever(
        metadata_store=container.metadata_store,
        vector_store=container.vector_store,
        keyword_search=container.keyword_search,
        embedding_manager=container.embedding_manager,
        reranker=container.reranker
    )
    container.document_service = DocumentService(
        metadata_store=container.metadata_store,
        vector_store=container.vector_store,
        keyword_search=container.keyword_search,
        embedding_manager=container.embedding_manager,
        documents_dir=docs_dir
    )
    container.retrieval_service = RetrievalService(hybrid_retriever=container.hybrid_retriever)
    container.chat_service = ChatService(
        hybrid_retriever=container.hybrid_retriever,
        answer_generator=container.answer_generator
    )

    monkeypatch.setattr(deps, "_container", container)

    yield {
        "container": container,
        "temp_path": temp_path,
        "settings": test_settings
    }

    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def test_client(temp_test_env):
    """FastAPI TestClient with isolated temporary container."""
    with TestClient(app) as client:
        yield client
