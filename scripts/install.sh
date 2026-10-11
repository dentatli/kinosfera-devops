#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
[[ $(id -u) -eq 0 ]] || { echo 'Run installation as root.' >&2; exit 1; }
if ! command -v docker >/dev/null || ! docker compose version >/dev/null 2>&1; then
    bash scripts/bootstrap-server.sh
fi
timedatectl set-ntp true
for attempt in {1..30}; do
    [[ $(timedatectl show -p NTPSynchronized --value) != yes ]] || break
    sleep 1
done
[[ $(timedatectl show -p NTPSynchronized --value) == yes ]] || {
    echo 'NTP is not synchronized; restore time synchronization before deployment.' >&2
    exit 1
}
bash scripts/deploy.sh
