"""
Authentication Router for Google Sign-In and User Session Management.
Supports Google Identity Services (GSI) verification via Google tokeninfo API.
"""

import hashlib
import hmac
import json
import logging
import time
from typing import Optional
from urllib.parse import urlencode
from fastapi import APIRouter, HTTPException, Header, Request, status
from fastapi.responses import RedirectResponse
import httpx
from config import settings
from schemas.auth import (
    AuthConfigResponse,
    GoogleAuthRequest,
    UserProfile,
    ConfigureAuthRequest,
    EmailLoginRequest,
    RegisterRequest,
    PasswordRecoveryRequest,
    SupabaseSessionSyncRequest
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])

# Secret key for local session signing
SESSION_SECRET = settings.GROQ_API_KEY[:32] if settings.GROQ_API_KEY else "perfusion_session_secret_key_8492"

# In-memory session store (token -> UserProfile)
ACTIVE_SESSIONS = {}

# Rate limiting store for login attempts: ip -> list of timestamps
LOGIN_ATTEMPTS = {}


def check_login_rate_limit(client_ip: str):
    """Prevent brute-force password guessing attacks (max 20 attempts per 5 minutes per IP)."""
    now = time.time()
    attempts = [t for t in LOGIN_ATTEMPTS.get(client_ip, []) if (now - t) < 300]
    if len(attempts) >= 20:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many authentication attempts. Please wait 5 minutes before trying again."
        )
    attempts.append(now)
    LOGIN_ATTEMPTS[client_ip] = attempts


def is_supabase_configured() -> bool:
    """Check if Supabase URL and Anon Key are set in settings."""
    url = getattr(settings, "SUPABASE_URL", "").strip()
    key = getattr(settings, "SUPABASE_ANON_KEY", "").strip()
    return bool(url and key)


async def supabase_request(
    method: str,
    path: str,
    json_data: Optional[dict] = None,
    bearer_token: Optional[str] = None
) -> tuple[int, dict]:
    """
    Make an asynchronous HTTP request to Supabase Auth REST API.
    """
    url = settings.SUPABASE_URL.strip().rstrip("/")
    key = settings.SUPABASE_ANON_KEY.strip()
    if not url or not key:
        return 503, {"error": "Supabase credentials not configured."}

    full_url = f"{url}/auth/v1{path}"
    headers = {
        "apikey": key,
        "Content-Type": "application/json"
    }
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    else:
        headers["Authorization"] = f"Bearer {key}"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.request(method, full_url, json=json_data, headers=headers)
            try:
                return resp.status_code, resp.json()
            except Exception:
                return resp.status_code, {"text": resp.text}
    except Exception as e:
        logger.error(f"Error contacting Supabase Auth at {full_url}: {e}")
        return 503, {"error": f"Supabase connection error: {str(e)}"}


def generate_session_token(sub: str, email: str) -> str:
    """Generate a tamper-proof session token."""
    payload = f"{sub}:{email}:{int(time.time())}"
    signature = hmac.new(SESSION_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}:{signature}"


# Maximum duration for signed local session tokens (7 days)
SESSION_MAX_AGE_SECONDS = 7 * 24 * 3600


def verify_session_token(token: str) -> bool:
    """Verify validity and expiration of a session token."""
    try:
        parts = token.split(":")
        if len(parts) != 4:
            return False
        sub, email, timestamp, signature = parts

        # Verify token expiration TTL
        try:
            ts = int(timestamp)
            now = int(time.time())
            if (now - ts) > SESSION_MAX_AGE_SECONDS or ts > (now + 300):
                return False
        except (ValueError, TypeError):
            return False

        payload = f"{sub}:{email}:{timestamp}"
        expected = hmac.new(SESSION_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature, expected)
    except Exception:
        return False


def hash_password(password: str) -> str:
    """Hash password using HMAC-SHA256 with secret salt."""
    return hmac.new(SESSION_SECRET.encode(), password.strip().encode(), hashlib.sha256).hexdigest()


@router.get("/config", response_model=AuthConfigResponse)
async def get_auth_config():
    """
    Returns Supabase & Google configuration for frontend initialization.
    """
    supa_url = settings.SUPABASE_URL.strip() if getattr(settings, "SUPABASE_URL", None) else ""
    supa_key = settings.SUPABASE_ANON_KEY.strip() if getattr(settings, "SUPABASE_ANON_KEY", None) else ""
    client_id = settings.GOOGLE_CLIENT_ID.strip() if settings.GOOGLE_CLIENT_ID else ""
    supa_enabled = bool(supa_url and supa_key)
    return AuthConfigResponse(
        supabase_url=supa_url,
        supabase_anon_key=supa_key,
        supabase_enabled=supa_enabled,
        google_client_id=client_id,
        enabled=supa_enabled or bool(client_id),
        mode="live" if supa_enabled else "setup_required"
    )


@router.post("/configure", response_model=AuthConfigResponse)
async def configure_auth(payload: ConfigureAuthRequest):
    """
    Dynamically update Supabase / Google OAuth credentials, persist them to .env, and update runtime settings.
    """
    supa_url = payload.supabase_url.strip() if payload.supabase_url is not None else settings.SUPABASE_URL
    supa_key = payload.supabase_anon_key.strip() if payload.supabase_anon_key is not None else settings.SUPABASE_ANON_KEY
    client_id = payload.google_client_id.strip() if payload.google_client_id is not None else settings.GOOGLE_CLIENT_ID
    client_secret = payload.google_client_secret.strip() if payload.google_client_secret is not None else settings.GOOGLE_CLIENT_SECRET

    settings.SUPABASE_URL = supa_url
    settings.SUPABASE_ANON_KEY = supa_key
    settings.GOOGLE_CLIENT_ID = client_id
    if client_secret:
        settings.GOOGLE_CLIENT_SECRET = client_secret

    # Persist to .env
    try:
        env_path = ".env"
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        keys_to_update = {
            "SUPABASE_URL": supa_url,
            "SUPABASE_ANON_KEY": supa_key,
            "GOOGLE_CLIENT_ID": client_id,
        }
        if client_secret:
            keys_to_update["GOOGLE_CLIENT_SECRET"] = client_secret

        updated_lines = []
        found_keys = set()
        for line in lines:
            updated = False
            for k, val in keys_to_update.items():
                if line.startswith(f"{k}="):
                    updated_lines.append(f"{k}={val}\n")
                    found_keys.add(k)
                    updated = True
                    break
            if not updated:
                updated_lines.append(line)

        for k, val in keys_to_update.items():
            if k not in found_keys and val:
                updated_lines.append(f"{k}={val}\n")

        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(updated_lines)

        logger.info("Updated Supabase and OAuth credentials in .env successfully.")
    except Exception as e:
        logger.warning(f"Could not persist credentials to .env: {e}")

    supa_enabled = bool(supa_url and supa_key)
    return AuthConfigResponse(
        supabase_url=supa_url,
        supabase_anon_key=supa_key,
        supabase_enabled=supa_enabled,
        google_client_id=client_id,
        enabled=supa_enabled or bool(client_id),
        mode="live" if supa_enabled else "setup_required"
    )


@router.get("/google/login")
async def google_login(request: Request):
    """
    Standard OAuth 2.0 authorization redirect to Google Accounts.
    """
    client_id = settings.GOOGLE_CLIENT_ID.strip() if settings.GOOGLE_CLIENT_ID else ""
    if not client_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GOOGLE_CLIENT_ID is not configured in .env. Please configure your Google Client ID first."
        )

    base = str(request.base_url).rstrip("/")
    redirect_uri = f"{base}/api/v1/auth/google/callback"

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "select_account"
    }
    google_auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"
    return RedirectResponse(url=google_auth_url)


@router.get("/google/callback")
async def google_callback(request: Request, code: Optional[str] = None, error: Optional[str] = None):
    """
    OAuth 2.0 callback endpoint handling Google's authorization response.
    Exchanges code for tokens, extracts profile, and redirects to frontend with token.
    """
    if error:
        logger.warning(f"Google OAuth callback returned error: {error}")
        return RedirectResponse(url=f"/?auth_error={error}")

    if not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing authorization code from Google."
        )

    client_id = settings.GOOGLE_CLIENT_ID.strip() if settings.GOOGLE_CLIENT_ID else ""
    client_secret = settings.GOOGLE_CLIENT_SECRET.strip() if settings.GOOGLE_CLIENT_SECRET else ""

    base = str(request.base_url).rstrip("/")
    redirect_uri = f"{base}/api/v1/auth/google/callback"

    token_url = "https://oauth2.googleapis.com/token"
    token_data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            token_resp = await client.post(token_url, data=token_data)

        if token_resp.status_code != 200:
            err_msg = token_resp.text
            logger.error(f"Google token exchange failed: {err_msg}")
            return RedirectResponse(url="/?auth_error=token_exchange_failed")

        tokens = token_resp.json()
        access_token = tokens.get("access_token")

        # Fetch user profile using access token
        async with httpx.AsyncClient(timeout=10.0) as client:
            userinfo_resp = await client.get(
                "https://www.googleapis.com/oauth2/v3/userinfo",
                headers={"Authorization": f"Bearer {access_token}"}
            )

        if userinfo_resp.status_code != 200:
            logger.error(f"Failed to fetch Google userinfo: {userinfo_resp.text}")
            return RedirectResponse(url="/?auth_error=userinfo_failed")

        user_info = userinfo_resp.json()
        sub = user_info.get("sub")
        email = user_info.get("email")
        name = user_info.get("name", email.split("@")[0] if email else "Clinical Perfusionist")
        picture = user_info.get("picture")
        given_name = user_info.get("given_name")
        family_name = user_info.get("family_name")

        session_token = generate_session_token(sub, email)
        profile = UserProfile(
            sub=sub,
            email=email,
            name=name,
            given_name=given_name,
            family_name=family_name,
            picture=picture,
            role="Clinical Perfusionist",
            authenticated=True,
            token=session_token
        )

        ACTIVE_SESSIONS[session_token] = profile
        _persist_user_to_db(profile)
        logger.info(f"Successfully authenticated Google OAuth user: {email} ({name})")

        return RedirectResponse(url=f"/?auth_token={session_token}")

    except Exception as e:
        logger.error(f"Exception during Google OAuth callback: {e}")
        return RedirectResponse(url="/?auth_error=internal_error")


@router.post("/google", response_model=UserProfile)
async def authenticate_google(payload: GoogleAuthRequest):
    """
    Verifies a Google ID Token (JWT) sent from the frontend Google Sign-In button.
    Calls Google's official tokeninfo endpoint to validate signature, audience, and claims.
    """
    credential = payload.credential.strip()
    if not credential:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing Google authentication credential."
        )

    # Live Verification with Google Identity Services API
    google_tokeninfo_url = f"https://oauth2.googleapis.com/tokeninfo?id_token={credential}"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(google_tokeninfo_url)

        if resp.status_code != 200:
            error_detail = resp.json().get("error_description", "Invalid Google ID Token.")
            logger.warning(f"Google token verification failed: {error_detail}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Google authentication failed: {error_detail}"
            )

        token_data = resp.json()

        # Validate Audience if configured
        configured_client_id = settings.GOOGLE_CLIENT_ID.strip() if settings.GOOGLE_CLIENT_ID else None
        if configured_client_id and token_data.get("aud") != configured_client_id:
            logger.warning(
                f"Token audience mismatch: aud={token_data.get('aud')} vs configured={configured_client_id}"
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Google token was issued for a different client ID."
            )

        sub = token_data.get("sub")
        email = token_data.get("email")
        name = token_data.get("name", email.split("@")[0] if email else "Perfusion User")
        picture = token_data.get("picture")
        given_name = token_data.get("given_name")
        family_name = token_data.get("family_name")

        session_token = generate_session_token(sub, email)
        profile = UserProfile(
            sub=sub,
            email=email,
            name=name,
            given_name=given_name,
            family_name=family_name,
            picture=picture,
            role="Clinical Perfusionist",
            authenticated=True,
            token=session_token
        )

        ACTIVE_SESSIONS[session_token] = profile
        _persist_user_to_db(profile)
        logger.info(f"Successfully authenticated Google user: {email} ({name})")
        return profile

    except httpx.RequestError as e:
        logger.error(f"Network error contacting Google tokeninfo endpoint: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to contact Google OAuth service to verify identity."
        )


def _persist_user_to_db(profile: UserProfile):
    """Safely persist or update authenticated Google user in PostgreSQL."""
    try:
        from storage.db import is_db_configured, get_session_factory
        from storage.db_models import User
        from datetime import datetime

        if not is_db_configured():
            return

        factory = get_session_factory()
        if not factory:
            return

        with factory() as db:
            user = db.query(User).filter(User.id == profile.sub).first()
            if user:
                user.name = profile.name
                user.email = profile.email
                if profile.picture:
                    user.picture = profile.picture
                user.last_login_at = datetime.utcnow()
            else:
                user = User(
                    id=profile.sub,
                    email=profile.email,
                    name=profile.name,
                    given_name=profile.given_name,
                    family_name=profile.family_name,
                    picture=profile.picture,
                    role=profile.role,
                    last_login_at=datetime.utcnow()
                )
                db.add(user)
            db.commit()
    except Exception as e:
        logger.warning(f"Note on user persistence to PostgreSQL: {e}")


@router.get("/me", response_model=UserProfile)
async def get_current_user(authorization: Optional[str] = Header(None)):
    """
    Retrieve current authenticated user profile from Authorization header.
    Validates token against Supabase Auth API, in-memory cache, or signed session store.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated."
        )

    token = authorization.replace("Bearer ", "").strip()

    # 1. Check in-memory cache
    if token in ACTIVE_SESSIONS:
        return ACTIVE_SESSIONS[token]

    # 2. Check Supabase token validity
    if is_supabase_configured():
        status_code, resp_data = await supabase_request("GET", "/user", bearer_token=token)
        if status_code == 200:
            sub = resp_data.get("id")
            email = resp_data.get("email")
            meta = resp_data.get("user_metadata") or {}
            name = meta.get("name") or meta.get("full_name") or (email.split("@")[0].replace(".", " ").title() if email else "Clinician")
            picture = meta.get("avatar_url") or meta.get("picture")
            role = meta.get("role") or "Clinical Perfusionist"

            profile = UserProfile(
                sub=sub,
                email=email,
                name=name,
                picture=picture,
                role=role,
                authenticated=True,
                token=token
            )
            ACTIVE_SESSIONS[token] = profile
            _persist_user_to_db(profile)
            return profile

    # 3. Check local signed session token
    if verify_session_token(token):
        try:
            parts = token.split(":")
            sub, email, timestamp, signature = parts
            name = email.split("@")[0].replace(".", " ").title()
            picture = None
            role = "Clinical Perfusionist"

            try:
                from storage.db import is_db_configured, get_session_factory
                from storage.db_models import User

                if is_db_configured():
                    factory = get_session_factory()
                    if factory:
                        with factory() as db:
                            u = db.query(User).filter(User.id == sub).first()
                            if u:
                                name = u.name
                                picture = u.picture
                                role = u.role
            except Exception:
                pass

            restored_profile = UserProfile(
                sub=sub,
                email=email,
                name=name,
                picture=picture,
                role=role,
                authenticated=True,
                token=token
            )
            ACTIVE_SESSIONS[token] = restored_profile
            return restored_profile
        except Exception:
            pass

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired session token."
    )


@router.post("/logout")
async def logout(authorization: Optional[str] = Header(None)):
    """
    Log out and invalidate current session in cache and Supabase.
    """
    if authorization and authorization.startswith("Bearer "):
        token = authorization.replace("Bearer ", "").strip()
        ACTIVE_SESSIONS.pop(token, None)
        if is_supabase_configured():
            try:
                await supabase_request("POST", "/logout", bearer_token=token)
            except Exception as e:
                logger.debug(f"Supabase logout call: {e}")

    return {"status": "success", "message": "Logged out successfully."}


@router.post("/session", response_model=UserProfile)
async def sync_supabase_session(payload: SupabaseSessionSyncRequest):
    """
    Sync frontend Supabase session to backend, verifying the JWT with Supabase Auth API.
    """
    token = payload.access_token.strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing access token."
        )

    if is_supabase_configured():
        status_code, resp_data = await supabase_request("GET", "/user", bearer_token=token)
        if status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired Supabase token."
            )

        sub = resp_data.get("id")
        email = resp_data.get("email")
        meta = resp_data.get("user_metadata") or {}
        name = meta.get("name") or meta.get("full_name") or (email.split("@")[0].replace(".", " ").title() if email else "Clinician")
        picture = meta.get("avatar_url") or meta.get("picture")
        role = meta.get("role") or "Clinical Perfusionist"

        profile = UserProfile(
            sub=sub,
            email=email,
            name=name,
            picture=picture,
            role=role,
            authenticated=True,
            token=token
        )
        ACTIVE_SESSIONS[token] = profile
        _persist_user_to_db(profile)
        return profile

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Supabase is not configured on the server."
    )


@router.post("/recover-password")
async def recover_password(payload: PasswordRecoveryRequest):
    """
    Request password recovery email via Supabase Auth.
    """
    email = payload.email.strip().lower()
    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email is required."
        )

    if is_supabase_configured():
        status_code, resp_data = await supabase_request(
            "POST",
            "/recover",
            json_data={"email": email}
        )
        if status_code in (200, 204):
            return {
                "status": "success",
                "message": f"Password recovery instructions sent to {email} via Supabase."
            }
        err = resp_data.get("msg") or resp_data.get("message") or "Recovery request failed."
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err)

    return {
        "status": "info",
        "message": "Password recovery is managed by institutional IT. Supabase configuration is pending."
    }


@router.post("/login", response_model=UserProfile)
async def login_with_email(payload: EmailLoginRequest, request: Request):
    """
    Institutional Email and Password login.
    Uses Supabase Auth when configured, or local verified database accounts.
    NO DEMO ACCOUNTS.
    """
    client_ip = request.client.host if request.client else "127.0.0.1"
    check_login_rate_limit(client_ip)

    email = payload.email.strip().lower()
    password = payload.password.strip()

    if not email or not password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email and password are required."
        )

    # 1. Supabase Authentication
    if is_supabase_configured():
        status_code, resp_data = await supabase_request(
            "POST",
            "/token?grant_type=password",
            json_data={"email": email, "password": password}
        )
        if status_code != 200:
            err_msg = resp_data.get("error_description") or resp_data.get("msg") or resp_data.get("message") or "Invalid login credentials."
            logger.warning(f"Supabase login failed for {email}: {err_msg}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Supabase authentication failed: {err_msg}"
            )

        user_info = resp_data.get("user") or {}
        access_token = resp_data.get("access_token")
        sub = user_info.get("id") or f"supa_{hashlib.md5(email.encode()).hexdigest()[:16]}"
        meta = user_info.get("user_metadata") or {}
        name = meta.get("name") or meta.get("full_name") or email.split("@")[0].replace(".", " ").title()
        picture = meta.get("avatar_url") or meta.get("picture")
        role = meta.get("role") or "Clinical Perfusionist"

        profile = UserProfile(
            sub=sub,
            email=email,
            name=name,
            picture=picture,
            role=role,
            authenticated=True,
            token=access_token
        )
        ACTIVE_SESSIONS[access_token] = profile
        _persist_user_to_db(profile)
        logger.info(f"User authenticated via Supabase: {email} ({name})")
        return profile

    # 2. Local Database Authentication (when Supabase is pending setup)
    from storage.db import is_db_configured, get_session_factory
    from storage.db_models import User
    from datetime import datetime

    user_id = None
    user_name = None
    user_picture = None
    user_role = None
    user_found = False

    if is_db_configured():
        factory = get_session_factory()
        if factory:
            try:
                with factory() as db:
                    user_match = db.query(User).filter(User.email == email).first()
                    if user_match:
                        user_found = True
                        if user_match.password_hash:
                            if user_match.password_hash != hash_password(password):
                                raise HTTPException(
                                    status_code=status.HTTP_401_UNAUTHORIZED,
                                    detail="Incorrect password for this institutional account."
                                )
                        user_id = user_match.id
                        user_name = user_match.name
                        user_picture = user_match.picture
                        user_role = user_match.role or "Clinical Perfusionist"
                        user_match.last_login_at = datetime.utcnow()
                        db.commit()
            except HTTPException:
                raise
            except Exception as e:
                logger.warning(f"Error querying user table in login: {e}")

    if not user_found:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account not found. Please verify your email or click 'Create an account'."
        )

    sub = user_id or f"inst_{hashlib.md5(email.encode()).hexdigest()[:16]}"
    name = user_name or (email.split("@")[0].replace(".", " ").title() or "Clinical Perfusionist")
    picture = user_picture
    role = user_role or "Clinical Perfusionist"

    session_token = generate_session_token(sub, email)
    profile = UserProfile(
        sub=sub,
        email=email,
        name=name,
        picture=picture,
        role=role,
        authenticated=True,
        token=session_token
    )
    ACTIVE_SESSIONS[session_token] = profile
    _persist_user_to_db(profile)
    logger.info(f"User signed in: {email} ({name})")
    return profile


@router.post("/register", response_model=UserProfile)
async def register_account(payload: RegisterRequest):
    """
    Register a new clinical / student institutional account.
    Registers via Supabase Auth when configured, and syncs to PostgreSQL database.
    """
    email = payload.email.strip().lower()
    name = payload.name.strip()
    password = payload.password.strip()
    role = payload.role.strip() if payload.role else "Clinical Perfusionist"

    if not email or "@" not in email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A valid institutional email is required."
        )
    if len(password) < 4:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 4 characters long."
        )

    # 1. Supabase Registration
    if is_supabase_configured():
        status_code, resp_data = await supabase_request(
            "POST",
            "/signup",
            json_data={
                "email": email,
                "password": password,
                "data": {"name": name, "role": role}
            }
        )
        if status_code not in (200, 201):
            err_msg = resp_data.get("msg") or resp_data.get("message") or resp_data.get("error_description") or "Registration failed in Supabase."
            logger.warning(f"Supabase registration error for {email}: {err_msg}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Supabase registration error: {err_msg}"
            )

        user_info = resp_data.get("user") or resp_data
        sub = user_info.get("id") or f"supa_{hashlib.md5(email.encode()).hexdigest()[:16]}"
        access_token = resp_data.get("access_token") or generate_session_token(sub, email)

        profile = UserProfile(
            sub=sub,
            email=email,
            name=name,
            role=role,
            authenticated=True,
            token=access_token
        )
        ACTIVE_SESSIONS[access_token] = profile
        _persist_user_to_db(profile)
        logger.info(f"Clinician account registered with Supabase: {email} ({name})")
        return profile

    # 2. Local Database Registration
    import uuid
    from storage.db import is_db_configured, get_session_factory
    from storage.db_models import User
    from datetime import datetime

    sub = f"usr_{uuid.uuid4().hex[:16]}"
    pwd_hash = hash_password(password)

    if is_db_configured():
        factory = get_session_factory()
        if factory:
            try:
                with factory() as db:
                    existing = db.query(User).filter(User.email == email).first()
                    if existing:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="An account already exists with this institutional email. Please sign in."
                        )
                    new_user = User(
                        id=sub,
                        email=email,
                        name=name,
                        password_hash=pwd_hash,
                        role=role,
                        last_login_at=datetime.utcnow()
                    )
                    db.add(new_user)
                    db.commit()
            except HTTPException:
                raise
            except Exception as e:
                logger.warning(f"Error persisting new user in register: {e}")

    session_token = generate_session_token(sub, email)
    profile = UserProfile(
        sub=sub,
        email=email,
        name=name,
        role=role,
        authenticated=True,
        token=session_token
    )
    ACTIVE_SESSIONS[session_token] = profile
    logger.info(f"New clinician account registered: {email} ({name})")
    return profile



