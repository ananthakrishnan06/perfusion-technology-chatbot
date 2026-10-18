import json
import logging
import re
import threading
from typing import List, Optional
from config import settings
from schemas.chat import ChatMessage, ChatRequest, ChatResponse, MCQRequest, MCQResponse, RetrievalMeta
from retrieval.hybrid_search import HybridRetriever
from generation.answer_generator import AnswerGenerator, clean_generated_answer, INSUFFICIENT_EVIDENCE_PHRASE
from generation.exam_calibrator import detect_exam_marks, get_exam_configuration
from services.conversation_service import ConversationService
from storage.db import is_db_configured

logger = logging.getLogger(__name__)


class ChatService:
    """
    Coordinates evidence-grounded chat, study question generation,
    PostgreSQL conversation history, and long-term memory.
    """

    def __init__(
        self,
        hybrid_retriever: HybridRetriever,
        answer_generator: AnswerGenerator,
        conversation_service: Optional[ConversationService] = None
    ):
        self.hybrid_retriever = hybrid_retriever
        self.answer_generator = answer_generator
        self.conversation_service = conversation_service or ConversationService()

    def _detect_mentioned_documents(self, question: str) -> Optional[List[str]]:
        """
        Detect if a user prompt explicitly mentions or targets a known document filename or title.
        """
        q_lower = question.lower()
        all_docs = self.hybrid_retriever.metadata_store.list_documents()
        matched_doc_ids = []

        for doc in all_docs:
            fname = doc.filename or ""
            fname_lower = fname.lower()
            fname_stem = fname_lower.rsplit(".", 1)[0] if "." in fname_lower else fname_lower

            # Check full filename or stem
            if fname_lower in q_lower or (len(fname_stem) > 5 and fname_stem in q_lower):
                matched_doc_ids.append(doc.document_id)
                continue

            # Check significant sub-phrases / keywords in the filename
            keywords_by_doc = {
                "frequency": ["frequency master", "frequency_master", "rguhs question bank"],
                "ghosh": ["sunit ghosh", "sunith ghosh", "ghosh cpb", "ghosh"],
                "galletti": ["galletti", "christina mora", "mora cpb", "mora"],
                "wa0023": ["wa0023", "curriculum textbook", "799 page"]
            }
            for key, phrases in keywords_by_doc.items():
                if key in fname_lower and any(p in q_lower for p in phrases):
                    matched_doc_ids.append(doc.document_id)
                    break

        return matched_doc_ids if matched_doc_ids else None

    def ask_question(self, request: ChatRequest) -> ChatResponse:
        """
        Retrieve relevant evidence and generate an evidence-grounded answer using Groq.
        Persists turns and memorizes clinical facts in PostgreSQL when configured.
        """
        top_k = request.top_k or settings.TOP_K_FINAL

        # Clean user question from any client instructions
        clean_q = re.sub(r"\[Instruction:.*?\]", "", request.question, flags=re.DOTALL).strip()
        clean_q = clean_q.split("\n\n[Instruction:")[0].strip() or request.question

        # Detect exam marks specified in student query (e.g., 3 marks, 5M, (10 marks))
        detected_marks = detect_exam_marks(request.question) or detect_exam_marks(clean_q)
        exam_config = get_exam_configuration(detected_marks)
        if exam_config:
            # Scale retrieval depth to give broader evidence for multi-page answers
            top_k = max(top_k, exam_config.recommended_top_k)
        elif len(clean_q.split()) >= 35 or len(clean_q) >= 200:
            # Scale retrieval depth for comprehensive, multi-part, or case study prompts
            top_k = max(top_k, 8)

        # 1. Resolve document scope: explicit document_ids take priority, otherwise auto-detect from question
        document_ids = request.document_ids
        if not document_ids:
            document_ids = self._detect_mentioned_documents(clean_q)

        # 2. Manage PostgreSQL conversation session and retrieve stored clinical memories
        conv_id = request.conversation_id
        memory_context = ""
        if is_db_configured():
            try:
                memory_context = self.conversation_service.format_memory_context(limit=5)
                if not conv_id:
                    clean_title = clean_q.split("\n")[0][:60].strip() or "Clinical Inquiry"
                    created = self.conversation_service.create_conversation(title=clean_title)
                    if created:
                        conv_id = created["id"]
            except Exception as e:
                logger.warning(f"PostgreSQL memory lookup note: {e}")

        # Quick friendly handling for greetings / identity questions
        normalized = clean_q.lower().strip().rstrip("!?.,")
        if normalized in ("hi", "hello", "hey", "good morning", "good afternoon", "good evening", "who are you", "what can you do"):
            greeting_reply = (
                "Hello! I am **Perfusion AI**, your clinical decision support and educational assistant for Perfusion Technology. "
                "I am connected to your curriculum textbooks, clinical guidelines, and remote Cloud PostgreSQL database (with multi-turn session persistence and clinical memory). "
                "You can ask clinical questions, explore bypass circuit setups, check priming protocols, or review board exam topics. How can I help you today?"
            )
            chat_response = ChatResponse(
                answer=greeting_reply,
                grounded=True,
                insufficient_evidence=False,
                citations=[],
                retrieval=RetrievalMeta(method="direct_greeting", retrieved_chunks=0),
                conversation_id=conv_id,
                exam_marks=exam_config.marks if exam_config else None,
                target_words=exam_config.target_words if exam_config else None
            )
            if is_db_configured() and conv_id:
                try:
                    self.conversation_service.add_turn(
                        conversation_id=conv_id,
                        user_content=clean_q,
                        assistant_content=greeting_reply,
                        citations=[],
                        grounded=True
                    )
                except Exception as e:
                    logger.error(f"Failed to persist greeting turn in PostgreSQL: {e}")
            return chat_response

        # 3. Contextualize query if conversation history is present (for follow-ups like 'make it easier')
        search_query = self.answer_generator.contextualize_query(
            question=request.question,
            conversation_history=request.conversation_history
        )

        # If exam marks specified, strip mark notation from search_query so BM25 focuses strictly on medical concepts
        if exam_config:
            cleaned_search = re.sub(
                r'(?:\b|\()(?:\d{1,2})\s*(?:marks?|mark|[Mm])\b(?:\))?',
                ' ',
                search_query,
                flags=re.IGNORECASE
            ).strip()
            search_query = re.sub(r'\s+', ' ', cleaned_search).strip() or search_query

        # If scoped to a specific document, clean the query from filename noise so search focuses on concepts
        if document_ids and len(document_ids) == 1:
            doc = self.hybrid_retriever.metadata_store.get_document(document_ids[0])
            if doc and doc.filename:
                fname = doc.filename
                fname_stem = fname.rsplit(".", 1)[0] if "." in fname else fname
                cleaned = search_query
                for term in [fname, fname_stem, ".pdf", ".PDF"]:
                    cleaned = cleaned.replace(term, " ")
                cleaned = cleaned.strip()
                # Clean filler words that might be left after removing filename
                for filler in ["summarize key principles in", "summarize in", "principles in", "in", "about"]:
                    if cleaned.lower() == filler:
                        cleaned = ""
                        break
                if not cleaned:
                    search_query = "introduction overview key principles topics summary"
                else:
                    search_query = cleaned
            top_k = max(top_k, 7)

        # 4. Retrieve relevant passages using the contextualized query
        retrieved_chunks = self.hybrid_retriever.retrieve(
            query=search_query,
            document_ids=document_ids,
            top_k=top_k
        )

        # 5. Build effective conversation history, prepending memory context if available
        effective_history = list(request.conversation_history or [])
        if memory_context:
            # Prepend system-level memory reminder as a prior assistant context turn if history is short
            effective_history.insert(0, ChatMessage(
                role="assistant",
                content=f"[Stored Clinical Memory]: {memory_context}"
            ))

        # 6. Generate answer calibrated to exam marks
        chat_response = self.answer_generator.generate_answer(
            question=request.question,
            retrieved_chunks=retrieved_chunks,
            conversation_history=effective_history,
            exam_config=exam_config
        )
        chat_response.conversation_id = conv_id
        if exam_config:
            chat_response.exam_marks = exam_config.marks
            chat_response.target_words = exam_config.target_words

        # 7. Persist conversation turn and extract clinical memories into PostgreSQL
        if is_db_configured() and conv_id:
            try:
                import threading
                citations_dump = [c.model_dump() if hasattr(c, "model_dump") else c.dict() for c in chat_response.citations]
                self.conversation_service.add_turn(
                    conversation_id=conv_id,
                    user_content=clean_q,
                    assistant_content=chat_response.answer,
                    citations=citations_dump,
                    grounded=chat_response.grounded
                )
                # Run memory extraction in a lightweight background thread to avoid delaying response delivery
                threading.Thread(
                    target=self.conversation_service.extract_and_memorize,
                    args=(conv_id, clean_q, chat_response.answer),
                    daemon=True
                ).start()
            except Exception as e:
                logger.error(f"Failed to persist chat turn in PostgreSQL: {e}")

        return chat_response

    def generate_study_mcqs(self, request: MCQRequest) -> MCQResponse:
        """
        Retrieve evidence for a perfusion topic and generate educational MCQs.
        """
        # Retrieve passages for the topic (retrieve slightly more context for MCQ creation)
        retrieved_chunks = self.hybrid_retriever.retrieve(
            query=request.topic,
            document_ids=request.document_ids,
            top_k=min(10, max(5, request.num_questions * 2))
        )

        return self.answer_generator.generate_mcqs(
            topic=request.topic,
            num_questions=request.num_questions,
            difficulty=request.difficulty or "intermediate",
            retrieved_chunks=retrieved_chunks
        )

    def stream_question(self, request: ChatRequest):
        """
        Stream an evidence-grounded answer as Server-Sent Events (SSE).
        Emits metadata, tokens in real time, and persists the turn on completion.
        """
        top_k = request.top_k or settings.TOP_K_FINAL

        clean_q = re.sub(r"\[Instruction:.*?\]", "", request.question, flags=re.DOTALL).strip()
        clean_q = clean_q.split("\n\n[Instruction:")[0].strip() or request.question

        detected_marks = detect_exam_marks(request.question) or detect_exam_marks(clean_q)
        exam_config = get_exam_configuration(detected_marks)
        if exam_config:
            top_k = max(top_k, exam_config.recommended_top_k)
        elif len(clean_q.split()) >= 35 or len(clean_q) >= 200:
            top_k = max(top_k, 8)

        document_ids = request.document_ids
        if not document_ids:
            document_ids = self._detect_mentioned_documents(clean_q)

        conv_id = request.conversation_id
        memory_context = ""
        if is_db_configured():
            try:
                memory_context = self.conversation_service.format_memory_context(limit=5)
                if not conv_id:
                    clean_title = clean_q.split("\n")[0][:60].strip() or "Clinical Inquiry"
                    created = self.conversation_service.create_conversation(title=clean_title)
                    if created:
                        conv_id = created["id"]
            except Exception as e:
                logger.warning(f"PostgreSQL memory lookup note: {e}")

        # Quick friendly handling for greetings / identity questions
        normalized = clean_q.lower().strip().rstrip("!?.,")
        if normalized in ("hi", "hello", "hey", "good morning", "good afternoon", "good evening", "who are you", "what can you do"):
            greeting_reply = (
                "Hello! I am **Perfusion AI**, your clinical decision support and educational assistant for Perfusion Technology. "
                "I am connected to your curriculum textbooks, clinical guidelines, and remote Cloud PostgreSQL database (with multi-turn session persistence and clinical memory). "
                "You can ask clinical questions, explore bypass circuit setups, check priming protocols, or review board exam topics. How can I help you today?"
            )
            meta = {
                "type": "meta",
                "conversation_id": conv_id,
                "grounded": True,
                "exam_marks": exam_config.marks if exam_config else None,
                "target_words": exam_config.target_words if exam_config else None
            }
            yield f"data: {json.dumps(meta)}\n\n"
            yield f"data: {json.dumps({'type': 'token', 'content': greeting_reply})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'answer': greeting_reply})}\n\n"

            if is_db_configured() and conv_id:
                try:
                    self.conversation_service.add_turn(
                        conversation_id=conv_id,
                        user_content=clean_q,
                        assistant_content=greeting_reply,
                        citations=[],
                        grounded=True
                    )
                except Exception as e:
                    logger.error(f"Failed to persist greeting turn: {e}")
            return

        search_query = self.answer_generator.contextualize_query(
            question=request.question,
            conversation_history=request.conversation_history
        )

        if exam_config:
            cleaned_search = re.sub(
                r'(?:\b|\()(?:\d{1,2})\s*(?:marks?|mark|[Mm])\b(?:\))?',
                ' ',
                search_query,
                flags=re.IGNORECASE
            ).strip()
            search_query = re.sub(r'\s+', ' ', cleaned_search).strip() or search_query

        if document_ids and len(document_ids) == 1:
            doc = self.hybrid_retriever.metadata_store.get_document(document_ids[0])
            if doc and doc.filename:
                fname = doc.filename
                fname_stem = fname.rsplit(".", 1)[0] if "." in fname else fname
                cleaned = search_query
                for term in [fname, fname_stem, ".pdf", ".PDF"]:
                    cleaned = cleaned.replace(term, " ")
                cleaned = cleaned.strip()
                if not cleaned:
                    search_query = "introduction overview key principles topics summary"
                else:
                    search_query = cleaned
            top_k = max(top_k, 7)

        # Retrieve relevant passages concurrently (FAISS + BM25 in parallel)
        retrieved_chunks = self.hybrid_retriever.retrieve(
            query=search_query,
            document_ids=document_ids,
            top_k=top_k
        )

        meta = {
            "type": "meta",
            "conversation_id": conv_id,
            "grounded": bool(retrieved_chunks),
            "exam_marks": exam_config.marks if exam_config else None,
            "target_words": exam_config.target_words if exam_config else None
        }
        yield f"data: {json.dumps(meta)}\n\n"

        effective_history = list(request.conversation_history or [])
        if memory_context:
            effective_history.insert(0, ChatMessage(
                role="assistant",
                content=f"[Stored Clinical Memory]: {memory_context}"
            ))

        full_raw_answer = []
        for token in self.answer_generator.stream_answer(
            question=request.question,
            retrieved_chunks=retrieved_chunks,
            conversation_history=effective_history,
            exam_config=exam_config
        ):
            full_raw_answer.append(token)
            yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"

        complete_text = "".join(full_raw_answer)
        cleaned_answer = clean_generated_answer(complete_text)

        yield f"data: {json.dumps({'type': 'done', 'answer': cleaned_answer})}\n\n"

        # Background async persistence to PostgreSQL
        if is_db_configured() and conv_id:
            try:
                citations_dump = [c.model_dump() if hasattr(c, "model_dump") else c.dict() for c in self.answer_generator.build_citations_from_chunks(retrieved_chunks)]
                self.conversation_service.add_turn(
                    conversation_id=conv_id,
                    user_content=clean_q,
                    assistant_content=cleaned_answer,
                    citations=citations_dump,
                    grounded=bool(retrieved_chunks)
                )
                threading.Thread(
                    target=self.conversation_service.extract_and_memorize,
                    args=(conv_id, clean_q, cleaned_answer),
                    daemon=True
                ).start()
            except Exception as e:
                logger.error(f"Failed to persist stream turn: {e}")

