from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from app.api.auth_context import hash_token
from app.core.schemas import (
    UserRecord,
    WorkspaceInvitationCreateResponse,
    WorkspaceInvitationRecord,
    WorkspaceRecord,
)


class InvitationService:
    VALID_ROLES = {"admin", "analyst", "viewer"}

    def __init__(self, metadata_store, *, ttl_hours: int = 168) -> None:
        self.metadata_store = metadata_store
        self.ttl_hours = ttl_hours

    def create_invitation(
        self,
        *,
        workspace: WorkspaceRecord,
        email: str,
        role: str,
        invited_by: UserRecord,
        expires_at: datetime | None = None,
    ) -> WorkspaceInvitationCreateResponse:
        normalized_role = role.strip().lower()
        if normalized_role not in self.VALID_ROLES:
            raise ValueError("Invitation role must be admin, analyst, or viewer.")
        normalized_email = email.strip().lower()
        if "@" not in normalized_email:
            raise ValueError("Invitation email is invalid.")
        token = f"aiwana_inv_{secrets.token_urlsafe(32)}"
        expiry = expires_at or (datetime.utcnow() + timedelta(hours=self.ttl_hours))
        record = self.metadata_store.create_workspace_invitation(
            workspace_id=workspace.workspace_id,
            tenant_id=workspace.tenant_id,
            email=normalized_email,
            role=normalized_role,
            invited_by=invited_by.user_id,
            token_hash=hash_token(token),
            expires_at=expiry,
        )
        return WorkspaceInvitationCreateResponse(**record.model_dump(), invitation_token=token)

    def accept_for_google_identity(
        self,
        *,
        workspace_id: str,
        email: str,
        subject: str,
        display_name: str | None = None,
        avatar_url: str | None = None,
    ) -> tuple[UserRecord, WorkspaceInvitationRecord]:
        normalized_email = email.strip().lower()
        invitation = self.metadata_store.get_pending_invitation_for_email(workspace_id, normalized_email)
        if invitation is None:
            raise PermissionError("No pending invitation exists for this Google account and workspace.")
        user = self.metadata_store.get_user_by_email(normalized_email)
        if user is None:
            user = self.metadata_store.create_user(
                normalized_email,
                display_name=display_name,
                tenant_id=invitation.tenant_id,
                preferences={
                    "auth_provider": "google",
                    "provider_subject": subject,
                    "avatar_url": avatar_url,
                    "email_verified": True,
                },
            )
        else:
            if user.tenant_id != invitation.tenant_id:
                raise PermissionError("Invited Google account belongs to a different tenant.")
            if user.status != "active":
                raise PermissionError("User is not active.")
            updater = getattr(self.metadata_store, "update_user_auth_profile", None)
            if callable(updater):
                user = updater(
                    user.user_id,
                    auth_provider="google",
                    provider_subject=subject,
                    display_name=display_name,
                    avatar_url=avatar_url,
                    email_verified=True,
                ) or user
        accepted = self.metadata_store.accept_workspace_invitation(invitation.invitation_id, user.user_id)
        if accepted is None:
            raise PermissionError("Invitation is no longer available.")
        return user, accepted

