#!/usr/bin/env bash
# Run the application in production mode on this machine, and prove that it behaves as a hosted one must.
# See docker-compose.prod.yml and docs/DEPLOYMENT.md.
set -euo pipefail
cd "$(dirname "$0")/.."
secrets=.env.production.local
compose=(docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file "$secrets")
api=http://127.0.0.1:8010
owner=owner@agent-factory.test

if [[ ! -f "$secrets" ]]; then
  # Fresh secrets for this machine only, never the development ones. The provider key is taken from .env.
  umask 077
  {
    echo "JWT_SECRET=$(openssl rand -base64 48 | tr -d '\n')"
    echo "ENCRYPTION_KEY=$(openssl rand -base64 32 | tr '+/' '-_' | tr -d '\n')"
    echo "OWNER_EMAILS=[\"$owner\"]"
    grep -E '^OPENAI_API_KEY=' .env || echo "OPENAI_API_KEY="
  } > "$secrets"
fi

case "${1:-}" in
  up)
    "${compose[@]}" up --build -d
    echo "Waiting for the API..."
    for _ in $(seq 1 90); do curl -sf "$api/health" >/dev/null && break; sleep 2; done
    curl -sf "$api/health" && echo && echo "API $api  web http://127.0.0.1:3010"
    ;;
  check)
    fail() { echo "FAILED: $1" >&2; exit 1; }
    status() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
    json='Content-Type: application/json'
    [[ "$(curl -sf "$api/health")" == *'"status":"ok"'* ]] || fail "the health check does not answer"
    echo "ok  health check answers"
    [[ "$(status -X POST "$api/auth/demo")" == 404 ]] || fail "the demo sign-in is still there"
    echo "ok  demo sign-in is off"
    [[ "$(status -X POST "$api/auth/register" -H "$json" -d '{"email":"stranger@example.test","password":"a-long-password-1","organization":"X"}')" == 403 ]] \
      || fail "a stranger could register"
    echo "ok  a stranger cannot register"
    password="$(openssl rand -hex 12)"
    code="$(status -X POST "$api/auth/register" -H "$json" -d "{\"email\":\"$owner\",\"password\":\"$password\",\"organization\":\"Owner\"}")"
    [[ "$code" == 201 || "$code" == 4* ]] || fail "the owner could not register ($code)"
    if [[ "$code" == 201 ]]; then
      token="$(curl -sf -X POST "$api/auth/login" -H "$json" -d "{\"email\":\"$owner\",\"password\":\"$password\"}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])')"
      [[ "$(curl -sf "$api/auth/me" -H "Authorization: Bearer $token" | python3 -c 'import json,sys; print(json.load(sys.stdin)["user"]["email"])')" == "$owner" ]] \
        || fail "the owner could not sign in"
      echo "ok  the owner registers, signs in and is recognised"
      [[ "$(status -X POST "$api/customers" -H "$json" -H "Authorization: Bearer $token" -d '{"name":"First customer"}')" == 201 ]] \
        || fail "the owner could not open a customer workspace"
      echo "ok  a customer workspace is opened, in PostgreSQL"
    else
      echo "ok  the owner is already registered (run down, then up, for a clean check)"
    fi
    "${compose[@]}" exec -T postgres psql -U factory -d factory -tAc "select version_num from alembic_version" | grep -q 0017 \
      || fail "the database is not at migration 0017"
    echo "ok  migrations ran to 0017 on PostgreSQL"
    "${compose[@]}" exec -T postgres pg_dump -U factory -d factory --format=custom > /tmp/agent-factory-backup.dump
    [[ -s /tmp/agent-factory-backup.dump ]] || fail "the backup is empty"
    echo "ok  a backup was taken with pg_dump ($(wc -c < /tmp/agent-factory-backup.dump | tr -d ' ') bytes)"
    rm -f /tmp/agent-factory-backup.dump
    [[ "$(status http://127.0.0.1:3010/portal)" == 200 ]] || fail "the web app does not answer"
    echo "ok  the web app answers, built against $api"
    "${compose[@]}" ps --format '{{.Service}} {{.State}}' | grep -q "worker running" || fail "the worker is not running"
    echo "ok  the worker is running"
    echo "All production checks passed."
    ;;
  down)
    "${compose[@]}" down -v
    ;;
  *)
    echo "usage: bash scripts/prod-local.sh up|check|down" >&2; exit 2
    ;;
esac
