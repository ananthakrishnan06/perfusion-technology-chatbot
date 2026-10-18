import json
import logging
import re
from typing import List, Optional, Tuple
from config import settings
from schemas.chat import ChatMessage, ChatResponse, Citation, MCQItem, MCQOption, MCQResponse, RetrievalMeta
from schemas.retrieval import RetrievedChunk
from generation.groq_client import GroqClientWrapper, GroqError
from generation.prompts import build_chat_messages, build_mcq_messages
from generation.exam_calibrator import detect_exam_marks, get_exam_configuration, ExamConfig

logger = logging.getLogger(__name__)

INSUFFICIENT_EVIDENCE_PHRASE = "I could not find sufficient supporting information in the indexed Perfusion Technology documents to answer this question reliably."


def clean_generated_answer(text: str) -> str:
    """
    Ensure the generated answer contains purely clinical content:
    - Removes parenthetical and bracketed source citations (e.g. '(Source: ...)', '[Source: ...]', '(wa0023.pdf, p. 4)').
    - Removes word count metadata and target declarations (e.g. '(Word count: ~960...)', 'Word count: 550').
    - Cleans up trailing metadata lines and extra whitespace.
    """
    if not text:
        return ""

    cleaned = text

    # 1. Remove explicit word count blocks and annotations (handles nested parentheses as well)
    cleaned = re.sub(r'(?i)[\(\[\*#_]*\s*(?:total\s+)?word\s*count[\*#_]*\s*:[^\n]*', '', cleaned)
    cleaned = re.sub(r'(?i)\(\s*approx(?:\.|imately)?\s*\d+\s*(?:-\s*\d+)?\s*words?[^\n]*', '', cleaned)
    cleaned = re.sub(r'(?i)\(\s*(?:within\s+the\s+)?\d+[\s–-]+\d+\s*-?\s*word\s+target[^\n]*', '', cleaned)
    cleaned = re.sub(r'(?i)\(\s*target\s*:\s*~?\s*\d+\s*words?[^\n]*', '', cleaned)

    # 2. Remove in-text citations like (Source: ...), [Source: ...]
    cleaned = re.sub(r'(?i)\(\s*source\s*:[^)]*\)', '', cleaned)
    cleaned = re.sub(r'(?i)\[\s*source\s*:[^\]]*\]', '', cleaned)
    cleaned = re.sub(r'(?i)\(\s*ref(?:\.|erence)?\s*:[^)]*\)', '', cleaned)
    cleaned = re.sub(r'(?i)\[\s*ref(?:\.|erence)?\s*:[^\]]*\]', '', cleaned)
    # File citations like (.pdf, p. 12)
    cleaned = re.sub(r'\([^\)]*\.pdf(?:[^\)]*p(?:p)?\.?\s*\d+)?\)', '', cleaned)
    cleaned = re.sub(r'\[[^\]]*\.pdf(?:[^\]]*p(?:p)?\.?\s*\d+)?\]', '', cleaned)
    # Standalone page citations like (p. 12), (pp. 12-14), (page 6)
    cleaned = re.sub(r'\(\s*p(?:p|age|ages)?\.?\s*\d+(?:\s*[-–]\s*\d+)?\s*\)', '', cleaned)
    cleaned = re.sub(r'\[\s*p(?:p|age|ages)?\.?\s*\d+(?:\s*[-–]\s*\d+)?\s*\]', '', cleaned)

    # Clean double spaces before punctuation from stripped parens
    cleaned = re.sub(r'[ \t]+\.', '.', cleaned)
    cleaned = re.sub(r'[ \t]+,', ',', cleaned)
    cleaned = re.sub(r'[ \t]{2,}', ' ', cleaned)

    # 3. Clean trailing meta lines
    lines = cleaned.splitlines()
    while lines and re.search(r'(?i)^\s*[\*_#\(\[]*(?:word\s*count|references?|sources?|target)[\*_#\(\]]*\s*:?.*$', lines[-1].strip()):
        lines.pop()
    cleaned = '\n'.join(lines).strip()
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)

    return cleaned


class AnswerGenerator:
    """
    Coordinates evidence-grounded answer generation, programmatic citation extraction,
    and multiple-choice study question formulation.
    """

    def __init__(self, groq_client: Optional[GroqClientWrapper] = None):
        self.groq_client = groq_client or GroqClientWrapper()

    @staticmethod
    def build_citations_from_chunks(chunks: List[RetrievedChunk], max_citations: int = 5) -> List[Citation]:
        """
        Extract unique citations directly from retrieved passage chunks.
        Avoids duplicate (source, page, chunk_id) tuples.
        """
        citations: List[Citation] = []
        seen_keys = set()

        for chunk in chunks[:max_citations]:
            key = (chunk.source, chunk.page, chunk.chunk_id)
            if key not in seen_keys:
                seen_keys.add(key)
                # Build concise excerpt (first 250 characters or first full sentence)
                excerpt = chunk.text.strip().replace("\n", " ")
                if len(excerpt) > 280:
                    period_idx = excerpt[:280].rfind(". ")
                    if period_idx > 80:
                        excerpt = excerpt[:period_idx + 1]
                    else:
                        excerpt = excerpt[:280] + "..."

                citations.append(Citation(
                    source=chunk.source,
                    page=chunk.page,
                    chunk_id=chunk.chunk_id,
                    excerpt=excerpt
                ))

        return citations

    def contextualize_query(
        self,
        question: str,
        conversation_history: Optional[List[ChatMessage]] = None
    ) -> str:
        """
        If conversation history exists and question is referential (e.g. 'make it easier',
        'explain that in simpler terms', 'what about the second point'), rewrite it into
        a standalone search query so that hybrid retrieval finds the appropriate textbook passages.
        """
        if not conversation_history:
            return question

        # Clean any appended client-side instructions for search query detection
        clean_q = re.sub(r"\[Instruction:.*?\]", "", question, flags=re.DOTALL).strip()
        if not clean_q:
            clean_q = question

        q_words = clean_q.split()

        # Check for referential pronouns or conversational directives that actually depend on prior turn
        referential_pronouns = r"\b(it|its|this|that|these|those|the above|previous|earlier|former|latter)\b"
        followup_directives = r"\b(easier|simpler|simplify|break it down|more detail|tell me more|expand on|what about the)\b"

        has_pronoun = bool(re.search(referential_pronouns, clean_q, re.IGNORECASE))
        has_directive = bool(re.search(followup_directives, clean_q, re.IGNORECASE))

        # If prompt is comprehensive (>= 15 words) and not an explicit short follow-up directive,
        # preserve the full query so hybrid retrieval matches all clinical scenario details and variables.
        if len(q_words) >= 15 and not re.search(r"^\s*(?:make|explain|break|summarize|simplify)\s+(?:the\s+above|it|this|that)", clean_q, re.IGNORECASE):
            return clean_q

        # If question is self-contained (has >= 4 words and lacks backward-referencing pronouns/directives),
        # return it directly. This avoids a 500-1000ms sequential Groq LLM network call!
        if not has_pronoun and not has_directive and len(q_words) >= 4:
            return clean_q

        # Construct prompt for fast Groq query contextualization only when truly needed
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a search query reformulator for a medical perfusion knowledge base. "
                    "Given the recent conversation history and a follow-up user prompt, rewrite the follow-up "
                    "into a concise, standalone keyword search query (maximum 8-10 words) that captures the core medical topic. "
                    "Do NOT answer the question. Output ONLY the standalone search query text."
                )
            }
        ]

        # Add recent conversation turns
        for turn in conversation_history[-3:]:
            messages.append({"role": turn.role, "content": turn.content[:300]})

        messages.append({
            "role": "user",
            "content": f"Follow-up: {clean_q}\nStandalone medical search query:"
        })

        try:
            standalone_query = self.groq_client.generate_chat_completion(
                messages=messages,
                max_tokens=40,
                temperature=0.0
            ).strip().strip('"').strip("'")
            if standalone_query and len(standalone_query) > 2:
                logger.info(f"Contextualized follow-up query '{clean_q}' -> '{standalone_query}'")
                return standalone_query
        except Exception as e:
            logger.warning(f"Query contextualization failed: {e}. Falling back to combined query.")

        # Fallback: combine last user topic with follow-up
        last_user_query = ""
        for turn in reversed(conversation_history):
            if turn.role == "user":
                last_user_query = re.sub(r"\[Instruction:.*?\]", "", turn.content, flags=re.DOTALL).strip()
                break
        return f"{last_user_query} {clean_q}".strip()

    def generate_answer(
        self,
        question: str,
        retrieved_chunks: List[RetrievedChunk],
        conversation_history: Optional[List[ChatMessage]] = None,
        exam_config: Optional[ExamConfig] = None
    ) -> ChatResponse:
        """
        Generate evidence-grounded answer using retrieved chunks, calibrated to exam marks.
        """
        if exam_config is None:
            detected_marks = detect_exam_marks(question)
            exam_config = get_exam_configuration(detected_marks)

        # If no chunks were retrieved or scores are too low, return insufficient evidence immediately
        if not retrieved_chunks:
            return ChatResponse(
                answer=INSUFFICIENT_EVIDENCE_PHRASE,
                grounded=False,
                insufficient_evidence=True,
                citations=[],
                retrieval=RetrievalMeta(method="hybrid", retrieved_chunks=0),
                exam_marks=exam_config.marks if exam_config else None,
                target_words=exam_config.target_words if exam_config else None
            )

        messages = build_chat_messages(
            question=question,
            retrieved_chunks=retrieved_chunks,
            conversation_history=conversation_history,
            exam_config=exam_config
        )

        max_tokens = exam_config.recommended_max_tokens if exam_config else None

        try:
            raw_answer = self.groq_client.generate_chat_completion(
                messages=messages,
                max_tokens=max_tokens
            )
        except GroqError as e:
            logger.error(f"Groq generation error: {e}")
            raise

        # Check if the generated response flagged insufficient evidence
        is_insufficient = (
            INSUFFICIENT_EVIDENCE_PHRASE.lower() in raw_answer.lower()
            or "could not find sufficient" in raw_answer.lower()
            or "insufficient supporting information" in raw_answer.lower()
        )

        citations = [] if is_insufficient else self.build_citations_from_chunks(retrieved_chunks)

        cleaned_answer = clean_generated_answer(raw_answer)

        return ChatResponse(
            answer=cleaned_answer,
            grounded=not is_insufficient,
            insufficient_evidence=is_insufficient,
            citations=citations,
            retrieval=RetrievalMeta(
                method=retrieved_chunks[0].retrieval_method if retrieved_chunks else "hybrid",
                retrieved_chunks=len(retrieved_chunks)
            ),
            exam_marks=exam_config.marks if exam_config else None,
            target_words=exam_config.target_words if exam_config else None
        )

    def stream_answer(
        self,
        question: str,
        retrieved_chunks: List[RetrievedChunk],
        conversation_history: Optional[List[ChatMessage]] = None,
        exam_config: Optional[ExamConfig] = None
    ):
        """
        Stream tokens directly from Groq for the given question and retrieved passages.
        Yields individual token strings in real time for instant UI responsiveness.
        """
        if not retrieved_chunks:
            yield INSUFFICIENT_EVIDENCE_PHRASE
            return

        messages = build_chat_messages(
            question=question,
            retrieved_chunks=retrieved_chunks,
            conversation_history=conversation_history,
            exam_config=exam_config
        )

        max_tokens = exam_config.recommended_max_tokens if exam_config else None
        for token in self.groq_client.stream_chat_completion(messages=messages, max_tokens=max_tokens):
            yield token

    def generate_mcqs(
        self,
        topic: str,
        num_questions: int,
        difficulty: str,
        retrieved_chunks: List[RetrievedChunk]
    ) -> MCQResponse:
        """
        Generate multiple-choice study questions grounded in retrieved passages.
        """
        if not retrieved_chunks:
            return MCQResponse(
                topic=topic,
                questions=[],
                total_questions=0,
                insufficient_evidence=True,
                citations=[]
            )

        messages = build_mcq_messages(
            topic=topic,
            num_questions=num_questions,
            difficulty=difficulty,
            retrieved_chunks=retrieved_chunks
        )

        try:
            raw_response = self.groq_client.generate_chat_completion(
                messages=messages,
                response_format={"type": "json_object"}
            )
        except GroqError as e:
            logger.error(f"Groq MCQ generation error: {e}")
            raise

        # Parse JSON
        chunk_map = {c.chunk_id: c for c in retrieved_chunks}
        all_citations = self.build_citations_from_chunks(retrieved_chunks)

        try:
            # Extract JSON block if wrapped in markdown code blocks
            clean_json = raw_response.strip()
            if clean_json.startswith("```json"):
                clean_json = clean_json[7:]
            if clean_json.startswith("```"):
                clean_json = clean_json[3:]
            if clean_json.endswith("```"):
                clean_json = clean_json[:-3]
            clean_json = clean_json.strip()

            parsed = json.loads(clean_json)

            if parsed.get("error") == "insufficient_evidence":
                return MCQResponse(
                    topic=topic,
                    questions=[],
                    total_questions=0,
                    insufficient_evidence=True,
                    citations=[]
                )

            questions_data = parsed.get("questions", [])
            mcq_items: List[MCQItem] = []

            for q in questions_data:
                options = [
                    MCQOption(key=opt["key"], text=opt["text"])
                    for opt in q.get("options", [])
                ]

                # Resolve supporting citation if chunk ID specified
                sup_id = q.get("supporting_chunk_id")
                q_citations = []
                if sup_id and sup_id in chunk_map:
                    q_citations = self.build_citations_from_chunks([chunk_map[sup_id]])
                if not q_citations:
                    q_citations = all_citations[:1]

                mcq_items.append(MCQItem(
                    question=q.get("question", ""),
                    options=options,
                    correct_answer=q.get("correct_answer", "A"),
                    explanation=q.get("explanation", ""),
                    citations=q_citations
                ))

            return MCQResponse(
                topic=topic,
                questions=mcq_items,
                total_questions=len(mcq_items),
                insufficient_evidence=False,
                citations=all_citations
            )

        except Exception as e:
            logger.error(f"Failed to parse MCQ JSON output: {e}\nRaw output: {raw_response}")
            return MCQResponse(
                topic=topic,
                questions=[],
                total_questions=0,
                insufficient_evidence=True,
                citations=[]
            )

