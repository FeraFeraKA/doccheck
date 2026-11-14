#!/usr/bin/env bash
set -euo pipefail
umask 077

repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
state=${DOCCHECK_RENDER_WORKER_HOME:-"$HOME/doccheck-data/render-uploads"}
venv=${DOCCHECK_PILOT_VENV:-"$repo/.venv-ml"}
chisel=${DOCCHECK_CHISEL_BIN:-"$HOME/doccheck-data/tools/chisel-1.12.0"}
db=doccheck_render_uploads
cd "$repo"
export PYTHONPATH="$repo/backend/src:$repo/backend/ml_module/src:$repo${PYTHONPATH:+:$PYTHONPATH}"

case "${1:-}" in
    local)
        mkdir -p "$state/uploads"
        exec 9>"$state/local.lock"
        if ! flock -n 9; then
            printf '%s\n' 'The local Render worker is already running.' >&2
            exit 1
        fi
        if ! psql -d postgres -Atqc "select 1 from pg_database where datname='$db'" | grep -qx 1; then
            printf 'Provision the local database first: sudo -u postgres createdb -O %s %s\n' \
                "$(id -un)" "$db" >&2
            exit 1
        fi
        export DATABASE_URL="postgresql+psycopg:///$db"
        export DOCCHECK_UPLOAD_ROOT="$state/uploads"
        export DOCCHECK_PUBLIC_DEMO=0 DOCCHECK_WEB_SESSIONS=1 DOCCHECK_TRIAL_MODE=0
        export DOCCHECK_GPU_LOCK="${DOCCHECK_GPU_LOCK:-$HOME/doccheck-data/qwen-gpu.lock}"
        export DOCCHECK_QWEN_MODEL_DIR="${DOCCHECK_QWEN_MODEL_DIR:-$HOME/doccheck-data/model}"
        export DOCCHECK_QWEN_ADAPTER_PATH="${DOCCHECK_QWEN_ADAPTER_PATH:-$HOME/doccheck-data/adapter/0000100_adapters.safetensors}"
        export DOCCHECK_CODE_REVISION="$(git rev-parse HEAD)"
        "$venv/bin/python" -m alembic -c backend/alembic.ini upgrade head
        api_pid=
        worker_pid=
        cleanup() {
            for pid in "$api_pid" "$worker_pid"; do
                if [[ -n "$pid" ]]; then
                    kill "$pid" 2>/dev/null || true
                    wait "$pid" 2>/dev/null || true
                fi
            done
        }
        trap cleanup EXIT
        trap 'exit 0' INT TERM
        "$venv/bin/python" -m uvicorn doccheck_backend.api:app --host 127.0.0.1 \
            --port 18083 --no-access-log &
        api_pid=$!
        "$venv/bin/python" -m doccheck_backend.run_worker --v32 &
        worker_pid=$!
        wait -n "$api_pid" "$worker_pid"
        ;;
    credentials)
        install -d -m 0700 "$state"
        if [[ ! -s "$state/tunnel-token" ]]; then
            (set -o noclobber; openssl rand -hex 32 >"$state/tunnel-token")
        fi
        if [[ ! -s "$state/tunnel-server.key" ]]; then
            "$chisel" server --keygen "$state/tunnel-server.key"
        fi
        base64 -w0 "$state/tunnel-server.key" >"$state/tunnel-server-key.base64"
        printf 'Render secrets are ready in %s\n' "$state"
        ;;
    tunnel)
        origin=${2:-}
        fingerprint=${3:-}
        if [[ ! "$origin" =~ ^https://[a-z0-9-]+[.]onrender[.]com$ || -z "$fingerprint" ]]; then
            printf '%s\n' 'Set the Render HTTPS origin and the Chisel SSH fingerprint.' >&2
            exit 2
        fi
        token=$(<"$state/tunnel-token")
        if [[ ! "$token" =~ ^[0-9a-f]{64}$ ]]; then
            printf '%s\n' 'The tunnel credential is missing or invalid.' >&2
            exit 2
        fi
        curl --fail --silent --max-time 5 http://127.0.0.1:18083/health >/dev/null
        AUTH="doccheck:$token" exec "$chisel" client --fingerprint "$fingerprint" \
            --keepalive 20s --max-retry-interval 30s "$origin/_tunnel" \
            R:127.0.0.1:19741:127.0.0.1:18083
        ;;
    *)
        printf 'Usage: %s credentials | local | tunnel HTTPS_ORIGIN SSH_FINGERPRINT\n' "$0" >&2
        exit 2
        ;;
esac
