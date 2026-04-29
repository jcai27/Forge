# Verified Work-Sample Platform

Opinionated MVP for a reusable, verified backend engineering work sample. The repo is structured as a narrow pilot product for startup and mid-market engineering teams that want a faster alternative to bespoke take-homes.

The current build is a working local prototype of a standardized backend assessment platform:
- one seeded backend API track
- one bounded session runtime
- one immutable submission artifact flow
- one candidate report
- one employer report
- one internal review and runtime operations surface

## What is implemented

- FastAPI backend with seeded demo data and the core MVP domain model.
- Public API flows for sessions, events, submissions, candidate reports, employer reports, reviews, reviewer assignments, and calibration runs.
- Deterministic provenance, integrity, automated scoring, and track-version-aware benchmark summaries.
- Runtime abstraction with Docker-backed per-session workspaces when Docker is available, plus local filesystem fallback for environments without Docker.
- Next.js frontend shell for candidate, employer, and internal reviewer experiences, styled as a restrained testing-console UI rather than a marketing site.
- Internal runtime operations surface for backend status, cleanup cadence, and recent workspace inspection.
- Product docs for the first backend API track, rubric, reviewer manual, and design-partner pilot workflow.
- Production deployment checklist for the managed pilot in `docs/ops/production-deployment-checklist.md`.

## Monorepo layout

- `apps/api`: FastAPI app and tests.
- `apps/web`: Next.js product shell.
- `docs`: track content and operating docs.

## Seeded demo identifiers

- Candidate user: `candidate_demo`
- Employer reviewer: `employer_manager_demo`
- Internal reviewer/admin: `admin_reviewer_demo`
- Organization: `org_design_partner_demo`
- Track version: `track_backend_api_v1`
- Candidate report: generated after submission
- Employer report token: generated after submission

## Local development

### API

```bash
cd apps/api
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
uvicorn app.main:app --reload
```

Default local API URL: `http://127.0.0.1:8000`

In local development, the runtime job worker is embedded in the API by default, so launching a candidate workspace does not require a second process.

To run the runtime job worker as a dedicated process instead of embedding it in the API:

```bash
cd apps/api
source .venv/bin/activate
RUNTIME_WORKER_EMBED_IN_API=false python -m app.worker_main
```

### Web

```bash
cd apps/web
npm install
npm run dev
```

Default local web URL: `http://localhost:3000`

### Docker Compose

```bash
docker compose up --build
```

The backend defaults to SQLite for zero-setup local development, but the compose stack uses Postgres and Redis so the service boundaries stay aligned with the target architecture.

## Key surfaces

- `/`: product overview and core API contract
- `/candidate/report/[reportId]`: candidate-facing verified report
- `/employer/report/[shareToken]`: employer-facing portable report
- `/admin/review-queue`: internal reviewer queue
- `/admin/runtime`: runtime health, cleanup loop status, and recent workspace inventory

## Runtime model

- Sessions provision a seeded workspace under `apps/api/.runtime/workspaces/<workspace_id>/repo`.
- Docker is preferred in `RUNTIME_BACKEND=auto`; the platform falls back to the filesystem runtime if Docker is unavailable.
- Docker-backed sessions run with outbound networking disabled and explicit CPU, memory, pid, and tmpfs constraints.
- Submission creation freezes an immutable artifact bundle under `apps/api/.runtime/submissions/<submission_id>/`.
- Startup and periodic cleanup are controlled by `RUNTIME_CLEANUP_ON_STARTUP` and `RUNTIME_CLEANUP_INTERVAL_SECONDS`.

## Product notes

- AI use is allowed and summarized, not banned.
- Reports become portable only after human review.
- Benchmarks are calculated only within the same `track_version_id`.
- Employer-facing telemetry is summarized into review evidence rather than exposing raw keystroke surveillance.
- Benchmarks and percentiles are always scoped to a single `track_version_id`.
- The frontend is intentionally minimal and operational, aiming to feel like standardized testing software rather than a generic hiring marketplace.
