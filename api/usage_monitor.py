"""Record AI request outcomes without retaining prompts or answers."""
import json
import logging
import time

from anyio import CancelScope
from starlette.concurrency import run_in_threadpool

from config import settings
from storage.admin_models import UsageEvent
from storage.db import get_session_factory, is_db_configured

logger = logging.getLogger(__name__)
OPERATIONS = {"/chat/ask": "chat", "/chat/stream": "chat_stream", "/study/mcq": "study"}


def save_usage(data, citations):
    try:
        if citations:
            from api.dependencies import get_document_service
            store = get_document_service().metadata_store
            chunks = (store.get_chunk(citation.get("chunk_id", "")) for citation in citations)
            data["documents"] = sorted({chunk.document_id for chunk in chunks if chunk})
        with get_session_factory().begin() as db:
            db.add(UsageEvent(**data))
    except Exception as error:
        logger.warning("Usage recording failed (%s)", type(error).__name__)


async def monitor_usage(request, call_next):
    path = request.url.path.removeprefix(settings.API_PREFIX)
    operation = OPERATIONS.get(path)
    if request.method != "POST" or not operation or not is_db_configured():
        return await call_next(request)
    start = time.monotonic()
    response = await call_next(request)
    if not getattr(request.state, "ai_admitted", False):
        return response
    source = response.body_iterator

    async def observe():
        saved = False
        pending = b""

        async def record(success, citations=()):
            nonlocal saved
            if saved:
                return
            saved = True
            elapsed = round((time.monotonic() - start) * 1000)
            with CancelScope(shield=True):
                await run_in_threadpool(save_usage, {
                    "user_id": getattr(request.state, "user_id", None),
                    "operation": operation,
                    "success": success,
                    "elapsed_ms": elapsed,
                }, citations)

        try:
            async for chunk in source:
                if not saved:
                    pending += chunk if isinstance(chunk, bytes) else chunk.encode()
                    if path == "/chat/stream":
                        frames = pending.split(b"\n\n")
                        pending = frames.pop()
                        for frame in frames:
                            if not frame.startswith(b"data:"):
                                continue
                            try:
                                event = json.loads(frame[5:])
                            except ValueError:
                                continue
                            if event.get("type") == "done":
                                await record(bool(event.get("answer")), event.get("citations") or ())
                            elif event.get("type") == "error":
                                await record(False)
                yield chunk

            if path != "/chat/stream" and response.status_code < 400:
                try:
                    answer = json.loads(pending)
                except ValueError:
                    answer = {}
                await record(bool(answer.get("answer") or answer.get("questions") or answer.get("insufficient_evidence")),
                             answer.get("citations") or ())
        finally:
            await record(False)

    response.body_iterator = observe()
    return response
