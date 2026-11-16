"""Compare isolated offline HTTP publication before/after backup and volume loss.

Writes evidence outside catalog volume. --patch must only use an isolated test
volume. Captures byte hashes of database, ordered cards and deterministic API
responses plus all SQLite metadata; no golden data rebuilt from seed.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import urllib.error
import urllib.parse
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--patch', action='store_true')
    parser.add_argument('--save', type=Path)
    parser.add_argument('--expect', type=Path)
    args = parser.parse_args()
    from data.bootstrap_catalog import DEFAULT_RUNTIME_PATH, sha256_file
    from data.incremental_catalog import publish_changes
    from data.runtime_catalog import DiskCatalog
    assert not Path('/app/data/catalog_seed.json').exists()
    assert not Path('/app/data/objects.json').exists()
    catalog = DiskCatalog(DEFAULT_RUNTIME_PATH)
    if args.patch:
        with catalog.snapshot() as snapshot:
            revision = snapshot.metadata['catalog_revision']
            earth = snapshot.object('earth')
        earth['description'] = earth.get('description','') + ' Delivery backup verified working patch'
        publish_changes(DEFAULT_RUNTIME_PATH, expected_revision=revision, upserts=[earth])
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def get(path, headers=None):
        request = urllib.request.Request('http://127.0.0.1:8000'+path, headers=headers or {})
        with opener.open(request, timeout=30) as response:
            return response.read(), response.headers

    health = json.loads(get('/api/health')[0])
    assert health == {'status':'ok','objects':3471}, health
    nearby = json.loads(get('/api/spatial/v1/nearby?scale=local&frame=equatorial&x=0&y=0&z=0&radius=32')[0])
    sector = '/api/spatial/v1/sectors/'+urllib.parse.quote(nearby['sectors'][0]['id'],safe='')
    paths = ['/api/health', '/api/objects/earth', '/api/search?q=%D0%B7%D0%B5%D0%BC%D0%BB%D1%8F',
             '/api/objects', '/api/objects?format=v1', '/api/objects?format=v2',
             '/api/spatial/v1/nearby?scale=local&frame=equatorial&x=0&y=0&z=0&radius=32',
             sector, '/api/positions/v1/sectors/solar:verified?at=2026-11-06T12:00:00Z']
    responses = {}
    for path in paths:
        body, headers = get(path, {'Accept':'application/octet-stream'} if 'format=' in path else None)
        responses[path] = dict(sha256=hashlib.sha256(body).hexdigest(), bytes=len(body), etag=headers.get('ETag'))
        if path == paths[-1]:
            assert {row['id'] for row in json.loads(body)['objects']} == {'sun','earth','moon','mercury','venus'}
    try:
        get(sector, {'If-None-Match':'W/'+responses[sector]['etag']})
        raise AssertionError('missing 304')
    except urllib.error.HTTPError as error:
        assert error.code == 304
    with catalog.snapshot() as snapshot:
        cards = hashlib.sha256()
        for row in snapshot.select(raw=True):
            cards.update(row.encode())
            cards.update(b'\n')
        result = dict(database_sha256=sha256_file(DEFAULT_RUNTIME_PATH),
                      ordered_cards_sha256=cards.hexdigest(), metadata=snapshot.metadata,
                      responses=responses, etag304=True)
    if args.expect:
        expected = json.loads(args.expect.read_text())
        assert result == expected, 'working publication/API mismatch after restore or image update'
    if args.save:
        args.save.write_text(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
    print(json.dumps(dict(ok=True,health=3471,api_checks=len(paths),
                         revision=result['metadata']['catalog_revision'],sha256=result['database_sha256'])))


if __name__ == '__main__':
    main()
