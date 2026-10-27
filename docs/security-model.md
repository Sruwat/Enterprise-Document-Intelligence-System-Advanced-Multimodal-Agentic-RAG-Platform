# Security Model

Roles:

- owner
- admin
- analyst
- member
- viewer
- auditor

Sensitive backend routes must derive identity from the authenticated session or API key, not from frontend-submitted `user_id`, `tenant_id`, `workspace_id`, or `role`.

Core permissions include:

- `workspace.read`
- `workspace.manage`
- `members.read`
- `members.invite`
- `members.manage`
- `documents.read`
- `documents.upload`
- `documents.delete`
- `chat.query`
- `evidence.read`
- `audit.read`
- `settings.manage`
- `api_keys.read`
- `api_keys.create`
- `api_keys.revoke`

Audit logs must never include passwords, raw API keys, OAuth secrets, LLM provider secrets, or document contents.

