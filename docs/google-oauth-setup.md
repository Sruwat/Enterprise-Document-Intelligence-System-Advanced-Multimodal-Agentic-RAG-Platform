# Google OAuth Setup

1. Create a Google Cloud project.
2. Configure the OAuth consent screen.
3. Create an OAuth 2.0 Client ID for a web application.
4. Add the authorized JavaScript origin, for example `https://aiwana.example.com`.
5. Add the backend redirect URI, for example `https://api.aiwana.example.com/auth/google/callback`.
6. Set these backend environment variables:

```env
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=
AUTH_SECRET=
AUTH_COOKIE_SECURE=true
```

Development callback example:

```env
GOOGLE_REDIRECT_URI=http://localhost:8000/auth/google/callback
AUTH_COOKIE_SECURE=false
```

Aiwana is invitation-only: a Google account cannot enter a workspace unless a pending invitation exists for the same email and workspace.

