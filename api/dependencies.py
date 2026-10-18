from functools import lru_cache
from config import settings
from storage.metadata_store import MetadataStore
from retrieval.embeddings import EmbeddingManager
from retrieval.vector_store import FAISSVectorStore
from retrieval.keyword_search import BM25KeywordSearch
from retrieval.reranker import CrossEncoderReranker
from retrieval.hybrid_search import HybridRetriever
from generation.groq_client import GroqClientWrapper
from generation.gemini_client import GeminiClientWrapper
from generation.answer_generator import AnswerGenerator
from services.document_service import DocumentService
from services.retrieval_service import RetrievalService
from services.chat_service import ChatService
from services.conversation_service import ConversationService


class AppContainer:
    """Singleton container holding application state and services."""
    def __init__(self):
        self.metadata_store = MetadataStore()
        self.embedding_manager = EmbeddingManager()
        self.vector_store = FAISSVectorStore()
        self.keyword_search = BM25KeywordSearch()
        self.reranker = CrossEncoderReranker()
        self.hybrid_retriever = HybridRetriever(
            metadata_store=self.metadata_store,
            vector_store=self.vector_store,
            keyword_search=self.keyword_search,
            embedding_manager=self.embedding_manager,
            reranker=self.reranker
        )
        self.gemini_client = GeminiClientWrapper()
        self.groq_client = GroqClientWrapper()
        self.answer_generator = AnswerGenerator(
            gemini_client=self.gemini_client,
            groq_client=self.groq_client,
            primary_provider=settings.PRIMARY_LLM_PROVIDER
        )
        self.document_service = DocumentService(
            metadata_store=self.metadata_store,
            vector_store=self.vector_store,
            keyword_search=self.keyword_search,
            embedding_manager=self.embedding_manager
        )
        self.conversation_service = ConversationService()
        self.chat_service = ChatService(
            hybrid_retriever=self.hybrid_retriever,
            answer_generator=self.answer_generator,
            conversation_service=self.conversation_service
        )


_container: AppContainer = None


def get_container() -> AppContainer:
    global _container
    if _container is None:
        _container = AppContainer()
    return _container


def get_document_service() -> DocumentService:
    return get_container().document_service


def get_retrieval_service() -> RetrievalService:
    return get_container().retrieval_service


def get_chat_service() -> ChatService:
    return get_container().chat_service


def get_conversation_service() -> ConversationService:
    return get_container().conversation_service

