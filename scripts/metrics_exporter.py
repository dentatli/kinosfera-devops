"""Prometheus metrics from normalized Nginx access events over internal UDP."""

import collections
import http.server
import json
import re
import socket
import threading

lock = threading.Lock()
requests = collections.Counter()
duration_counts = collections.Counter()
duration_sums = collections.Counter()
buckets = collections.Counter()
parse_errors = 0
boundaries = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.4, 0.5, 1, 2.5, 5, 10, float('inf'))


def endpoint(path):
    if path in ('/ping', '/dummy', '/db_dummy', '/long_dummy', '/operation'):
        return path
    if re.fullmatch(r'/api/(movie|customer|session)', path):
        return path
    if re.fullmatch(r'/api/(movie|customer|session)/[0-9]+', path):
        return path.rsplit('/', 1)[0] + '/{id}'
    return 'other'


def receive():
    global parse_errors
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024 * 1024)
    sock.bind(('0.0.0.0', 9514))
    while True:
        packet, _ = sock.recvfrom(65536)
        try:
            data = json.loads(packet[packet.index(b'{'):])
            route = endpoint(data['path'])
            method = data['method'] if data['method'] in ('GET', 'POST', 'DELETE', 'HEAD', 'PUT', 'PATCH', 'OPTIONS') else 'OTHER'
            status = str(int(data['status']))
            seconds = float(data['duration'])
            with lock:
                requests[(route, method, status)] += 1
                duration_counts[(route, method)] += 1
                duration_sums[(route, method)] += seconds
                for boundary in boundaries:
                    if seconds <= boundary:
                        buckets[(route, method, boundary)] += 1
        except (ValueError, KeyError, TypeError):
            with lock:
                parse_errors += 1


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != '/metrics':
            self.send_error(404)
            return
        lines = ['# TYPE kinosfera_http_requests_total counter']
        with lock:
            for (route, method, status), value in sorted(requests.items()):
                lines.append(f'kinosfera_http_requests_total{{endpoint="{route}",method="{method}",status="{status}"}} {value}')
            lines.append('# TYPE kinosfera_http_request_duration_seconds histogram')
            for (route, method), count in sorted(duration_counts.items()):
                labels = f'endpoint="{route}",method="{method}"'
                for boundary in boundaries:
                    le = '+Inf' if boundary == float('inf') else str(boundary)
                    lines.append(f'kinosfera_http_request_duration_seconds_bucket{{{labels},le="{le}"}} {buckets[(route, method, boundary)]}')
                lines.append(f'kinosfera_http_request_duration_seconds_count{{{labels}}} {count}')
                lines.append(f'kinosfera_http_request_duration_seconds_sum{{{labels}}} {duration_sums[(route, method)]}')
            lines.append(f'kinosfera_metrics_parse_errors_total {parse_errors}')
        payload = ('\n'.join(lines) + '\n').encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain; version=0.0.4')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


if __name__ == '__main__':
    threading.Thread(target=receive, daemon=True).start()
    http.server.ThreadingHTTPServer(('0.0.0.0', 9100), Handler).serve_forever()
