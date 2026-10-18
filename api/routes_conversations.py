import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from api.routes_auth import get_current_user
from schemas.auth import UserProfile
from services.conversation_service import ConversationService
from storage.db import is_db_configured

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/conversations", tags=["Conversations & Memory"])


# Schemas
class ConversationCreateRequest(BaseModel):
    title: Optional[str] = Field(default="New Perfusion Inquiry", max_length=250)


class ConversationRenameRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=250, description="New title for conversation")


class MemoryCreateRequest(BaseModel):
    key: str = Field(..., min_length=1, max_length=100)
    content: str = Field(..., min_length=1)
    category: Optional[str] = Field(default="user_preference")
    conversation_id: Optional[str] = None


def get_conversation_service() -> ConversationService:
    from api.dependencies import get_conversation_service as _get_conv
    return _get_conv()


@router.get("", summary="List all conversation sessions for authenticated user")
def list_conversations(
    limit: int = 50,
    search: Optional[str] = None,
    current_user: UserProfile = Depends(get_current_user),
    conv_service: ConversationService = Depends(get_conversation_service)
):
    """
    Retrieve all conversation sessions belonging strictly to the authenticated user.
    """
    if not is_db_configured():
        return {
            "status": "database_not_configured",
            "message": "PostgreSQL DATABASE_URL is not set in .env",
            "conversations": []
        }
    return {
        "status": "ok",
        "conversations": conv_service.list_conversations(
            user_id=current_user.sub,
            limit=limit,
            search=search
        )
    }


@router.post("", summary="Create a new conversation session for authenticated user")
def create_conversation(
    req: ConversationCreateRequest,
    current_user: UserProfile = Depends(get_current_user),
    conv_service: ConversationService = Depends(get_conversation_service)
):
    """
    Create a new chat session owned by the authenticated user.
    """
    if not is_db_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PostgreSQL DATABASE_URL is not configured in .env"
        )
    conv = conv_service.create_conversation(
        user_id=current_user.sub,
        title=req.title or "New Perfusion Inquiry"
    )
    if not conv:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create conversation in PostgreSQL."
        )
    return conv


@router.get("/memories/all", summary="List stored long-term clinical memories for user")
def list_memories(
    limit: int = 25,
    current_user: UserProfile = Depends(get_current_user),
    conv_service: ConversationService = Depends(get_conversation_service)
):
    """
    Retrieve clinical memories stored for the authenticated user across their sessions.
    """
    if not is_db_configured():
        return {"status": "database_not_configured", "memories": []}
    return {
        "status": "ok",
        "memories": conv_service.list_memories(user_id=current_user.sub, limit=limit)
    }


@router.post("/memories", summary="Manually store a long-term memory for user")
def create_memory(
    req: MemoryCreateRequest,
    current_user: UserProfile = Depends(get_current_user),
    conv_service: ConversationService = Depends(get_conversation_service)
):
    """
    Store a clinical fact or user preference in long-term memory for the authenticated user.
    """
    if not is_db_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PostgreSQL DATABASE_URL is not configured in .env"
        )
    mem = conv_service.save_memory(
        user_id=current_user.sub,
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
    current_user: UserProfile = Depends(get_current_user),
    conv_service: ConversationService = Depends(get_conversation_service)
):
    """
    Load a specific conversation with all historical user and assistant messages.
    Enforces that the conversation belongs to the authenticated user.
    """
    if not is_db_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PostgreSQL DATABASE_URL is not configured in .env"
        )
    conv, status_code = conv_service.get_conversation(
        conversation_id=conversation_id,
        user_id=current_user.sub
    )
    if status_code == "not_found":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found.")
    if status_code == "forbidden":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: You do not have permission to access this conversation."
        )
    if not conv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found.")
    return conv


@router.patch("/{conversation_id}", summary="Rename a conversation session")
def rename_conversation(
    conversation_id: str,
    req: ConversationRenameRequest,
    current_user: UserProfile = Depends(get_current_user),
    conv_service: ConversationService = Depends(get_conversation_service)
):
    """
    Rename an existing conversation belonging to the authenticated user.
    """
    if not is_db_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PostgreSQL DATABASE_URL is not configured in .env"
        )
    conv, status_code = conv_service.rename_conversation(
        conversation_id=conversation_id,
        user_id=current_user.sub,
        title=req.title
    )
    if status_code == "not_found":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found.")
    if status_code == "forbidden":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: You do not have permission to rename this conversation."
        )
    if not conv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found.")
    return conv


@router.delete("/{conversation_id}", summary="Delete a conversation session")
def delete_conversation(
    conversation_id: str,
    current_user: UserProfile = Depends(get_current_user),
    conv_service: ConversationService = Depends(get_conversation_service)
):
    """
    Delete a conversation session and all its messages.
    Enforces that the conversation belongs to the authenticated user.
    """
    if not is_db_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PostgreSQL DATABASE_URL is not configured in .env"
        )
    success, status_code = conv_service.delete_conversation(
        conversation_id=conversation_id,
        user_id=current_user.sub
    )
    if status_code == "not_found":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found.")
    if status_code == "forbidden":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: You do not have permission to delete this conversation."
        )
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found or could not be deleted.")
    return {"status": "ok", "deleted": True, "conversation_id": conversation_id}
