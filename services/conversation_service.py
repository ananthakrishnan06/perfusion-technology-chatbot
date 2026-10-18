import logging
import uuid
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from storage.db import get_session_factory, is_db_configured
from storage.db_models import Conversation, Message, Memory

logger = logging.getLogger(__name__)


class ConversationService:
    """
    Service for managing persistent multi-turn chat sessions and long-term
    clinical memory in PostgreSQL.
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
    # CONVERSATION SESSION MANAGEMENT
    # =========================================================================
    def create_conversation(self, title: str = "New Perfusion Inquiry") -> Optional[Dict[str, Any]]:
        """Create a new conversation session."""
        session = self._get_session()
        if not session:
            logger.warning("PostgreSQL not configured. Cannot persist conversation.")
            return None
        try:
            conv = Conversation(id=str(uuid.uuid4()), title=title[:250])
            session.add(conv)
            session.commit()
            session.refresh(conv)
            return conv.to_dict(include_messages=False)
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to create conversation: {e}")
            return None
        finally:
            if self._session is None:
                session.close()

    def get_conversation(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a conversation with all messages and citations."""
        session = self._get_session()
        if not session:
            return None
        try:
            conv = session.query(Conversation).filter(Conversation.id == conversation_id).first()
            if not conv:
                return None
            return conv.to_dict(include_messages=True)
        except Exception as e:
            logger.error(f"Failed to fetch conversation {conversation_id}: {e}")
            return None
        finally:
            if self._session is None:
                session.close()

    def list_conversations(self, limit: int = 50) -> List[Dict[str, Any]]:
        """List all recent conversations ordered by last update."""
        session = self._get_session()
        if not session:
            return []
        try:
            convs = (
                session.query(Conversation)
                .order_by(Conversation.updated_at.desc())
                .limit(limit)
                .all()
            )
            return [c.to_dict(include_messages=False) for c in convs]
        except Exception as e:
            logger.error(f"Failed to list conversations: {e}")
            return []
        finally:
            if self._session is None:
                session.close()

    def delete_conversation(self, conversation_id: str) -> bool:
        """Delete a conversation and all its messages / memories."""
        session = self._get_session()
        if not session:
            return False
        try:
            conv = session.query(Conversation).filter(Conversation.id == conversation_id).first()
            if not conv:
                return False
            session.delete(conv)
            session.commit()
            return True
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to delete conversation {conversation_id}: {e}")
            return False
        finally:
            if self._session is None:
                session.close()

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        citations: Optional[List[Dict[str, Any]]] = None,
        grounded: bool = True
    ) -> Optional[Dict[str, Any]]:
        """Append a message turn to a conversation session."""
        session = self._get_session()
        if not session:
            return None
        try:
            conv = session.query(Conversation).filter(Conversation.id == conversation_id).first()
            if not conv:
                # Auto-create if conversation doesn't exist yet
                conv = Conversation(
                    id=conversation_id,
                    title=content[:60] + "..." if len(content) > 60 else content
                )
                session.add(conv)
                session.flush()
            elif conv.title == "New Perfusion Inquiry" and role == "user":
                # Update title to first user question
                conv.title = content[:60] + "..." if len(content) > 60 else content

            msg = Message(
                id=str(uuid.uuid4()),
                conversation_id=conversation_id,
                role=role,
                content=content,
                citations=citations or [],
                grounded=grounded
            )
            session.add(msg)
            session.commit()
            session.refresh(msg)
            return msg.to_dict()
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to add message to conversation {conversation_id}: {e}")
            return None
        finally:
            if self._session is None:
                session.close()

    def add_turn(
        self,
        conversation_id: str,
        user_content: str,
        assistant_content: str,
        citations: Optional[List[Dict[str, Any]]] = None,
        grounded: bool = True
    ) -> bool:
        """Batch persist both user and assistant message turns in a single atomic transaction."""
        session = self._get_session()
        if not session:
            return False
        try:
            conv = session.query(Conversation).filter(Conversation.id == conversation_id).first()
            if not conv:
                conv = Conversation(
                    id=conversation_id,
                    title=user_content[:60] + "..." if len(user_content) > 60 else user_content
                )
                session.add(conv)
                session.flush()
            elif conv.title == "New Perfusion Inquiry":
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
            session.commit()
            return True
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to batch add turn to conversation {conversation_id}: {e}")
            return False
        finally:
            if self._session is None:
                session.close()

    # =========================================================================
    # LONG-TERM MEMORY ENGINE ("MEMORIZE")
    # =========================================================================
    def save_memory(
        self,
        key: str,
        content: str,
        category: str = "clinical_pearl",
        conversation_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Store a long-term memory entity."""
        session = self._get_session()
        if not session:
            return None
        try:
            # Check if key already exists in same conversation or global
            existing = session.query(Memory).filter(Memory.key == key).first()
            if existing:
                existing.content = content
                existing.category = category
                session.commit()
                session.refresh(existing)
                return existing.to_dict()

            mem = Memory(
                id=str(uuid.uuid4()),
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
            logger.error(f"Failed to save memory: {e}")
            return None
        finally:
            if self._session is None:
                session.close()

    def list_memories(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Retrieve stored long-term clinical memories."""
        session = self._get_session()
        if not session:
            return []
        try:
            memories = (
                session.query(Memory)
                .order_by(Memory.updated_at.desc())
                .limit(limit)
                .all()
            )
            return [m.to_dict() for m in memories]
        except Exception as e:
            logger.error(f"Failed to retrieve memories: {e}")
            return []
        finally:
            if self._session is None:
                session.close()

    def format_memory_context(self, limit: int = 5) -> str:
        """
        Format recent stored clinical memories into a prompt block for the LLM.
        Provides long-term continuity across conversation sessions.
        """
        memories = self.list_memories(limit=limit)
        if not memories:
            return ""

        lines = ["[Clinical Context & Stored Memories from Previous Sessions]"]
        for m in memories:
            lines.append(f"• {m['key']}: {m['content']}")
        return "\n".join(lines)

    def extract_and_memorize(
        self,
        conversation_id: str,
        user_text: str,
        assistant_text: str
    ) -> None:
        """
        Heuristic memory extractor: identifies clinical preferences, patient parameters,
        and high-yield topics discussed in the turn to memorize for future sessions.
        """
        u_lower = user_text.lower()

        # Check for explicit user preferences or case parameters
        if any(w in u_lower for w in ["i prefer", "my patient", "our protocol", "we use", "remember that", "note that"]):
            self.save_memory(
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
                    key=f"Recent Discussion: {title}",
                    content=summary_excerpt,
                    category="clinical_pearl",
                    conversation_id=conversation_id
                )
                break

