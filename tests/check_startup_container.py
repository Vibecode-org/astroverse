"""HTTP/persistence acceptance probe run inside an isolated, networkless stack.

The caller removes catalog JSON in a derived test image, patches its private
volume, then runs verify after Docker restart/recreate/image rebuild. Never
point this patch probe at the ordinary application's persistent database.
"""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('patch', 'verify'))
    args = parser.parse_args()
    from data.bootstrap_catalog import DEFAULT_RUNTIME_PATH
    from data.incremental_catalog import publish_changes
    from data.runtime_catalog import DiskCatalog
    marker = DEFAULT_RUNTIME_PATH.parent/'startup-acceptance.json'
    assert not Path('/app/data/catalog_seed.json').exists()
    assert not Path('/app/data/objects.json').exists()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def get(path, etag=None, binary=False):
        request_headers = {'If-None-Match': etag} if etag else {}
        if binary:
            request_headers['Accept'] = 'application/octet-stream'
        request = urllib.request.Request('http://127.0.0.1:8000'+path,
                                         headers=request_headers)
        with opener.open(request, timeout=15) as response:
            return response.read(), response.headers

    assert json.loads(get('/api/health')[0]) == {'status': 'ok', 'objects': 3471}
    earth = json.loads(get('/api/objects/earth')[0])
    assert earth['id'] == 'earth'
    assert any(row['id'] == 'earth' for row in json.loads(get('/api/search?q=%D0%B7%D0%B5%D0%BC%D0%BB%D1%8F')[0]))
    nearby = json.loads(get('/api/spatial/v1/nearby?scale=local&frame=equatorial&x=0&y=0&z=0&radius=32')[0])
    sid = urllib.parse.quote(nearby['sectors'][0]['id'], safe='')
    page, headers = get('/api/spatial/v1/sectors/'+sid)
    assert json.loads(page)['objects']
    try:
        get('/api/spatial/v1/sectors/'+sid, 'W/'+headers['ETag'])
        raise AssertionError('expected conditional 304')
    except urllib.error.HTTPError as error:
        assert error.code == 304
    binary_hashes = {}
    for version in ('v1', 'v2'):
        blob, _ = get('/api/objects?format='+version, binary=True)
        assert blob[:4] == b'ASTV'
        binary_hashes[version] = hashlib.sha256(blob).hexdigest()
    positions = json.loads(get('/api/positions/v1/sectors/solar:verified?at=2026-11-06T12:00:00Z')[0])
    assert {row['id'] for row in positions['objects']} == {'sun', 'earth', 'moon', 'mercury', 'venus'}
    if args.action == 'patch':
        assert not marker.exists(), 'use a fresh isolated acceptance volume'
        with DiskCatalog(DEFAULT_RUNTIME_PATH).snapshot() as snapshot:
            previous = snapshot.metadata['catalog_revision']
        changed = {**earth, 'description': earth.get('description', '')+' SQLite persistence acceptance'}
        metadata = publish_changes(DEFAULT_RUNTIME_PATH, expected_revision=previous, upserts=[changed])
        marker.write_text(json.dumps({'revision': metadata['catalog_revision'], 'earth': changed,
                                      'previous_revision': previous}, ensure_ascii=False))
        assert json.loads(get('/api/objects/earth')[0]) == changed
    else:
        saved = json.loads(marker.read_text())
        assert earth == saved['earth']
        with DiskCatalog(DEFAULT_RUNTIME_PATH).snapshot() as snapshot:
            assert snapshot.metadata['catalog_revision'] == saved['revision']
        assert 'persistence acceptance' in earth['description']
    print(json.dumps({'action': args.action, 'health': 3471, 'json_free': True,
                      'binary_sha256': binary_hashes, 'revision': json.loads(marker.read_text())['revision']}))


if __name__ == '__main__':
    main()
