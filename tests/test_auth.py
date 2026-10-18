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
    """Test POST /api/v1/auth/configure and GET /api/v1/auth/google/login."""
    orig_id = client.get("/api/v1/auth/config").json()["google_client_id"]
    try:
        # Configure mock credentials
        conf_res = client.post(
            "/api/v1/auth/configure",
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

        # Test callback error handling
        cb_res = client.get("/api/v1/auth/google/callback?error=access_denied", follow_redirects=False)
        assert cb_res.status_code in (302, 307)
        assert "auth_error=access_denied" in cb_res.headers["location"]
    finally:
        # Cleanly restore
        client.post(
            "/api/v1/auth/configure",
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




