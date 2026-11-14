#!/usr/bin/env bash
set -euo pipefail
umask 077
repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
state=${DOCCHECK_PILOT_HOME:-"$HOME/doccheck-data/pilot"}
venv=${DOCCHECK_PILOT_VENV:-"$repo/.venv-ml"}
db=doccheck_pilot
api_port=18082
https_port=8443
mkdir -p "$state"/{uploads,logs,client_body,proxy_temp,fastcgi_temp,uwsgi_temp,scgi_temp}
cd "$repo"
export DOCCHECK_CODE_REVISION="${DOCCHECK_CODE_REVISION:-$(git rev-parse HEAD 2>/dev/null || true)}"

case "${1:-start}" in
  start)
    if curl -sS --max-time 1 -o /dev/null "http://127.0.0.1:$api_port/health" 2>/dev/null; then
      printf '%s\n' "Pilot API is already running."
      exit 1
    fi
    test -s frontend/dist/index.html
    if ! psql -d postgres -Atqc "select 1 from pg_database where datname='$db'" | grep -qx 1; then
      printf 'Provision local database first: sudo -u postgres createdb -O %s %s\n' "$(id -un)" "$db" >&2
      exit 1
    fi
    if [[ ! -s "$state/access" ]]; then
      password=$(openssl rand -hex 24)
      printf 'pilot:%s\n' "$password" > "$state/access"
    fi
    if [[ ! -s "$state/htpasswd" ]]; then
      IFS=: read -r user password < "$state/access"
      printf '%s:%s\n' "$user" "$(openssl passwd -6 -stdin <<<"$password")" > "$state/htpasswd"
    fi
    if [[ ! -s "$state/localhost.crt" || ! -s "$state/localhost.key" ]]; then
      openssl req -x509 -newkey rsa:2048 -nodes -days 30 -subj '/CN=localhost' \
        -addext 'subjectAltName=DNS:localhost,IP:127.0.0.1' \
        -keyout "$state/localhost.key" -out "$state/localhost.crt" 2>/dev/null
    fi
    export DATABASE_URL="postgresql+psycopg:///$db"
    export DOCCHECK_UPLOAD_ROOT="$state/uploads"
    export DOCCHECK_PUBLIC_DEMO=0
    export DOCCHECK_GPU_LOCK="${DOCCHECK_GPU_LOCK:-$HOME/doccheck-data/qwen-gpu.lock}"
    export DOCCHECK_QWEN_MODEL_DIR="${DOCCHECK_QWEN_MODEL_DIR:-$HOME/doccheck-data/model}"
    export DOCCHECK_QWEN_ADAPTER_PATH="${DOCCHECK_QWEN_ADAPTER_PATH:-$HOME/doccheck-data/adapter/0000100_adapters.safetensors}"
    "$venv/bin/python" -m alembic -c backend/alembic.ini upgrade head
    # The proxy checks access for the UI, API and all source downloads.
    cat > "$state/nginx.conf" <<EOF
pid $state/nginx.pid;
error_log $state/logs/nginx-error.log warn;
worker_processes 1;
events { worker_connections 64; }
http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;
    client_body_temp_path $state/client_body;
    proxy_temp_path $state/proxy_temp;
    fastcgi_temp_path $state/fastcgi_temp;
    uwsgi_temp_path $state/uwsgi_temp;
    scgi_temp_path $state/scgi_temp;
    server {
        listen 127.0.0.1:$https_port ssl;
        server_name localhost;
        ssl_protocols TLSv1.2 TLSv1.3;
        ssl_certificate $state/localhost.crt;
        ssl_certificate_key $state/localhost.key;
        auth_basic "DocCheck pilot";
        auth_basic_user_file $state/htpasswd;
        access_log $state/logs/access.log combined;
        root $repo/frontend/dist;
        client_max_body_size 252m;
        add_header Cache-Control "no-store" always;
        location ~ ^/(api/|health\$) {
            proxy_pass http://127.0.0.1:$api_port;
            proxy_set_header Host \$host;
            proxy_set_header Authorization "";
            proxy_read_timeout 120s;
            proxy_connect_timeout 5s;
        }
        location / { try_files \$uri \$uri/ /index.html; }
    }
}
EOF
    /usr/sbin/nginx -t -p "$state" -c "$state/nginx.conf"
    nohup "$venv/bin/python" -m uvicorn doccheck_backend.api:app --host 127.0.0.1 \
      --port "$api_port" --no-access-log >> "$state/logs/api.log" 2>&1 </dev/null &
    printf '%s\n' "$!" > "$state/api.pid"
    nohup "$venv/bin/python" -m doccheck_backend.run_worker --v32 \
      >> "$state/logs/worker.log" 2>&1 </dev/null &
    printf '%s\n' "$!" > "$state/worker.pid"
    /usr/sbin/nginx -p "$state" -c "$state/nginx.conf"
    for attempt in {1..30}; do
      if curl -fsS --max-time 1 "http://127.0.0.1:$api_port/health" >/dev/null 2>&1; then
        break
      fi
      if [[ $attempt -eq 30 ]]; then
        printf 'Pilot API did not become ready. See %s/logs/api.log\n' "$state" >&2
        exit 1
      fi
      sleep 1
    done
    printf 'Closed pilot: https://localhost:%s\n' "$https_port"
    ;;
  stop)
    if [[ -f "$state/nginx.pid" ]]; then
      /usr/sbin/nginx -p "$state" -c "$state/nginx.conf" -s quit
    fi
    for service in api worker; do
      if [[ -s "$state/$service.pid" ]]; then
        pid=$(cat "$state/$service.pid")
        if [[ -r "/proc/$pid/cmdline" ]] &&
            tr '\0' ' ' < "/proc/$pid/cmdline" | grep -Fq "doccheck_backend."; then
          kill -TERM "$pid"
        fi
      fi
    done
    ;;
  *) printf 'Usage: %s [start|stop]\n' "$0" >&2; exit 2;;
esac
