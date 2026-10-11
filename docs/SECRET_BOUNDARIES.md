# Credential filtering boundaries

Server-managed credentials remain encrypted. Model payloads, connector responses,
execution inputs/outputs, traces, rubric payloads, optimization evidence and browser
serialization filter known credential values, including occurrences in ordinary string
fields and dictionary keys. Filtering includes literal values, JSON escapes, URL and
base64 encodings, passwords within encrypted credential JSON/DSNs, and Basic-auth
username/password combinations. Global API/signing/encryption keys are also filtered.
The filter does not mutate adapter-owned data.

Tenant credential lookup includes current connection credentials, trigger secrets and
retired ciphertext. It never reads another tenant's credential rows. The service passes
the lookup only to its server-side filter; decrypted values never become model tools,
arguments, schemas or browser fields. Adapter authentication uses the active encrypted
connection field, independently of filtering.

Revocation locks the owned connection, archives its ciphertext in the internal
`secret_redaction_entries` table, clears the active dispatch credential and marks the
connection revoked. Historical data remains filtered. The internal table has no API
or connector interface and cannot authorize dispatch. Repeated revocation is idempotent.
Migration 0006 adds this table. Downgrading removes its historical filtering evidence;
retain encrypted backups when managing schema/key changes.

Tests use fictional credentials and explicit local SDK/adapter fixtures. They inspect
actual SDK model inputs, tool results, final outputs, persisted events, serialized rows,
authorized dispatch receipts, tenant isolation and historical filtering after revocation.
No live provider or external production write is part of this evidence.

This filter handles known values and conventional credential markers, not every possible
encoding or unknown private datum. Resource-specific field minimization, PII policy,
transport/DNS hardening and key/retention governance remain separate unfinished work.
Credentials are not an appropriate business input: collisions with required identifiers
or schema literals may cause validation to fail safely after filtering.

## Scanned pages

With `DOCUMENT_READING` on, a scanned page or photo is sent to the model provider as an image
(docs/INTAKE.md). Known-value filtering works on text and cannot be applied to a picture, so a
credential printed on such a page reaches the provider. The transcription that comes back is
filtered before it is returned to the browser and again when it is stored in a case. Do not turn
reading on for documents that may show credentials.
