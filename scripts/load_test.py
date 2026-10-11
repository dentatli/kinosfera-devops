"""HTTP load at a fixed arrival rate, with queue delay included in latency."""

import argparse
import collections
import concurrent.futures
import datetime
import http.client
import json
import math
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

local = threading.local()


def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(len(ordered) * fraction) - 1)], 3)


def request(args, url, scheduled, number):
    started = time.monotonic()
    connection = getattr(local, 'connection', None)
    if connection is None:
        cls = http.client.HTTPSConnection if url.scheme == 'https' else http.client.HTTPConnection
        if args.proxy:
            proxy = urlsplit(args.proxy)
            connection = cls(proxy.hostname, proxy.port or 8080, timeout=args.timeout)
            connection.set_tunnel(url.hostname, url.port or (443 if url.scheme == 'https' else 80))
        else:
            connection = cls(url.hostname, url.port, timeout=args.timeout)
        local.connection = connection
    path = url.path or '/'
    if url.query:
        path += '?' + url.query
    body = args.data
    if args.operation:
        code = args.operation_codes[number % len(args.operation_codes)]
        operation_id = (code << 32) | ((args.operation_start + number) & 0xffffffff)
        body = json.dumps({'operation': operation_id})
    status = 0
    error = None
    try:
        headers = {'Content-Type': 'application/json'} if body is not None else {}
        connection.request(args.method, path, body=body, headers=headers)
        response = connection.getresponse()
        status = response.status
        # Stream large lists instead of retaining their data in the benchmark process.
        while response.read(65536):
            pass
    except (OSError, http.client.HTTPException) as exc:
        error = type(exc).__name__
        connection.close()
        local.connection = None
    finished = time.monotonic()
    return {
        'status': status,
        'error': error,
        'latency_ms': (finished - scheduled) * 1000,
        'service_ms': (finished - started) * 1000,
        'queue_ms': (started - scheduled) * 1000,
        'start': started,
        'finish': finished,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('url')
    parser.add_argument('--rps', type=float, default=60)
    parser.add_argument('--duration', type=float, default=10)
    parser.add_argument('--workers', type=int, default=128)
    parser.add_argument('--timeout', type=float, default=10)
    parser.add_argument('--proxy', help='HTTP CONNECT proxy URL, e.g. http://127.0.0.1:1080')
    parser.add_argument('--method', default='GET')
    parser.add_argument('--data')
    parser.add_argument('--operation', action='store_true')
    parser.add_argument('--operation-start', type=int, default=0)
    parser.add_argument('--operation-codes', type=lambda value: [int(x) for x in value.split(',')], default=[0, 1, 2, 6, 7, 8, 9],
                        help='Safe operation types in bits 32..35; 3,4,5 inject faults and are rejected here')
    parser.add_argument('--max-error-percent', type=float, default=1)
    parser.add_argument('--p90-limit-ms', type=float)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.rps <= 0 or args.duration <= 0 or args.workers <= 0:
        parser.error('rps, duration and workers must be positive')
    if args.operation:
        args.method = 'POST'
        if not args.operation_codes or any(code not in (0, 1, 2, 6, 7, 8, 9) for code in args.operation_codes):
            parser.error('Use safe operation codes 0,1,2,6,7,8,9; inject faults separately')
    url = urlsplit(args.url)
    if url.scheme not in ('http', 'https') or not url.hostname:
        parser.error('Supply an HTTP(S) URL')
    if args.proxy:
        proxy = urlsplit(args.proxy)
        if proxy.scheme != 'http' or not proxy.hostname or proxy.username or proxy.password:
            parser.error('Supply an HTTP proxy URL without credentials')
    count = math.ceil(args.rps * args.duration)
    futures = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        start = time.monotonic()
        for number in range(count):
            scheduled = start + number / args.rps
            delay = scheduled - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            futures.append(pool.submit(request, args, url, scheduled, number))
        results = [future.result() for future in futures]
    elapsed = time.monotonic() - start
    successes = [r for r in results if 200 <= r['status'] < 300 and r['error'] is None]
    errors = len(results) - len(successes)
    error_percent = errors * 100 / len(results)
    p90 = percentile([r['latency_ms'] for r in successes], 0.9)
    started_in_window = sum(r['start'] < start + args.duration for r in results)
    completed_in_window = sum(r['finish'] < start + args.duration for r in results)
    buckets = collections.defaultdict(lambda: {'requests': 0, 'errors': 0})
    for r in results:
        second = int(r['start'] - start)
        buckets[second]['requests'] += 1
        buckets[second]['errors'] += int(not (200 <= r['status'] < 300) or r['error'] is not None)
    passed = error_percent <= args.max_error_percent and started_in_window >= count * 0.99
    if args.p90_limit_ms is not None:
        passed = passed and p90 is not None and p90 < args.p90_limit_ms
    report = {
        'timestamp_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'url': args.url, 'method': args.method,
        'proxy': args.proxy,
        'target_rps': args.rps, 'arrival_window_seconds': args.duration,
        'operation_codes': args.operation_codes if args.operation else None,
        'elapsed_seconds': round(elapsed, 3),
        'requests': len(results), 'successes': len(successes), 'errors': errors,
        'error_percent': round(error_percent, 4),
        'status_counts': dict(collections.Counter(str(r['status']) for r in results)),
        'exception_counts': dict(collections.Counter(r['error'] for r in results if r['error'])),
        'started_rps': round(started_in_window / args.duration, 3),
        'completed_rps_in_window': round(completed_in_window / args.duration, 3),
        'successful_latency_ms': {
            'p50': percentile([r['latency_ms'] for r in successes], 0.5),
            'p90': p90,
            'p99': percentile([r['latency_ms'] for r in successes], 0.99),
        },
        'all_latency_ms_p90': percentile([r['latency_ms'] for r in results], 0.9),
        'queue_ms_p99': percentile([r['queue_ms'] for r in results], 0.99),
        'criteria': {'max_error_percent': args.max_error_percent, 'p90_limit_ms': args.p90_limit_ms},
        'per_second': dict(sorted(buckets.items())),
        'passed': passed,
    }
    output = json.dumps(report, indent=2) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding='utf-8')
    print(output, end='')
    raise SystemExit(0 if passed else 1)


if __name__ == '__main__':
    main()
