from typing import Any, List, Optional
from pydantic import BaseModel, Field, field_validator


class ChatMessage(BaseModel):
    """A single turn in optional conversation history."""
    role: str = Field(default="user", description="Role: 'user' or 'assistant'")
    content: str = Field(..., max_length=50000, description="Message text")

    @field_validator("role", mode="before")
    @classmethod
    def normalize_role(cls, v: Any) -> str:
        s = str(v or "user").lower().strip()
        if s in ("user", "human"):
            return "user"
        return "assistant"

    @field_validator("content", mode="before")
    @classmethod
    def normalize_content(cls, v: Any) -> str:
        s = str(v or "").strip()
        return s if s else "..."


class ChatRequest(BaseModel):
    """Request payload for asking a question."""
    question: str = Field(..., min_length=1, max_length=30000, description="User question")
    document_ids: Optional[List[str]] = Field(
        default=None,
        description="Optional list of document IDs to restrict search to. Searches all active documents if omitted or empty."
    )
    top_k: int = Field(default=5, ge=1, le=20, description="Number of passages to retrieve for grounding")
    conversation_history: Optional[List[ChatMessage]] = Field(
        default=None,
        description="Optional recent conversation turns for context continuity"
    )
    conversation_id: Optional[str] = Field(
        default=None,
        description="Optional persistent conversation session ID for PostgreSQL storage & memory"
    )

    @field_validator("conversation_id", mode="before")
    @classmethod
    def sanitize_conversation_id(cls, v: Any) -> Optional[str]:
        if not v:
            return None
        s = str(v).strip()
        if s.lower() in ("null", "undefined", "none", "", "false"):
            return None
        return s


class Citation(BaseModel):
    """Source citation referencing an authentic passage from an uploaded PDF."""
    source: str = Field(..., description="Original PDF filename")
    page: int = Field(..., ge=1, description="Original 1-based PDF page number")
    chunk_id: str = Field(..., description="Unique chunk identifier")
    excerpt: str = Field(..., description="Exact supporting text excerpt from the document")


class RetrievalMeta(BaseModel):
    """Retrieval metadata returned with answer."""
    method: str = Field(default="hybrid", description="Retrieval method used (e.g. hybrid, semantic, bm25)")
    retrieved_chunks: int = Field(..., description="Number of chunks retrieved and supplied as context")


class ChatResponse(BaseModel):
    """Standardized response from the PerfusionGPT assistant."""
    answer: str = Field(..., description="Evidence-grounded answer or insufficient evidence notice")
    grounded: bool = Field(..., description="True if answer is backed by retrieved evidence")
    insufficient_evidence: bool = Field(..., description="True if indexed documents lacked sufficient evidence")
    citations: List[Citation] = Field(default_factory=list, description="List of source citations used")
    retrieval: RetrievalMeta = Field(..., description="Retrieval metadata")
    conversation_id: Optional[str] = Field(default=None, description="Active persistent conversation session ID")
    exam_marks: Optional[int] = Field(default=None, description="Detected exam marks tier (e.g. 3, 5, 10)")
    target_words: Optional[int] = Field(default=None, description="Target word count based on marks")


# Study / Multiple-Choice Questions schemas
class MCQOption(BaseModel):
    """A single multiple choice option."""
    key: str = Field(..., description="Option letter: A, B, C, or D")
    text: str = Field(..., description="Option text")


class MCQItem(BaseModel):
    """A generated multiple-choice question item."""
    question: str
    options: List[MCQOption]
    correct_answer: str = Field(..., description="The correct option key (e.g., 'A', 'B', 'C', or 'D')")
    explanation: str = Field(..., description="Educational explanation grounded in the retrieved sources")
    citations: List[Citation] = Field(default_factory=list, description="Supporting PDF citations")


class MCQRequest(BaseModel):
    """Request payload to generate multiple-choice study questions."""
    topic: str = Field(..., min_length=2, max_length=5000, description="Perfusion topic (e.g., 'Centrifugal pumps', 'Arterial filters')")
    num_questions: int = Field(default=3, ge=1, le=10, description="Number of questions to generate (1 to 10)")
    document_ids: Optional[List[str]] = Field(default=None, description="Optional document IDs filter")
    difficulty: Optional[str] = Field(default="intermediate", description="Difficulty level: beginner, intermediate, advanced")


class MCQResponse(BaseModel):
    """Response containing generated multiple-choice study questions."""
    topic: str
    questions: List[MCQItem]
    total_questions: int
    insufficient_evidence: bool = False
    citations: List[Citation] = Field(default_factory=list)

