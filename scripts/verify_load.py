"""Run every mandatory fixed-rate load profile sequentially."""

import argparse
import json
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('base_url')
    parser.add_argument('--output-dir', type=Path, default=Path('reports'))
    parser.add_argument('--profile-seconds', type=int, default=30)
    args = parser.parse_args()
    if args.profile_seconds <= 0:
        parser.error('profile-seconds must be positive')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    profiles = [
        ('operation-120', '/operation', 120, args.profile_seconds, ['--operation']),
        ('db-dummy-120', '/db_dummy', 120, args.profile_seconds, []),
        ('movie-120', '/api/movie/1', 120, args.profile_seconds, []),
        ('customer-120', '/api/customer/1', 120, args.profile_seconds, []),
        ('session-120', '/api/session/1', 120, args.profile_seconds, []),
        ('peak-180', '/db_dummy', 180, 60, []),
        ('stable-60', '/db_dummy', 60, 60, []),
    ]
    reports = []
    for name, path, rps, duration, extra in profiles:
        report_file = args.output_dir / f'{name}.json'
        with report_file.with_suffix('.log').open('w', encoding='utf-8') as log:
            result = subprocess.run([
                sys.executable, str(Path(__file__).with_name('load_test.py')),
                args.base_url.rstrip('/') + path, '--rps', str(rps), '--duration', str(duration),
                '--output', str(report_file), *extra,
                *(['--p90-limit-ms', '400'] if rps == 120 else []),
            ], stdout=log, stderr=log)
        report = json.loads(report_file.read_text())
        reports.append(report)
        print(json.dumps({'profile': name, 'passed': report['passed'], 'errors': report['errors'],
                          'p90_ms': report['successful_latency_ms']['p90'], 'started_rps': report['started_rps']}), flush=True)
    summary = {'reports': reports, 'passed': len(reports) == len(profiles) and all(r['passed'] for r in reports)}
    (args.output_dir / 'load-suite.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    raise SystemExit(0 if summary['passed'] else 1)


if __name__ == '__main__':
    main()
