"""
Authentication Router for Google Sign-In and User Session Management.
Supports Google Identity Services (GSI) verification via Google tokeninfo API.
"""

import hashlib
import hmac
import json
import logging
import re
import smtplib
import ssl
from email.message import EmailMessage
from itsdangerous import BadData, URLSafeTimedSerializer
import time
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlencode, urlparse
from fastapi import APIRouter, Depends, HTTPException, Header, Request, Response, status
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool
import httpx
from config import settings
from schemas.auth import (
    AuthConfigResponse,
    GoogleAuthRequest,
    UserProfile,
    ConfigureAuthRequest,
    EmailLoginRequest,
    RegisterRequest, RegistrationPending, GoogleCodeExchange,
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

session_signer = URLSafeTimedSerializer(SESSION_SECRET, salt="session-v2")
registration_signer = URLSafeTimedSerializer(SESSION_SECRET, salt="email-registration-v1")
SESSION_MAX_AGE_SECONDS = 7 * 24 * 3600


# In-memory cache of revoked token hashes (SHA-256)
REVOKED_TOKENS_MEM = set()

# Rate limiting store for login attempts: ip -> list of timestamps
LOGIN_ATTEMPTS = {}

# Rate limiting store for registration attempts: ip -> list of timestamps
REGISTER_ATTEMPTS = {}


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


def check_register_rate_limit(client_ip: str):
    """
    Prevent spam account registration and automated signup attacks (max 5 signups per 15 minutes per IP).
    Persists across server restarts and instances when PostgreSQL is configured.
    """
    now = time.time()
    # 1. Check in DB if configured
    try:
        from storage.db import is_db_configured, get_session_factory
        from storage.db_models import RegisterRateLimit

        if is_db_configured():
            factory = get_session_factory()
            if factory:
                with factory() as db:
                    window_start = datetime.now(timezone.utc) - timedelta(minutes=15)
                    count = db.query(RegisterRateLimit).filter(
                        RegisterRateLimit.ip_address == client_ip,
                        RegisterRateLimit.attempt_time >= window_start
                    ).count()
                    if count >= 5:
                        raise HTTPException(
                            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                            detail="Too many account registration attempts. Please wait 15 minutes before creating another account."
                        )
                    # Record current registration attempt
                    db.add(RegisterRateLimit(ip_address=client_ip))
                    # Opportunistically prune expired records older than 30 minutes
                    old_threshold = datetime.now(timezone.utc) - timedelta(minutes=30)
                    db.query(RegisterRateLimit).filter(RegisterRateLimit.attempt_time < old_threshold).delete()
                    db.commit()
                    return
    except HTTPException:
        raise
    except Exception as e:
        logger.debug(f"DB registration rate limit note: {e}")

    # 2. In-memory fallback
    attempts = [t for t in REGISTER_ATTEMPTS.get(client_ip, []) if (now - t) < 900]
    if len(attempts) >= 5:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many account registration attempts. Please wait 15 minutes before creating another account."
        )
    attempts.append(now)
    REGISTER_ATTEMPTS[client_ip] = attempts


def reset_rate_limits():
    """Reset rate limit caches (useful in test environments)."""
    LOGIN_ATTEMPTS.clear()
    REGISTER_ATTEMPTS.clear()
    try:
        from storage.db import is_db_configured, get_session_factory
        from storage.db_models import LoginRateLimit, RegisterRateLimit
        if is_db_configured():
            factory = get_session_factory()
            if factory:
                with factory() as db:
                    db.query(LoginRateLimit).delete()
                    db.query(RegisterRateLimit).delete()
                    db.commit()
    except Exception:
        pass


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

    if any(ord(ch) < 33 for ch in url) or "\\" in url or url.startswith("//"):
        return False
    parsed = urlparse(url)
    if parsed.fragment or parsed.query:
        return False
    if url.startswith("/"):
        return not parsed.path.startswith("/api/")
    allowed = [str(request.base_url), settings.FRONTEND_URL, *settings.CORS_ORIGINS]
    return parsed.scheme in {"https", "http"} and any(
        (parsed.scheme, parsed.netloc) == (origin.scheme, origin.netloc)
        for origin in map(urlparse, allowed) if origin.netloc
    )


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


def generate_session_token(sub: str, email: str, *, verified: bool = False, name: str = "", role: str = "",
                           picture=None, given_name=None, family_name=None) -> str:
    claims = {"sub": sub, "email": email, "verified": verified, "name": name,
              "picture": picture, "given_name": given_name, "family_name": family_name,
              "role": display_role(role), "nonce": secrets.token_urlsafe(16)}
    return "v2." + session_signer.dumps(claims)


def display_role(role) -> str:
    if not isinstance(role, str) or not role.strip() or role.strip().lower() in {"admin", "administrator"}:
        return "Clinical Perfusionist"
    return role.strip()


def account_role(email, verified, label=None):
    if verified and email.strip().lower() in settings.ADMIN_EMAILS:
        return "admin"
    return display_role(label)


def supabase_profile(user, token):
    if not token or not user.get("id") or not user.get("email") or not user.get("email_confirmed_at"):
        raise HTTPException(401, "Please verify your email and sign in.")
    meta = user.get("user_metadata") or {}
    role = display_role(meta.get("role"))
    if (user.get("app_metadata") or {}).get("role") in ("admin", "administrator"):
        role = "admin"
    return UserProfile(sub=user["id"], email=user["email"], name=meta.get("name") or meta.get("full_name")
                       or user["email"].split("@")[0], picture=meta.get("avatar_url"), role=role, token=token)


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
    if not token or len(token) > 16384 or is_token_revoked(token):
        return None
    if token.startswith("v2."):
        try:
            claims = session_signer.loads(token[3:], max_age=SESSION_MAX_AGE_SECONDS)
        except BadData:
            return None
        email = claims["email"]
        return UserProfile(sub=claims["sub"], email=email, name=claims["name"] or email.split("@")[0],
                           picture=claims.get("picture"), given_name=claims.get("given_name"),
                           family_name=claims.get("family_name"),
                           role=account_role(email, claims["verified"], claims["role"]), token=token)
    if is_supabase_configured() and token.count(".") == 2:
        code, user = await supabase_request("GET", "/user", bearer_token=token)
        if code == 200:
            return supabase_profile(user, token)
    return None


SESSION_COOKIE = "perfusion_session"


def browser_session(request):
    if request.headers.get("X-Perfusion-Session") != "cookie":
        return False
    origin = request.headers.get("origin", "").rstrip("/")
    if origin and request.headers.get("sec-fetch-site") != "same-origin" and origin not in (
        str(request.base_url).rstrip("/"), settings.FRONTEND_URL.rstrip("/")
    ):
        raise HTTPException(403, "Untrusted session origin.")
    return True


def deliver_profile(profile, request, response):
    response.headers["Cache-Control"] = "no-store"
    if browser_session(request):
        response.set_cookie(SESSION_COOKIE, profile.token, httponly=True, secure=request.url.scheme == "https" or request.url.hostname not in {"localhost", "127.0.0.1", "testserver", "::1"},
                            samesite="lax", max_age=SESSION_MAX_AGE_SECONDS, path="/api/")
        return profile.model_copy(update={"token": None})
    return profile


def request_token(request, authorization):
    if authorization:
        if not authorization.startswith("Bearer "):
            raise HTTPException(401, "Invalid authorization header.")
        return authorization[7:].strip()
    return request.cookies.get(SESSION_COOKIE) if browser_session(request) else None


async def get_optional_current_user(request: Request, authorization: Optional[str] = Header(None)) -> Optional[UserProfile]:
    token = request_token(request, authorization)
    if not token:
        return None
    profile = await resolve_user_from_token(token)
    if not profile:
        raise HTTPException(401, "Invalid or expired session.")
    if not authorization:
        return profile.model_copy(update={"token": None})
    return profile


async def get_current_user(request: Request, authorization: Optional[str] = Header(None)) -> UserProfile:
    profile = await get_optional_current_user(request, authorization)
    if not profile:
        raise HTTPException(401, "Authentication required.")
    return profile


async def require_admin(user: UserProfile = Depends(get_current_user)) -> UserProfile:
    if user.role != "admin":
        raise HTTPException(403, "Administrative privileges required.")
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
        google_redirect_uri=settings.GOOGLE_REDIRECT_URI,
        enabled=supa_enabled or bool(client_id),
        mode="live" if supa_enabled else "setup_required"
    )


@router.post("/configure", response_model=AuthConfigResponse)
async def configure_auth(
    payload: ConfigureAuthRequest,
    current_user: UserProfile = Depends(require_admin)
):
    """
    Dynamically update Supabase / Google OAuth credentials, persist them to .env, and update runtime settings.
    Requires administrative privileges.
    """
    if any(any(char in value for char in "\r\n\x00") for value in payload.model_dump(exclude_none=True).values()):
        raise HTTPException(400, "Invalid authentication setting.")
    # URL validation for Supabase endpoint
    if payload.supabase_url is not None:
        raw_url = payload.supabase_url.strip()
        if raw_url:
            parsed = urlparse(raw_url)
            if parsed.scheme != "https" or not parsed.netloc:
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
        google_redirect_uri=settings.GOOGLE_REDIRECT_URI,
        enabled=supa_enabled or bool(client_id),
        mode="live" if supa_enabled else "setup_required"
    )


def google_redirect_uri(request: Request) -> str:
    if settings.GOOGLE_REDIRECT_URI:
        return settings.GOOGLE_REDIRECT_URI
    if settings.FRONTEND_URL:
        return settings.FRONTEND_URL.rstrip("/") + OAUTH_COOKIE_PATH
    return str(request.url_for("google_callback"))


oauth_state_signer = URLSafeTimedSerializer(SESSION_SECRET, salt="google-login-state")
OAUTH_COOKIE = "perfusion_google_state"
OAUTH_COOKIE_PATH = "/api/v1/auth/google/callback"


@router.get("/google/login")
async def google_login(request: Request, challenge: str, return_to: Optional[str] = None):
    if not settings.GOOGLE_CLIENT_ID or not re.fullmatch(r"[A-Za-z0-9_-]{43}", challenge):
        raise HTTPException(400, "Google sign-in requires a configured client and a valid browser challenge.")
    target = return_to or settings.FRONTEND_URL or "/app/"
    if not is_safe_redirect_url(target, request):
        raise HTTPException(400, "Invalid sign-in destination.")
    state = secrets.token_urlsafe(32)
    params = {"client_id": settings.GOOGLE_CLIENT_ID, "redirect_uri": google_redirect_uri(request),
              "response_type": "code", "scope": "openid email profile", "state": state,
              "code_challenge": challenge, "code_challenge_method": "S256"}
    response = RedirectResponse("https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params))
    response.set_cookie(OAUTH_COOKIE, oauth_state_signer.dumps([state, target]), httponly=True,
                        secure=request.url.scheme == "https" or request.url.hostname not in {"localhost", "127.0.0.1", "testserver", "::1"}, samesite="lax", max_age=600, path=OAUTH_COOKIE_PATH)
    return response


@router.get("/google/callback")
async def google_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    try:
        expected, target = oauth_state_signer.loads(request.cookies.get(OAUTH_COOKIE, ""), max_age=600)
    except BadData:
        raise HTTPException(400, "Google sign-in expired. Start again.")
    if not secrets.compare_digest(state.encode(), expected.encode()) or not is_safe_redirect_url(target, request):
        raise HTTPException(400, "Invalid sign-in state.")
    # The browser alone holds the PKCE verifier. Google consumes the code once.
    result = {"auth_error": "sign_in_failed"} if error or not code else {"google_code": code}
    response = RedirectResponse(target + "#" + urlencode(result), headers={"Cache-Control": "no-store",
                                                                          "Referrer-Policy": "no-referrer"})
    response.delete_cookie(OAUTH_COOKIE, path=OAUTH_COOKIE_PATH)
    return response


def google_profile(data: dict) -> UserProfile:
    if str(data.get("email_verified")).lower() != "true" or not data.get("sub") or not data.get("email"):
        raise HTTPException(401, "A verified Google email is required.")
    profile = UserProfile(sub=data["sub"], email=data["email"], name=data.get("name") or data["email"],
                          picture=data.get("picture"), given_name=data.get("given_name"),
                          family_name=data.get("family_name"), role=account_role(data["email"], True))
    profile.token = generate_session_token(profile.sub, profile.email, verified=True, name=profile.name,
                                           picture=profile.picture, given_name=profile.given_name,
                                           family_name=profile.family_name)
    _persist_user_to_db(profile)
    return profile


@router.post("/google/exchange", response_model=UserProfile)
async def google_exchange(payload: GoogleCodeExchange, request: Request, response: Response):
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        raise HTTPException(503, "Google sign-in is unavailable.")
    async with httpx.AsyncClient(timeout=10) as client:
        result = await client.post("https://oauth2.googleapis.com/token", data={
            "client_id": settings.GOOGLE_CLIENT_ID, "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "redirect_uri": google_redirect_uri(request), "code": payload.code,
            "code_verifier": payload.verifier, "grant_type": "authorization_code",
        })
        if result.status_code != 200 or not result.json().get("access_token"):
            raise HTTPException(401, "Google sign-in expired or was invalid.")
        user = await client.get("https://www.googleapis.com/oauth2/v3/userinfo",
                                headers={"Authorization": "Bearer " + result.json()["access_token"]})
        if user.status_code != 200:
            raise HTTPException(401, "Google identity verification failed.")
    return deliver_profile(google_profile(user.json()), request, response)


@router.post("/google", response_model=UserProfile)
async def authenticate_google(payload: GoogleAuthRequest, request: Request, response: Response):
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

    if not settings.GOOGLE_CLIENT_ID:
        raise HTTPException(400, "Google sign-in is unavailable.")
    from google.auth.transport.requests import Request as GoogleRequest
    from google.oauth2.id_token import verify_oauth2_token
    from google.auth.exceptions import GoogleAuthError
    try:
        data = await run_in_threadpool(verify_oauth2_token, credential, GoogleRequest(), settings.GOOGLE_CLIENT_ID)
    except (ValueError, GoogleAuthError):
        raise HTTPException(401, "Google identity verification failed.")
    return deliver_profile(google_profile(data), request, response)


@router.get("/me", response_model=UserProfile)
async def me_endpoint(current_user: UserProfile = Depends(get_current_user)):
    """
    Retrieve current authenticated user profile from Authorization header.
    Validates token against Supabase Auth API, in-memory cache, or signed session store.
    """
    return current_user


@router.post("/logout")
async def logout(request: Request, response: Response, authorization: Optional[str] = Header(None)):
    token = request_token(request, authorization)
    if token and await resolve_user_from_token(token):
        revoke_token(token)
        if is_supabase_configured() and not token.startswith("v2."):
            await supabase_request("POST", "/logout", bearer_token=token)
    if browser_session(request):
        response.delete_cookie(SESSION_COOKIE, path="/api/")
    response.headers["Cache-Control"] = "no-store"
    return {"status": "success"}


@router.post("/session", response_model=UserProfile)
async def sync_supabase_session(payload: SupabaseSessionSyncRequest, request: Request, response: Response):
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

        if is_token_revoked(token):
            raise HTTPException(401, "Invalid session.")
        profile = supabase_profile(resp_data, token)
        _persist_user_to_db(profile)
        return deliver_profile(profile, request, response)

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
async def login_with_email(payload: EmailLoginRequest, request: Request, response: Response):
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
        profile = supabase_profile(user_info, access_token)
        _persist_user_to_db(profile)
        logger.info(f"User authenticated via Supabase: {email} ({profile.name})")
        return deliver_profile(profile, request, response)

    # 2. Local Database Authentication (when Supabase is pending setup)
    from storage.db import is_db_configured, get_session_factory
    from storage.db_models import User

    user_id = None
    user_name = None
    user_picture = None
    user_role = None
    email_verified = False
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
                            email_verified = user_match.email_verified
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

    session_token = generate_session_token(sub, email, verified=email_verified, name=name, role=role, picture=picture)
    profile = UserProfile(
        sub=sub,
        email=email,
        name=name,
        picture=picture,
        role=account_role(email, email_verified, role),
        authenticated=True,
        token=session_token
    )
    _persist_user_to_db(profile)
    logger.info(f"User signed in: {email} ({name})")
    return deliver_profile(profile, request, response)


def send_registration_code(email: str, code: str):
    message = EmailMessage()
    message["From"] = settings.SMTP_FROM
    message["To"] = email
    message["Subject"] = "Verify your PerfusionGPT email"
    message.set_content(f"Enter this code in the registration form within 10 minutes: {code}")
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as smtp:
        smtp.starttls(context=ssl.create_default_context())
        if settings.SMTP_USERNAME:
            smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        smtp.send_message(message)


def registration_proof(payload, code):
    # Bind proof to this mailbox and password without exposing a password hash in the challenge.
    values = [payload.email.strip().lower(), payload.password.strip(), code]
    return hmac.new(SESSION_SECRET.encode(), json.dumps(values).encode(), hashlib.sha256).hexdigest()


@router.post("/register", response_model=UserProfile | RegistrationPending)
async def register_account(payload: RegisterRequest, request: Request, response: Response):
    check_register_rate_limit(request.client.host if request.client else "unknown")
    email = payload.email.strip().lower()
    name = payload.name.strip()
    password = payload.password.strip()
    role = display_role(payload.role)
    if not re.fullmatch(r"[^@\s,;<>]+@[^@\s,;<>]+", email) or len(email) > 254:
        raise HTTPException(400, "A valid email address is required.")
    if len(password) < 8:
        raise HTTPException(400, "Use at least eight characters for your password.")
    pending_message = "Check your email to verify your account."
    if is_supabase_configured():
        code, data = await supabase_request("POST", "/signup", json_data={
            "email": email, "password": password, "data": {"name": name, "role": role}
        })
        if code not in (200, 201):
            raise HTTPException(400, "Registration could not be completed.")
        if not data.get("access_token") or not (data.get("user") or {}).get("email_confirmed_at"):
            return RegistrationPending(message=pending_message)
        profile = supabase_profile(data["user"], data["access_token"])
        _persist_user_to_db(profile)
        return deliver_profile(profile, request, response)

    from storage.db import get_session_factory
    from storage.db_models import User
    from sqlalchemy.exc import IntegrityError
    import uuid
    factory = get_session_factory()
    if not factory or not settings.SMTP_HOST or not settings.SMTP_FROM:
        raise HTTPException(503, "Email registration is unavailable. Contact your administrator.")
    if not payload.challenge:
        code = secrets.token_hex(8)
        challenge = registration_signer.dumps(registration_proof(payload, code))
        try:
            await run_in_threadpool(send_registration_code, email, code)
        except (OSError, smtplib.SMTPException, ValueError):
            raise HTTPException(503, "Verification email could not be delivered.")
        return RegistrationPending(message=pending_message, challenge=challenge)
    try:
        expected = registration_signer.loads(payload.challenge, max_age=600)
    except BadData:
        raise HTTPException(400, "Verification expired. Start registration again.")
    if not secrets.compare_digest(expected, registration_proof(payload, payload.verification_code or "")):
        raise HTTPException(400, "Incorrect verification code.")
    user_id = "usr_" + uuid.uuid4().hex
    with factory() as db:
        db.add(User(id=user_id, email=email, email_verified=True, name=name, role=role,
                    password_hash=hash_password(password), last_login_at=datetime.now(timezone.utc)))
        try:
            db.commit()
        except IntegrityError:
            raise HTTPException(409, "Account already registered. Please sign in.")
    token = generate_session_token(user_id, email, verified=True, name=name, role=role)
    profile = UserProfile(sub=user_id, email=email, name=name, role=account_role(email, True, role), token=token)
    return deliver_profile(profile, request, response)
