# Workspace access

Each authenticated session selects an organization. Every request resolves its current
membership from the database; a JWT does not preserve a removed member's access or an
old role. Administrators manage membership. Editors create/build/invoke agents, while
viewers inspect workspace evidence. High-impact approval and deployment actions retain
administrator requirements and their existing explicit authorization gates.

## Inviting a teammate

Open Settings → Invite a teammate, enter their email and choose a role. Viewer is the
default. The server returns a random single-use invitation code once. Share it privately
with the recipient. The application does not automatically send email. The code is not
retained in local storage, invitation lists, audit events or the database; only its
SHA-256 hash is persisted. Codes have 256 bits of randomness and expire after 72 hours
by default; the API allows 1–168 hours.

The recipient signs in or registers using the invited email, opens Settings, enters the
code under Join an invited workspace and accepts. This grants the selected membership
and switches to that workspace. The recipient keeps any previous memberships and can
switch between authorized workspaces in Settings. Switching reloads the application;
signing out or signing in clears the query cache so another account cannot inherit
cached workspace data.

Invitation acceptance requires both the code and an authenticated account with the
matching normalized email. Expired, revoked, consumed and wrong-recipient codes return
an unavailable response. The inviting administrator must still have administrator access.
Creating a replacement for the same email revokes previous outstanding invitations.
Invitations cannot upgrade an existing membership; role changes use the separate
administrator control. Registration is local password authentication; this application
does not claim that it has independently verified email ownership or sends verification
email. Possession of the privately delivered invitation code is the grant authority.

Administrators can revoke pending invitations, change teammates' roles and remove
membership. Own-administrator demotion and removal are rejected. Administrative mutations
and invitation acceptance serialize on the organization in PostgreSQL and recheck the
administrator after obtaining the lock. Tests prove concurrent invitation claims create
one membership and competing administrator demotions preserve one authorized admin.
SQLite remains the local development database; PostgreSQL is required in production.

Removed members' existing workspace tokens fail on their next request. They can still
sign in to other memberships. Downgraded members immediately use their new permissions.
Queued deployed invocations also recheck current membership before model/tool execution.

## API contracts

All endpoints require authentication. The organization in the session scopes lists and
administrative actions; accepting an invitation is the explicit cross-organization grant.

| Endpoint | Behavior |
| --- | --- |
| `GET /organizations/members?offset=0&limit=20` | Paginated current-organization members with email and role; no password hashes |
| `PATCH /organizations/members/{id}` | Administrator assigns `{role: admin/editor/viewer}` |
| `DELETE /organizations/members/{id}` | Administrator removes membership; returns HTTP 204 |
| `GET /organizations/invitations?offset=0&limit=20` | Administrator lists recipient/role/status/expiry; no codes or hashes |
| `POST /organizations/invitations` | Administrator creates `{email, role, ttl_hours}`; returns the code once |
| `POST /organizations/invitations/{id}/revoke` | Administrator revokes an unconsumed invitation |
| `POST /organization-invitations/accept` | Matching signed-in recipient submits `{token}` and receives the joined-workspace session |
| `POST /auth/switch-organization` | Member submits `{org_id}` and receives a session for that current membership |

Cross-tenant administrative IDs return 404. Collections accept offsets and limits of
1–200. Invitations and membership changes have audit events; invitation acceptance is
recorded in the joined organization's audit history. The published OpenAPI document
includes these requests and pagination parameters. Migration `0007` adds the invitation
table without changing existing membership or business history.
