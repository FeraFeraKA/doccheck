#!/bin/sh
set -eu
umask 077

: "${DOCCHECK_TUNNEL_TOKEN:?Configure the tunnel credential}"
: "${DOCCHECK_TUNNEL_SERVER_KEY:?Configure the base64-encoded SSH host key}"
case "$DOCCHECK_TUNNEL_TOKEN" in
    *[!0-9a-f]*) exit 2 ;;
esac
test "${#DOCCHECK_TUNNEL_TOKEN}" -eq 64
port=${PORT:-10000}
bind=${DOCCHECK_GATEWAY_BIND:-0.0.0.0}
case "$port" in *[!0-9]*|'') exit 2 ;; esac
case "$bind" in 0.0.0.0|127.0.0.1) ;; *) exit 2 ;; esac

here=$(cd "$(dirname "$0")" && pwd)
state=$(mktemp -d /tmp/doccheck-gateway.XXXXXXXX)
tunnel_pid=
nginx_pid=
cleanup() {
    for pid in "$nginx_pid" "$tunnel_pid"; do
        if [ -n "$pid" ]; then
            kill "$pid" 2>/dev/null || true
            wait "$pid" 2>/dev/null || true
        fi
    done
    rm -f "$state/host-key" "$state/users.json" "$state/nginx.conf" "$state/nginx.pid"
    rmdir "$state/body" "$state/proxy" "$state/fastcgi" "$state/uwsgi" "$state/scgi" "$state" \
        2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 0' INT TERM

printf '%s' "$DOCCHECK_TUNNEL_SERVER_KEY" | base64 -d > "$state/host-key"
printf '{"doccheck:%s":["^R:127[.]0[.]0[.]1:19741$"]}\n' "$DOCCHECK_TUNNEL_TOKEN" \
    > "$state/users.json"
unset DOCCHECK_TUNNEL_SERVER_KEY DOCCHECK_TUNNEL_TOKEN AUTH CHISEL_KEY
sed -e "s|@RUN@|$state|g" -e "s|@PORT@|$port|g" -e "s|@BIND@|$bind|g" \
    "$here/nginx.conf.template" > "$state/nginx.conf"
nginx -t -p "$state" -c "$state/nginx.conf"

chisel server --host 127.0.0.1 --port 19740 --reverse \
    --keyfile "$state/host-key" --authfile "$state/users.json" --keepalive 20s &
tunnel_pid=$!
nginx -p "$state" -c "$state/nginx.conf" -g 'daemon off;' &
nginx_pid=$!

while kill -0 "$tunnel_pid" 2>/dev/null && kill -0 "$nginx_pid" 2>/dev/null; do
    sleep 1
done
exit 1
