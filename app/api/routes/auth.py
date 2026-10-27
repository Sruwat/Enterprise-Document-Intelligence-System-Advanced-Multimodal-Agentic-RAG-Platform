from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Query, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from app.api.auth_context import bearer_token, hash_token
from app.core.dependencies import get_app_settings, get_email_sender, get_metadata_store
from app.core.schemas import AuthResponse, GoogleAuthUrlResponse, GoogleCallbackRequest, UserRecord
from app.services.auth.google import GoogleAuthService
from app.services.auth.invitations import InvitationService

router = APIRouter(prefix="/auth", tags=["auth"])


class AuthRequest(BaseModel):
    email: str
    password: str = Field(min_length=8)
    display_name: str | None = None


class TokenResponse(BaseModel):
    status: str
    token: str | None = None


class EmailRequest(BaseModel):
    email: str


class TokenRequest(BaseModel):
    token: str


class PasswordResetConfirmRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8)


@router.post("/signup", response_model=AuthResponse, status_code=201)
def signup(
    request: AuthRequest,
    response: Response,
    metadata_store=Depends(get_metadata_store),
    settings=Depends(get_app_settings),
) -> AuthResponse:
    _validate_password_strength(request.password)
    existing = metadata_store.get_user_by_email(request.email)
    if existing is not None:
        metadata_store.add_audit_log(
            "auth.signup",
            tenant_id="default-tenant",
            status="failure",
            message="User already exists.",
            metadata={"email": request.email.lower()},
        )
        raise HTTPException(status_code=409, detail="User already exists.")
    user = metadata_store.create_user(
        request.email,
        display_name=request.display_name,
        preferences={**_password_payload(request.password), "created_via": "local_api", "email_verified": False},
    )
    workspace = metadata_store.create_workspace(
        f"{user.display_name or user.email.split('@')[0]}'s Knowledge Space",
        owner_id=user.user_id,
        tenant_id=user.tenant_id,
        private_mode=False,
        external_ai_allowed=True,
    )
    token = _issue_session(user.user_id, metadata_store)
    _set_session_cookie(response, token, settings)
    metadata_store.add_audit_log("auth.signup", user=user, resource_type="user", resource_id=user.user_id, metadata={"workspace_id": workspace.workspace_id})
    return AuthResponse(user=_redact_user(user), session_token=token)


@router.post("/verify-email/request", response_model=TokenResponse)
def request_email_verification(
    request: EmailRequest,
    metadata_store=Depends(get_metadata_store),
    settings=Depends(get_app_settings),
    email_sender=Depends(get_email_sender),
) -> TokenResponse:
    user = metadata_store.get_user_by_email(request.email)
    if user is None:
        return TokenResponse(status="ok")
    token = _issue_action_token(user.user_id, "email_verification", metadata_store, ttl_minutes=24 * 60)
    email_sender.send_auth_action(to_email=user.email, action="email_verification", token=token)
    metadata_store.add_audit_log("auth.verify_email.request", user=user, resource_type="user", resource_id=user.user_id)
    return TokenResponse(status="ok", token=None if _is_production(settings) else token)


@router.post("/verify-email/confirm", response_model=TokenResponse)
def confirm_email_verification(
    request: TokenRequest,
    metadata_store=Depends(get_metadata_store),
) -> TokenResponse:
    user_id = metadata_store.consume_auth_action_token(hash_token(request.token), "email_verification")
    if not user_id:
        raise HTTPException(status_code=400, detail="Invalid or expired verification token.")
    user = metadata_store.update_user_preferences(user_id, {"email_verified": True})
    metadata_store.add_audit_log("auth.verify_email.confirm", user=user, resource_type="user", resource_id=user_id)
    return TokenResponse(status="ok")


@router.post("/password-reset/request", response_model=TokenResponse)
def request_password_reset(
    request: EmailRequest,
    metadata_store=Depends(get_metadata_store),
    settings=Depends(get_app_settings),
    email_sender=Depends(get_email_sender),
) -> TokenResponse:
    user = metadata_store.get_user_by_email(request.email)
    if user is None:
        return TokenResponse(status="ok")
    token = _issue_action_token(user.user_id, "password_reset", metadata_store, ttl_minutes=60)
    email_sender.send_auth_action(to_email=user.email, action="password_reset", token=token)
    metadata_store.add_audit_log("auth.password_reset.request", user=user, resource_type="user", resource_id=user.user_id)
    return TokenResponse(status="ok", token=None if _is_production(settings) else token)


@router.post("/password-reset/confirm", response_model=TokenResponse)
def confirm_password_reset(
    request: PasswordResetConfirmRequest,
    metadata_store=Depends(get_metadata_store),
) -> TokenResponse:
    _validate_password_strength(request.new_password)
    user_id = metadata_store.consume_auth_action_token(hash_token(request.token), "password_reset")
    if not user_id:
        raise HTTPException(status_code=400, detail="Invalid or expired password reset token.")
    user = metadata_store.update_user_preferences(user_id, _password_payload(request.new_password))
    metadata_store.add_audit_log("auth.password_reset.confirm", user=user, resource_type="user", resource_id=user_id)
    return TokenResponse(status="ok")


@router.post("/login", response_model=AuthResponse)
def login(
    request: AuthRequest,
    response: Response,
    metadata_store=Depends(get_metadata_store),
    settings=Depends(get_app_settings),
) -> AuthResponse:
    _validate_password_strength(request.password, allow_legacy=True)
    user = metadata_store.get_user_by_email(request.email)
    if user is None:
        metadata_store.add_audit_log(
            "auth.login",
            tenant_id="default-tenant",
            status="failure",
            message="Unknown email.",
            metadata={"email": request.email.lower()},
        )
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    _ensure_active_user(user)
    if not _verify_password(request.password, user.preferences):
        metadata_store.add_audit_log("auth.login", user=user, status="failure", message="Invalid password.")
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    token = _issue_session(user.user_id, metadata_store, settings)
    _set_session_cookie(response, token, settings)
    metadata_store.add_audit_log("auth.login", user=user, resource_type="user", resource_id=user.user_id)
    return AuthResponse(user=_redact_user(user), session_token=token)


@router.get("/google/login", response_model=GoogleAuthUrlResponse)
def google_login_url(
    workspace_id: str = Query(default="default"),
    settings=Depends(get_app_settings),
    metadata_store=Depends(get_metadata_store),
) -> GoogleAuthUrlResponse:
    workspace = metadata_store.get_workspace(workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Knowledge space not found.")
    try:
        url = GoogleAuthService(settings).authorization_url(workspace_id=workspace_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return GoogleAuthUrlResponse(authorization_url=url)


@router.post("/google/callback", response_model=AuthResponse)
def google_callback(
    request: GoogleCallbackRequest,
    response: Response,
    settings=Depends(get_app_settings),
    metadata_store=Depends(get_metadata_store),
) -> AuthResponse:
    return _complete_google_callback(request, response, settings, metadata_store)


@router.get("/google/callback")
def google_callback_redirect(
    code: str = Query(default=""),
    state: str = Query(...),
    settings=Depends(get_app_settings),
    metadata_store=Depends(get_metadata_store),
) -> RedirectResponse:
    redirect = RedirectResponse(url=_frontend_auth_redirect(settings, success=True), status_code=303)
    try:
        _complete_google_callback(GoogleCallbackRequest(code=code or None, state=state), redirect, settings, metadata_store)
    except HTTPException:
        return RedirectResponse(url=_frontend_auth_redirect(settings, success=False), status_code=303)
    return redirect


def _complete_google_callback(
    request: GoogleCallbackRequest,
    response: Response,
    settings,
    metadata_store,
) -> AuthResponse:
    google = GoogleAuthService(settings)
    try:
        state = google.verify_state(request.state)
        workspace_id = str(state.get("workspace_id") or "default")
        identity = google.exchange_code_for_identity(request.code) if request.code else google.verify_id_token(request.id_token or "")
        user, invitation = InvitationService(metadata_store, ttl_hours=settings.invitation_ttl_hours).accept_for_google_identity(
            workspace_id=workspace_id,
            email=identity.email,
            subject=identity.subject,
            display_name=identity.display_name,
            avatar_url=identity.avatar_url,
        )
    except PermissionError as exc:
        metadata_store.add_audit_log("auth.google", tenant_id="default-tenant", status="failure", message=str(exc))
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:
        metadata_store.add_audit_log("auth.google", tenant_id="default-tenant", status="failure", message="Google authentication failed.")
        raise HTTPException(status_code=401, detail="Google authentication failed.") from exc
    _ensure_active_user(user)
    token = _issue_session(user.user_id, metadata_store, settings)
    _set_session_cookie(response, token, settings)
    metadata_store.add_audit_log("auth.google", user=user, workspace_id=invitation.workspace_id, resource_type="workspace_invitation", resource_id=invitation.invitation_id)
    return AuthResponse(user=_redact_user(user), session_token=token)


def _frontend_auth_redirect(settings, *, success: bool) -> str:
    base_url = settings.cors_origins[0] if getattr(settings, "cors_origins", None) else "http://localhost:3000"
    status = "success" if success else "failed"
    return f"{base_url.rstrip('/')}/settings?auth=google-{status}"


@router.post("/logout")
def logout(
    response: Response,
    authorization: str | None = Header(default=None),
    aiwana_session: str | None = Cookie(default=None),
    metadata_store=Depends(get_metadata_store),
) -> dict:
    token = bearer_token(authorization) or aiwana_session
    if token:
        user_id = metadata_store.get_user_id_for_session(hash_token(token))
        metadata_store.revoke_auth_session(hash_token(token))
        user = metadata_store.get_user(user_id) if user_id else None
        metadata_store.add_audit_log("auth.logout", user=user, resource_type="auth_session", resource_id=hash_token(token)[:12])
    response.delete_cookie("aiwana_session", path="/")
    return {"status": "ok"}


@router.get("/me", response_model=UserRecord)
def me(
    authorization: str | None = Header(default=None),
    aiwana_session: str | None = Cookie(default=None),
    metadata_store=Depends(get_metadata_store),
) -> UserRecord:
    token = bearer_token(authorization) or aiwana_session
    user_id = metadata_store.get_user_id_for_session(hash_token(token)) if token else None
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    user = metadata_store.get_user(user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Session expired.")
    _ensure_active_user(user)
    return _redact_user(user)


def _issue_session(user_id: str, metadata_store, settings=None) -> str:
    token = f"aiwana_{uuid.uuid4().hex}{secrets.token_hex(16)}"
    ttl_hours = int(getattr(settings, "session_ttl_hours", 12) or 12)
    metadata_store.create_auth_session(hash_token(token), user_id, datetime.utcnow() + timedelta(hours=ttl_hours))
    return token


def _issue_action_token(user_id: str, action: str, metadata_store, ttl_minutes: int) -> str:
    token = f"aiwana_{action}_{uuid.uuid4().hex}{secrets.token_hex(16)}"
    metadata_store.create_auth_action_token(hash_token(token), user_id, action, datetime.utcnow() + timedelta(minutes=ttl_minutes))
    return token


def _set_session_cookie(response: Response, token: str, settings) -> None:
    response.set_cookie(
        "aiwana_session",
        token,
        max_age=int(getattr(settings, "session_ttl_hours", 12) or 12) * 60 * 60,
        httponly=True,
        secure=bool(settings.auth_cookie_secure) if settings.app_env.lower() == "production" else False,
        samesite="lax",
        path="/",
    )


def _password_payload(password: str) -> dict[str, str]:
    salt = secrets.token_hex(16)
    return {"password_salt": salt, "password_hash": _hash_password(password, salt)}


def _hash_password(password: str, salt: str) -> str:
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 200_000)
    return digest.hex()


def _verify_password(password: str, preferences: dict) -> bool:
    salt = str(preferences.get("password_salt", ""))
    expected = str(preferences.get("password_hash", ""))
    if salt and expected:
        return hmac.compare_digest(expected, _hash_password(password, salt))
    legacy_expected = expected
    if legacy_expected:
        legacy = hashlib.sha256(f"aiwana-v1:{password}".encode("utf-8")).hexdigest()
        return hmac.compare_digest(legacy_expected, legacy)
    return False


def _redact_user(user: UserRecord) -> UserRecord:
    user.preferences = {key: value for key, value in user.preferences.items() if key not in {"password_hash", "password_salt"}}
    user.updated_at = user.updated_at or datetime.utcnow()
    return user


def _is_production(settings) -> bool:
    return str(settings.app_env).lower() == "production"


def _validate_password_strength(password: str, *, allow_legacy: bool = False) -> None:
    if allow_legacy:
        return
    lowered = password.lower()
    weak_terms = {"password", "12345678", "qwerty", "letmein"}
    if lowered in weak_terms or len(password) < 8:
        raise HTTPException(status_code=422, detail="Password is too weak.")


def _ensure_active_user(user: UserRecord) -> None:
    if user.status != "active":
        raise HTTPException(status_code=403, detail="User account is disabled or suspended.")
