#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if ! command -v docker >/dev/null || ! docker compose version >/dev/null 2>&1; then
    echo 'Install Docker Engine and the Compose v2 plugin first.' >&2
    exit 1
fi
mkdir -p config .state
export SERVER_BIND_IP=${SERVER_BIND_IP:-$(ip -4 route get 1.1.1.1 | awk '{for(i=1;i<=NF;i++) if($i=="src") {print $(i+1); exit}}')}
export TLS_DOMAIN=${TLS_DOMAIN:-kinosfera.test}
if [[ ! -f .env ]]; then
    : "${STUDENT_EMAIL:?Set STUDENT_EMAIL before the first deployment}"
    export STUDENT_EMAIL
    umask 077
    python3 - <<'PY'
import secrets
import os
import re
from pathlib import Path
email = os.environ['STUDENT_EMAIL']
if not re.fullmatch(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+', email):
    raise SystemExit('Set a valid STUDENT_EMAIL')
Path('.env').write_text(
    f'STUDENT_EMAIL={email}\n'
    f'POSTGRES_PASSWORD={secrets.token_hex(24)}\nHTTP_PORT=80\n'
    f'SERVER_BIND_IP={os.environ["SERVER_BIND_IP"]}\n'
    f'TLS_DOMAIN={os.environ["TLS_DOMAIN"]}\n'
    f'GRAFANA_PASSWORD={secrets.token_hex(16)}\n', encoding='utf-8'
)
PY
fi
# Upgrade an existing environment without rotating its database credentials.
if ! grep -q '^GRAFANA_PASSWORD=' .env; then
    python3 -c 'import secrets; print("GRAFANA_PASSWORD=" + secrets.token_hex(16))' >> .env
fi
if ! grep -q '^SERVER_BIND_IP=' .env; then
    printf 'SERVER_BIND_IP=%s\n' "$SERVER_BIND_IP" >> .env
fi
if ! grep -q '^TLS_DOMAIN=' .env; then
    printf 'TLS_DOMAIN=%s\n' "$TLS_DOMAIN" >> .env
fi
set -a
source .env
set +a
if [[ "$POSTGRES_PASSWORD" == generated-by-deploy-script || "$GRAFANA_PASSWORD" == generated-by-deploy-script ]]; then
    echo 'Remove the password placeholders from .env or replace them with random passwords before deployment.' >&2
    exit 1
fi
python3 - <<'PY'
import os
from pathlib import Path
email = os.environ['STUDENT_EMAIL']
password = os.environ['POSTGRES_PASSWORD']
if not email or '@' not in email or '\n' in email:
    raise SystemExit('Set a valid STUDENT_EMAIL in .env')
h = 2166136261
for b in email.encode():
    h = ((h ^ b) * 16777619) & 0xffffffff
port = (h >> 17) + 1024
Path('.state/port').write_text(str(port), encoding='utf-8')
# Quote values using JSON syntax, which is also valid YAML.
import json
config = (
    f'student_email: {json.dumps(email)}\npostgres_cluster:\n'
    '  hosts:\n  - address: postgres\n    port: 5432\n  user: bingo\n'
    f'  password: {json.dumps(password)}\n  db_name: bingo\n'
    '  ssl_mode: disable\n  use_closest_node: false\n'
)
Path('config/bingo.yaml').write_text(config, encoding='utf-8')
source = Path('config/haproxy.cfg').read_text(encoding='utf-8')
import re
source = re.sub(r'(server app[12] app[12]:)\d+', rf'\g<1>{port}', source)
Path('config/haproxy.cfg').write_text(source, encoding='utf-8')
PY
python3 scripts/configure-edge.py
export BINGO_PORT
BINGO_PORT=$(cat .state/port)
# Keep the derived port available for subsequent manual Compose commands.
sed -i '/^BINGO_PORT=/d' .env
printf 'BINGO_PORT=%s\n' "$BINGO_PORT" >> .env
chmod 600 .env
chmod 644 config/bingo.yaml

docker compose config --quiet
docker compose build app1
docker compose up -d --wait postgres
bash scripts/ensure-network-rule.sh
if [[ $(id -u) -eq 0 && "$PWD" == /opt/kinosfera ]]; then
    install -m 644 config/kinosfera-network.service /etc/systemd/system/kinosfera-network.service
    systemctl daemon-reload
    systemctl enable --now kinosfera-network.service
fi

if [[ ! -f .state/prepared ]]; then
    exists=$(docker compose exec -T postgres psql -U bingo -d bingo -Atc \
        "SELECT to_regclass('public.customers') IS NOT NULL")
    if [[ "$exists" == t ]]; then
        echo 'Tables already exist without the completion marker. Inspect the data before retrying initialization.' >&2
        exit 1
    fi
    docker compose --profile tools run --rm prepare
    touch .state/prepared
fi

if [[ ! -f .state/indexes ]]; then
    docker compose exec -T postgres psql -U bingo -d bingo < sql/001-performance-indexes.sql
    touch .state/indexes
fi

docker compose up -d --wait app1 app2
docker compose up -d balancer metrics prometheus grafana edge
docker compose exec -T balancer haproxy -c -f /usr/local/etc/haproxy/haproxy.cfg
docker compose exec -T edge nginx -t
curl --retry 10 --retry-delay 1 --retry-all-errors --max-time 3 \
    --fail --silent --show-error "http://$SERVER_BIND_IP:${HTTP_PORT:-80}/ping"
printf '\nDeployment ready on HTTP port %s; application port %s.\n' "${HTTP_PORT:-80}" "$BINGO_PORT"
