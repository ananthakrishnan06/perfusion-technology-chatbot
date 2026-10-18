from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from schemas.auth import UserProfile
from schemas.chat import ChatRequest, ChatResponse
from services.chat_service import ChatService
from generation.groq_client import GroqConfigurationError, GroqAPIError
from generation.gemini_client import GeminiConfigurationError, GeminiAPIError
from api.dependencies import get_chat_service, get_optional_current_user
from storage.db import is_db_configured

router = APIRouter(prefix="/chat", tags=["Chat"])


class TranscribeResponse(BaseModel):
    text: str


@router.post(
    "/ask",
    response_model=ChatResponse,
    summary="Ask an evidence-grounded Perfusion Technology question"
)
def ask_question(
    request: ChatRequest,
    current_user: Optional[UserProfile] = Depends(get_optional_current_user),
    chat_service: ChatService = Depends(get_chat_service)
):
    """
    Ask a question grounded in the uploaded Perfusion Technology documents.
    
    Retrieves the most relevant passages using hybrid FAISS and BM25 search,
    synthesizes an evidence-grounded answer via Google Gemini (with automatic Groq fallback),
    and returns verifiable source citations with 1-based original PDF page numbers.
    """
    try:
        user_id = current_user.sub if current_user else None
        return chat_service.ask_question(request, user_id=user_id)
    except HTTPException:
        raise
    except (GroqConfigurationError, GeminiConfigurationError) as ge:
        detail_msg = f"Groq API service is not configured: {str(ge)}" if isinstance(ge, GroqConfigurationError) else f"Gemini API service is not configured: {str(ge)}"
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=detail_msg
        )
    except (GroqAPIError, GeminiAPIError) as ae:
        detail_msg = f"Groq generation failed: {str(ae)}" if isinstance(ae, GroqAPIError) else f"Gemini generation failed: {str(ae)}"
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=detail_msg
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred while answering your question: {str(e)}"
        )


@router.post(
    "/stream",
    summary="Stream an evidence-grounded Perfusion Technology answer in real time"
)
def stream_question(
    request: ChatRequest,
    current_user: Optional[UserProfile] = Depends(get_optional_current_user),
    chat_service: ChatService = Depends(get_chat_service)
):
    """
    Stream tokens in real-time as Server-Sent Events (SSE) for instant UI responsiveness.
    """
    user_id = current_user.sub if current_user else None
    conv_id = request.conversation_id
    if is_db_configured() and conv_id:
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required to access conversation history."
            )
        ownership = chat_service.conversation_service.check_conversation_ownership(conv_id, user_id)
        if ownership == "forbidden":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: You do not have permission to access this conversation."
            )

    try:
        return StreamingResponse(
            chat_service.stream_question(request, user_id=user_id),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"
            }
        )
    except HTTPException:
        raise
    except GroqConfigurationError as ge:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Groq API service is not configured: {str(ge)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred while streaming your answer: {str(e)}"
        )


@router.post(
    "/transcribe",
    response_model=TranscribeResponse,
    summary="Transcribe spoken audio recording to text via Groq Whisper"
)
async def transcribe_audio_endpoint(
    file: UploadFile = File(...),
    chat_service: ChatService = Depends(get_chat_service)
):
    """
    Transcribe microphone audio using Groq's official whisper-large-v3-turbo model.
    Includes clinical Perfusion Technology terminology priming for high accuracy.
    """
    try:
        file_bytes = await file.read()
        if not file_bytes:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty audio recording uploaded.")

        filename = file.filename or "audio.webm"
        text = chat_service.transcribe_audio(file_bytes=file_bytes, filename=filename)
        return TranscribeResponse(text=text)
    except HTTPException:
        raise
    except GroqConfigurationError as ge:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Groq API service is not configured: {str(ge)}"
        )
    except GroqAPIError as ae:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Audio transcription failed: {str(ae)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred while transcribing audio: {str(e)}"
        )


