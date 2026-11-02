import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_auth_config_endpoint():
    """Test GET /api/v1/auth/config."""
    res = client.get("/api/v1/auth/config")
    assert res.status_code == 200
    data = res.json()
    assert "supabase_url" in data
    assert "supabase_anon_key" in data
    assert "supabase_enabled" in data
    assert "google_client_id" in data
    assert "enabled" in data
    assert "mode" in data


def test_auth_demo_accounts_removed():
    """Verify demo accounts have been completely removed and return 401."""
    # 1. Google demo credential must no longer bypass authentication
    res_google = client.post("/api/v1/auth/google", json={"credential": "demo_google_clinician"})
    assert res_google.status_code in (400, 401)

    # 2. Hardcoded email bypass must no longer log in without registration
    res_email = client.post(
        "/api/v1/auth/login",
        json={"email": "unregistered_clinician@hospital.edu", "password": "any_password"}
    )
    assert res_email.status_code == 401


def test_auth_unauthorized_me():
    """Test GET /api/v1/auth/me without valid token."""
    res = client.get("/api/v1/auth/me")
    assert res.status_code == 401

    res_invalid = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer invalid_token"})
    assert res_invalid.status_code == 401


def test_auth_configure_and_login_redirect():
    """Test POST /api/v1/auth/configure and GET /api/v1/auth/google/login with security checks."""
    from api.routes_auth import generate_session_token, ACTIVE_SESSIONS
    from schemas.auth import UserProfile

    # 1. Verify unauthenticated configure is rejected with 401
    unauth_res = client.post(
        "/api/v1/auth/configure",
        json={
            "supabase_url": "https://mockproject.supabase.co",
            "supabase_anon_key": "mock_anon_key_123"
        }
    )
    assert unauth_res.status_code == 401

    # 2. Verify non-admin configure is rejected with 403
    student_token = generate_session_token("student_123", "student@clinic.edu")
    ACTIVE_SESSIONS[student_token] = UserProfile(
        sub="student_123", email="student@clinic.edu", name="Student", role="student", token=student_token
    )
    forbidden_res = client.post(
        "/api/v1/auth/configure",
        headers={"Authorization": f"Bearer {student_token}"},
        json={
            "supabase_url": "https://mockproject.supabase.co",
            "supabase_anon_key": "mock_anon_key_123"
        }
    )
    assert forbidden_res.status_code == 403

    # 3. Verify admin configure succeeds with 200
    admin_token = generate_session_token("admin_123", "admin@clinic.edu")
    ACTIVE_SESSIONS[admin_token] = UserProfile(
        sub="admin_123", email="admin@clinic.edu", name="Admin", role="admin", token=admin_token
    )
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    try:
        conf_res = client.post(
            "/api/v1/auth/configure",
            headers=admin_headers,
            json={
                "supabase_url": "https://mockproject.supabase.co",
                "supabase_anon_key": "mock_anon_key_123",
                "google_client_id": "test-mock-client-id.apps.googleusercontent.com",
                "google_client_secret": "mock_secret_123"
            }
        )
        assert conf_res.status_code == 200
        conf_data = conf_res.json()
        assert conf_data["supabase_enabled"] is True
        assert conf_data["supabase_url"] == "https://mockproject.supabase.co"
        assert conf_data["google_client_id"] == "test-mock-client-id.apps.googleusercontent.com"

        # Test login redirect (should redirect to accounts.google.com)
        login_res = client.get("/api/v1/auth/google/login", follow_redirects=False)
        assert login_res.status_code in (302, 307)
        assert "accounts.google.com" in login_res.headers["location"]

        # Test open redirect protection on login endpoint
        evil_login_res = client.get("/api/v1/auth/google/login?return_to=https://evil.com", follow_redirects=False)
        assert evil_login_res.status_code in (302, 307)
        assert "evil.com" not in evil_login_res.headers["location"]

        # Test callback error handling
        cb_res = client.get("/api/v1/auth/google/callback?error=access_denied", follow_redirects=False)
        assert cb_res.status_code in (302, 307)
        assert "auth_error=access_denied" in cb_res.headers["location"]
    finally:
        # Cleanly restore
        client.post(
            "/api/v1/auth/configure",
            headers=admin_headers,
            json={"supabase_url": "", "supabase_anon_key": "", "google_client_id": "", "google_client_secret": ""}
        )


def test_auth_email_register_and_login():
    """Test POST /api/v1/auth/register and subsequent login."""
    import uuid
    unique_email = f"clinician_{uuid.uuid4().hex[:8]}@clinic.edu"
    reg_res = client.post(
        "/api/v1/auth/register",
        json={
            "name": "Dr. Perfusion Specialist",
            "email": unique_email,
            "password": "secure_password_123",
            "role": "Chief Perfusionist"
        }
    )
    assert reg_res.status_code == 200
    user_data = reg_res.json()
    assert user_data["name"] == "Dr. Perfusion Specialist"
    assert user_data["email"] == unique_email
    assert user_data["token"] is not None

    # Login with the newly registered account
    login_res = client.post(
        "/api/v1/auth/login",
        json={"email": unique_email, "password": "secure_password_123"}
    )
    assert login_res.status_code == 200
    assert login_res.json()["email"] == unique_email

    # Wrong password test
    bad_login = client.post(
        "/api/v1/auth/login",
        json={"email": unique_email, "password": "wrong_password"}
    )
    assert bad_login.status_code == 401

    # Test me endpoint with the registered user's token
    headers = {"Authorization": f"Bearer {user_data['token']}"}
    me_res = client.get("/api/v1/auth/me", headers=headers)
    assert me_res.status_code == 200
    assert me_res.json()["email"] == unique_email

    # Test logout
    logout_res = client.post("/api/v1/auth/logout", headers=headers)
    assert logout_res.status_code == 200


def test_auth_recover_password():
    """Test POST /api/v1/auth/recover-password."""
    res = client.post(
        "/api/v1/auth/recover-password",
        json={"email": "clinician@clinic.edu"}
    )
    assert res.status_code == 200
    data = res.json()
    assert "message" in data


def test_register_role_escalation_prevented():
    """Test that unauthorized clients cannot assign themselves admin role on registration."""
    import uuid
    attacker_email = f"attacker_{uuid.uuid4().hex[:8]}@untrusted.com"
    res = client.post(
        "/api/v1/auth/register",
        json={
            "email": attacker_email,
            "name": "Attacker",
            "password": "strongPassword123!",
            "role": "admin"
        }
    )
    assert res.status_code == 200
    profile = res.json()
    assert profile["role"].lower() not in ("admin", "administrator")
    assert profile["role"] == "Clinical Perfusionist"


def test_register_rate_limiting():
    """Test that spamming registrations from the same IP triggers 429 Too Many Requests."""
    import uuid
    from api.routes_auth import reset_rate_limits
    reset_rate_limits()

    # Perform 5 registrations
    for i in range(5):
        unique_email = f"spam_user_{i}_{uuid.uuid4().hex[:6]}@clinic.edu"
        res = client.post(
            "/api/v1/auth/register",
            json={
                "email": unique_email,
                "name": f"Spam User {i}",
                "password": "securePassword123!"
            }
        )
        assert res.status_code == 200

    # 6th attempt must be blocked by rate limiter
    blocked_email = f"spam_user_blocked_{uuid.uuid4().hex[:6]}@clinic.edu"
    res_blocked = client.post(
        "/api/v1/auth/register",
        json={
            "email": blocked_email,
            "name": "Blocked User",
            "password": "securePassword123!"
        }
    )
    assert res_blocked.status_code == 429
    assert "Too many account registration attempts" in res_blocked.json()["detail"]
    reset_rate_limits()


def test_persistent_secret_key():
    """Test that SECRET_KEY is stable and persistent across invocations."""
    from config import _get_or_create_persistent_secret
    k1 = _get_or_create_persistent_secret()
    k2 = _get_or_create_persistent_secret()
    assert k1 == k2
    assert len(k1) >= 32





