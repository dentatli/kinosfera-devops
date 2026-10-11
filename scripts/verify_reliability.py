"""Sequential samples for list error rates and create/delete reliability."""

import argparse
import datetime
import http.client
import json
import time
from pathlib import Path
from urllib.parse import urlsplit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('base_url')
    parser.add_argument('--initial-max-session-id', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    url = urlsplit(args.base_url)
    connection = http.client.HTTPConnection(url.hostname, url.port, timeout=180)
    summaries = []
    errors = []

    def call(method, path, payload=None, retain=False):
        started = time.monotonic()
        try:
            connection.request(method, path, json.dumps(payload) if payload is not None else None,
                               {'Content-Type': 'application/json'} if payload is not None else {})
            response = connection.getresponse()
            size = 0
            chunks = []
            while chunk := response.read(65536):
                size += len(chunk)
                if retain:
                    chunks.append(chunk)
            body = json.loads(b''.join(chunks)) if retain and size else None
            return response.status, body, size, time.monotonic() - started
        except (OSError, ValueError, http.client.HTTPException) as exc:
            connection.close()
            errors.append({'method': method, 'path': path, 'exception': type(exc).__name__})
            return 0, None, 0, time.monotonic() - started

    for path, count, limit in [('/api/movie', 300, 1), ('/api/customer', 300, 1), ('/api/session', 60, 5)]:
        statuses = []
        elapsed = 0
        sizes = []
        for _ in range(count):
            status, _, size, seconds = call('GET', path)
            statuses.append(status)
            sizes.append(size)
            elapsed += seconds
        failures = sum(status != 200 for status in statuses)
        error_percent = failures * 100 / count
        summary = {'method': 'GET', 'path': path, 'requests': count, 'errors': failures,
                   'error_percent': error_percent, 'max_error_percent': limit,
                   'elapsed_seconds': round(elapsed, 3), 'min_body_bytes': min(sizes),
                   'max_body_bytes': max(sizes), 'passed': error_percent <= limit}
        summaries.append(summary)
        print(json.dumps(summary), flush=True)

    created = []
    create_failures = 0
    delete_failures = 0
    for _ in range(300):
        payload = {'customer_id': 1, 'movie_id': 1,
                   'start_time': datetime.datetime.now(datetime.timezone.utc).isoformat()}
        status, body, _, _ = call('POST', '/api/session', payload, retain=True)
        candidate = body.get('id') if isinstance(body, dict) else None
        if status not in (200, 201) or not isinstance(candidate, int) or candidate <= args.initial_max_session_id:
            create_failures += 1
            errors.append({'method': 'POST', 'status': status, 'problem': 'Cannot identify a newly created session'})
            continue
        created.append(candidate)
        status, _, _, _ = call('DELETE', f'/api/session/{candidate}')
        if status not in (200, 204):
            delete_failures += 1
            errors.append({'method': 'DELETE', 'status': status, 'created_session_id': candidate})

    for method, count, failures in [('POST', 300, create_failures), ('DELETE', len(created), delete_failures)]:
        percent = failures * 100 / count if count else 100
        summary = {'method': method, 'path': '/api/session' if method == 'POST' else '/api/session/{id}',
                   'requests': count, 'errors': failures, 'error_percent': percent, 'max_error_percent': 1,
                   'passed': percent <= 1 and count > 0}
        summaries.append(summary)
        print(json.dumps(summary), flush=True)
    connection.close()
    report = {'timestamp_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'summaries': summaries, 'errors': errors, 'created_session_ids': created,
              'passed': all(item['passed'] for item in summaries)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    raise SystemExit(0 if report['passed'] else 1)


if __name__ == '__main__':
    main()
