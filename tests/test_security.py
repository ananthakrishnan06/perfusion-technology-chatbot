from urllib.parse import parse_qs, urlparse
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner

from api import routes_auth
from config import settings
from main import app


def test_cookie_session_expiration_and_logout(verified_registration, monkeypatch):
    client = TestClient(app, base_url="https://testserver", headers={"X-Perfusion-Session": "cookie"})
    payload = {"email": "browser@example.org", "name": "Browser User", "password": "long-password"}
    registered = verified_registration(client, payload, headers={"X-Perfusion-Session": "cookie"})
    assert registered.status_code == 200
    assert registered.json()["token"] is None
    cookie = registered.headers["set-cookie"]
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=lax" in cookie
    assert client.get("/api/v1/auth/me").json()["email"] == payload["email"]
    assert client.get("/api/v1/auth/me").json()["token"] is None
    assert client.get("/api/v1/auth/me", headers={"Origin": "https://elsewhere.invalid"}).status_code == 403
    with monkeypatch.context() as clock:
        later = int(routes_auth.time.time()) + routes_auth.SESSION_MAX_AGE_SECONDS + 1
        clock.setattr(TimestampSigner, "get_timestamp", lambda self: later)
        assert client.get("/api/v1/auth/me").status_code == 401
    assert client.post("/api/v1/auth/logout").status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401


def test_supabase_requires_confirmation_and_server_owned_roles(monkeypatch):
    client = TestClient(app)
    monkeypatch.setattr(settings, "SUPABASE_URL", "https://example.invalid")
    monkeypatch.setattr(settings, "SUPABASE_ANON_KEY", "test")
    payload = {"email": "student@example.org", "name": "Student", "password": "long-password"}
    user = {"id": "student", "email": payload["email"], "user_metadata": {"role": "admin"}}
    upstream = AsyncMock(return_value=(200, {"user": user}))
    monkeypatch.setattr(routes_auth, "supabase_request", upstream)
    pending = client.post("/api/v1/auth/register", json=payload)
    assert pending.json()["status"] == "verification_required" and "token" not in pending.json()
    upstream.return_value = 200, user
    headers = {"Authorization": "Bearer test.provider.session"}
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401
    user["email_confirmed_at"] = "2026-01-01T00:00:00Z"
    assert client.get("/api/v1/auth/me", headers=headers).json()["role"] == "Clinical Perfusionist"
    assert client.post("/api/v1/auth/configure", headers=headers, json={}).status_code == 403
    user["app_metadata"] = {"role": "admin"}
    assert client.get("/api/v1/auth/me", headers=headers).json()["role"] == "admin"
    upstream.return_value = 401, {}
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401


def test_google_redirect_binds_browser_and_exchanges_code(monkeypatch):
    import httpx
    import hashlib
    import base64
    client = TestClient(app, base_url="https://testserver")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "client")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "private")
    verifier = "v" * 43
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    start = client.get("/api/v1/auth/google/login", params={"challenge": challenge}, follow_redirects=False)
    params = parse_qs(urlparse(start.headers["location"]).query)
    assert params["code_challenge"] == [challenge] and params["code_challenge_method"] == ["S256"]
    callback = {"state": params["state"][0], "code": "one-use-code"}
    assert TestClient(app).get("/api/v1/auth/google/callback", params=callback).status_code == 400
    redirect = client.get("/api/v1/auth/google/callback", params=callback, follow_redirects=False)
    assert redirect.status_code == 307
    assert redirect.headers["location"].endswith("#google_code=one-use-code")
    assert client.get("/api/v1/auth/google/callback", params=callback).status_code == 400

    def provider(request):
        if request.url.path == "/token":
            fields = parse_qs(request.content.decode())
            assert fields["code_verifier"] == [verifier] and fields["code"] == ["one-use-code"]
            return httpx.Response(200, json={"access_token": "provider-only"})
        return httpx.Response(200, json={"sub": "google-account", "email": "admin@clinic.edu", "email_verified": True})

    upstream = httpx.AsyncClient(transport=httpx.MockTransport(provider))
    monkeypatch.setattr(routes_auth.httpx, "AsyncClient", lambda **kwargs: upstream)
    signed_in = client.post("/api/v1/auth/google/exchange", headers={"X-Perfusion-Session": "cookie"},
                            json={"code": "one-use-code", "verifier": verifier})
    assert signed_in.status_code == 200 and signed_in.json()["token"] is None
    assert signed_in.json()["role"] == "admin" and "HttpOnly" in signed_in.headers["set-cookie"]


def test_shared_ai_quota_across_routes(monkeypatch):
    from api.dependencies import get_chat_service
    from unittest.mock import Mock
    from schemas.chat import MCQResponse
    monkeypatch.setattr(settings, "AI_REQUESTS_PER_MINUTE", 1)
    service = Mock()
    service.generate_study_mcqs.return_value = MCQResponse(topic="study", questions=[], total_questions=0,
                                                           insufficient_evidence=True, citations=[])
    monkeypatch.setitem(app.dependency_overrides, get_chat_service, lambda: service)
    client = TestClient(app)
    assert client.post("/api/v1/study/mcq", json={"topic": "study"}).status_code == 200
    for path in ("ask", "stream"):
        denied = client.post("/api/v1/chat/" + path, json={"question": "study"})
        assert denied.status_code == 429 and int(denied.headers["retry-after"]) > 0
    assert client.post("/api/v1/chat/transcribe", files={"file": ("test.wav", b"test")}).status_code == 429
    service.transcribe_audio.assert_not_called()
