from fastapi import APIRouter
from config import settings

router = APIRouter(tags=["Health"])


@router.get("/health", summary="Health check")
@router.get("/api/v1/health", summary="Health check (API prefix)")
def health_check():
    """
    Check service health and version information.
    """
    return {
        "status": "ok",
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION
    }

