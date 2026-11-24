"""Shared one-minute AI request quotas, charged before provider work begins."""
import hashlib
import threading
import time

from fastapi import Depends, HTTPException, Request
from api.dependencies import get_optional_current_user
from storage.admin_models import AccountControl, DailyUsage, utcnow
from storage.admin_state import options
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import SQLAlchemyError

from config import settings
from storage.db import get_session_factory, is_db_configured
from storage.db_models import AIUsageWindow

_lock = threading.Lock()
_local_minute = -1
_counts = {}


def check_ai_quota(request: Request, user=Depends(get_optional_current_user)):
    global _local_minute
    minute = int(time.time()) // 60
    ip = request.client.host if request.client else "unknown"
    limits = [("all", settings.AI_TOTAL_REQUESTS_PER_MINUTE),
              (hashlib.sha256(ip.encode()).hexdigest(), settings.AI_REQUESTS_PER_MINUTE)]
    retry = {"Retry-After": str(60 - int(time.time()) % 60)}
    if not is_db_configured():
        with _lock:
            if minute != _local_minute:
                _counts.clear()
                _local_minute = minute
            if any(_counts.get(key, 0) >= limit for key, limit in limits):
                raise HTTPException(429, "AI usage limit reached. Try again shortly.", headers=retry)
            for key, _ in limits:
                _counts[key] = _counts.get(key, 0) + 1
        request.state.ai_admitted = True
        return

    factory = get_session_factory()
    if not factory:
        raise HTTPException(503, "AI usage tracking is temporarily unavailable.")
    try:
        with factory.begin() as db:
            table = AIUsageWindow.__table__
            insert = sqlite_insert if db.get_bind().dialect.name == "sqlite" else pg_insert
            config = options(db)
            if config.get("maintenance") and (not user or user.role != "admin"):
                raise HTTPException(503, "Perfusion AI is under maintenance.")
            control = db.get(AccountControl, user.sub) if user else None
            daily = control.daily_limit if control and control.daily_limit is not None else config.get("daily_requests")
            if daily is not None:
                day_table = DailyUsage.__table__
                charge = insert(day_table).values(bucket=user.sub if user else "guest:" + limits[1][0], day=utcnow().date().isoformat(), requests=1)
                charge = charge.on_conflict_do_update(
                    index_elements=[day_table.c.bucket, day_table.c.day],
                    set_={"requests": day_table.c.requests + 1}, where=day_table.c.requests < daily)
                if db.execute(charge.returning(day_table.c.requests)).scalar_one_or_none() is None:
                    raise HTTPException(429, "Daily AI request limit reached.")
            db.execute(delete(table).where(table.c.minute < minute))
            for key, limit in limits:
                charge = insert(table).values(bucket=key, minute=minute, requests=1)
                charge = charge.on_conflict_do_update(
                    index_elements=[table.c.bucket, table.c.minute],
                    set_={"requests": table.c.requests + 1}, where=table.c.requests < limit)
                # INSERT rowcount can be unknown even when the charge succeeded.
                if db.execute(charge.returning(table.c.requests)).scalar_one_or_none() is None:
                    raise HTTPException(429, "AI usage limit reached. Try again shortly.", headers=retry)
        request.state.ai_admitted = True
    except SQLAlchemyError:
        raise HTTPException(503, "AI usage tracking is temporarily unavailable.")
