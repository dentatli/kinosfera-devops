"""Run acceptance checks on the origin; fault tests require --faults explicitly."""

import argparse
import datetime
import http.client
import json
import socket
import ssl
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('host', help='Origin IPv4 address (not the public SSH tunnel endpoint)')
    parser.add_argument('--domain', default='kinosfera.test')
    parser.add_argument('--ca', type=Path, default=Path('certs/server.crt'))
    parser.add_argument('--output-dir', type=Path, default=Path('reports/acceptance'))
    parser.add_argument('--smoke', action='store_true', help='Functional, TLS and monitoring checks only')
    parser.add_argument('--faults', action='store_true', help='Restart each replica under 60 RPS; run from project root on the origin')
    parser.add_argument('--http3-python', type=Path, help='Python interpreter with aioquic installed')
    parser.add_argument('--extended-reliability', action='store_true', help='300 samples per small list and CRUD, 60 session lists')
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    scripts = Path(__file__).resolve().parent
    checks = []

    def run(name, script, *extra, executable=sys.executable):
        report = args.output_dir / f'{name}.json'
        with report.with_suffix('.log').open('w', encoding='utf-8') as log:
            result = subprocess.run([str(executable), str(scripts / script), *map(str, extra)], stdout=log, stderr=log)
        checks.append({'name': name, 'passed': result.returncode == 0, 'exit_code': result.returncode,
                       'report': 'load-suite.json' if name == 'load' else report.name})
        print(json.dumps(checks[-1]), flush=True)

    base = f'http://{args.host}'
    run('functional', 'verify_api.py', base, '--initial-max-session-id', '5000000', '--output', args.output_dir / 'functional.json')
    transport = {'domain': args.domain, 'checks': []}
    context = ssl.create_default_context(cafile=str(args.ca))
    for secure in (False, True):
        connection = http.client.HTTPConnection(args.host, 443 if secure else 80, timeout=5)
        try:
            connection.connect()
            if secure:
                connection.sock = context.wrap_socket(connection.sock, server_hostname=args.domain)
            connection.request('GET', '/ping', headers={'Host': args.domain})
            response = connection.getresponse()
            body = response.read()
            transport['checks'].append({'scheme': 'https' if secure else 'http', 'status': response.status,
                                        'no_redirect': response.getheader('Location') is None,
                                        'certificate_verified': secure,
                                        'passed': response.status == 200 and body == b'pong\n' and response.getheader('Location') is None})
        except (OSError, http.client.HTTPException) as exc:
            transport['checks'].append({'passed': False, 'error': type(exc).__name__})
        finally:
            connection.close()
    try:
        h2context = ssl.create_default_context(cafile=str(args.ca))
        h2context.set_alpn_protocols(['h2'])
        with socket.create_connection((args.host, 443), timeout=5) as raw:
            with h2context.wrap_socket(raw, server_hostname=args.domain) as tls:
                transport['checks'].append({'protocol': tls.selected_alpn_protocol(), 'passed': tls.selected_alpn_protocol() == 'h2'})
    except OSError as exc:
        transport['checks'].append({'passed': False, 'error': type(exc).__name__})
    transport['passed'] = all(c['passed'] for c in transport['checks'])
    (args.output_dir / 'transport.json').write_text(json.dumps(transport, indent=2) + '\n', encoding='utf-8')
    checks.append({'name': 'transport', 'passed': transport['passed'], 'report': 'transport.json'})

    # Only run these on the origin: Prometheus is intentionally bound to loopback.
    monitoring = {'targets': [], 'passed': False}
    try:
        conn = http.client.HTTPConnection('127.0.0.1', 19090, timeout=5)
        conn.request('GET', '/api/v1/targets')
        response = conn.getresponse()
        body = json.loads(response.read())
        conn.close()
        monitoring['targets'] = [{'job': t['labels'].get('job'), 'health': t['health']} for t in body['data']['activeTargets']]
        monitoring['passed'] = response.status == 200 and {'api', 'haproxy'} <= {t['job'] for t in monitoring['targets']} and all(t['health'] == 'up' for t in monitoring['targets'])
    except (OSError, ValueError, KeyError, http.client.HTTPException) as exc:
        monitoring['error'] = type(exc).__name__
    (args.output_dir / 'monitoring.json').write_text(json.dumps(monitoring, indent=2) + '\n', encoding='utf-8')
    checks.append({'name': 'monitoring', 'passed': monitoring['passed'], 'report': 'monitoring.json'})

    if args.http3_python:
        run('http3', 'verify_http3.py', args.host, '--server-name', args.domain, '--ca', args.ca,
            '--output', args.output_dir / 'http3.json', executable=args.http3_python)
    if not args.smoke:
        run('load', 'verify_load.py', base, '--output-dir', args.output_dir)
        run('cache', 'verify_cache.py', base, '--output', args.output_dir / 'cache.json')
    if args.faults:
        for mode in ('kill', '500'):
            run(f'failover-{mode}', 'failover_test.py', base, '--mode', mode, '--output', args.output_dir / f'failover-{mode}.json')
    if args.extended_reliability:
        run('reliability', 'verify_reliability.py', base, '--initial-max-session-id', '5000000', '--output', args.output_dir / 'reliability.json')
    summary = {'timestamp_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'host': args.host,
               'scope': 'smoke' if args.smoke else 'acceptance', 'http3_checked': bool(args.http3_python),
               'faults_checked': args.faults, 'checks': checks, 'passed': all(c['passed'] for c in checks)}
    (args.output_dir / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary, indent=2))
    raise SystemExit(0 if summary['passed'] else 1)


if __name__ == '__main__':
    main()
