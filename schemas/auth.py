"""
Authentication Schemas for Google Sign-In and User Session Management.
"""

from typing import Optional
from pydantic import BaseModel, Field, EmailStr


class GoogleAuthRequest(BaseModel):
    """Payload sent by the frontend after Google Identity Services authentication."""
    credential: str = Field(..., description="Google ID Token (JWT) returned by Google Identity Services")
    client_id: Optional[str] = Field(None, description="Optional client ID verification check")


class UserProfile(BaseModel):
    """User profile data returned upon successful authentication."""
    sub: str = Field(..., description="Unique Google User ID")
    email: str = Field(..., description="User's primary Google email address")
    name: str = Field(..., description="User's full display name")
    given_name: Optional[str] = None
    family_name: Optional[str] = None
    picture: Optional[str] = Field(None, description="URL of user's Google profile avatar")
    role: str = Field(default="Clinical Perfusionist", description="Clinical or educational user role")
    authenticated: bool = True
    token: Optional[str] = Field(None, description="Application session or bearer token")


class AuthConfigResponse(BaseModel):
    """Configuration endpoint for frontend Supabase & Google Auth initialization."""
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_enabled: bool = False
    google_client_id: str = ""
    enabled: bool = False
    mode: str = Field(default="live", description="'live' if Supabase is configured, otherwise 'setup_required'")


class ConfigureAuthRequest(BaseModel):
    """Request payload to update Supabase / Google credentials."""
    supabase_url: Optional[str] = Field(None, description="Supabase project URL")
    supabase_anon_key: Optional[str] = Field(None, description="Supabase publishable/anon API key")
    google_client_id: Optional[str] = Field(None, description="Google OAuth 2.0 Web Client ID")
    google_client_secret: Optional[str] = Field(None, description="Optional Google OAuth 2.0 Web Client Secret")


class EmailLoginRequest(BaseModel):
    """Payload for institutional email/password login."""
    email: str = Field(..., description="Institutional email address")
    password: str = Field(..., description="User password")
    remember_me: bool = True


class RegisterRequest(BaseModel):
    """Payload for registering a new clinician account."""
    name: str = Field(..., min_length=2, max_length=100)
    email: str = Field(..., description="Institutional email address")
    password: str = Field(..., min_length=4)
    role: Optional[str] = Field(default="Clinical Perfusionist")


class PasswordRecoveryRequest(BaseModel):
    """Payload for requesting a password recovery email via Supabase."""
    email: str = Field(..., description="User's institutional email address")


class SupabaseSessionSyncRequest(BaseModel):
    """Sync frontend Supabase session token to backend."""
    access_token: str = Field(..., description="Supabase Auth JWT access token")




