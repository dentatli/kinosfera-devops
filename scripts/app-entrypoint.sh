#!/bin/sh
set -eu

log_dir=$(printf '%s' "$STUDENT_EMAIL" | sha1sum | cut -c1-10)
mkdir -p "/opt/bongo/logs/$log_dir"
if [ "${1:-run_server}" != run_server ]; then
    exec bingo "$@"
fi

bingo run_server &
app_pid=$!
watchdog_pid=
cleanup() {
    [ -z "$watchdog_pid" ] || kill "$watchdog_pid" 2>/dev/null || true
    kill "$app_pid" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

# Docker healthcheck reports state but does not restart a live hung process.
# Let startup finish, then terminate the container after three failed probes.
(
    sleep 15
    failures=0
    while kill -0 "$app_pid" 2>/dev/null; do
        if ! logrotate --state /opt/bongo/logs/logrotate.state /etc/logrotate.d/bingo; then
            printf '%s\n' 'watchdog: log rotation failed' >&2
        fi
        if curl --silent --fail --max-time 2 "http://127.0.0.1:$BINGO_PORT/ping" >/dev/null; then
            failures=0
        else
            failures=$((failures + 1))
        fi
        if [ "$failures" -ge 3 ]; then
            printf '%s\n' 'watchdog: /ping failed three times; restarting application' >&2
            kill -TERM "$app_pid" 2>/dev/null || true
            sleep 3
            kill -KILL "$app_pid" 2>/dev/null || true
            exit
        fi
        sleep 2
    done
) &
watchdog_pid=$!
set +e
wait "$app_pid"
status=$?
set -e
exit "$status"
