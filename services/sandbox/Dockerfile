# Build context is the repository root. The image holds the service, the runner and the shared
# static policy, and nothing else: no application code, no dependencies, no credentials.
FROM python:3.13-slim
RUN useradd --system --uid 10001 --no-create-home sandbox
COPY services/sandbox/server.py services/sandbox/runner.py apps/api/factory/codepolicy.py /app/
ENV PYTHONDONTWRITEBYTECODE=1 SANDBOX_WIPE_TMP=1
USER 10001:10001
CMD ["python", "-I", "/app/server.py", "/run/sandbox/sandbox.sock"]
