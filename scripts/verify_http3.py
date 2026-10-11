"""Perform an actual HTTP/3 request with CA verification (requires aioquic)."""

import argparse
import asyncio
import json
import ssl
from pathlib import Path

from aioquic.asyncio import QuicConnectionProtocol, connect
from aioquic.h3.connection import H3_ALPN, H3Connection
from aioquic.h3.events import DataReceived, HeadersReceived
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import ConnectionTerminated, ProtocolNegotiated


class Client(QuicConnectionProtocol):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.http = H3Connection(self._quic)
        self.future = None
        self.stream_id = None
        self.headers = []
        self.body = bytearray()
        self.alpn = None

    def quic_event_received(self, event):
        if isinstance(event, ProtocolNegotiated):
            self.alpn = event.alpn_protocol
        if isinstance(event, ConnectionTerminated) and self.future is not None and not self.future.done():
            self.future.set_exception(ConnectionError(event.reason_phrase))
        for http_event in self.http.handle_event(event):
            if isinstance(http_event, (HeadersReceived, DataReceived)) and http_event.stream_id == self.stream_id:
                if isinstance(http_event, HeadersReceived):
                    self.headers.extend(http_event.headers)
                else:
                    self.body.extend(http_event.data)
                if http_event.stream_ended and not self.future.done():
                    self.future.set_result(None)

    async def get(self, authority):
        self.future = asyncio.get_running_loop().create_future()
        self.stream_id = self._quic.get_next_available_stream_id()
        self.http.send_headers(self.stream_id, [
            (b':method', b'GET'), (b':scheme', b'https'),
            (b':authority', authority.encode()), (b':path', b'/ping'),
        ], end_stream=True)
        self.transmit()
        await asyncio.wait_for(self.future, timeout=10)
        status = dict(self.headers).get(b':status', b'').decode()
        return {'alpn': self.alpn, 'status': status, 'body': self.body.decode(),
                'certificate_verified': True, 'passed': self.alpn == 'h3' and status == '200' and self.body == b'pong\n'}


async def check(args):
    configuration = QuicConfiguration(is_client=True, alpn_protocols=H3_ALPN)
    configuration.verify_mode = ssl.CERT_REQUIRED
    configuration.server_name = args.server_name
    configuration.load_verify_locations(cafile=str(args.ca))
    async with connect(args.host, args.port, configuration=configuration, create_protocol=Client) as client:
        return await client.get(args.server_name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('host')
    parser.add_argument('--server-name', default='kinosfera.test')
    parser.add_argument('--port', type=int, default=443)
    parser.add_argument('--ca', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = asyncio.run(asyncio.wait_for(check(args), timeout=15))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report['passed'] else 1)


if __name__ == '__main__':
    main()
