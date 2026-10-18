from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from schemas.chat import ChatRequest, ChatResponse
from services.chat_service import ChatService
from generation.groq_client import GroqConfigurationError, GroqAPIError
from api.dependencies import get_chat_service

router = APIRouter(prefix="/chat", tags=["Chat"])


@router.post(
    "/ask",
    response_model=ChatResponse,
    summary="Ask an evidence-grounded Perfusion Technology question"
)
def ask_question(
    request: ChatRequest,
    chat_service: ChatService = Depends(get_chat_service)
):
    """
    Ask a question grounded in the uploaded Perfusion Technology documents.
    
    Retrieves the most relevant passages using hybrid FAISS and BM25 search,
    synthesizes an evidence-grounded answer via Groq API, and returns verifiable
    source citations with 1-based original PDF page numbers.
    """
    try:
        return chat_service.ask_question(request)
    except GroqConfigurationError as ge:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Groq API service is not configured: {str(ge)}"
        )
    except GroqAPIError as ae:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Groq generation failed: {str(ae)}"
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
    chat_service: ChatService = Depends(get_chat_service)
):
    """
    Stream tokens in real-time as Server-Sent Events (SSE) for instant UI responsiveness.
    """
    try:
        return StreamingResponse(
            chat_service.stream_question(request),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"
            }
        )
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

