import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from config import settings
from api.routes_health import router as health_router
from api.routes_documents import router as documents_router
from api.routes_retrieval import router as retrieval_router
from api.routes_chat import router as chat_router
from api.routes_study import router as study_router
from api.routes_auth import router as auth_router
from api.routes_conversations import router as conversations_router
from storage.db import init_db
from api.dependencies import get_container

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("perfusion_gpt")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.
    Initializes storage, loads indices, and warms up foundational services.
    """
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}...")
    settings.ensure_directories()
    # Initialize PostgreSQL database if configured
    init_db()
    # Trigger singleton container creation and index loading
    container = get_container()
    logger.info(
        f"Initialized knowledge base: {len(container.metadata_store.documents)} documents, "
        f"{len(container.metadata_store.chunks)} chunks, {container.vector_store.total_vectors} vectors in FAISS."
    )
    # Pre-warm embedding model to eliminate first-query cold-start latency
    container.embedding_manager.warmup()
    yield
    logger.info(f"Shutting down {settings.APP_NAME}...")


app = FastAPI(
    title="PerfusionGPT — RAG Backend for Perfusion Technology",
    description=(
        "Evidence-grounded Retrieval-Augmented Generation (RAG) backend for Perfusion Technology education. "
        "Retrieves authoritative information from uploaded medical textbooks, lecture notes, and papers, "
        "and synthesizes answers with authentic page-level citations using Groq."
    ),
    version=settings.APP_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan
)

# Configure CORS for future Stitch frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
    allow_methods=settings.CORS_ALLOW_METHODS,
    allow_headers=settings.CORS_ALLOW_HEADERS,
)


@app.middleware("http")
async def add_security_and_cache_headers(request: Request, call_next):
    response = await call_next(request)
    # Defense-in-depth OWASP HTTP security headers
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"

    if request.url.path.startswith("/app") or request.url.path == "/":
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


# Global Exception Handlers to prevent internal trace leaks
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": True,
            "status_code": exc.status_code,
            "message": exc.detail
        }
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception on {request.method} {request.url.path}: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": True,
            "status_code": 500,
            "message": "An internal server error occurred while processing your request."
        }
    )


# Register API Routers
app.include_router(health_router)
app.include_router(documents_router, prefix=settings.API_PREFIX)
app.include_router(retrieval_router, prefix=settings.API_PREFIX)
app.include_router(chat_router, prefix=settings.API_PREFIX)
app.include_router(study_router, prefix=settings.API_PREFIX)
app.include_router(auth_router, prefix=settings.API_PREFIX)
app.include_router(conversations_router, prefix=settings.API_PREFIX)

# Mount Frontend UI (Matching User's Perfusion AI Specification)
frontend_dir = Path(__file__).resolve().parent / "frontend"
if frontend_dir.exists():
    app.mount("/app", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")


@app.get("/", summary="API Root", tags=["Health"])
def api_root():
    """Root endpoint for backend API status and documentation link."""
    return {
        "status": "online",
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs_url": "/docs",
        "health_check": "/api/v1/health"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)

