# Managed Pilot Production Deployment Checklist

This document is the concrete deployment checklist for running the platform in a real managed hiring pilot for one backend assessment track.

It is intentionally stricter than the local-development README. The goal is not "app boots"; the goal is "candidate sessions, review operations, and employer-facing evidence stay reliable under real hiring use."

## Scope

- One track only: `track_backend_api_v1`
- Human-reviewed employer output only
- No auth/SSO in scope yet
- Managed pilot operations model, not self-serve SaaS

## Current Code Reality

The codebase now supports:

- production-aware runtime state and review state models
- fail-closed runtime policy when `ENVIRONMENT=production` and filesystem fallback is disabled
- attempt records, runtime jobs, audit events, and report-access records
- reviewer claim, draft, publish, and revoke flows
- cohort-minimum benchmark visibility rules
- immutable submission manifests and object-store-style artifact URIs

The codebase still does not provide:

- a true external background worker queue
- cloud object storage integration
- managed preview ingress outside the app process
- Alembic-based migration workflow
- auth or identity verification

Until those gaps are closed, deploy this as a tightly managed pilot with explicit operational ownership.

## Target Deployment Topology

Run these as separate deployable units:

1. API service
   - FastAPI app from `apps/api`
   - handles candidate, reviewer, employer, and internal API traffic

2. Web service
   - Next.js app from `apps/web`
   - points to the API through `FRONTEND_URL` and client API config

3. Postgres
   - managed Postgres instance
   - backups enabled
   - point-in-time recovery enabled if available

4. Runtime host pool
   - isolated hosts or nodes that can run Docker workloads reliably
   - outbound network blocked for candidate containers by default
   - enough CPU and memory headroom for concurrent sessions

5. Durable artifact storage
   - for the current code, this must be a mounted durable volume, not ephemeral disk
   - back it up independently
   - do not rely on container-local filesystem persistence

6. Reverse proxy / ingress
   - TLS termination
   - route web and API traffic
   - support preview proxy paths under the API host

7. Worker process
   - for the current implementation this can be a second API deployment with dedicated operational ownership
   - long term this should become a real job worker

## Environment Baseline

Set these values explicitly in production.

### Required API settings

- `ENVIRONMENT=production`
- `DATABASE_URL=<managed-postgres-url>`
- `FRONTEND_URL=<public-web-origin>`
- `RUNTIME_BACKEND=auto`
- `RUNTIME_ALLOW_FILESYSTEM_FALLBACK=false`
- `RUNTIME_DOCKER_BIN=docker`
- `RUNTIME_ROOT=<durable-mounted-path>/runtime`
- `OBJECT_STORE_ROOT=<durable-mounted-path>/object-store`
- `RUNTIME_TEMPLATE_ROOT=<app-path>/app/runtime/templates`
- `RUNTIME_SESSION_CPU=2`
- `RUNTIME_SESSION_MEMORY=2g`
- `RUNTIME_SESSION_TIMEOUT_SECONDS=21600`
- `RUNTIME_CLEANUP_ON_STARTUP=true`
- `RUNTIME_CLEANUP_INTERVAL_SECONDS=300`
- `PREVIEW_ENABLED=true`
- `PREVIEW_HOST=127.0.0.1`
- `PREVIEW_PORT_START=41000`
- `PREVIEW_PORT_END=41100`
- `PREVIEW_IDLE_TIMEOUT_SECONDS=900`
- `PREVIEW_STARTUP_TIMEOUT_SECONDS=20`
- `PREVIEW_CLEANUP_INTERVAL_SECONDS=300`
- `REPORT_ACCESS_TTL_HOURS=168`
- `REVIEW_SLA_HOURS=24`

### Required web settings

- point the web app at the public API origin used by the API service
- ensure the web and API public origins match the CORS config in `apps/api/app/main.py`

### Required infrastructure-level settings

- Docker available on every runtime node
- host firewall or platform network policy blocks candidate runtime egress by default
- mounted durable storage sized for runtime workspaces and frozen artifacts
- backup policy for Postgres and artifact storage
- log retention and central collection

## Pre-Deployment Checklist

Complete this before any production deploy.

### Database

- Provision managed Postgres.
- Create a dedicated database for this platform.
- Verify the API can connect using `DATABASE_URL`.
- Confirm startup initializes schema and runs the versioned migrations in `apps/api/app/db/migrations.py`.
- Take and restore a backup once before launch.

### Runtime

- Install Docker on runtime nodes.
- Verify `docker version` succeeds for the API process user.
- Confirm candidate containers can start and stop without manual intervention.
- Confirm candidate container egress is blocked.
- Confirm `RUNTIME_ALLOW_FILESYSTEM_FALLBACK=false` is active in production.
- Confirm a missing Docker daemon causes session provisioning to fail, not fall back to filesystem.

### Durable storage

- Mount persistent storage for `RUNTIME_ROOT`.
- Mount persistent storage for `OBJECT_STORE_ROOT`.
- Confirm those mounts survive process restart and host reboot.
- Confirm storage backups run on a schedule.
- Confirm storage capacity alerts exist before the mount fills.

### Networking

- Put the API behind HTTPS.
- Put the web app behind HTTPS.
- Verify the API can proxy preview traffic without exposing raw container ports publicly.
- Verify preview routes are reachable only through the API proxy path.

### Review operations

- Seed or create the reviewer identities needed for the pilot.
- Verify the review queue loads in `/admin/review-queue`.
- Verify claim, save draft, publish, and revoke flows against a seeded submission.
- Decide who owns daily queue triage and SLA follow-up.

## Deployment Steps

Run these in order.

1. Deploy Postgres.
2. Deploy the API with production env vars and durable mounts.
3. Start the API once and verify:
   - `/health` returns `200`
   - schema migration table exists
   - seeded track and demo data exist only if you intend to keep them in the environment
4. Deploy the web app against the public API origin.
5. Run an end-to-end dry run:
   - create an attempt
   - launch a session
   - confirm session reaches `ready`
   - edit and save a file
   - run tests
   - create a checkpoint
   - submit
   - claim review
   - save draft review
   - publish review
   - open employer report
   - revoke report access
6. Confirm runtime cleanup expires stale sessions and expired report links.

## Go-Live Acceptance Checklist

These must all be true before real candidate traffic.

- Candidate sessions fail closed when Docker isolation is unavailable.
- Session provisioning succeeds on healthy runtime nodes.
- Submission freeze produces immutable `object://` artifact refs and manifest refs.
- Employer report access is created only after reviewer publication.
- Report-access revocation works immediately.
- Preview failures do not block submission.
- Benchmark percentile is hidden when cohort size is below the configured threshold.
- Review queue shows assignment and publication state for every pending submission.
- Runtime cleanup loop is running and has completed at least one successful pass.
- Logs for API, runtime actions, and cleanup are being collected centrally.

## Launch-Day Runbook

Use this checklist on the day candidate traffic starts.

### Before opening candidate traffic

- Verify `/health` from the public API origin.
- Open `/admin/runtime` and confirm:
  - active backend is Docker
  - cleanup loop is running
  - Docker is available
- Open `/admin/review-queue` and confirm the page loads cleanly.
- Launch one internal dry-run candidate session and complete a submission.
- Publish and then revoke a test employer report link.

### During candidate traffic

- Monitor session provisioning latency.
- Monitor number of `runtime_failed` sessions.
- Monitor cleanup status every hour.
- Monitor reviewer queue depth and overdue reviews.
- Monitor storage growth in `RUNTIME_ROOT` and `OBJECT_STORE_ROOT`.

### Stop-launch conditions

Pause candidate traffic immediately if any of these happen:

- Docker unavailable on runtime nodes
- sessions launching on filesystem fallback in production
- multiple candidate submissions fail to freeze artifacts
- reviewer publication creates broken employer links
- preview proxy starts leaking direct host-port assumptions
- durable storage usage is near capacity
- cleanup loop stops running

## Daily Operations Checklist

- Review `/admin/runtime` for cleanup errors and backend state.
- Review `/admin/review-queue` for overdue items.
- Sample one published report and one revoked link.
- Check storage growth and prune expired data through retention jobs.
- Confirm backups completed for Postgres and durable artifact storage.

## Weekly Operations Checklist

- Review candidate completion rate.
- Review runtime failure reasons.
- Review reviewer turnaround time against `REVIEW_SLA_HOURS`.
- Review flagged submissions and second-review volume.
- Review benchmark cohort growth and whether percentiles are being shown appropriately.
- Review artifact retention and storage cost.

## Known Limitations That Still Need Engineering Work

These are not blockers for a tightly managed pilot, but they are real limitations.

### 1. Background jobs are still in-process

Provisioning, preview start/stop, artifact freeze, and cleanup are modeled as runtime jobs, but they still execute inside the API process. Move them to a real worker queue before scaling beyond a controlled pilot.

### 2. Object storage is still local-path backed

The storage abstraction exists, but it still writes to local mounted storage. Replace it with S3-compatible storage before treating artifacts as cloud-native durable records.

### 3. Preview still depends on host-local process management

Preview remains app-managed and port-backed under the hood. Move preview to a dedicated service or ingress model before higher concurrency.

### 4. Migrations are versioned but not yet operator-grade

The code now runs explicit migrations, but there is no Alembic workflow, no migration CI, and no rollback discipline yet.

## Recommended Next Engineering Sequence

If you continue hardening after this deployment setup, do the next four items in this order:

1. Replace in-process runtime jobs with a real worker queue.
2. Replace local object-store backing with cloud object storage.
3. Move preview to a dedicated managed service path.
4. Introduce Alembic migrations and migration CI.
