from datetime import timedelta
from pathlib import Path
import csv
import io
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete
from sqlalchemy.orm import Session

from api.routes_auth import SESSION_MAX_AGE_SECONDS, get_optional_current_user, hash_password, require_admin, verify_password
from storage.admin_state import BOOTSTRAP_ID, audit, options
from storage.admin_models import AccountControl, AdminSetting, AppSession, AuditEvent, UsageEvent, utcnow
from storage.db import get_db
from storage.db_models import Conversation, Memory, Message, User
from storage.knowledge_archive import archive_document, tombstone
from config import settings

router = APIRouter(prefix="/admin", tags=["Admin"])
ONLINE_MINUTES = 5


def admin_db(db=Depends(get_db)):
    if db is None:
        raise HTTPException(503, "The dashboard requires a database.")
    return db


def username(user):
    name = user.name.strip()
    return name if "@" not in name else "User " + user.id[-8:]


def stamp(value):
    return value.isoformat() + "Z" if value else None


def protected_user(user):
    return (
        user.id == BOOTSTRAP_ID
        or (user.role or "").lower() in {"admin", "administrator"}
        or user.email.lower() in settings.ADMIN_EMAILS
    )


def session_limit(db):
    return min(options(db).get("session_minutes", SESSION_MAX_AGE_SECONDS // 60), SESSION_MAX_AGE_SECONDS // 60)


def online_sessions(db, now):
    return db.query(AppSession.user_id).filter(
        AppSession.revoked.is_(False),
        AppSession.seen >= now - timedelta(minutes=ONLINE_MINUTES),
        AppSession.started > now - timedelta(minutes=session_limit(db)),
    )


def managed_user(db, user_id):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found.")
    if protected_user(user):
        raise HTTPException(403, "Administrator accounts are protected.")
    return user


@router.get("/page", include_in_schema=False)
async def dashboard_page(request: Request):
    token = request.cookies.get("perfusion_session")
    try:
        profile = await get_optional_current_user(request, "Bearer " + token if token else None)
    except HTTPException as error:
        if error.status_code != 401:
            raise
        profile = None
    if not profile or profile.role != "admin":
        return RedirectResponse("/", status_code=303)
    page = Path(__file__).resolve().parent / "admin.html"
    return HTMLResponse(page.read_text(encoding="utf-8"), headers={"Cache-Control": "no-store"})


class PasswordChange(BaseModel):
    current: str = Field(min_length=1, max_length=1024)
    replacement: str = Field(min_length=12, max_length=1024)


@router.post("/password")
def change_password(body: PasswordChange, admin=Depends(require_admin), db: Session = Depends(admin_db)):
    user = db.get(User, admin.sub)
    if not user or user.id != BOOTSTRAP_ID or not verify_password(body.current, user.password_hash):
        raise HTTPException(400, "Current password is incorrect.")
    if verify_password(body.replacement, user.password_hash):
        raise HTTPException(400, "Choose a different password.")
    user.password_hash = hash_password(body.replacement)
    control = db.get(AccountControl, user.id)
    control.rotate_password = False
    control.revoked_before = utcnow()
    audit(db, admin.sub, "admin_password_changed")
    db.commit()
    response = Response(status_code=204)
    response.delete_cookie("perfusion_session", path="/api/")
    return response


@router.get("/overview")
def overview(admin=Depends(require_admin), db: Session = Depends(admin_db)):
    from api.dependencies import get_document_service
    docs = get_document_service().metadata_store.list_documents()
    now = utcnow()
    query = db.query(UsageEvent)
    last = db.query(UsageEvent).filter(UsageEvent.operation.in_(["chat", "chat_stream", "study"])).order_by(UsageEvent.at.desc()).first()
    return {
        "users": db.query(User).count(),
        "active": online_sessions(db, now).join(User, User.id == AppSession.user_id).distinct().count(),
        "pdfs": len(docs), "indexed": sum(doc.status == "indexed" for doc in docs),
        "requests": query.count(), "today": query.filter(UsageEvent.at >= now.replace(hour=0, minute=0, second=0, microsecond=0)).count(),
        "failed": query.filter_by(success=False).count(), "tokens": None,
        "llm_status": ("Last request succeeded" if last.success else "Last request failed") if last else None,
    }


@router.get("/users")
def users(search: str = "", status: str = "", admin=Depends(require_admin), db: Session = Depends(admin_db)):
    accounts = {row.user_id: row for row in db.query(AccountControl)}
    from sqlalchemy import func
    counts = dict(db.query(UsageEvent.user_id, func.count()).group_by(UsageEvent.user_id))
    seen = dict(db.query(AppSession.user_id, func.max(AppSession.seen)).group_by(AppSession.user_id))
    online = {row[0] for row in online_sessions(db, utcnow())}
    rows = []
    for user in db.query(User).order_by(User.created_at.desc()):
        control = accounts.get(user.id)
        current = control.status if control else "active"
        if current == "active" and control and control.blocked_until and control.blocked_until > utcnow():
            current = "blocked"
        label = username(user)
        if (search and search.casefold() not in label.casefold()) or (status and current != status):
            continue
        rows.append({"id": user.id, "username": label, "status": current, "online": user.id in online and current == "active",
                     "registered": stamp(user.created_at), "last_login": stamp(user.last_login_at), "last_active": stamp(seen.get(user.id)),
                     "requests": counts.get(user.id, 0), "tokens": None, "role": "admin" if protected_user(user) else "user",
                     "daily_limit": control.daily_limit if control else None})
    return rows


class UserAction(BaseModel):
    action: str
    minutes: int = Field(default=60, ge=1, le=10080)
    daily_limit: int | None = Field(default=None, ge=1, le=100000)
    confirmation: str = ""


@router.post("/users/{user_id}")
def change_user(user_id: str, body: UserAction, admin=Depends(require_admin), db: Session = Depends(admin_db)):
    user = managed_user(db, user_id)
    control = db.get(AccountControl, user_id)
    if not control:
        control = AccountControl(user_id=user_id, status="active")
        db.add(control)
    action = body.action
    if action == "suspend":
        control.status = "suspended"
    elif action == "reactivate":
        control.status = "active"
        control.blocked_until = None
    elif action == "block":
        control.blocked_until = utcnow() + timedelta(minutes=body.minutes)
    elif action == "limit":
        control.daily_limit = body.daily_limit
    elif action == "delete":
        if body.confirmation != user_id:
            raise HTTPException(400, "Confirm the user ID to delete this account.")
        control.status = "deleted"
        conversations = db.query(Conversation.id).filter_by(user_id=user_id)
        db.execute(delete(Message).where(Message.conversation_id.in_(conversations)))
        db.execute(delete(Memory).where((Memory.user_id == user_id) | Memory.conversation_id.in_(conversations)))
        db.execute(delete(Conversation).where(Conversation.user_id == user_id))
        db.delete(user)
    elif action != "logout":
        raise HTTPException(400, "Unknown user action.")
    if action in {"logout", "block", "suspend", "delete"}:
        control.revoked_before = utcnow()
        db.query(AppSession).filter_by(user_id=user_id).update({"revoked": True})
    audit(db, admin.sub, "user_" + action, user_id)
    db.commit()
    return {"ok": True}


@router.get("/sessions")
def sessions(admin=Depends(require_admin), db: Session = Depends(admin_db)):
    now = utcnow()
    result = []
    limit = session_limit(db)
    for row, user in db.query(AppSession, User).join(User, User.id == AppSession.user_id).order_by(AppSession.seen.desc()).limit(1000):
        expired = row.started + timedelta(minutes=limit) <= now
        result.append({"id": row.id, "user_id": user.id, "username": username(user), "browser": row.browser,
                       "login": stamp(row.started), "last_active": stamp(row.seen),
                       "can_sign_out": not protected_user(user) and not row.revoked and not expired,
                       "duration_seconds": max(0, int(((row.seen if row.revoked or expired else now) - row.started).total_seconds())),
                       "status": "revoked" if row.revoked else "expired" if expired else "online" if row.seen >= now-timedelta(minutes=ONLINE_MINUTES) else "offline"})
    return result


@router.delete("/sessions/{session_id}")
def terminate_session(session_id: str, admin=Depends(require_admin), db: Session = Depends(admin_db)):
    row = db.get(AppSession, session_id)
    if not row:
        raise HTTPException(404, "Session not found.")
    managed_user(db, row.user_id)
    row.revoked = True
    audit(db, admin.sub, "session_revoked", row.user_id)
    db.commit()
    return {"ok": True}


@router.post("/sessions/logout-all")
def logout_all(admin=Depends(require_admin), db: Session = Depends(admin_db)):
    for user in db.query(User).all():
        if protected_user(user):
            continue
        row = db.get(AccountControl, user.id)
        if not row:
            row = AccountControl(user_id=user.id, status="active")
            db.add(row)
        row.revoked_before = utcnow()
        db.query(AppSession).filter_by(user_id=user.id).update({"revoked": True})
    audit(db, admin.sub, "normal_sessions_revoked")
    db.commit()
    return {"ok": True}


@router.get("/logs")
def logs(admin=Depends(require_admin), db: Session = Depends(admin_db)):
    return [{"at": stamp(row.at), "actor": row.actor, "action": row.action, "target": row.target}
            for row in db.query(AuditEvent).order_by(AuditEvent.at.desc()).limit(500)]


class SystemSettings(BaseModel):
    max_pdf_mb: int = Field(50, ge=1, le=250)
    daily_requests: int | None = Field(None, ge=1, le=100000)
    max_response_tokens: int | None = Field(None, ge=128, le=16384)
    registrations: bool = True
    maintenance: bool = False
    primary_llm: str = Field("groq", pattern="^(groq|gemini)$")
    retrieval_limit: int = Field(20, ge=1, le=20)
    session_minutes: int = Field(1440, ge=5, le=43200)


@router.get("/settings")
def get_settings(admin=Depends(require_admin), db: Session = Depends(admin_db)):
    return SystemSettings(**({"max_pdf_mb": settings.MAX_UPLOAD_SIZE_MB, "session_minutes": 10080, "primary_llm": settings.PRIMARY_LLM_PROVIDER} | options(db)))


@router.put("/settings")
def update_settings(body: SystemSettings, admin=Depends(require_admin), db: Session = Depends(admin_db)):
    if body.max_pdf_mb > settings.MAX_UPLOAD_SIZE_MB:
        raise HTTPException(422, f"The server upload ceiling is {settings.MAX_UPLOAD_SIZE_MB} MB.")
    for key, value in body.model_dump().items():
        row = db.get(AdminSetting, key)
        if row:
            row.value = value
        else:
            db.add(AdminSetting(name=key, value=value))
    audit(db, admin.sub, "settings_updated")
    db.commit()
    return body


@router.get("/usage")
def usage(start: str = "", end: str = "", user_id: str = "", export: bool = False,
          admin=Depends(require_admin), db: Session = Depends(admin_db)):
    from datetime import date, datetime, time
    try:
        last = date.fromisoformat(end) if end else utcnow().date()
        first = date.fromisoformat(start) if start else last-timedelta(days=29)
        if not 0 <= (last-first).days <= 366 or last == date.max:
            raise ValueError
    except (ValueError, OverflowError):
        raise HTTPException(400, "Choose a valid date range of up to one year.")
    query = db.query(UsageEvent).filter(UsageEvent.at >= datetime.combine(first, time.min), UsageEvent.at < datetime.combine(last+timedelta(days=1), time.min))
    if user_id:
        query = query.filter_by(user_id=user_id)
    rows = query.order_by(UsageEvent.at).all()
    if export:
        file = io.StringIO()
        writer = csv.writer(file)
        writer.writerow(["timestamp", "user_id", "operation", "success", "elapsed_ms"])
        for row in rows:
            safe_id = row.user_id or ""
            if not re.fullmatch(r"[a-zA-Z0-9_-]+", safe_id):
                safe_id = ""
            writer.writerow([stamp(row.at), safe_id, row.operation, row.success, row.elapsed_ms])
        return Response(file.getvalue(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=usage.csv"})
    from collections import Counter
    daily = Counter(row.at.date().isoformat() for row in rows)
    weekly = Counter((row.at.date()-timedelta(days=row.at.weekday())).isoformat() for row in rows)
    monthly = Counter(row.at.strftime("%Y-%m") for row in rows)
    activity = {}
    for row in rows:
        if row.user_id:
            activity.setdefault(row.at.date().isoformat(), set()).add(row.user_id)
    documents = Counter(document for row in rows for document in row.documents)
    from api.dependencies import get_document_service
    catalog = get_document_service().metadata_store.list_documents()
    subjects = Counter()
    modules = Counter()
    for doc in catalog:
        if doc.subject and documents[doc.document_id]:
            subjects[doc.subject] += documents[doc.document_id]
        if doc.module and documents[doc.document_id]:
            modules[doc.module] += documents[doc.document_id]
    return {"start": first.isoformat(), "end": last.isoformat(), "daily": dict(daily), "weekly": dict(weekly), "monthly": dict(monthly),
            "hourly": dict(Counter(row.at.hour for row in rows)),
            "active_users": {day: len(ids) for day, ids in activity.items()},
            "uploads": dict(Counter(doc.uploaded_at[:10] for doc in catalog if first.isoformat() <= doc.uploaded_at[:10] <= last.isoformat())),
            "documents": {doc.filename: documents[doc.document_id] for doc in catalog if documents[doc.document_id]},
            "subjects": dict(subjects), "modules": dict(modules), "total": len(rows),
            "failed": sum(not row.success for row in rows), "average_ms": round(sum(row.elapsed_ms for row in rows)/len(rows)) if rows else None,
            "tokens": None, "estimated_cost": None}
from fastapi import File, Form, UploadFile
from api.dependencies import get_document_service
from ingestion.pdf_loader import PDFLoader, PDFProcessingError
import uuid


class Categories(BaseModel):
    course: str = Field("", max_length=100)
    semester: str = Field("", max_length=100)
    subject: str = Field("", max_length=100)
    module: str = Field("", max_length=100)
    topic: str = Field("", max_length=100)


def store_categories(service, doc_id, categories):
    doc = service.metadata_store.get_document(doc_id)
    if not doc:
        raise HTTPException(404, "Document not found.")
    if categories:
        updated = doc.model_copy(update=categories.model_dump())
        service.metadata_store.add_document(updated, service.metadata_store.get_all_chunks([doc_id]))
    return doc


@router.get("/documents")
def admin_documents(admin=Depends(require_admin), service=Depends(get_document_service)):
    return service.metadata_store.list_documents()


@router.patch("/documents/{doc_id}")
def categorize(doc_id: str, categories: Categories, admin=Depends(require_admin),
               db: Session = Depends(admin_db), service=Depends(get_document_service)):
    doc = store_categories(service, doc_id, categories)
    archive_document(db, service, doc_id)
    audit(db, admin.sub, "pdf_categories_updated", doc_id)
    db.commit()
    return {"id": doc.document_id}


def pdf_path(service, doc_id):
    doc = store_categories(service, doc_id, None)
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", doc_id):
        raise HTTPException(404, "Document not found.")
    path = service.documents_dir / (doc_id + ".pdf")
    if not path.is_file():
        raise HTTPException(404, "The original PDF is unavailable on this server.")
    return doc, path


@router.get("/documents/{doc_id}/preview")
def preview(doc_id: str, page: int = 1, admin=Depends(require_admin), service=Depends(get_document_service)):
    import pymupdf
    _, path = pdf_path(service, doc_id)
    try:
        with pymupdf.open(path) as pdf:
            if not 1 <= page <= len(pdf):
                raise HTTPException(404, "Page not found.")
            image = pdf[page-1].get_pixmap(dpi=90).tobytes("png")
    except (RuntimeError, ValueError):
        raise HTTPException(422, "The PDF page could not be rendered.")
    return Response(image, media_type="image/png", headers={"Cache-Control": "no-store"})


def index_pdf(service, db, admin, data, name, categories):
    from schemas.document import DocumentMetadata
    import hashlib
    result = service.process_pdf_file(data, name)
    if result.processing_status == "indexed" and not result.chunk_count:
        doc = service.metadata_store.get_document(result.document_id)
        service.metadata_store.delete_document(result.document_id)
        service.metadata_store.add_document(doc.model_copy(update={
            "status": "failed", "error_message": "The PDF has no extractable text. Enable OCR and reprocess.",
            **categories.model_dump(),
        }), [])
        result.processing_status = "failed"
        result.error_details = "The PDF has no extractable text. Enable OCR and reprocess."
        audit(db, admin.sub, "pdf_index_failed", result.document_id)
    elif result.processing_status == "indexed":
        store_categories(service, result.document_id, categories)
        audit(db, admin.sub, "pdf_uploaded", result.document_id)
    elif result.processing_status == "failed":
        doc_id = str(uuid.uuid4())
        service.documents_dir.mkdir(parents=True, exist_ok=True)
        (service.documents_dir / (doc_id + ".pdf")).write_bytes(data)
        failed = DocumentMetadata(document_id=doc_id, filename=name, file_hash=hashlib.sha256(data).hexdigest(),
                                  file_size_bytes=len(data), total_pages=result.page_count, total_chunks=0,
                                  status="failed", error_message=result.error_details, **categories.model_dump())
        service.metadata_store.add_document(failed, [])
        result.document_id = doc_id
        audit(db, admin.sub, "pdf_index_failed", doc_id)
    if result.processing_status in {"indexed", "failed"}:
        archive_document(db, service, result.document_id)
    return result


@router.post("/documents/upload")
def upload_pdfs(files: list[UploadFile] = File(...), categories: str = Form("{}"), replace: str = Form(""),
                admin=Depends(require_admin), db: Session = Depends(admin_db), service=Depends(get_document_service)):
    try:
        tags = Categories.model_validate_json(categories)
    except ValueError:
        raise HTTPException(422, "Invalid document categories.")
    if not 1 <= len(files) <= 10 or (replace and len(files) != 1):
        raise HTTPException(400, "Choose up to ten PDFs, or one PDF when replacing.")
    if replace:
        store_categories(service, replace, None)
    limit = min(options(db).get("max_pdf_mb", settings.MAX_UPLOAD_SIZE_MB), settings.MAX_UPLOAD_SIZE_MB)*1024*1024
    remaining = limit
    prepared = []
    for file in files:
        name = re.split(r"[/\\]", file.filename or "")[-1][:200]
        data = file.file.read(remaining+1)
        remaining -= len(data)
        if remaining < 0:
            raise HTTPException(413, "The upload exceeds the configured batch limit.")
        try:
            PDFLoader.validate_pdf_bytes(data, name)
        except PDFProcessingError:
            audit(db, admin.sub, "pdf_validation_failed")
            db.commit()
            raise HTTPException(422, "Upload a valid PDF within the configured limit.")
        prepared.append((data, name))

    results = []
    for data, name in prepared:
        result = index_pdf(service, db, admin, data, name, tags)
        if replace and result.processing_status == "indexed":
            service.delete_document(replace)
            tombstone(db, replace)
            audit(db, admin.sub, "pdf_replaced", replace)
        db.commit()
        results.append(result)
    return results


@router.post("/documents/{doc_id}/reprocess")
def reprocess(doc_id: str, admin=Depends(require_admin), db: Session = Depends(admin_db),
              service=Depends(get_document_service)):
    doc, path = pdf_path(service, doc_id)
    if doc.status != "failed":
        raise HTTPException(409, "Only failed documents can be reprocessed.")
    result = index_pdf(service, db, admin, path.read_bytes(), doc.filename, Categories(**doc.model_dump()))
    if result.document_id not in {doc_id, "unassigned"}:
        service.delete_document(doc_id)
        tombstone(db, doc_id)
    audit(db, admin.sub, "pdf_reprocessed" if result.processing_status == "indexed" else "pdf_index_failed", doc_id)
    db.commit()
    return result


@router.delete("/documents/{doc_id}")
def remove_pdf(doc_id: str, admin=Depends(require_admin), db: Session = Depends(admin_db), service=Depends(get_document_service)):
    if not service.delete_document(doc_id):
        raise HTTPException(404, "Document not found.")
    tombstone(db, doc_id)
    audit(db, admin.sub, "pdf_deleted", doc_id)
    db.commit()
    return {"ok": True}
