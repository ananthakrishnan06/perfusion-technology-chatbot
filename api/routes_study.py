from fastapi import APIRouter, Depends, HTTPException, status
from schemas.chat import MCQRequest, MCQResponse
from services.chat_service import ChatService
from generation.groq_client import GroqConfigurationError, GroqAPIError
from api.dependencies import get_chat_service

router = APIRouter(prefix="/study", tags=["Study & MCQs"])


@router.post(
    "/mcq",
    response_model=MCQResponse,
    summary="Generate evidence-grounded multiple-choice study questions"
)
def generate_study_mcq(
    request: MCQRequest,
    chat_service: ChatService = Depends(get_chat_service)
):
    """
    Generate multiple-choice questions on a perfusion topic derived from indexed PDF evidence.
    
    Returns 4 answer choices, the correct option, educational explanation, and citations.
    If evidence is insufficient, returns an explicit insufficient evidence notice.
    """
    try:
        response = chat_service.generate_study_mcqs(request)
        if response.insufficient_evidence:
            return response
        return response
    except GroqConfigurationError as ge:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Groq API service is not configured: {str(ge)}"
        )
    except GroqAPIError as ae:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Groq question generation failed: {str(ae)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred while generating study questions: {str(e)}"
        )

