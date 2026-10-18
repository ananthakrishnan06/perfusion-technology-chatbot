import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from services.conversation_service import ConversationService
from storage.db import is_db_configured

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/conversations", tags=["Conversations & Memory"])


# Schemas
class ConversationCreateRequest(BaseModel):
    title: Optional[str] = Field(default="New Perfusion Inquiry", max_length=250)


class MemoryCreateRequest(BaseModel):
    key: str = Field(..., min_length=1, max_length=100)
    content: str = Field(..., min_length=1)
    category: Optional[str] = Field(default="user_preference")
    conversation_id: Optional[str] = None


def get_conversation_service() -> ConversationService:
    from api.dependencies import get_conversation_service as _get_conv
    return _get_conv()


@router.get("", summary="List all recent conversation sessions")
def list_conversations(
    limit: int = 50,
    conv_service: ConversationService = Depends(get_conversation_service)
):
    """Retrieve all past conversation sessions ordered by last activity."""
    if not is_db_configured():
        return {
            "status": "database_not_configured",
            "message": "PostgreSQL DATABASE_URL is not set in .env",
            "conversations": []
        }
    return {
        "status": "ok",
        "conversations": conv_service.list_conversations(limit=limit)
    }


@router.post("", summary="Create a new conversation session")
def create_conversation(
    req: ConversationCreateRequest,
    conv_service: ConversationService = Depends(get_conversation_service)
):
    """Create a new chat session."""
    if not is_db_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PostgreSQL DATABASE_URL is not configured in .env"
        )
    conv = conv_service.create_conversation(title=req.title or "New Perfusion Inquiry")
    if not conv:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create conversation in PostgreSQL."
        )
    return conv


@router.get("/memories/all", summary="List stored long-term clinical memories")
def list_memories(
    limit: int = 25,
    conv_service: ConversationService = Depends(get_conversation_service)
):
    """Retrieve long-term clinical memories stored across all chat sessions."""
    if not is_db_configured():
        return {"status": "database_not_configured", "memories": []}
    return {
        "status": "ok",
        "memories": conv_service.list_memories(limit=limit)
    }


@router.post("/memories", summary="Manually store a long-term memory")
def create_memory(
    req: MemoryCreateRequest,
    conv_service: ConversationService = Depends(get_conversation_service)
):
    """Store a clinical fact or user preference in long-term memory."""
    if not is_db_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PostgreSQL DATABASE_URL is not configured in .env"
        )
    mem = conv_service.save_memory(
        key=req.key,
        content=req.content,
        category=req.category or "user_preference",
        conversation_id=req.conversation_id
    )
    if not mem:
        raise HTTPException(status_code=500, detail="Failed to persist memory in PostgreSQL.")
    return mem


@router.get("/{conversation_id}", summary="Get conversation details and full turn history")
def get_conversation(
    conversation_id: str,
    conv_service: ConversationService = Depends(get_conversation_service)
):
    """Load a specific conversation with all historical user and assistant messages."""
    if not is_db_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PostgreSQL DATABASE_URL is not configured in .env"
        )
    conv = conv_service.get_conversation(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return conv


@router.delete("/{conversation_id}", summary="Delete a conversation session")
def delete_conversation(
    conversation_id: str,
    conv_service: ConversationService = Depends(get_conversation_service)
):
    """Delete a conversation session and all its messages."""
    if not is_db_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PostgreSQL DATABASE_URL is not configured in .env"
        )
    success = conv_service.delete_conversation(conversation_id)
    if not success:
        raise HTTPException(status_code=404, detail="Conversation not found or could not be deleted.")
    return {"status": "ok", "deleted": True, "conversation_id": conversation_id}
