import uuid
import pytest
from fastapi.testclient import TestClient
from main import app
from storage.db import get_engine, is_db_configured
from storage.db_models import Conversation, Message, Memory
from sqlalchemy.orm import Session

client = TestClient(app)


def register_user(email: str, name: str, password: str = "P@ssword123!", role: str = "Perfusionist"):
    """Helper to register a user and return their profile with auth headers."""
    res = client.post(
        "/api/v1/auth/register",
        json={
            "name": name,
            "email": email,
            "password": password,
            "role": role
        }
    )
    assert res.status_code == 200, f"Registration failed: {res.text}"
    user_data = res.json()
    token = user_data["token"]
    headers = {"Authorization": f"Bearer {token}"}
    return user_data, headers


def test_conversations_strict_user_isolation(test_client):
    """
    Test that User A and User B have strictly isolated conversation lists.
    User A cannot see User B's conversations and vice-versa.
    """
    # 1. Register User A and User B
    uid_a_email = f"user_a_{uuid.uuid4().hex[:6]}@clinic.org"
    uid_b_email = f"user_b_{uuid.uuid4().hex[:6]}@hospital.edu"

    user_a, headers_a = register_user(uid_a_email, "Dr. Alice Perfusion")
    user_b, headers_b = register_user(uid_b_email, "Dr. Bob Perfusion")

    # 2. User A creates 2 conversations
    conv_a1 = client.post(
        "/api/v1/conversations",
        headers=headers_a,
        json={"title": "Chat A1 - Hypothermic CPB"}
    ).json()
    assert "id" in conv_a1

    conv_a2 = client.post(
        "/api/v1/conversations",
        headers=headers_a,
        json={"title": "Chat A2 - Cardioplegia Protocols"}
    ).json()
    assert "id" in conv_a2

    # 3. User B creates 1 conversation
    conv_b1 = client.post(
        "/api/v1/conversations",
        headers=headers_b,
        json={"title": "Chat B1 - ECMO Circuit Setup"}
    ).json()
    assert "id" in conv_b1

    # 4. List User A's conversations -> should see A1 and A2, NOT B1
    list_a_res = client.get("/api/v1/conversations", headers=headers_a)
    assert list_a_res.status_code == 200
    convs_a = list_a_res.json().get("conversations", [])
    ids_a = [c["id"] for c in convs_a]
    assert conv_a1["id"] in ids_a
    assert conv_a2["id"] in ids_a
    assert conv_b1["id"] not in ids_a

    # 5. List User B's conversations -> should see B1, NOT A1 or A2
    list_b_res = client.get("/api/v1/conversations", headers=headers_b)
    assert list_b_res.status_code == 200
    convs_b = list_b_res.json().get("conversations", [])
    ids_b = [c["id"] for c in convs_b]
    assert conv_b1["id"] in ids_b
    assert conv_a1["id"] not in ids_b
    assert conv_a2["id"] not in ids_b


def test_cross_user_direct_access_forbidden(test_client):
    """
    Test IDOR prevention: User B cannot GET, PATCH, or DELETE User A's conversation.
    """
    uid_a_email = f"user_a_idor_{uuid.uuid4().hex[:6]}@clinic.org"
    uid_b_email = f"user_b_idor_{uuid.uuid4().hex[:6]}@hospital.edu"

    _, headers_a = register_user(uid_a_email, "Clinician Alice")
    _, headers_b = register_user(uid_b_email, "Clinician Bob")

    # User A creates a conversation
    conv_a = client.post(
        "/api/v1/conversations",
        headers=headers_a,
        json={"title": "Private Coronary Perfusion Notes"}
    ).json()
    conv_a_id = conv_a["id"]

    # 1. User B attempts GET on User A's conversation -> 403 Forbidden
    get_res = client.get(f"/api/v1/conversations/{conv_a_id}", headers=headers_b)
    assert get_res.status_code == 403, f"Expected 403 Forbidden, got {get_res.status_code}: {get_res.text}"

    # 2. User B attempts PATCH (rename) on User A's conversation -> 403 Forbidden
    patch_res = client.patch(
        f"/api/v1/conversations/{conv_a_id}",
        headers=headers_b,
        json={"title": "Hacked Title"}
    )
    assert patch_res.status_code == 403, f"Expected 403 Forbidden, got {patch_res.status_code}: {patch_res.text}"

    # 3. User B attempts DELETE on User A's conversation -> 403 Forbidden
    del_res = client.delete(f"/api/v1/conversations/{conv_a_id}", headers=headers_b)
    assert del_res.status_code == 403, f"Expected 403 Forbidden, got {del_res.status_code}: {del_res.text}"

    # 4. Verify User A can still retrieve and modify their conversation
    get_a_res = client.get(f"/api/v1/conversations/{conv_a_id}", headers=headers_a)
    assert get_a_res.status_code == 200
    assert get_a_res.json()["title"] == "Private Coronary Perfusion Notes"


def test_cross_user_chat_message_injection_forbidden(test_client, monkeypatch):
    """
    Test that User B cannot inject messages into User A's conversation via /chat/ask or /chat/stream.
    """
    from generation.gemini_client import GeminiClientWrapper
    monkeypatch.setattr(
        GeminiClientWrapper,
        "generate_chat_completion",
        lambda self, messages, **kwargs: "Mock clinical answer."
    )

    uid_a_email = f"user_a_chat_{uuid.uuid4().hex[:6]}@clinic.org"
    uid_b_email = f"user_b_chat_{uuid.uuid4().hex[:6]}@hospital.edu"

    _, headers_a = register_user(uid_a_email, "Clinician Alice")
    _, headers_b = register_user(uid_b_email, "Clinician Bob")

    # User A creates a conversation
    conv_a = client.post(
        "/api/v1/conversations",
        headers=headers_a,
        json={"title": "Alice Channel"}
    ).json()
    conv_a_id = conv_a["id"]

    # 1. User B attempts to send question targeting User A's conversation_id -> 403 Forbidden
    ask_res = client.post(
        "/api/v1/chat/ask",
        headers=headers_b,
        json={
            "question": "Unauthorized message injection",
            "conversation_id": conv_a_id
        }
    )
    assert ask_res.status_code == 403, f"Expected 403 Forbidden, got {ask_res.status_code}"

    # 2. User B attempts to stream question targeting User A's conversation_id -> 403 Forbidden
    stream_res = client.post(
        "/api/v1/chat/stream",
        headers=headers_b,
        json={
            "question": "Unauthorized streaming injection",
            "conversation_id": conv_a_id
        }
    )
    assert stream_res.status_code == 403, f"Expected 403 Forbidden, got {stream_res.status_code}"


def test_unauthenticated_requests_rejected(test_client):
    """
    Test that unauthenticated requests to conversation management endpoints receive HTTP 401.
    """
    # 1. GET /conversations without token -> 401
    res_list = client.get("/api/v1/conversations")
    assert res_list.status_code == 401

    # 2. POST /conversations without token -> 401
    res_create = client.post("/api/v1/conversations", json={"title": "Secret"})
    assert res_create.status_code == 401

    # 3. GET /conversations/{id} without token -> 401
    res_get = client.get("/api/v1/conversations/some-arbitrary-uuid")
    assert res_get.status_code == 401

    # 4. DELETE /conversations/{id} without token -> 401
    res_del = client.delete("/api/v1/conversations/some-arbitrary-uuid")
    assert res_del.status_code == 401

    # 5. POST /chat/ask with conversation_id without token -> 401
    res_ask = client.post(
        "/api/v1/chat/ask",
        json={"question": "What is ACT?", "conversation_id": "some-arbitrary-uuid"}
    )
    assert res_ask.status_code == 401


def test_ephemeral_guest_chat_without_conversation_id(test_client, monkeypatch):
    """
    Test that unauthenticated guest users can ask questions without conversation_id
    and get answers without error or database writes (backward compatibility for educational RAG).
    """
    from generation.gemini_client import GeminiClientWrapper
    monkeypatch.setattr(
        GeminiClientWrapper,
        "generate_chat_completion",
        lambda self, messages, **kwargs: "Educational answer for guest."
    )

    res = client.post(
        "/api/v1/chat/ask",
        json={"question": "What is the function of a bubble trap?"}
    )
    assert res.status_code == 200
    data = res.json()
    assert "answer" in data
    # Guest conversation_id is None / not persisted
    assert data.get("conversation_id") is None


def test_clinical_memories_user_isolation(test_client):
    """
    Test that long-term clinical memories are isolated per user.
    """
    uid_a_email = f"user_a_mem_{uuid.uuid4().hex[:6]}@clinic.org"
    uid_b_email = f"user_b_mem_{uuid.uuid4().hex[:6]}@hospital.edu"

    _, headers_a = register_user(uid_a_email, "Alice Clinician")
    _, headers_b = register_user(uid_b_email, "Bob Clinician")

    # User A creates a memory
    client.post(
        "/api/v1/conversations/memories",
        headers=headers_a,
        json={"key": "heparin_target_act", "content": "480 seconds standard"}
    )

    # User B creates a memory
    client.post(
        "/api/v1/conversations/memories",
        headers=headers_b,
        json={"key": "heparin_target_act", "content": "400 seconds minimum"}
    )

    # User A fetches memories
    mems_a = client.get("/api/v1/conversations/memories/all", headers=headers_a).json().get("memories", [])
    assert len(mems_a) >= 1
    contents_a = [m["content"] for m in mems_a]
    assert "480 seconds standard" in contents_a
    assert "400 seconds minimum" not in contents_a

    # User B fetches memories
    mems_b = client.get("/api/v1/conversations/memories/all", headers=headers_b).json().get("memories", [])
    assert len(mems_b) >= 1
    contents_b = [m["content"] for m in mems_b]
    assert "400 seconds minimum" in contents_b
    assert "480 seconds standard" not in contents_b


def test_legacy_unowned_conversation_cannot_be_accessed_by_any_user(test_client):
    """
    Verify that legacy conversations where user_id is NULL are not visible to or modifiable by
    any authenticated user.
    """
    engine = get_engine()
    if engine is None:
        pytest.skip("PostgreSQL database not configured")

    unowned_id = f"legacy_conv_{uuid.uuid4().hex[:8]}"

    # Insert an unowned conversation directly
    with Session(engine) as session:
        legacy = Conversation(
            id=unowned_id,
            user_id=None,
            title="Legacy Unowned Session"
        )
        session.add(legacy)
        session.commit()

    try:
        # Register User A
        uid_a_email = f"user_a_legacy_{uuid.uuid4().hex[:6]}@clinic.org"
        _, headers_a = register_user(uid_a_email, "Alice Legacy Check")

        # 1. User A lists conversations -> legacy must NOT be in the list
        list_res = client.get("/api/v1/conversations", headers=headers_a)
        assert list_res.status_code == 200
        conv_ids = [c["id"] for c in list_res.json().get("conversations", [])]
        assert unowned_id not in conv_ids

        # 2. User A attempts direct access to legacy unowned conversation -> 403 Forbidden
        get_res = client.get(f"/api/v1/conversations/{unowned_id}", headers=headers_a)
        assert get_res.status_code == 403

        # 3. User A attempts deletion of legacy unowned conversation -> 403 Forbidden
        del_res = client.delete(f"/api/v1/conversations/{unowned_id}", headers=headers_a)
        assert del_res.status_code == 403
    finally:
        # Clean up database
        with Session(engine) as session:
            session.query(Conversation).filter(Conversation.id == unowned_id).delete()
            session.commit()

