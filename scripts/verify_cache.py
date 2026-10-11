"""Observe the allowed long_dummy cache over a full expiry cycle."""

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
    parser.add_argument('--duration', type=float, default=65)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    url = urlsplit(args.base_url)
    deadline = time.monotonic() + args.duration
    samples = []
    while time.monotonic() < deadline:
        connection = http.client.HTTPConnection(url.hostname, url.port, timeout=10)
        started = time.monotonic()
        sample = {}
        try:
            connection.request('GET', '/long_dummy')
            response = connection.getresponse()
            body = json.loads(response.read())
            finished = time.monotonic()
            stamp = datetime.datetime.strptime(body['stamp'], '%Y-%m-%d %H:%M:%S').replace(tzinfo=datetime.timezone.utc)
            age = (datetime.datetime.now(datetime.timezone.utc) - stamp).total_seconds()
            sample = {'status': response.status, 'cache': response.getheader('X-Cache'),
                      'seconds': round(finished - started, 4), 'age_seconds': round(age, 3),
                      'passed': response.status == 200 and 0 <= age <= 60}
        except (OSError, ValueError, KeyError, http.client.HTTPException) as exc:
            sample = {'passed': False, 'error': type(exc).__name__}
        finally:
            connection.close()
        samples.append(sample)
        time.sleep(max(0, 1 - (time.monotonic() - started)))
    fast = sum(sample.get('seconds', 999) < 1 for sample in samples)
    report = {'samples': samples, 'fast_fraction': fast / len(samples),
              'max_age_seconds': max((s.get('age_seconds', 0) for s in samples), default=0),
              'passed': all(s['passed'] for s in samples) and fast / len(samples) >= 0.75}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: value for key, value in report.items() if key != 'samples'}, indent=2))
    raise SystemExit(0 if report['passed'] else 1)


if __name__ == '__main__':
    main()
