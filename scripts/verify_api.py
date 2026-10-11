"""Verify real API responses, lists and an isolated create/delete lifecycle."""

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
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--initial-max-session-id', type=int, required=True)
    parser.add_argument('--list-repetitions', type=int, default=3)
    args = parser.parse_args()
    base = urlsplit(args.base_url)
    results = []

    def call(method, path, payload=None, expected=(200,), stream=False):
        connection = http.client.HTTPConnection(base.hostname, base.port, timeout=180)
        started = time.monotonic()
        result = {'method': method, 'path': path}
        body = None
        try:
            headers = {'Content-Type': 'application/json'} if payload is not None else {}
            connection.request(method, path, json.dumps(payload) if payload is not None else None, headers)
            response = connection.getresponse()
            result['status'] = response.status
            result['x_cache'] = response.getheader('X-Cache')
            if stream:
                size = 0
                while chunk := response.read(65536):
                    size += len(chunk)
                result['body_bytes'] = size
            else:
                raw = response.read()
                result['body_bytes'] = len(raw)
                try:
                    body = json.loads(raw)
                except ValueError:
                    body = raw.decode(errors='replace')
                if not (200 <= response.status < 300):
                    result['error_body'] = body
            result['passed'] = response.status in expected and result['x_cache'] is None
        except (OSError, http.client.HTTPException) as exc:
            result['passed'] = False
            result['exception'] = type(exc).__name__
        finally:
            result['elapsed_seconds'] = round(time.monotonic() - started, 3)
            connection.close()
            results.append(result)
        return result, body

    for path in ('/ping', '/db_dummy', '/api/movie/1', '/api/customer/1', '/api/session/1'):
        call('GET', path)
    for path in ('/api/movie', '/api/customer', '/api/session'):
        for _ in range(args.list_repetitions):
            call('GET', path, stream=True)

    created_id = None
    payload = {
        'customer_id': 1, 'movie_id': 1,
        'start_time': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    try:
        result, body = call('POST', '/api/session', payload, expected=(200, 201))
        if result['passed'] and isinstance(body, dict):
            candidate = body.get('id')
            for field in ('session', 'data'):
                if candidate is None and isinstance(body.get(field), dict):
                    candidate = body[field].get('id')
            if isinstance(candidate, int) and candidate > args.initial_max_session_id:
                created_id = candidate
                call('GET', f'/api/session/{created_id}')
            else:
                results.append({'passed': False, 'problem': 'Creation response has no safely identifiable new session id', 'response': body})
    finally:
        if created_id is not None:
            call('DELETE', f'/api/session/{created_id}', expected=(200, 204))
            call('GET', f'/api/session/{created_id}', expected=(404,))
    report = {
        'timestamp_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'base_url': args.base_url, 'checks': results,
        'created_session_id': created_id,
        'passed': all(check['passed'] for check in results),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report['passed'] else 1)


if __name__ == '__main__':
    main()
