import logging
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

logger = logging.getLogger(__name__)

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
        logger.error(f"LLM configuration error in ask_question: {ge}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI generation service is not properly configured. Please contact the administrator."
        )
    except (GroqAPIError, GeminiAPIError) as ae:
        logger.error(f"LLM generation error in ask_question: {ae}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI generation service encountered an upstream provider error. Please try again."
        )
    except Exception as e:
        logger.error(f"Unhandled error in ask_question: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while answering your question. Please try again."
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
    except (GroqConfigurationError, GeminiConfigurationError) as ge:
        logger.error(f"LLM configuration error in stream_question: {ge}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI generation service is not properly configured. Please contact the administrator."
        )
    except (GroqAPIError, GeminiAPIError) as ae:
        logger.error(f"LLM generation error in stream_question: {ae}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI generation service encountered an upstream provider error. Please try again."
        )
    except Exception as e:
        logger.error(f"Unhandled error in stream_question: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while streaming your answer. Please try again."
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
        # Validate audio recording size (max 25MB) incrementally in chunks
        max_audio_bytes = 25 * 1024 * 1024
        total_audio = 0
        audio_chunks = []
        while True:
            chunk = await file.read(64 * 1024)
            if not chunk:
                break
            total_audio += len(chunk)
            if total_audio > max_audio_bytes:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail="Audio recording exceeds 25 MB size limit."
                )
            audio_chunks.append(chunk)

        file_bytes = b"".join(audio_chunks)
        if not file_bytes:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty audio recording uploaded.")

        filename = file.filename or "audio.webm"
        text = chat_service.transcribe_audio(file_bytes=file_bytes, filename=filename)
        return TranscribeResponse(text=text)
    except HTTPException:
        raise
    except GroqConfigurationError as ge:
        logger.error(f"Transcription configuration error: {ge}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Audio transcription service is not configured."
        )
    except GroqAPIError as ae:
        logger.error(f"Transcription generation failed: {ae}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Audio transcription failed due to an upstream service error. Please try again."
        )
    except Exception as e:
        logger.error(f"Unhandled error in transcribe: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while transcribing your audio recording. Please try again."
        )


