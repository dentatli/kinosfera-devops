#!/usr/bin/env bash
set -euo pipefail
[[ $(id -u) -eq 0 ]] || { echo 'Run bootstrap as root.' >&2; exit 1; }
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y docker.io docker-compose-v2 python3 curl openssl
systemctl enable --now docker
docker version --format '{{.Server.Version}}'
docker compose version
