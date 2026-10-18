from api.routes_health import router as health_router
from api.routes_documents import router as documents_router
from api.routes_retrieval import router as retrieval_router
from api.routes_chat import router as chat_router
from api.routes_study import router as study_router

__all__ = [
    "health_router",
    "documents_router",
    "retrieval_router",
    "chat_router",
    "study_router",
]

