# Integration setup

Administrators configure connections in the integration workspace. Credentials go in
`secret`, which is encrypted at rest and never returned by REST APIs. Configuration
is restricted to non-secret metadata. Connections with missing credentials remain in
`setup_required`; testing discovers approved tools and marks successful connections
connected. Revocation clears active dispatch credentials and blocks existing versions.
Retired ciphertext is kept only for historical filtering; see SECRET_BOUNDARIES.md.

- Fixture: built-in fictional ERP. Read and approval-gated write permissions are separate.
- REST: `base_url`, `allowed_hosts`, `health_path`, and `operations` containing `name`,
  `description`, static relative `path`, `method`, `input_schema`, `output_schema`.
  Store bearer token as secret. Private/loopback/metadata hosts are rejected; redirects
  are disabled. GET/HEAD requests may retry HTTP 429 twice; write methods dispatch once.
  Discarded responses close before a bounded retry delay. Responses stream with separate
  2 MB wire/decoded limits, including capped gzip/deflate decompression. Oversized length
  headers reject before a body read; oversized streams stop early. Unsupported, truncated
  or trailing compressed payloads reject. The HTTP request/retry/body phase has a 15-second
  total deadline, including DNS resolution. Each new connection resolves within its
  deadline, checks every address and passes a validated numeric public IP to the socket.
  HTTP Host and verified TLS identity retain the approved hostname. Private, loopback,
  metadata, scoped and IPv6 transition destinations reject before socket dispatch.
  Connections are restricted to the configured origin; environment proxies and redirects
  are disabled. Deployment network egress policy and other connector paths still require
  independent enforcement and audit.
- PostgreSQL: store a DSN as secret, set `schema` and a `tables` allowlist. Use a dedicated
  read-only database role. The adapter enforces read-only transactions, statement timeout,
  identifier quoting and bounded results; it exposes no arbitrary SQL execution.
- Files: create a file connection and upload CSV/XLSX. Limits: 5 MB, 10,000 records.
  Resources start private. Explicitly authorize model visibility per imported source.
- Webhooks: configure an input JSON schema and a signing secret. POST to
  `/webhooks/{connection_id}` with `X-Webhook-Timestamp` (Unix seconds) and
  `X-Webhook-Signature` (hex HMAC-SHA256 of `timestamp + '.' + raw_body`). A five-minute
  replay window and persisted deduplication prevent repeat ingestion. Imported events
  require explicit model visibility authorization.
- Email: use `provider: "mock"` for testable, labeled fictional messages. For a real
  provider configure `imap_host`, `smtp_host` and secret JSON with `username`/`password`.
  IMAP uses TLS, read-only selection and BODY.PEEK; SMTP uses TLS. Sending is a write
  requiring approval. OAuth app registration is not available in this environment;
  this is a working credential-based IMAP/SMTP adapter, not a claimed OAuth connection.
- MCP: configure streamable HTTP `url`, `allowed_hosts`, `allowed_tools`, `read_tools`.
  Store bearer token as secret. Discovery uses the installed SDK MCP client and builds
  typed tool definitions from actual server schemas. Unclassified tools are writes by
  default and require approval. The MCP 2 client uses a compatible native httpx2 transport
  with the same public-IP pinning, origin restriction and verified TLS identity as REST.
  Tests initialize, discover and call a tool through an owned local TLS server, with a
  test-only socket delegate; production never allows that loopback mapping. Wrong-host
  certificates reject before an HTTP request. Each session shares separate 2 MB wire and
  decoded response budgets across initialization, pagination and open streams. Gzip and
  deflate are decoded with an output cap before JSON/SSE parsing; unsupported encodings
  and oversized advertised lengths reject. Completed compressed bodies reject truncation
  and trailing data. Streams
  close on failure. The installed SDK caps individual SSE events at 1 MB; automatic tool
  discovery stops after 10 pages. Initialization/discovery or initialization/tool-call
  share a 15-second operation deadline, including trickling responses and reconnect waits.
  The transport applies the same lifetime deadline to further requests and body reads;
  session cleanup cannot dispatch another HTTP request after that deadline.
  Automatic tool-call retries are disabled. No external server credentials have been
  supplied; email/Postgres transport bounds and deployment egress still need audit.

Versions pin tool contracts and connection configuration fingerprints. Changes require
new immutable candidate configuration and evaluation rather than silently changing a
production version. Reads and writes check tenant, tool, connection and resource scope.
Synthetic evaluations execute fixture tools only. Replay environments can simulate
ordered external reads/writes without network access; explicitly authorized read-only
checks can use approved connections. External writes are always forbidden during live
evaluation. See [EVALUATIONS.md](EVALUATIONS.md) for recordings and minimized imports.

Production tool write requests first stage an approval in execution context. A valid
final agent result publishes it as pending. Invalid final
output, provider failure or timeout exposes no actionable approval, even if an interim
checkpoint commits execution events. Queued/running/failed executions cannot dispatch
an approval; administrators can reject stale requests without a side effect.

Explicit approval records dispatch intent before network I/O. Failed or interrupted
external dispatches remain `reconciliation_required`/`dispatching`; the platform never blindly retries an
ambiguous email or HTTP write. A human must reconcile against provider records before
choosing a new request. Fixture ERP mutations and approval state commit atomically.
Use `POST /approvals/{id}/reconcile` with `outcome: "applied"` or `"not_applied"`
and a documented `receipt` after verifying the provider independently. The Approvals
page exposes this action. A still-dispatching operation must first exceed its timeout
plus 30 seconds; reconciliation is final and never reissues the operation.

Deployment invocation webhooks are separate from imported data webhooks. Create a
webhook trigger in Deployments and POST `{input, idempotency_key}` to
`/deployment-webhooks/{trigger_id}` with the same HMAC timestamp/signature contract.
The signing secret is encrypted and never returned. Schedules use a configured interval
and input; missed slots coalesce after downtime. Both enqueue durable invocations,
recheck authorization, respect deployment limits and retain normal approval gates.


Queued live deployment calls persist per-model reservations before dispatch. Unknown
provider charges remain reserved against lifetime limits after failure/recovery. Model
and tool checkpoints recheck authorization and worker ownership. Successful result and
staged approvals commit with queue settlement; failed/stale executions cannot publish
approvals. Costs are configured estimates from reported tokens, not provider invoices.
Standalone production/preview calls outside this queue still need equivalent accounting.
