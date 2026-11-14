#!/usr/bin/env bash
set -euo pipefail
umask 077
repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
state=${DOCCHECK_TRIAL_HOME:-"$HOME/doccheck-data/public-trial"}
venv=${DOCCHECK_PILOT_VENV:-"$repo/.venv-ml"}
export DATABASE_URL=postgresql+psycopg:///doccheck_public_trial
export DOCCHECK_UPLOAD_ROOT="$state/public-trial-uploads"
export DOCCHECK_PUBLIC_DEMO=0
export DOCCHECK_TRIAL_MODE=1
export DOCCHECK_GPU_LOCK="${DOCCHECK_GPU_LOCK:-$HOME/doccheck-data/qwen-gpu.lock}"
export DOCCHECK_QWEN_MODEL_DIR="${DOCCHECK_QWEN_MODEL_DIR:-$HOME/doccheck-data/model}"
export DOCCHECK_QWEN_ADAPTER_PATH="${DOCCHECK_QWEN_ADAPTER_PATH:-$HOME/doccheck-data/adapter/0000100_adapters.safetensors}"
export DOCCHECK_TRIAL_PACKAGE="${DOCCHECK_TRIAL_PACKAGE:-$state/package}"

mkdir -p "$state"/{logs,client_body,proxy_temp,fastcgi_temp,uwsgi_temp,scgi_temp}
cd "$repo"
export DOCCHECK_CODE_REVISION="${DOCCHECK_CODE_REVISION:-$(git rev-parse HEAD 2>/dev/null || true)}"
case "${1:-start}" in
  start)
    if [[ -S "$state/trial-api.sock" ]]; then
      printf '%s\n' 'The public trial API is already running.'
      exit 1
    fi
    test -f "$state/frontend/index.html"
    test -f "$DOCCHECK_TRIAL_PACKAGE/inputs.json"
    "$venv/bin/python" -m alembic -c backend/alembic.ini upgrade head
    cat > "$state/nginx.conf" <<EOF
pid $state/nginx.pid;
error_log $state/logs/nginx-error.log warn;
worker_processes 1;
events { worker_connections 64; }
http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;
    access_log off;
    client_body_temp_path $state/client_body;
    proxy_temp_path $state/proxy_temp;
    fastcgi_temp_path $state/fastcgi_temp;
    uwsgi_temp_path $state/uwsgi_temp;
    scgi_temp_path $state/scgi_temp;
    upstream trial_api { server unix:$state/trial-api.sock; }
    limit_req_zone \$binary_remote_addr zone=trial_requests:1m rate=2r/s;
    server {
        listen 127.0.0.1:18743;
        root $state/frontend;
        client_max_body_size 1k;
        add_header Cache-Control "no-store" always;
        add_header X-Content-Type-Options nosniff always;
        location = /api/v0/trial {
            limit_req zone=trial_requests burst=8 nodelay;
            limit_req_status 429;
            proxy_pass http://trial_api;
            proxy_read_timeout 30s;
        }
        location ~ ^/(health\$|api/v0/runs/[A-Fa-f0-9-]+(?:/.*)?\$) {
            limit_except GET { deny all; }
            proxy_pass http://trial_api;
            proxy_read_timeout 30s;
        }
        location /api/ { return 404; }
        location / { try_files \$uri \$uri/ /index.html; }
    }
}
EOF
    /usr/sbin/nginx -t -p "$state" -c "$state/nginx.conf"
    nohup "$venv/bin/python" -m uvicorn doccheck_backend.public_trial:app --uds "$state/trial-api.sock" \
      --no-access-log >> "$state/logs/api.log" 2>&1 </dev/null &
    api_pid=$!
    printf '%s\n' "$api_pid" > "$state/api.pid"
    for attempt in {1..30}; do
      kill -0 "$api_pid"
      if curl -fsS --max-time 1 --unix-socket "$state/trial-api.sock" \
        http://localhost/health | grep -Fq '"public_trial":true'; then
        break
      fi
      if [[ "$attempt" = 30 ]]; then
        printf 'Trial API did not become ready. See %s/logs/api.log\n' "$state" >&2
        exit 1
      fi
      sleep 1
    done
    nohup "$venv/bin/python" -m doccheck_backend.run_worker --v32 \
      >> "$state/logs/worker.log" 2>&1 </dev/null &
    printf '%s\n' "$!" > "$state/worker.pid"
    /usr/sbin/nginx -p "$state" -c "$state/nginx.conf"
    for attempt in {1..30}; do
      if curl -fsS --max-time 1 http://127.0.0.1:18743/health 2>/dev/null | grep -Fq '"public_trial":true'; then
        printf '%s\n' 'Public trial origin is ready at http://127.0.0.1:18743'
        exit 0
      fi
      sleep 1
    done
    printf 'Trial API did not become ready. See %s/logs/api.log\n' "$state" >&2
    exit 1
    ;;
  stop)
    if [[ -s "$state/nginx.pid" ]]; then
      /usr/sbin/nginx -p "$state" -c "$state/nginx.conf" -s quit
    fi
    for service in tunnel api worker; do
      if [[ -s "$state/$service.pid" ]]; then
        pid=$(cat "$state/$service.pid")
        if [[ -r "/proc/$pid/cmdline" ]] &&
            tr '\0' ' ' < "/proc/$pid/cmdline" | grep -Eq 'doccheck_backend\.|cloudflared'; then
          kill -TERM "$pid"
          for attempt in {1..20}; do
            if ! kill -0 "$pid" 2>/dev/null; then break; fi
            if [[ $(ps -o stat= -p "$pid") = Z* ]]; then break; fi
            sleep 0.25
          done
        fi
      fi
    done
    if [[ -S "$state/trial-api.sock" ]] && ! kill -0 "$(cat "$state/api.pid")" 2>/dev/null; then
      rm -- "$state/trial-api.sock"
    fi
    ;;
  *) printf 'Usage: %s [start|stop]\n' "$0" >&2; exit 2;;
esac
