"""Record completed AI API requests without storing prompts or answers."""
import json
import logging
import time

from storage.admin_models import UsageEvent
from storage.db import get_session_factory, is_db_configured

logger = logging.getLogger(__name__)


def save_usage(data):
    try:
        with get_session_factory().begin() as db:
            db.add(UsageEvent(**data))
    except Exception as error:
        logger.warning("Usage recording failed (%s)", type(error).__name__)


async def monitor_usage(request, call_next):
    from config import settings
    path = request.url.path.removeprefix(settings.API_PREFIX)
    operations = {"/chat/ask": "chat", "/chat/stream": "chat_stream", "/study/mcq": "study"}
    if request.method != "POST" or path not in operations or not is_db_configured():
        return await call_next(request)
    from starlette.concurrency import run_in_threadpool
    start = time.monotonic()
    response = await call_next(request)
    admitted = getattr(request.state, "ai_admitted", False)
    if not admitted:
        return response
    source = response.body_iterator

    async def observe():
        complete = False
        documents = []
        pending = b""
        try:
            async for chunk in source:
                pending += chunk if isinstance(chunk, bytes) else chunk.encode()
                if path == "/chat/stream":
                    frames = pending.split(b"\n\n")
                    pending = frames.pop()
                    for frame in frames:
                        if frame.startswith(b"data:"):
                            try:
                                event = json.loads(frame[5:])
                                if event.get("type") == "done":
                                    complete = bool(event.get("answer"))
                                    documents = event.get("citations") or []
                            except (ValueError, AttributeError):
                                pass
                yield chunk
            if path != "/chat/stream" and response.status_code < 400:
                try:
                    answer = json.loads(pending)
                    complete = bool(answer.get("answer") or answer.get("questions") or answer.get("insufficient_evidence"))
                    documents = answer.get("citations") or []
                except (ValueError, AttributeError):
                    pass
        finally:
            from api.dependencies import get_document_service
            store = get_document_service().metadata_store
            ids = set()
            for citation in documents:
                match = store.get_chunk(citation.get("chunk_id", ""))
                if match:
                    ids.add(match.document_id)
            await run_in_threadpool(save_usage, {
                "user_id": getattr(request.state, "user_id", None), "operation": operations[path],
                "success": complete, "elapsed_ms": round((time.monotonic()-start)*1000), "documents": sorted(ids),
            })
    response.body_iterator = observe()
    return response
