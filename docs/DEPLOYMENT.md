# Deployment

How Agent Factory leaves a laptop. One provider is written up, Render, because it supplies everything
the application needs without a server to look after: containers built from this repository's
Dockerfiles, PostgreSQL with backups, a key value store, HTTPS, a place to keep secrets, and health
checks. `render.yaml` at the root of the repository describes the whole deployment.

Nothing here has been deployed. No account was created and nothing was bought. What is proven is
that the same images and settings run in production mode on one machine (`scripts/prod-local.sh`),
and that the test suite passes on PostgreSQL. What only a real deployment can prove is listed at
the end.

## What runs

| Service | What it is | Plan in `render.yaml` |
|---|---|---|
| `agent-factory-api` | FastAPI, from `apps/api/Dockerfile`. Runs `alembic upgrade head` before each deploy. | 0.5 CPU, 512 MB |
| `agent-factory-worker` | The build and job worker, same image. Also checks connected mailboxes. | 0.5 CPU, 512 MB |
| `agent-factory-web` | Next.js, from `apps/web/Dockerfile`. | 0.5 CPU, 512 MB |
| `agent-factory-db` | PostgreSQL 17. | 0.1 CPU, 256 MB |
| `agent-factory-limits` | Key value store for request limits, reachable only from the other services. | 256 MB |

Not deployed: the sandbox that runs builder-written tool code. It needs a Unix socket shared between
two containers, one of them with no network, and Render has no way to give that. Without
`SANDBOX_SOCKET` the application refuses such tools; it never runs them in its own process. Agents
that read documents, which is everything in the two demos, do not use it. Hosting the sandbox needs
a machine you control (the Compose file runs it).

## Cost

About **$37 a month** before usage: three services at $7, PostgreSQL at $6 plus $0.30 a GB of
storage, and the key value store at $10. These figures are from Render's own articles and plan
pages as read in October 2026 (https://render.com/pricing, https://render.com/docs/compute-plans);
check the pricing page before relying on them. Model spend is separate and goes to the model
provider. 512 MB is tight for a worker rendering scanned PDFs; the next size up is $25.

## Settings a hosted instance must have

`ENVIRONMENT=production` refuses to start without all of these, and turns the demo sign-in off:

| Setting | Why |
|---|---|
| `JWT_SECRET` | 40 characters or more, not the development one. Render generates it for the API; the worker needs the same value. |
| `ENCRYPTION_KEY` | Encrypts stored credentials (mailbox passwords, connector keys). Lose it and they cannot be read back. |
| `DATABASE_URL` | PostgreSQL. Render's `postgresql://` form is accepted as it is. |
| `REGISTRATION=invited` | Only `OWNER_EMAILS` and people holding a pending invitation may create an account. A hosted instance runs on your model provider key: with open registration a stranger could open a workspace and spend it. |
| `OWNER_EMAILS` | A JSON list: the address that makes the first account. |
| `CORS_ORIGINS` | A JSON list with the web app's public address. |
| `FORWARDED_ALLOW_IPS=*` | Requests arrive through Render's proxy. Without this every visitor shares one request limit. Set it only behind a proxy you trust. |
| `NEXT_PUBLIC_API_URL` | On the web service: the API's public address. It is built into the pages, so changing it means deploying the web service again. |

## Deploying it: the steps that need you

None of these can be done for you: each needs your account, your card or your secrets.

1. Create a Render account and connect it to the GitHub repository `jcai27/Forge`.
2. Generate an encryption key and keep a copy somewhere safe:
   `python3 -c "import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"`
3. In Render: **New > Blueprint**, choose the repository. It reads `render.yaml` and asks for the
   values marked `sync: false`:
   - `ENCRYPTION_KEY`: the key from step 2, on both the API and the worker.
   - `OPENAI_API_KEY`: your provider key, on both.
   - `OWNER_EMAILS`: `["you@example.com"]`.
   - `CORS_ORIGINS`: `["https://agent-factory-web.onrender.com"]`, or your own domain.
   - `NEXT_PUBLIC_API_URL`: `https://agent-factory-api.onrender.com`, or your own domain.
   - `JWT_SECRET` on the worker: copy the value Render generated for the API (API service >
     Environment).
4. Wait for the first deploy. The API's pre-deploy step runs the migrations.
5. Open the web address, choose **Create an account**, and register with the owner address. Nobody
   else can.
6. If you use your own domain: add it to both web services in Render (it issues the certificate),
   then update `CORS_ORIGINS` and `NEXT_PUBLIC_API_URL` and redeploy the web service.

Deploys are manual (`autoDeployTrigger: off`): a push to the repository changes nothing until you
deploy it.

## Backups

Render's paid PostgreSQL plans include logical backups and point-in-time recovery, by its pricing
page. Do not rely on a setting you have not tested: after the first deploy, restore a backup into a
scratch database once. A copy you hold yourself:

    pg_dump "$DATABASE_URL" --format=custom --file=agent-factory-$(date +%F).dump

with the external connection address from the database's page in Render. Keep the encryption key
with the backup, separately from it: a backup without the key has every stored credential
unreadable.

## Health

`GET /health` on the API answers `{"status": "ok"}` and is what Render checks. It is not rate
limited. The web service is checked at `/`.

## Proving it on one machine

    bash scripts/prod-local.sh up       # build, start in production mode on ports 8010 and 3010
    bash scripts/prod-local.sh check    # health, closed registration, no demo sign-in, a sign-in, migrations, a backup
    bash scripts/prod-local.sh down     # stop and remove it, with its database

It uses `docker-compose.prod.yml` laid over `docker-compose.yml`, with fresh secrets in
`.env.production.local` (not in git) and the provider key from `.env`. This runs beside the
development app and the test database without touching either. It includes the sandbox, which the
Render deployment does not.

The test suite on PostgreSQL:

    docker compose up -d postgres redis
    cd apps/api && TEST_DATABASE_URL=postgresql+psycopg://factory:local-factory-password@127.0.0.1:55432/factory uv run pytest -q

## What only a real deployment proves

- That `render.yaml` is accepted as written. It follows Render's Blueprint specification
  (https://render.com/docs/blueprint-spec) but has never been submitted.
- That Render passes `NEXT_PUBLIC_API_URL` to the web image's build.
- HTTPS, the proxy headers and the request limits behind Render's proxy.
- That 512 MB is enough for the worker under real documents.
- Backups and a restore.
