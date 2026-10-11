"""Render the origin edge config and validate or generate its TLS certificate."""

import ipaddress
import os
import re
import subprocess
import ssl
from pathlib import Path


def configure(root):
    domain = os.environ.get('TLS_DOMAIN', 'kinosfera.test')
    if not re.fullmatch(r'(?=.{1,253}$)[a-zA-Z0-9](?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?', domain):
        raise SystemExit('TLS_DOMAIN must be a DNS name without a scheme, port or path')
    address = str(ipaddress.IPv4Address(os.environ['SERVER_BIND_IP']))
    mode = os.environ.get('TLS_CERT_MODE', 'selfsigned')
    if mode not in ('selfsigned', 'provided'):
        raise SystemExit('TLS_CERT_MODE must be selfsigned or provided')
    cert_dir = root / 'certs'
    cert_dir.mkdir(exist_ok=True)
    certificate, key = cert_dir / 'server.crt', cert_dir / 'server.key'
    valid = certificate.exists() and key.exists()
    if valid:
        host_check = subprocess.run(['openssl', 'x509', '-in', str(certificate), '-noout', '-checkhost', domain],
                                    capture_output=True, text=True)
        valid = host_check.returncode == 0 and ' does match certificate' in host_check.stdout
        valid = valid and subprocess.run(['openssl', 'x509', '-in', str(certificate), '-noout', '-checkend', '86400'],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
        ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).load_cert_chain(certificate, key)
    if not valid:
        if mode == 'provided':
            raise SystemExit('Provided certificate is missing, expires within 24h or does not cover TLS_DOMAIN')
        if certificate.exists() or key.exists():
            # Never silently replace a supplied certificate or private key.
            raise SystemExit('Existing TLS files do not cover TLS_DOMAIN or expire soon. Back them up and remove both before regenerating.')
        san = f'DNS:{domain}' + (f',IP:{address}' if address != '0.0.0.0' else '')
        subprocess.run([
            'openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '365',
            '-subj', f'/CN={domain}', '-addext', f'subjectAltName={san}',
            '-keyout', str(key), '-out', str(certificate),
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        key.chmod(0o600)
    # Nginx's own config check also verifies that the private key matches.
    config = (root / 'config/nginx.conf').read_text(encoding='utf-8')
    config = config.replace('server_name kinosfera.test;', f'server_name {domain};')
    (root / '.state').mkdir(exist_ok=True)
    (root / '.state/nginx.conf').write_text(config, encoding='utf-8')


if __name__ == '__main__':
    configure(Path(__file__).resolve().parent.parent)
