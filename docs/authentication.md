# Aiwana Authentication

Aiwana supports local password sessions for development/admin bootstrap and Google OpenID Connect for enterprise onboarding.

Production defaults:

- `REQUIRE_AUTH=true`
- `ENABLE_LOCAL_USER_FALLBACK=false`
- `AUTH_SECRET` must be set
- session cookies are `HttpOnly`
- production cookies use `AUTH_COOKIE_SECURE=true`

Disabled or suspended users are rejected by the central auth dependency before protected routes run.

## Google Flow

1. Admin creates a workspace invitation for an email address.
2. User clicks Continue with Google.
3. Backend validates OAuth state and Google identity.
4. Backend checks an unexpired pending invitation for that exact normalized email and workspace.
5. User is created or linked to Google.
6. Workspace membership is created with the invited role.
7. Invitation is marked accepted.
8. A server-side session is issued and audit logged.

No Google password is stored by Aiwana.

