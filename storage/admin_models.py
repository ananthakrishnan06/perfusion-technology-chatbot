"""Additive tables for administrative controls and reporting."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Integer, JSON, LargeBinary, String

from storage.db import Base


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_id():
    return str(uuid.uuid4())


class AccountControl(Base):
    __tablename__ = "account_controls"
    user_id = Column(String(100), primary_key=True)
    status = Column(String(20), default="active", nullable=False)
    blocked_until = Column(DateTime)
    revoked_before = Column(DateTime)
    daily_limit = Column(Integer)
    rotate_password = Column(Boolean, default=False, nullable=False)


class AppSession(Base):
    __tablename__ = "app_sessions"
    id = Column(String(36), primary_key=True, default=new_id)
    digest = Column(String(64), unique=True, nullable=False)
    user_id = Column(String(100), nullable=False, index=True)
    browser = Column(String(32), nullable=False)
    started = Column(DateTime, default=utcnow, nullable=False)
    seen = Column(DateTime, default=utcnow, nullable=False, index=True)
    revoked = Column(Boolean, default=False, nullable=False)


class AdminSetting(Base):
    __tablename__ = "admin_settings"
    name = Column(String(50), primary_key=True)
    value = Column(JSON, nullable=False)


class AuditEvent(Base):
    __tablename__ = "admin_audit_events"
    id = Column(String(36), primary_key=True, default=new_id)
    at = Column(DateTime, default=utcnow, nullable=False, index=True)
    actor = Column(String(100), nullable=False)
    action = Column(String(50), nullable=False)
    target = Column(String(180), nullable=False, default="")


class UsageEvent(Base):
    __tablename__ = "app_usage_events"
    id = Column(String(36), primary_key=True, default=new_id)
    at = Column(DateTime, default=utcnow, nullable=False, index=True)
    user_id = Column(String(100), index=True)
    operation = Column(String(32), nullable=False)
    success = Column(Boolean, nullable=False)
    elapsed_ms = Column(Integer, nullable=False)
    documents = Column(JSON, nullable=False, default=list)
class DailyUsage(Base):
    __tablename__ = "app_daily_usage"
    bucket = Column(String(100), primary_key=True)
    day = Column(String(10), primary_key=True)
    requests = Column(Integer, nullable=False)
class KnowledgeDocument(Base):
    __tablename__ = "managed_knowledge_documents"
    id = Column(String(100), primary_key=True)
    metadata_json = Column(JSON)
    chunks = Column(JSON)
    pdf = Column(LargeBinary)
    deleted = Column(Boolean, default=False, nullable=False)
