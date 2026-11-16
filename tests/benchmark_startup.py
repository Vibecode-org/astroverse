"""Disposable-container startup comparison, including entrypoint and API readiness.

Run baseline against the PRE-SPRINT image, mounting only this script. This
benchmark changes its container-local catalog_config.json; never run on a host.
Fixture generation and artifact preparation are outside startup measurements.
Each API process is fresh; the host/page cache is not flushed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request


def rss(pid):
    return {line.split(':')[0]: int(line.split()[1])
            for line in Path(f'/proc/{pid}/status').read_text().splitlines()
            if line.startswith(('VmRSS:', 'VmHWM:'))}


def server(env, count):
    with socket.socket() as reserve:
        reserve.bind(('127.0.0.1', 0))
        port = reserve.getsockname()[1]
    started = time.perf_counter()
    log_config = Path(tempfile.gettempdir())/'startup-benchmark-logging.json'
    log_config.write_text(json.dumps({
        'version': 1, 'disable_existing_loggers': False,
        'handlers': {'stderr': {'class': 'logging.StreamHandler'}},
        'root': {'level': 'INFO', 'handlers': ['stderr']}}))
    process = subprocess.Popen(
        [sys.executable, '/app/backend/entrypoint.py', 'uvicorn',
         'backend.app:app', '--host', '127.0.0.1', '--port', str(port),
         '--log-config', str(log_config)],
        cwd='/app', env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    peak = 0
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    result = None
    try:
        while time.perf_counter() - started < 300:
            if process.poll() is not None:
                raise RuntimeError(process.stderr.read().decode())
            peak = max(peak, rss(process.pid).get('VmHWM', 0))
            try:
                with opener.open(f'http://127.0.0.1:{port}/api/health', timeout=.1) as response:
                    assert json.load(response)['objects'] == count
                break
            except (OSError, urllib.error.URLError):
                time.sleep(.01)
        else:
            raise RuntimeError('startup deadline')
        result = dict(ready_seconds=time.perf_counter()-started,
                      startup_sampled_peak_kib=peak, api_kib=rss(process.pid))
        return result
    finally:
        process.terminate()
        _, logs = process.communicate(timeout=15)
        if result is not None:
            result['integrity_checks_seconds'] = [float(value) for value in re.findall(
                r'SQLite integrity verification: ([0-9.]+)s', logs.decode())]
            result['copy_checksum_seconds'] = [float(value) for value in re.findall(
                r'SQLite copy/checksum: ([0-9.]+)s', logs.decode())]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--count', type=int, choices=(100000, 1000000), required=True)
    parser.add_argument('--baseline', action='store_true')
    args = parser.parse_args()
    if not Path('/.dockerenv').exists():
        parser.error('run only inside a disposable Docker container')
    from tests.benchmark_streaming import generate
    with tempfile.TemporaryDirectory(prefix='startup-bench-') as directory:
        root = Path(directory)
        source, artifact = root/'source.json', root/'catalog.sqlite'
        generate(source, args.count)
        env = {**os.environ, 'ASTROVERSE_CATALOG_MODE': 'offline',
               'ASTROVERSE_CATALOG_PATH': str(root/'objects.json'),
               'ASTROVERSE_SECTOR_PATH': ''}
        result = dict(count=args.count, mode='before' if args.baseline else 'after')
        config = Path('/app/data/catalog_config.json')
        config_bytes = config.read_bytes()
        try:
            if args.baseline:
                settings = json.loads(config_bytes)
                settings['seed'] = str(source)
                config.write_text(json.dumps(settings))
            else:
                before = time.perf_counter()
                prepared = subprocess.check_output(
                    [sys.executable, '-m', 'data.bootstrap_catalog', 'build',
                     str(source), str(artifact)], cwd='/app', text=True)
                result['artifact_preparation_seconds'] = time.perf_counter()-before
                result['preparation_output'] = prepared.strip()
                # The caller bind-mounts an EMPTY, private runtime directory.
                # Never run this against the ordinary application's volume.
                runtime = Path('/app/data/runtime/catalog.sqlite')
                if runtime.exists():
                    raise RuntimeError('benchmark requires an empty private runtime mount')
                bundled = Path('/app/data/bootstrap/catalog.sqlite')
                for suffix in ('', '.sha256', '.manifest.json'):
                    shutil.copyfile(str(artifact)+suffix, str(bundled)+suffix)
            result['first'] = server(env, args.count)
            result['restart'] = server(env, args.count)
            result['source_bytes'] = source.stat().st_size
            if artifact.exists():
                result['sqlite_bytes'] = artifact.stat().st_size
                result['artifact_sha256'] = hashlib.file_digest(artifact.open('rb'), 'sha256').hexdigest()
            print(json.dumps(result, sort_keys=True), flush=True)
        finally:
            config.write_bytes(config_bytes)


if __name__ == '__main__':
    main()
