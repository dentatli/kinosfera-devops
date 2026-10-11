"""Inject one application fault at a time under 60 RPS of real uncached traffic."""

import argparse
import http.client
import json
import subprocess
import sys
import time
from pathlib import Path


def compose(*args):
    return subprocess.run(['docker', 'compose', *args], check=True, capture_output=True, text=True).stdout.strip()


def restart_count(service):
    container = compose('ps', '-q', service)
    return int(subprocess.run(['docker', 'inspect', '--format', '{{.RestartCount}}', container],
                              check=True, capture_output=True, text=True).stdout.strip())


def ping(port):
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=1)
    try:
        connection.request('GET', '/ping')
        response = connection.getresponse()
        response.read()
        return response.status == 200
    except (OSError, http.client.HTTPException):
        return False
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('base_url')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--services', default='app1,app2')
    parser.add_argument('--mode', choices=('kill', '500'), default='kill')
    args = parser.parse_args()
    services = args.services.split(',')
    if any(service not in ('app1', 'app2') for service in services):
        parser.error('Only app1 and app2 can be tested')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    phases = []
    for service in services:
        ports = {'app1': 18081, 'app2': 18082}
        if not all(ping(port) for port in ports.values()):
            raise SystemExit('Both applications must be healthy before injecting a fault')
        before = restart_count(service)
        load_file = args.output.with_name(f'load-{service}-{args.mode}.json')
        output_log = load_file.with_suffix('.log')
        with output_log.open('w') as log:
            load = subprocess.Popen([
                sys.executable, str(Path(__file__).with_name('load_test.py')),
                args.base_url.rstrip('/') + '/db_dummy', '--rps', '60', '--duration', '20',
                '--timeout', '5', '--p90-limit-ms', '400', '--max-error-percent', '0',
                '--output', str(load_file),
            ], stdout=log, stderr=log)
            time.sleep(3)
            fault_time = time.monotonic()
            injection = None
            if args.mode == 'kill':
                compose('exec', '-T', service, 'sh', '-c', 'kill -KILL $(pidof bingo)')
            else:
                connection = http.client.HTTPConnection('127.0.0.1', ports[service], timeout=3)
                try:
                    connection.request('POST', '/operation', json.dumps({'operation': 5 << 32}),
                                       {'Content-Type': 'application/json'})
                    response = connection.getresponse()
                    response.read()
                    injection = response.status
                finally:
                    connection.close()
            recovered = None
            while time.monotonic() - fault_time < 55:
                if restart_count(service) > before and ping(ports[service]):
                    recovered = time.monotonic() - fault_time
                    break
                time.sleep(0.5)
            returncode = load.wait(timeout=60)
        load_report = json.loads(load_file.read_text())
        phase = {'service': service, 'fault': args.mode, 'injection_http_status': injection,
                 'recovery_seconds': round(recovered, 3) if recovered is not None else None,
                 'load_report': load_report,
                 'passed': recovered is not None and recovered < 60 and returncode == 0}
        phases.append(phase)
        print(json.dumps({key: value for key, value in phase.items() if key != 'load_report'}), flush=True)
        if not phase['passed']:
            break
    report = {'phases': phases, 'passed': len(phases) == len(services) and all(p['passed'] for p in phases)}
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    raise SystemExit(0 if report['passed'] else 1)


if __name__ == '__main__':
    main()
