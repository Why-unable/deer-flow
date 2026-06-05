#!/usr/bin/env bash
set -euo pipefail

DEER_FLOW_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MMKB_ROOT="${MMKB_ROOT:-$DEER_FLOW_ROOT/../mmkb}"
if [ -d "$MMKB_ROOT" ]; then
  MMKB_ROOT="$(cd "$MMKB_ROOT" && pwd)"
fi
MMKB_ENV_FILE="${MMKB_ENV_FILE:-$MMKB_ROOT/.env}"
DEER_FLOW_ENV_FILE="${DEER_FLOW_ENV_FILE:-$DEER_FLOW_ROOT/.env}"
DEER_FLOW_BASE_URL="${DEER_FLOW_BASE_URL-http://127.0.0.1:2026}"
TOKEN_KEY="DEER_FLOW_INTERNAL_AUTH_TOKEN"
FIX=false

usage() {
  cat <<EOF
Usage: $0 [--fix]

Checks the MMKB-to-DeerFlow internal authentication setup.

Environment overrides:
  MMKB_ENV_FILE       MMKB .env path (default: $MMKB_ENV_FILE)
  MMKB_ROOT           MMKB root (default: $MMKB_ROOT)
  DEER_FLOW_ENV_FILE  DeerFlow .env path (default: $DEER_FLOW_ENV_FILE)
  DEER_FLOW_BASE_URL  Gateway URL; set empty to skip live check

--fix synchronizes a missing token from the other .env, or generates one when
both are missing. Existing mismatched tokens are never overwritten.
EOF
}

log_ok() {
  printf '[OK] %s\n' "$1"
}

log_warn() {
  printf '[WARN] %s\n' "$1" >&2
}

log_error() {
  printf '[ERROR] %s\n' "$1" >&2
}

read_env_token() {
  local file="$1"
  if [ ! -f "$file" ]; then
    printf ''
    return
  fi

  (
    set +u
    unset DEER_FLOW_INTERNAL_AUTH_TOKEN
    set -a
    # shellcheck disable=SC1090
    source "$file"
    set +a
    printf '%s' "${DEER_FLOW_INTERNAL_AUTH_TOKEN:-}"
  )
}

write_env_token() {
  local file="$1"
  local token="$2"
  local temp_file

  mkdir -p "$(dirname "$file")"
  touch "$file"
  temp_file="$(mktemp)"
  awk -v key="$TOKEN_KEY" -v value="$token" '
    BEGIN { replaced = 0 }
    $0 ~ "^[[:space:]]*(export[[:space:]]+)?" key "=" {
      if (!replaced) {
        print key "=" value
        replaced = 1
      }
      next
    }
    { print }
    END {
      if (!replaced) {
        print key "=" value
      }
    }
  ' "$file" >"$temp_file"
  chmod --reference="$file" "$temp_file" 2>/dev/null || true
  mv "$temp_file" "$file"
}

generate_token() {
  if command -v python3 >/dev/null 2>&1; then
    python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
    return
  fi
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -base64 32 | tr '+/' '-_' | tr -d '=\n'
    return
  fi
  log_error "Cannot generate token: python3 and openssl are both unavailable."
  exit 1
}

fingerprint() {
  local token="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    printf '%s' "$token" | sha256sum | awk '{print substr($1, 1, 12)}'
  else
    printf 'unavailable'
  fi
}

for arg in "$@"; do
  case "$arg" in
    --fix)
      FIX=true
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      log_error "Unknown argument: $arg"
      usage
      exit 2
      ;;
  esac
done

mmkb_token="$(read_env_token "$MMKB_ENV_FILE")"
deerflow_token="$(read_env_token "$DEER_FLOW_ENV_FILE")"

if [ "$FIX" = true ]; then
  if [ -z "$mmkb_token" ] && [ -z "$deerflow_token" ]; then
    shared_token="$(generate_token)"
    write_env_token "$MMKB_ENV_FILE" "$shared_token"
    write_env_token "$DEER_FLOW_ENV_FILE" "$shared_token"
    log_ok "Generated one shared token in both .env files."
  elif [ -z "$mmkb_token" ]; then
    write_env_token "$MMKB_ENV_FILE" "$deerflow_token"
    log_ok "Copied the existing DeerFlow token into MMKB .env."
  elif [ -z "$deerflow_token" ]; then
    write_env_token "$DEER_FLOW_ENV_FILE" "$mmkb_token"
    log_ok "Copied the existing MMKB token into DeerFlow .env."
  elif [ "$mmkb_token" != "$deerflow_token" ]; then
    log_error "Both .env files contain different tokens; refusing to overwrite either one."
    log_error "Choose the intended token manually, then rerun this script."
    exit 1
  fi

  mmkb_token="$(read_env_token "$MMKB_ENV_FILE")"
  deerflow_token="$(read_env_token "$DEER_FLOW_ENV_FILE")"
fi

failed=false

if [ -z "$mmkb_token" ]; then
  log_error "MMKB .env is missing $TOKEN_KEY: $MMKB_ENV_FILE"
  failed=true
else
  log_ok "MMKB .env contains $TOKEN_KEY (fingerprint: $(fingerprint "$mmkb_token"))."
fi

if [ -z "$deerflow_token" ]; then
  log_error "DeerFlow .env is missing $TOKEN_KEY: $DEER_FLOW_ENV_FILE"
  failed=true
else
  log_ok "DeerFlow .env contains $TOKEN_KEY (fingerprint: $(fingerprint "$deerflow_token"))."
fi

if [ -n "$mmkb_token" ] && [ -n "$deerflow_token" ]; then
  if [ "$mmkb_token" = "$deerflow_token" ]; then
    log_ok "MMKB and DeerFlow .env tokens match."
  else
    log_error "MMKB and DeerFlow .env tokens do not match."
    failed=true
  fi
fi

if [ -n "$mmkb_token" ]; then
  sourced_token="$(read_env_token "$MMKB_ENV_FILE")"
  if [ "$sourced_token" = "$mmkb_token" ]; then
    log_ok "MMKB .env can be sourced and exports the expected token."
  else
    log_error "MMKB .env did not export the expected token when sourced."
    failed=true
  fi
fi

relevant_process_detected=false
runtime_checked=false
runtime_inspection_incomplete=false
mmkb_runtime_ready=false
running_mmkb_pids="$(
  ps -eo pid=,args= 2>/dev/null \
    | awk '
        /manage.py runserver|gunicorn.*mmkb_demo|uwsgi.*mmkb_demo/ &&
        $0 !~ /awk/ {
          print $1
        }
      ' \
    || true
)"
if [ -n "$running_mmkb_pids" ] && [ -n "$mmkb_token" ]; then
  while IFS= read -r pid; do
    [ -n "$pid" ] || continue
    process_cwd="$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)"
    process_cmdline="$(tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null || true)"
    if [ "$process_cwd" != "$MMKB_ROOT" ] && [[ "$process_cmdline" != *"$MMKB_ROOT"* ]]; then
      continue
    fi
    relevant_process_detected=true
    if [ ! -r "/proc/$pid/environ" ]; then
      log_warn "Cannot inspect environment of running MMKB process PID $pid."
      runtime_inspection_incomplete=true
      continue
    fi
    runtime_checked=true
    runtime_token="$(
      tr '\0' '\n' <"/proc/$pid/environ" \
        | awk -F= -v key="$TOKEN_KEY" '$1 == key {sub(/^[^=]*=/, ""); print; exit}'
    )"
    if [ "$runtime_token" = "$mmkb_token" ]; then
      log_ok "Running MMKB process PID $pid loaded the expected internal token."
      mmkb_runtime_ready=true
    elif [ -z "$runtime_token" ]; then
      log_error "Running MMKB process PID $pid did not load $TOKEN_KEY."
      log_error "Restart MMKB with ./scripts/run_django.sh or source .env before manual startup."
      failed=true
    else
      log_error "Running MMKB process PID $pid loaded a different internal token."
      log_error "Restart MMKB after confirming the intended .env value."
      failed=true
    fi
  done <<<"$running_mmkb_pids"
  if [ "$relevant_process_detected" = false ]; then
    log_warn "No running MMKB process detected for $MMKB_ROOT; start MMKB after this check."
  elif [ "$runtime_checked" = false ] || [ "$runtime_inspection_incomplete" = true ]; then
    log_warn "Running MMKB process detected, but its environment could not be inspected."
  fi
else
  log_warn "No running MMKB process detected for $MMKB_ROOT; start MMKB after this check."
fi

if [ -n "$DEER_FLOW_BASE_URL" ] && [ -n "$mmkb_token" ] && command -v curl >/dev/null 2>&1; then
  health_status="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 5 "$DEER_FLOW_BASE_URL/health" || true)"
  if [ "$health_status" = "200" ]; then
    log_ok "DeerFlow health endpoint is reachable."
    auth_status="$(
      curl -sS -o /dev/null -w '%{http_code}' --max-time 5 \
        -H "X-DeerFlow-Internal-Token: $mmkb_token" \
        "$DEER_FLOW_BASE_URL/api/models" || true
    )"
    if [ "$auth_status" = "200" ]; then
      log_ok "Running DeerFlow Gateway accepts the MMKB internal token."
    else
      log_error "Gateway protected endpoint returned HTTP ${auth_status:-unreachable}."
      log_error "If .env tokens match, restart DeerFlow Gateway so it reloads the token."
      failed=true
    fi
  else
    log_warn "Skipped live authentication check: DeerFlow health returned HTTP ${health_status:-unreachable}."
  fi
fi

if [ "$failed" = true ]; then
  if [ "$FIX" = false ]; then
    printf '\nRun this safe repair for missing-token cases:\n  %s --fix\n' "$0" >&2
  fi
  exit 1
fi

printf '\nInternal authentication configuration passed.\n'

if [ "$mmkb_runtime_ready" = true ] && [ "$runtime_inspection_incomplete" = false ]; then
  printf 'Running MMKB already loaded the expected internal token; no restart is required.\n'
elif [ "$relevant_process_detected" = true ]; then
  cat <<EOF
Restart MMKB so it loads the expected internal token:
  cd "$MMKB_ROOT" && ./scripts/run_django.sh
EOF
else
  cat <<EOF
Start MMKB with:
  cd "$MMKB_ROOT" && ./scripts/run_django.sh

If starting Django manually, source MMKB .env in that same shell first:
  set -a
  source "$MMKB_ENV_FILE"
  set +a
EOF
fi
