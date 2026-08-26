#!/usr/bin/env bash
# Bring the whole platform up on the latest code.
#
# Why this exists: the backends mount their source and reload themselves, but the three web
# services bake a production build into their image with no mount. A plain `docker compose up`
# therefore serves stale frontend code. This always rebuilds what needs rebuilding.
#
# Builds run one service at a time on purpose. Building the Nuxt apps in parallel exhausts the
# Docker VM's memory and kills the daemon.
#
#   ./scripts/dev.sh          build everything, start, verify
#   ./scripts/dev.sh web      only the three frontends
#   ./scripts/dev.sh api      only the backends (use after changing requirements.txt)
#   ./scripts/dev.sh up       start without building (backends still pick up Python changes)
#   ./scripts/dev.sh check    just report health
#   ./scripts/dev.sh logs     follow logs for a service, e.g. ./scripts/dev.sh logs pulse

set -uo pipefail
cd "$(dirname "$0")/.."

API_SERVICES=(pulse)
WEB_SERVICES=(pulse-web identity-web forge-web)
MODE="${1:-all}"

say()  { printf "\n\033[1m%s\033[0m\n" "$*"; }
fail() { printf "\033[31m%s\033[0m\n" "$*"; }
ok()   { printf "\033[32m%s\033[0m\n" "$*"; }

wait_for_daemon() {
  docker info >/dev/null 2>&1 && return 0
  say "Docker is not running. Starting it."
  open -a Docker 2>/dev/null
  for _ in $(seq 1 60); do
    docker info >/dev/null 2>&1 && { ok "Docker is up."; return 0; }
    sleep 5
  done
  fail "Docker did not start. Open Docker Desktop and try again."
  return 1
}

check_space() {
  local reclaimable
  reclaimable=$(docker system df --format '{{.Reclaimable}}' 2>/dev/null | head -1)
  [ -n "${reclaimable:-}" ] && printf "Reclaimable image space: %s (run 'docker builder prune -f' if builds start failing)\n" "$reclaimable"
}

build_one() {
  say "Building $1"
  if ! docker compose build "$1"; then
    fail "Build failed for $1."
    docker info >/dev/null 2>&1 || fail "The Docker daemon died, most likely out of memory. Raise it in Docker Desktop under Resources, then rerun."
    exit 1
  fi
}

# `docker compose up` can report "dependency failed to start: container ... exited (0)" when
# postgres or redis are still finishing a restart, usually after the Docker daemon was restarted.
# Nothing is wrong; they just need a moment. Retry once before treating it as a real failure.
start_stack() {
  docker compose up -d && return 0
  say "Compose reported a dependency was not ready. Waiting for postgres and redis, then retrying."
  docker compose up -d postgres redis >/dev/null 2>&1
  for _ in $(seq 1 24); do
    local pg rd
    pg=$(docker inspect --format='{{.State.Health.Status}}' cc-platforms-postgres-1 2>/dev/null)
    rd=$(docker inspect --format='{{.State.Health.Status}}' cc-platforms-redis-1 2>/dev/null)
    [ "$pg" = "healthy" ] && [ "$rd" = "healthy" ] && break
    sleep 5
  done
  docker compose up -d
}

health() {
  say "Health"
  local bad=0 code
  for pair in "identity 8001" "pulse 8002" "forge 8003"; do
    set -- $pair
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 20 "http://localhost:$2/health")
    if [ "$code" = "200" ]; then ok "  $1 api    :$2  ok"
    else fail "  $1 api    :$2  $code"; bad=1; fi
  done
  for pair in "forge 3000" "pulse 3001" "identity 3002"; do
    set -- $pair
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 30 "http://localhost:$2/")
    if [ "$code" = "200" ]; then ok "  $1 web    :$2  ok"
    else fail "  $1 web    :$2  $code"; bad=1; fi
  done
  if [ "$bad" = "0" ]; then
    say "Ready. Sign in at http://localhost:3002"
  else
    say "Something is not answering. Check its logs:"
    printf "  ./scripts/dev.sh logs pulse\n"
    docker compose ps
    return 1
  fi
}

case "$MODE" in
  check) wait_for_daemon && health ;;
  logs)  docker compose logs -f "${2:-pulse}" ;;
  up)    wait_for_daemon && start_stack && sleep 6 && health ;;
  web)   wait_for_daemon || exit 1; check_space
         for s in "${WEB_SERVICES[@]}"; do build_one "$s"; done
         start_stack && sleep 6 && health ;;
  api)   wait_for_daemon || exit 1; check_space
         for s in "${API_SERVICES[@]}"; do build_one "$s"; done
         start_stack && sleep 6 && health ;;
  all)   wait_for_daemon || exit 1; check_space
         for s in "${API_SERVICES[@]}" "${WEB_SERVICES[@]}"; do build_one "$s"; done
         start_stack && sleep 8 && health ;;
  *)     fail "Unknown option '$MODE'. Use: all, web, api, up, check, logs"; exit 1 ;;
esac
