import uuid
from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, JSON, String, Text
from sqlalchemy.orm import relationship
from storage.db import Base

class User(Base):
    """Represents an authenticated Google user profile."""
    __tablename__ = "users"

    id = Column(String(100), primary_key=True)  # Google 'sub', email hash, or uuid
    email = Column(String(255), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=False)
    password_hash = Column(String(255), nullable=True)
    given_name = Column(String(100), nullable=True)
    family_name = Column(String(100), nullable=True)
    picture = Column(String(500), nullable=True)
    role = Column(String(100), default="Clinical Perfusionist")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_login_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "email": self.email,
            "name": self.name,
            "given_name": self.given_name,
            "family_name": self.family_name,
            "picture": self.picture,
            "role": self.role,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None
        }


class Conversation(Base):
    """Represents a multi-turn chat session with Perfusion AI."""
    __tablename__ = "conversations"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title = Column(String(255), nullable=False, default="New Perfusion Inquiry")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    messages = relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at.asc()"
    )
    memories = relationship(
        "Memory",
        back_populates="conversation",
        cascade="all, delete-orphan"
    )

    def to_dict(self, include_messages: bool = False):
        data = {
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "message_count": len(self.messages) if self.messages else 0
        }
        if include_messages and self.messages:
            data["messages"] = [m.to_dict() for m in self.messages]
        return data


class Message(Base):
    """Represents an individual message turn within a conversation."""
    __tablename__ = "messages"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id = Column(
        String(36),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    role = Column(String(20), nullable=False)  # 'user' or 'assistant'
    content = Column(Text, nullable=False)
    citations = Column(JSON, nullable=True)     # Stores list of citation dicts
    grounded = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    conversation = relationship("Conversation", back_populates="messages")

    def to_dict(self):
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "role": self.role,
            "content": self.content,
            "citations": self.citations or [],
            "grounded": self.grounded,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }


class Memory(Base):
    """
    Represents long-term clinical memory extracted across conversations.
    Enables the assistant to recall past clinical discussions, patient cases,
    and user preferences across sessions.
    """
    __tablename__ = "memories"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id = Column(
        String(36),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=True,
        index=True
    )
    category = Column(String(50), nullable=False, default="clinical_pearl")  # 'clinical_topic', 'preference', 'case_detail', 'clinical_pearl'
    key = Column(String(100), index=True, nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    conversation = relationship("Conversation", back_populates="memories")

    def to_dict(self):
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "category": self.category,
            "key": self.key,
            "content": self.content,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }

