from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import urllib.parse
from dataclasses import dataclass
from typing import Any

from app.core.config import Settings


@dataclass(frozen=True)
class GoogleIdentity:
    email: str
    subject: str
    display_name: str | None = None
    avatar_url: str | None = None
    email_verified: bool = False


class GoogleAuthService:
    AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_URL = "https://oauth2.googleapis.com/token"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def authorization_url(self, *, workspace_id: str) -> str:
        if not self.settings.google_client_id:
            raise RuntimeError("GOOGLE_CLIENT_ID is not configured.")
        state = self._state_token({"workspace_id": workspace_id, "nonce": secrets.token_urlsafe(12)})
        params = {
            "client_id": self.settings.google_client_id,
            "redirect_uri": self.settings.google_redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "prompt": "select_account",
            "access_type": "offline",
        }
        return f"{self.AUTH_URL}?{urllib.parse.urlencode(params)}"

    def verify_state(self, state: str | None) -> dict[str, Any]:
        if not state:
            raise ValueError("Missing OAuth state.")
        return self._verify_signed_payload(state, purpose="oauth-state")

    def exchange_code_for_identity(self, code: str) -> GoogleIdentity:
        if not self.settings.google_client_id or not self.settings.google_client_secret:
            raise RuntimeError("Google OAuth client ID/secret are not configured.")
        try:
            import httpx
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("httpx is required for Google OAuth code exchange.") from exc
        payload = {
            "code": code,
            "client_id": self.settings.google_client_id,
            "client_secret": self.settings.google_client_secret,
            "redirect_uri": self.settings.google_redirect_uri,
            "grant_type": "authorization_code",
        }
        with httpx.Client(timeout=20.0) as client:
            response = client.post(self.TOKEN_URL, data=payload)
            response.raise_for_status()
            data = response.json()
        return self.verify_id_token(str(data.get("id_token") or ""))

    def verify_id_token(self, token: str) -> GoogleIdentity:
        if not token:
            raise ValueError("Missing Google ID token.")
        try:
            from google.oauth2 import id_token as google_id_token
            from google.auth.transport import requests as google_requests

            claims = google_id_token.verify_oauth2_token(token, google_requests.Request(), self.settings.google_client_id)
        except Exception:
            if self.settings.app_env.lower() == "production":
                raise
            claims = self._verify_signed_payload(token, purpose="dev-google-id")
        email = str(claims.get("email") or "").strip().lower()
        subject = str(claims.get("sub") or "").strip()
        if not email or not subject:
            raise ValueError("Google identity token does not include email and subject.")
        if claims.get("email_verified") is False:
            raise ValueError("Google account email is not verified.")
        return GoogleIdentity(
            email=email,
            subject=subject,
            display_name=claims.get("name"),
            avatar_url=claims.get("picture"),
            email_verified=bool(claims.get("email_verified", True)),
        )

    def _state_token(self, payload: dict[str, Any]) -> str:
        return self._sign_payload(payload, purpose="oauth-state")

    def _sign_payload(self, payload: dict[str, Any], *, purpose: str) -> str:
        if not self.settings.auth_secret and self.settings.app_env.lower() == "production":
            raise RuntimeError("AUTH_SECRET is required in production.")
        secret = self.settings.auth_secret or "development-only-auth-secret"
        body = json.dumps({"purpose": purpose, **payload}, separators=(",", ":"), sort_keys=True).encode("utf-8")
        encoded = base64.urlsafe_b64encode(body).decode("ascii").rstrip("=")
        signature = hmac.new(secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).hexdigest()
        return f"{encoded}.{signature}"

    def _verify_signed_payload(self, token: str, *, purpose: str) -> dict[str, Any]:
        if "." not in token:
            raise ValueError("Malformed signed payload.")
        encoded, signature = token.rsplit(".", 1)
        secret = self.settings.auth_secret or "development-only-auth-secret"
        expected = hmac.new(secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise ValueError("Invalid signed payload signature.")
        padded = encoded + ("=" * (-len(encoded) % 4))
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
        if payload.get("purpose") != purpose:
            raise ValueError("Signed payload purpose mismatch.")
        return payload

