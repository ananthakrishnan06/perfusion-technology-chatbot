import logging
import uuid
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any, Tuple
from sqlalchemy.orm import Session
from storage.db import get_session_factory, is_db_configured
from storage.db_models import Conversation, Message, Memory

logger = logging.getLogger(__name__)


class ConversationService:
    """
    Service for managing persistent multi-turn chat sessions and long-term
    clinical memory in PostgreSQL, with strict user-level data isolation.
    """

    def __init__(self, session: Optional[Session] = None):
        self._session = session

    def _get_session(self) -> Optional[Session]:
        """Obtain active or new database session if PostgreSQL is configured."""
        if self._session is not None:
            return self._session
        factory = get_session_factory()
        if factory:
            return factory()
        return None

    # =========================================================================
    # CONVERSATION SESSION MANAGEMENT WITH USER ISOLATION
    # =========================================================================
    def create_conversation(
        self,
        user_id: str,
        title: str = "New Perfusion Inquiry",
        conversation_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Create a new conversation session assigned strictly to the authenticated user."""
        session = self._get_session()
        if not session:
            logger.warning("PostgreSQL not configured. Cannot persist conversation.")
            return None
        try:
            cid = conversation_id or str(uuid.uuid4())
            conv = Conversation(
                id=cid,
                user_id=user_id,
                title=title[:250]
            )
            session.add(conv)
            session.commit()
            session.refresh(conv)
            return conv.to_dict(include_messages=False)
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to create conversation for user {user_id}: {e}")
            return None
        finally:
            if self._session is None:
                session.close()

    def check_conversation_ownership(self, conversation_id: str, user_id: str) -> str:
        """
        Check ownership of a conversation.
        Returns:
            'ok'        -> Conversation exists and belongs to user (or unowned legacy claimed)
            'forbidden' -> Conversation belongs to a different user
            'not_found' -> Conversation does not exist
        """
        session = self._get_session()
        if not session:
            return "db_unavailable"
        try:
            conv = session.query(Conversation).filter(Conversation.id == conversation_id).first()
            if not conv:
                return "not_found"
            if conv.user_id and conv.user_id != user_id:
                return "forbidden"
            return "ok"
        except Exception as e:
            logger.error(f"Ownership check failed for {conversation_id}: {e}")
            return "error"
        finally:
            if self._session is None:
                session.close()

    def get_conversation(self, conversation_id: str, user_id: str) -> Tuple[Optional[Dict[str, Any]], str]:
        """
        Retrieve a conversation with all messages and citations, strictly verifying ownership.
        Returns (conversation_dict, status_string): ('ok', 'forbidden', or 'not_found').
        """
        session = self._get_session()
        if not session:
            return None, "db_unavailable"
        try:
            conv = session.query(Conversation).filter(Conversation.id == conversation_id).first()
            if not conv:
                return None, "not_found"
            # Strict ownership verification
            if conv.user_id != user_id:
                return None, "forbidden"
            return conv.to_dict(include_messages=True), "ok"
        except Exception as e:
            logger.error(f"Failed to fetch conversation {conversation_id} for user {user_id}: {e}")
            return None, "error"
        finally:
            if self._session is None:
                session.close()

    def list_conversations(
        self,
        user_id: str,
        limit: int = 50,
        search: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        List all recent conversations belonging strictly to the authenticated user.
        Unowned conversations or conversations from other users are strictly excluded.
        """
        session = self._get_session()
        if not session:
            return []
        try:
            query = session.query(Conversation).filter(Conversation.user_id == user_id)
            if search and search.strip():
                query = query.filter(Conversation.title.ilike(f"%{search.strip()}%"))
            convs = (
                query
                .order_by(Conversation.updated_at.desc())
                .limit(limit)
                .all()
            )
            return [c.to_dict(include_messages=False) for c in convs]
        except Exception as e:
            logger.error(f"Failed to list conversations for user {user_id}: {e}")
            return []
        finally:
            if self._session is None:
                session.close()

    def rename_conversation(
        self,
        conversation_id: str,
        user_id: str,
        title: str
    ) -> Tuple[Optional[Dict[str, Any]], str]:
        """
        Rename an existing conversation belonging to the authenticated user.
        Returns (conv_dict, status_string): ('ok', 'forbidden', 'not_found', or 'error').
        """
        session = self._get_session()
        if not session:
            return None, "db_unavailable"
        try:
            conv = session.query(Conversation).filter(Conversation.id == conversation_id).first()
            if not conv:
                return None, "not_found"
            if conv.user_id != user_id:
                return None, "forbidden"
            conv.title = title[:250].strip() or "Untitled Inquiry"
            conv.updated_at = datetime.now(timezone.utc)
            session.commit()
            session.refresh(conv)
            return conv.to_dict(include_messages=False), "ok"
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to rename conversation {conversation_id}: {e}")
            return None, "error"
        finally:
            if self._session is None:
                session.close()

    def delete_conversation(self, conversation_id: str, user_id: str) -> Tuple[bool, str]:
        """
        Delete a conversation and all its messages, strictly verifying user ownership.
        Returns (success_bool, status_string): ('ok', 'forbidden', 'not_found', or 'error').
        """
        session = self._get_session()
        if not session:
            return False, "db_unavailable"
        try:
            conv = session.query(Conversation).filter(Conversation.id == conversation_id).first()
            if not conv:
                return False, "not_found"
            if conv.user_id != user_id:
                return False, "forbidden"
            session.delete(conv)
            session.commit()
            return True, "ok"
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to delete conversation {conversation_id} for user {user_id}: {e}")
            return False, "error"
        finally:
            if self._session is None:
                session.close()

    def add_turn(
        self,
        conversation_id: str,
        user_id: str,
        user_content: str,
        assistant_content: str,
        citations: Optional[List[Dict[str, Any]]] = None,
        grounded: bool = True
    ) -> Tuple[bool, str]:
        """
        Batch persist both user and assistant message turns, strictly ensuring user ownership.
        Returns (success_bool, status_string).
        """
        session = self._get_session()
        if not session:
            return False, "db_unavailable"
        try:
            conv = session.query(Conversation).filter(Conversation.id == conversation_id).first()
            if not conv:
                conv = Conversation(
                    id=conversation_id,
                    user_id=user_id,
                    title=user_content[:60] + "..." if len(user_content) > 60 else user_content
                )
                session.add(conv)
                session.flush()
            else:
                if conv.user_id and conv.user_id != user_id:
                    return False, "forbidden"
                if not conv.user_id:
                    conv.user_id = user_id
                if conv.title == "New Perfusion Inquiry":
                    conv.title = user_content[:60] + "..." if len(user_content) > 60 else user_content

            user_msg = Message(
                id=str(uuid.uuid4()),
                conversation_id=conversation_id,
                role="user",
                content=user_content,
                citations=[],
                grounded=True
            )
            asst_msg = Message(
                id=str(uuid.uuid4()),
                conversation_id=conversation_id,
                role="assistant",
                content=assistant_content,
                citations=citations or [],
                grounded=grounded
            )
            session.add_all([user_msg, asst_msg])
            conv.updated_at = datetime.now(timezone.utc)
            session.commit()
            return True, "ok"
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to batch add turn to conversation {conversation_id}: {e}")
            return False, "error"
        finally:
            if self._session is None:
                session.close()

    # =========================================================================
    # USER-ISOLATED CLINICAL MEMORY ENGINE
    # =========================================================================
    def save_memory(
        self,
        user_id: str,
        key: str,
        content: str,
        category: str = "clinical_pearl",
        conversation_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Store a long-term memory entity isolated to the authenticated user."""
        session = self._get_session()
        if not session:
            return None
        try:
            existing = (
                session.query(Memory)
                .filter(Memory.user_id == user_id, Memory.key == key)
                .first()
            )
            if existing:
                existing.content = content
                existing.category = category
                existing.updated_at = datetime.now(timezone.utc)
                session.commit()
                session.refresh(existing)
                return existing.to_dict()

            mem = Memory(
                id=str(uuid.uuid4()),
                user_id=user_id,
                conversation_id=conversation_id,
                category=category,
                key=key[:95],
                content=content
            )
            session.add(mem)
            session.commit()
            session.refresh(mem)
            return mem.to_dict()
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to save memory for user {user_id}: {e}")
            return None
        finally:
            if self._session is None:
                session.close()

    def list_memories(self, user_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Retrieve stored long-term clinical memories isolated to the authenticated user."""
        session = self._get_session()
        if not session:
            return []
        try:
            memories = (
                session.query(Memory)
                .filter(Memory.user_id == user_id)
                .order_by(Memory.updated_at.desc())
                .limit(limit)
                .all()
            )
            return [m.to_dict() for m in memories]
        except Exception as e:
            logger.error(f"Failed to retrieve memories for user {user_id}: {e}")
            return []
        finally:
            if self._session is None:
                session.close()

    def format_memory_context(self, user_id: Optional[str] = None, limit: int = 5) -> str:
        """
        Format recent stored clinical memories into a prompt block for the LLM.
        Strictly isolated to user_id (returns empty string if user_id is None).
        """
        if not user_id:
            return ""
        memories = self.list_memories(user_id=user_id, limit=limit)
        if not memories:
            return ""

        lines = ["[Clinical Context & Stored Memories from Previous Sessions]"]
        for m in memories:
            lines.append(f"• {m['key']}: {m['content']}")
        return "\n".join(lines)

    def extract_and_memorize(
        self,
        conversation_id: str,
        user_id: str,
        user_text: str,
        assistant_text: str
    ) -> None:
        """
        Heuristic memory extractor: identifies clinical preferences and high-yield topics
        and persists them isolated to the authenticated user.
        """
        if not user_id:
            return
        u_lower = user_text.lower()

        # Check for explicit user preferences or case parameters
        if any(w in u_lower for w in ["i prefer", "my patient", "our protocol", "we use", "remember that", "note that"]):
            self.save_memory(
                user_id=user_id,
                key=f"User Clinical Context ({user_text[:35]}...)",
                content=user_text.strip(),
                category="user_preference",
                conversation_id=conversation_id
            )

        # Check for specific perfusion topics discussed
        perfusion_topics = {
            "heparin": "Heparin Anticoagulation & ACT Protocol",
            "protamine": "Protamine Reversal Strategy",
            "cardioplegia": "Myocardial Protection & Cardioplegia Protocol",
            "oxygenator": "Oxygenator Gas Exchange Strategy",
            "prime": "Circuit Prime Volume & Hemodilution Target",
            "cannula": "Vascular Cannulation Strategy",
            "ecmo": "Extracorporeal Membrane Oxygenation (ECMO) Configuration",
            "alpha-stat": "Alpha-Stat / pH-Stat Blood Gas Strategy",
            "hypothermia": "Hypothermia Management on CPB"
        }
        for kw, title in perfusion_topics.items():
            if kw in u_lower:
                summary_excerpt = assistant_text[:180].replace("\n", " ").strip()
                self.save_memory(
                    user_id=user_id,
                    key=f"Recent Discussion: {title}",
                    content=summary_excerpt,
                    category="clinical_pearl",
                    conversation_id=conversation_id
                )
                break
