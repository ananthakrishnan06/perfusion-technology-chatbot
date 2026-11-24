"""Shared account controls for the existing cookie and bearer authentication."""
import base64
import hashlib
import json
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import SQLAlchemyError

from storage.db import get_session_factory, is_db_configured
from storage.admin_models import AccountControl, AdminSetting, AppSession, AuditEvent, utcnow

BOOTSTRAP_ID = "perfusion-bootstrap-admin"


def digest(token):
    if not token.startswith("v2."):
        try:
            payload = token.split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
            if claims.get("session_id") and claims.get("sub"):
                token = f"supabase:{claims['sub']}:{claims['session_id']}"
        except (ValueError, KeyError, IndexError, AttributeError):
            pass
    return hashlib.sha256(token.encode()).hexdigest()


def audit(db, actor, action, target=""):
    db.add(AuditEvent(actor=actor, action=action, target=target[:180]))


def options(db):
    return {row.name: row.value for row in db.query(AdminSetting).all()}


def read_options():
    if not is_db_configured():
        return {}
    try:
        with get_session_factory()() as db:
            return options(db)
    except (SQLAlchemyError, TypeError):
        return {}


def enforce_session(profile, token, request, issued_at=None, *, login=False):
    if not is_db_configured():
        return profile
    factory = get_session_factory()
    if not factory:
        raise HTTPException(503, "Session storage is unavailable.")
    now = utcnow()
    try:
        with factory.begin() as db:
            control = db.get(AccountControl, profile.sub)
            if control:
                if control.status in ("deleted", "suspended") or (control.blocked_until and control.blocked_until > now):
                    raise HTTPException(401, "Account access is unavailable.")
                if control.revoked_before and (issued_at is None or issued_at <= control.revoked_before):
                    raise HTTPException(401, "Session revoked. Sign in again.")
            key = digest(token)
            row = db.query(AppSession).filter_by(digest=key).first()
            duration = db.get(AdminSetting, "session_minutes")
            if row and (row.revoked or (duration and row.started + timedelta(minutes=duration.value) <= now)):
                raise HTTPException(401, "Session expired. Sign in again.")
            if row:
                if (now - row.seen).total_seconds() >= 30:
                    row.seen = now
            else:
                agent = request.headers.get("user-agent", "").lower()
                browser = next((name for signature, name in (
                    ("edg/", "Edge"), ("firefox/", "Firefox"), ("chrome/", "Chrome"), ("safari/", "Safari")
                ) if signature in agent), "Other browser")
                if any(word in agent for word in ("mobile", "android", "iphone")):
                    browser += " mobile"
                table = AppSession.__table__
                insert = sqlite_insert if db.get_bind().dialect.name == "sqlite" else pg_insert
                db.execute(insert(table).values(digest=key, user_id=profile.sub, browser=browser, started=issued_at or now, seen=now)
                           .on_conflict_do_nothing(index_elements=[table.c.digest]))
            if duration and issued_at and issued_at + timedelta(minutes=duration.value) <= now:
                raise HTTPException(401, "Session expired. Sign in again.")
            if login and profile.role == "admin":
                audit(db, profile.sub, "admin_login")
            return profile.model_copy(update={"password_change_required": bool(control and control.rotate_password)})
    except SQLAlchemyError as exc:
        raise HTTPException(503, "Session storage is unavailable.") from exc
