"""
Authentication Router for Google Sign-In and User Session Management.
Supports Google Identity Services (GSI) verification via Google tokeninfo API.
"""

import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlencode, urlparse
from fastapi import APIRouter, Depends, HTTPException, Header, Request, status
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

import secrets
from datetime import datetime, timezone, timedelta

router = APIRouter(prefix="/auth", tags=["Authentication"])

# Secret key for local session signing (must be from settings.SECRET_KEY or secure runtime generation)
SESSION_SECRET = getattr(settings, "SECRET_KEY", "").strip()
if not SESSION_SECRET or SESSION_SECRET in ("your_strong_random_secret_key", "perfusion_session_secret_key_8492"):
    SESSION_SECRET = secrets.token_hex(32)

# In-memory session store (token -> UserProfile)
ACTIVE_SESSIONS = {}

# In-memory cache of revoked token hashes (SHA-256)
REVOKED_TOKENS_MEM = set()

# Rate limiting store for login attempts: ip -> list of timestamps
LOGIN_ATTEMPTS = {}


def is_token_revoked(token: str) -> bool:
    """Check if token hash has been invalidated/revoked in memory or PostgreSQL."""
    if not token:
        return True
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    if token_hash in REVOKED_TOKENS_MEM:
        return True

    try:
        from storage.db import is_db_configured, get_session_factory
        from storage.db_models import RevokedToken
        if is_db_configured():
            factory = get_session_factory()
            if factory:
                with factory() as db:
                    found = db.query(RevokedToken).filter(RevokedToken.token_hash == token_hash).first()
                    if found:
                        REVOKED_TOKENS_MEM.add(token_hash)
                        return True
    except Exception as e:
        logger.debug(f"DB check for revoked token: {e}")

    return False


def revoke_token(token: str):
    """Revoke a session token in memory and PostgreSQL across server restarts."""
    if not token:
        return
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    REVOKED_TOKENS_MEM.add(token_hash)
    try:
        from storage.db import is_db_configured, get_session_factory
        from storage.db_models import RevokedToken
        if is_db_configured():
            factory = get_session_factory()
            if factory:
                with factory() as db:
                    existing = db.query(RevokedToken).filter(RevokedToken.token_hash == token_hash).first()
                    if not existing:
                        db.add(RevokedToken(token_hash=token_hash))
                        db.commit()
    except Exception as e:
        logger.warning(f"Error persisting revoked token to DB: {e}")


def check_login_rate_limit(client_ip: str):
    """
    Prevent brute-force password guessing attacks (max 20 attempts per 5 minutes per IP).
    Persists across server restarts and instances when PostgreSQL is configured.
    """
    now = time.time()
    # 1. Check in DB if configured
    try:
        from storage.db import is_db_configured, get_session_factory
        from storage.db_models import LoginRateLimit

        if is_db_configured():
            factory = get_session_factory()
            if factory:
                with factory() as db:
                    window_start = datetime.now(timezone.utc) - timedelta(minutes=5)
                    count = db.query(LoginRateLimit).filter(
                        LoginRateLimit.ip_address == client_ip,
                        LoginRateLimit.attempt_time >= window_start
                    ).count()
                    if count >= 20:
                        raise HTTPException(
                            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                            detail="Too many authentication attempts. Please wait 5 minutes before trying again."
                        )
                    # Record current attempt
                    db.add(LoginRateLimit(ip_address=client_ip))
                    # Opportunistically prune expired records older than 10 minutes
                    old_threshold = datetime.now(timezone.utc) - timedelta(minutes=10)
                    db.query(LoginRateLimit).filter(LoginRateLimit.attempt_time < old_threshold).delete()
                    db.commit()
                    return
    except HTTPException:
        raise
    except Exception as e:
        logger.debug(f"DB rate limit query note: {e}")

    # 2. In-memory fallback
    attempts = [t for t in LOGIN_ATTEMPTS.get(client_ip, []) if (now - t) < 300]
    if len(attempts) >= 20:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many authentication attempts. Please wait 5 minutes before trying again."
        )
    attempts.append(now)
    LOGIN_ATTEMPTS[client_ip] = attempts


# Initialize Argon2 PasswordHasher (Argon2id - OWASP Recommended Standard)
try:
    from argon2 import PasswordHasher
    from argon2.exceptions import VerifyMismatchError
    _password_hasher = PasswordHasher(
        time_cost=3,
        memory_cost=65536,
        parallelism=4,
        hash_len=32,
        salt_len=16
    )
except ImportError:
    _password_hasher = None

# Pre-computed dummy hash to mitigate timing attacks on non-existent users
DUMMY_ARGON2_HASH = (
    _password_hasher.hash("dummy_timing_protection_password")
    if _password_hasher
    else "$argon2id$v=19$m=65536,t=3,p=4$dummy$dummy"
)


def hash_password(password: str) -> str:
    """Hash password using Argon2id with unique per-user cryptographically secure salt."""
    if _password_hasher:
        return _password_hasher.hash(password.strip())
    # Fallback to PBKDF2-HMAC-SHA256 with random 16-byte salt if argon2 not available
    salt = secrets.token_hex(16)
    kdf = hashlib.pbkdf2_hmac("sha256", password.strip().encode(), salt.encode(), 100000)
    return f"pbkdf2:{salt}:{kdf.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify password against Argon2id, PBKDF2, or legacy hash."""
    if not stored_hash:
        return False
    if stored_hash.startswith("$argon2"):
        if _password_hasher:
            try:
                return _password_hasher.verify(stored_hash, password.strip())
            except VerifyMismatchError:
                return False
            except Exception:
                return False
        return False
    elif stored_hash.startswith("pbkdf2:"):
        try:
            _, salt, expected_hex = stored_hash.split(":")
            kdf = hashlib.pbkdf2_hmac("sha256", password.strip().encode(), salt.encode(), 100000)
            return hmac.compare_digest(kdf.hex(), expected_hex)
        except Exception:
            return False
    else:
        # Legacy HMAC-SHA256 hash compatibility
        legacy_expected = hmac.new(SESSION_SECRET.encode(), password.strip().encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(stored_hash, legacy_expected)


def is_safe_redirect_url(url: Optional[str], request: Request) -> bool:
    """
    Validate that a redirect URL is strictly on the same origin or configured frontend.
    Rejects any attacker-controlled external URLs or protocol-relative URLs (e.g. //evil.com).
    """
    if not url or not isinstance(url, str):
        return False
    url = url.strip()
    if not url:
        return False

    # Disallow protocol-relative URLs (e.g. //evil.com) and backslashes (e.g. /\\evil.com)
    if url.startswith("//") or url.startswith("/\\"):
        return False

    # Safe relative paths (exclude recursive auth loops)
    if url.startswith("/") and not url.startswith("/api/v1/auth"):
        return True

    # Absolute URL checks
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False

        allowed_hosts = set()
        if request.url.netloc:
            allowed_hosts.add(request.url.netloc.lower())
        frontend_url = getattr(settings, "FRONTEND_URL", "").strip()
        if frontend_url:
            f_parsed = urlparse(frontend_url)
            if f_parsed.netloc:
                allowed_hosts.add(f_parsed.netloc.lower())
        for orig in getattr(settings, "CORS_ORIGINS", []):
            if orig != "*":
                o_parsed = urlparse(orig)
                if o_parsed.netloc:
                    allowed_hosts.add(o_parsed.netloc.lower())

        return parsed.netloc.lower() in allowed_hosts
    except Exception:
        return False


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
    """Verify validity, expiration, and non-revocation of a session token."""
    try:
        if is_token_revoked(token):
            return False
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


def _persist_user_to_db(profile: UserProfile):
    """Safely persist or update authenticated Google user in PostgreSQL."""
    try:
        from storage.db import is_db_configured, get_session_factory
        from storage.db_models import User

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
                user.last_login_at = datetime.now(timezone.utc)
            else:
                user = User(
                    id=profile.sub,
                    email=profile.email,
                    name=profile.name,
                    given_name=profile.given_name,
                    family_name=profile.family_name,
                    picture=profile.picture,
                    role=profile.role,
                    last_login_at=datetime.now(timezone.utc)
                )
                db.add(user)
            db.commit()
    except Exception as e:
        logger.warning(f"Note on user persistence to PostgreSQL: {e}")


async def resolve_user_from_token(token: str) -> Optional[UserProfile]:
    """
    Resolve a UserProfile from a token by checking:
    1. Active in-memory session cache (if not revoked)
    2. Supabase Auth API
    3. Tamper-proof signed local HMAC session tokens
    """
    if not token or not token.strip():
        return None
    token = token.strip()

    # Reject revoked tokens immediately
    if is_token_revoked(token):
        ACTIVE_SESSIONS.pop(token, None)
        return None

    # 1. Check in-memory cache
    if token in ACTIVE_SESSIONS:
        return ACTIVE_SESSIONS[token]

    # 2. Check Supabase token validity
    if is_supabase_configured():
        try:
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
        except Exception as e:
            logger.debug(f"Supabase token lookup note: {e}")

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

    return None


async def get_current_user(authorization: Optional[str] = Header(None)) -> UserProfile:
    """
    FastAPI dependency that enforces verified user authentication.
    Returns the authenticated UserProfile (with stable UID `sub`).
    Raises HTTP 401 if token is missing, invalid, or expired.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please sign in to access your chat sessions."
        )

    token = authorization.replace("Bearer ", "").strip()
    user = await resolve_user_from_token(token)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session token."
        )
    return user


async def get_optional_current_user(authorization: Optional[str] = Header(None)) -> Optional[UserProfile]:
    """
    FastAPI dependency for endpoints supporting both authenticated users and guest access.
    Returns UserProfile if valid Bearer token provided, None if no Authorization header is present,
    or raises HTTP 401 if a token was supplied but is invalid/expired.
    """
    if not authorization or not authorization.startswith("Bearer "):
        return None

    token = authorization.replace("Bearer ", "").strip()
    user = await resolve_user_from_token(token)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session token."
        )
    return user


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
async def configure_auth(
    payload: ConfigureAuthRequest,
    current_user: UserProfile = Depends(get_current_user)
):
    """
    Dynamically update Supabase / Google OAuth credentials, persist them to .env, and update runtime settings.
    Requires administrative privileges.
    """
    if not current_user or (current_user.role or "").lower() not in ("admin", "administrator"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrative privileges required to configure authentication credentials."
        )

    # URL validation for Supabase endpoint
    if payload.supabase_url is not None:
        raw_url = payload.supabase_url.strip()
        if raw_url:
            parsed = urlparse(raw_url)
            if parsed.scheme not in ("https", "http") or not parsed.netloc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid Supabase URL. Must be a valid URL (e.g. https://your-project.supabase.co)."
                )

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
async def google_login(request: Request, return_to: Optional[str] = None):
    """
    Standard OAuth 2.0 authorization redirect to Google Accounts.
    Passes target frontend return URL through the OAuth state parameter.
    Validates redirect destination to prevent open redirect vulnerabilities.
    """
    client_id = settings.GOOGLE_CLIENT_ID.strip() if settings.GOOGLE_CLIENT_ID else ""
    if not client_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GOOGLE_CLIENT_ID is not configured in .env. Please configure your Google Client ID first."
        )

    base = str(request.base_url).rstrip("/")
    redirect_uri = f"{base}/api/v1/auth/google/callback"

    # Resolve safe return URL (strictly validate to prevent open redirect to external domains)
    candidate_target = return_to or request.headers.get("referer") or getattr(settings, "FRONTEND_URL", "").strip() or "/"
    if is_safe_redirect_url(candidate_target, request):
        target_frontend = candidate_target
    else:
        target_frontend = getattr(settings, "FRONTEND_URL", "").strip() or "/"

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "select_account",
        "state": target_frontend
    }
    google_auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"
    return RedirectResponse(url=google_auth_url)


@router.get("/google/callback")
async def google_callback(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None
):
    """
    OAuth 2.0 callback endpoint handling Google's authorization response.
    Exchanges code for tokens, extracts profile, and redirects to frontend with token.
    Strictly validates destination in state to prevent token leakage via open redirect.
    """
    # Determine destination frontend URL safely
    if is_safe_redirect_url(state, request):
        frontend_base = state.rstrip("/")
    else:
        frontend_base = (getattr(settings, "FRONTEND_URL", "").strip() or "/").rstrip("/")

    if not frontend_base:
        frontend_base = "/"
    delim = "&" if "?" in frontend_base else "?"

    if error:
        logger.warning(f"Google OAuth callback returned error: {error}")
        return RedirectResponse(url=f"{frontend_base}{delim}auth_error={error}")

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
            return RedirectResponse(url=f"{frontend_base}{delim}auth_error=token_exchange_failed")

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
            return RedirectResponse(url=f"{frontend_base}{delim}auth_error=userinfo_failed")

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

        return RedirectResponse(url=f"{frontend_base}{delim}auth_token={session_token}")

    except Exception as e:
        logger.error(f"Exception during Google OAuth callback: {e}")
        return RedirectResponse(url=f"{frontend_base}{delim}auth_error=internal_error")


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


@router.get("/me", response_model=UserProfile)
async def me_endpoint(current_user: UserProfile = Depends(get_current_user)):
    """
    Retrieve current authenticated user profile from Authorization header.
    Validates token against Supabase Auth API, in-memory cache, or signed session store.
    """
    return current_user


@router.post("/logout")
async def logout(authorization: Optional[str] = Header(None)):
    """
    Log out and invalidate current session in cache, database, and Supabase.
    """
    if authorization and authorization.startswith("Bearer "):
        token = authorization.replace("Bearer ", "").strip()
        ACTIVE_SESSIONS.pop(token, None)
        revoke_token(token)
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
                detail="Invalid email or password."
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

    user_id = None
    user_name = None
    user_picture = None
    user_role = None
    authenticated = False

    if is_db_configured():
        factory = get_session_factory()
        if factory:
            try:
                with factory() as db:
                    user_match = db.query(User).filter(User.email == email).first()
                    if user_match and user_match.password_hash:
                        if verify_password(password, user_match.password_hash):
                            authenticated = True
                            user_id = user_match.id
                            user_name = user_match.name
                            user_picture = user_match.picture
                            user_role = user_match.role or "Clinical Perfusionist"
                            user_match.last_login_at = datetime.now(timezone.utc)
                            db.commit()
                    else:
                        # Dummy password verification to equalize timing and prevent user enumeration
                        if _password_hasher:
                            try:
                                _password_hasher.verify(DUMMY_ARGON2_HASH, password)
                            except Exception:
                                pass
            except Exception as e:
                logger.warning(f"Error querying user table in login: {e}")
    else:
        if _password_hasher:
            try:
                _password_hasher.verify(DUMMY_ARGON2_HASH, password)
            except Exception:
                pass

    if not authenticated:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password."
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
                        last_login_at=datetime.now(timezone.utc)
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



