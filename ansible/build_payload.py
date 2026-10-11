"""Bundle public deployment inputs reproducibly; exclude runtime data and secrets."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile


def build(source, output):
    source = source.resolve()
    names = {
        'bingo', 'Dockerfile', '.dockerignore', 'compose.yaml',
        'config/nginx.conf', 'config/haproxy.cfg', 'config/bingo-logrotate.conf',
        'config/kinosfera-network.service', 'config/prometheus.yml', 'config/dashboard.json',
    }
    for directory, suffixes in (('scripts', {'.sh', '.py'}), ('sql', {'.sql'}),
                                ('config/grafana', {'.yml', '.yaml', '.json'})):
        for path in (source / directory).rglob('*'):
            if path.is_file() and path.suffix in suffixes:
                names.add(path.relative_to(source).as_posix())
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('wb') as raw, gzip.GzipFile(filename='', fileobj=raw, mode='wb', mtime=0) as zipped:
        with tarfile.open(fileobj=zipped, mode='w', format=tarfile.PAX_FORMAT) as archive:
            for name in sorted(names):
                path = source / name
                if path.is_symlink() or not path.resolve().is_relative_to(source):
                    raise ValueError('Deployment input must be a regular file inside the source directory: ' + name)
                data = path.read_bytes()
                if name != 'bingo':
                    data = data.replace(b'\r\n', b'\n')
                elif not data.startswith(b'\x7fELF'):
                    raise ValueError('bingo must be the Linux ELF binary')
                info = tarfile.TarInfo(name)
                info.size = len(data)
                info.mode = 0o755 if name == 'bingo' or name.endswith('.sh') else 0o644
                info.mtime = 0
                archive.addfile(info, io.BytesIO(data))
    return {'archive': str(output), 'files': len(names),
            'sha256': hashlib.sha256(output.read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.source, args.output)))


if __name__ == '__main__':
    main()
