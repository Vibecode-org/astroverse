"""Bounded SBDB HTTP -> staging SQLite -> existing runtime catalog.

No paging/resume: SBDB does not pin database revisions. Missing rows never
mean deletion. Only explicit IDs owned by this adapter may be deleted.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import http.client
import json
import math
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time
from time import sleep as retry_sleep
import urllib.error
import urllib.parse
import urllib.request

import ijson
from ijson.common import ObjectBuilder

from data.incremental_catalog import publication_lock, RevisionConflict
from data.normalizers import make_object, measurement, SourceError, small_body_name
from data.runtime_catalog import DiskCatalog
from data.sectors import _canonical, SCHEMA_VERSION
from data.coordinates import coordinate_contract
from data.sources import JPL_SBDB
from data.streaming_catalog import build_streaming_index

ENDPOINT = 'https://ssd-api.jpl.nasa.gov/sbdb_query.api'
FIELDS = ['full_name', 'pdes', 'a', 'per', 'diameter']
ADAPTER = 'sbdb-asteroids/1'
NORMALIZATION = 'small-body/1'
OWNER = 'astroverse:sbdb-asteroids/1'
MAX_RECORDS = 2_000_000
MAX_BYTES = 1024**3
TOKEN_BYTES = 4096


class NoRedirect(urllib.request.HTTPRedirectHandler):
    # urllib's default redirect handler drains the body with an unbounded read.
    # Require an explicit endpoint instead, before any redirect body is read.
    def http_error_302(self, request, response, code, message, headers):
        response.close()
        raise SourceError('SBDB redirects are not permitted')

    http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class BoundedReader:
    """Bound bytes, nesting and lexical token size BEFORE the JSON parser."""
    def __init__(self, response, max_bytes, deadline):
        self.response, self.max_bytes, self.deadline = response, max_bytes, deadline
        self.digest = hashlib.sha256()
        self.size = self.token = self.depth = 0
        self.quoted = self.escape = False

    def read(self, size=-1):
        if time.monotonic() > self.deadline:
            raise TimeoutError('SBDB total download deadline')
        chunk = self.response.read1(min(65536, size) if size >= 0 else 65536)
        self.size += len(chunk)
        if self.size > self.max_bytes:
            raise SourceError('SBDB response byte limit')
        self.digest.update(chunk)
        for byte in chunk:
            if self.quoted:
                self.token += 1
                if self.escape:
                    self.escape = False
                elif byte == 92:
                    self.escape = True
                elif byte == 34:
                    self.quoted = False
                    self.token = 0
            elif byte == 34:
                self.quoted, self.token = True, 0
            elif byte in b'{[':
                self.depth += 1
                self.token = 0
                if self.depth > 4:
                    raise SourceError('SBDB nesting limit')
            elif byte in b'}]':
                self.depth -= 1
                self.token = 0
            elif byte in b',: \r\n\t':
                self.token = 0
            else:
                self.token += 1
            if self.token > TOKEN_BYTES:
                raise SourceError('SBDB field exceeds 4096 wire bytes')
        return chunk


def read_response(response, db, *, limit, max_bytes, deadline):
    """Stage raw rows on disk, so JSON member order has no significance."""
    reader = BoundedReader(response, max_bytes, deadline)
    metadata, keys = {}, set()
    row = None
    section = builder = None
    events = count = 0
    for prefix, event, value in ijson.parse(reader, use_float=True):
        if prefix == '' and event == 'map_key':
            if value not in {'signature', 'fields', 'count', 'data'} or value in keys:
                raise SourceError('unexpected or duplicate SBDB member')
            keys.add(value)
            section = value
            builder, events = ObjectBuilder(), 0
            continue
        if prefix == 'data' or prefix.startswith('data.'):
            if prefix == 'data' and event in {'start_array', 'end_array'}:
                continue
            if prefix == 'data.item' and event == 'start_array':
                row = []
            elif prefix == 'data.item.item' and event in {'string', 'number', 'null'} and row is not None:
                row.append(value)
                if len(row) > len(FIELDS):
                    raise SourceError('too many SBDB row fields')
            elif prefix == 'data.item' and event == 'end_array' and row is not None:
                if len(row) != len(FIELDS) or count >= limit:
                    raise SourceError('SBDB row width or record limit')
                db.execute('INSERT INTO raw VALUES (?,?)', (count, _canonical(row)))
                count += 1
                row = None
            else:
                raise SourceError('malformed SBDB data')
        elif prefix and section:
            events += 1
            if events > 64:
                raise SourceError('SBDB metadata limit')
            builder.event(event, value)
            metadata[section] = builder.value
        elif prefix != '' or event not in {'start_map', 'end_map'}:
            raise SourceError('SBDB envelope must be an object')
    if keys != {'signature', 'fields', 'count', 'data'} or metadata.get('fields') != FIELDS:
        raise SourceError('missing SBDB fields/envelope')
    signature = metadata.get('signature')
    if not isinstance(signature, dict) or signature.get('version') != '1.0' or not isinstance(signature.get('source'), str) or 'SBDB' not in signature['source']:
        raise SourceError('unsupported SBDB signature')
    total = metadata.get('count')
    if isinstance(total, bool) or not str(total).isdigit() or len(str(total)) > 12:
        raise SourceError('invalid SBDB count')
    if count != min(int(total), limit):
        raise SourceError('incomplete SBDB response')
    return {'sha256': reader.digest.hexdigest(), 'bytes': reader.size,
            'returned': count, 'matching_count': int(total), 'signature': signature}


def normalize(values, config, existing=None):
    row = dict(zip(FIELDS, values))
    name, designation = row['full_name'], row['pdes']
    if not isinstance(name, str) or not name.strip() or not isinstance(designation, str) or not designation.strip():
        raise SourceError('missing SBDB name/designation')
    designation = designation.strip()
    if len(designation) > 128:
        raise SourceError('SBDB designation limit')
    for field in ('a', 'per', 'diameter'):
        value = row[field]
        if value is not None:
            try:
                valid = not isinstance(value, bool) and math.isfinite(float(value)) and float(value) > 0
            except (ValueError, TypeError, OverflowError):
                valid = False
            if not valid:
                raise SourceError(f'invalid SBDB {field}')
    display_name = small_body_name(name)
    identities = {('asteroid', display_name.casefold()): existing} if existing else {}
    item = make_object('asteroid', display_name, 'solar', config, identities)
    item.update(id='sbdb:a:' + designation, parent='sun', source=JPL_SBDB,
                source_id=designation, source_url=ENDPOINT, import_owner=OWNER,
                au=measurement(row['a'], positive=True), period_days=measurement(row['per'], positive=True),
                radius_km=measurement(row['diameter'], positive=True)/2 if row['diameter'] is not None else None,
                source_epoch=None, source_frame=None, source_accuracy=None,
                description='Астероид из базы малых тел NASA JPL SBDB.')
    return item


def validate_staged(path, manifest):
    """Check the actual artifact, including manifest and referential indexes."""
    with DiskCatalog(path).snapshot() as snap:
        db = snap.db
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or db.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('SQLite integrity failure')
        if (snap.metadata['catalog_revision'] != manifest['semantic_revision'] or
                snap.metadata['import_manifest'] != manifest or manifest['catalog_schema'] != SCHEMA_VERSION):
            raise ValueError('manifest mismatch')
        if db.execute('SELECT count(*) FROM objects').fetchone()[0] != snap.metadata['object_count']:
            raise ValueError('object count mismatch')
        if db.execute('''SELECT 1 FROM objects o LEFT JOIN sectors s ON s.id=o.sector_id
                         LEFT JOIN objects r ON r.id=o.root_id WHERE s.id IS NULL OR r.id IS NULL LIMIT 1''').fetchone():
            raise ValueError('broken object index')
        if db.execute('''SELECT 1 FROM sectors s WHERE object_count !=
                         (SELECT count(*) FROM objects o WHERE o.sector_id=s.id) LIMIT 1''').fetchone():
            raise ValueError('sector count mismatch')
        if db.execute("""SELECT 1 FROM sector_bounds b LEFT JOIN sectors s
                         ON s.rowid=b.sector_rowid WHERE s.id IS NULL LIMIT 1""").fetchone():
            raise ValueError('orphan R-tree bounds')
        if db.execute("""SELECT 1 FROM sectors s LEFT JOIN sector_bounds b ON b.sector_rowid=s.rowid
            WHERE (s.min_x IS NULL AND b.sector_rowid IS NOT NULL) OR
                  (s.min_x IS NOT NULL AND (b.sector_rowid IS NULL OR
                   b.min_x>s.min_x OR b.min_y>s.min_y OR b.min_z>s.min_z OR
                   b.max_x<s.max_x OR b.max_y<s.max_y OR b.max_z<s.max_z)) LIMIT 1""").fetchone():
            raise ValueError('inconsistent R-tree bounds')
        meta = snap.metadata
        digest = hashlib.sha256(_canonical([SCHEMA_VERSION, coordinate_contract(),
                                meta['cell_size_ly'], meta['max_objects'], meta['max_depth']]).encode())
        for payload in snap.select(raw=True):
            digest.update(payload.encode())
            digest.update(b'\n')
        if digest.hexdigest() != meta['catalog_revision']:
            raise ValueError('semantic hash mismatch')
        if db.execute('SELECT count(*) FROM representations').fetchone()[0] != 2:
            raise ValueError('missing legacy representations')


def import_sbdb(path, *, expected_revision, url=ENDPOINT, limit=400, max_bytes=MAX_BYTES,
                timeout=30, total_timeout=600, retries=2, expected_sha256=None, deletes=(), mode='online'):
    """Serialize cooperating writers; retry whole transient HTTP attempts only."""
    if type(limit) is not int or not 1 <= limit <= MAX_RECORDS:
        raise ValueError('limit must be 1..2000000')
    if type(retries) is not int or not 0 <= retries <= 3:
        raise ValueError('retries must be 0..3')
    if not 0 < timeout <= 60 or not 0 < total_timeout <= 3600 or not 0 < max_bytes <= MAX_BYTES:
        raise ValueError('invalid HTTP budgets')
    if mode not in {'online', 'fixture'}:
        raise ValueError('invalid import mode')
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {'http', 'https'} or parsed.query or parsed.fragment or parsed.username:
        raise ValueError('URL must be a plain HTTP endpoint')
    path = Path(path).resolve()
    metrics = {}
    with publication_lock(path), DiskCatalog(path).snapshot() as old:
        previous = old.metadata
        if previous['catalog_revision'] != expected_revision:
            raise RevisionConflict('catalog revision changed')
        # Exact private namespace, under the SAME permanent publication lock.
        # No checkpoints are reused after SIGKILL; active file is never removed.
        prefix = '.' + path.name + '.import-'
        for orphan in path.parent.iterdir():
            if orphan.name.startswith(prefix) and orphan.is_dir() and not orphan.is_symlink():
                shutil.rmtree(orphan)
        with tempfile.TemporaryDirectory(dir=path.parent, prefix=prefix, ignore_cleanup_errors=True) as tmp:
            tmp = Path(tmp)
            with closing(sqlite3.connect(tmp/'source.sqlite')) as db:
                db.executescript('''PRAGMA cache_size=-8192; PRAGMA temp_store=FILE;
                    CREATE TABLE raw (ordinal INTEGER PRIMARY KEY, payload TEXT);
                    CREATE TABLE merged (id TEXT PRIMARY KEY, payload TEXT);
                    CREATE TABLE identities (source_id TEXT PRIMARY KEY, id TEXT UNIQUE);
                    CREATE TABLE legacy_names (name TEXT PRIMARY KEY, id TEXT UNIQUE);
                    CREATE TABLE incoming (source_id TEXT PRIMARY KEY, id TEXT UNIQUE);
                ''')
                started = time.perf_counter()
                request_url = url + '?' + urllib.parse.urlencode({'fields': ','.join(FIELDS), 'sb-kind': 'a', 'sort': 'pdes', 'limit': limit})
                deadline = time.monotonic() + total_timeout
                for attempt in range(retries+1):
                    db.execute('DELETE FROM raw')
                    request = urllib.request.Request(request_url, headers={'User-Agent': 'Astroverse/3.7-A', 'Accept-Encoding': 'identity'})
                    try:
                        remaining = deadline-time.monotonic()
                        if remaining <= 0:
                            raise TimeoutError('SBDB total download deadline')
                        with urllib.request.build_opener(NoRedirect()).open(request, timeout=min(timeout, remaining)) as response:
                            if response.status != 200 or response.headers.get('Content-Encoding', 'identity') != 'identity':
                                raise SourceError('unexpected SBDB HTTP status/encoding')
                            info = read_response(response, db, limit=limit, max_bytes=max_bytes, deadline=deadline)
                        length = response.headers.get('Content-Length')
                        if length is not None and int(length) != info['bytes']:
                            raise SourceError('incomplete HTTP Content-Length')
                        break
                    except (urllib.error.URLError, TimeoutError, OSError, http.client.IncompleteRead) as exc:
                        retryable = not isinstance(exc, urllib.error.HTTPError) or exc.code == 429 or exc.code >= 500
                        if not retryable or attempt == retries or time.monotonic() + 2**attempt >= deadline:
                            raise SourceError('SBDB download failed') from exc
                        retry_sleep(2**attempt)
                metrics['download_stage_seconds'] = time.perf_counter()-started
                if expected_sha256 is not None and info['sha256'] != expected_sha256:
                    raise SourceError('SBDB input hash mismatch')
                received = utc_now()
                config = json.loads(Path(__file__).with_name('catalog_config.json').read_text())
                for obj in old.select():
                    db.execute('INSERT INTO merged VALUES (?,?)', (obj['id'], _canonical(obj)))
                    if obj.get('source') == JPL_SBDB and obj.get('kind') == 'asteroid' and not obj.get('source_id'):
                        try:
                            db.execute('INSERT INTO legacy_names VALUES (?,?)', (obj.get('latin') or obj['name'], obj['id']))
                        except sqlite3.IntegrityError as exc:
                            raise SourceError('ambiguous legacy source name') from exc
                    if obj.get('source') == JPL_SBDB and obj.get('kind') == 'asteroid' and obj.get('source_id'):
                        try:
                            db.execute('INSERT INTO identities VALUES (?,?)', (str(obj['source_id']), obj['id']))
                        except sqlite3.IntegrityError as exc:
                            raise SourceError('ambiguous existing source identity') from exc
                for (payload,) in db.execute('SELECT payload FROM raw ORDER BY ordinal'):
                    values = json.loads(payload)
                    obj = normalize(values, config)
                    try:
                        db.execute('INSERT INTO incoming VALUES (?,NULL)', (obj['source_id'],))
                    except sqlite3.IntegrityError as exc:
                        raise SourceError('duplicate SBDB source identity') from exc
                    match = db.execute('SELECT id FROM identities WHERE source_id=?', (obj['source_id'],)).fetchone()
                    if not match:
                        match = db.execute('SELECT id FROM legacy_names WHERE name=?', (obj['latin'],)).fetchone()
                    if match:
                        existing = json.loads(db.execute('SELECT payload FROM merged WHERE id=?', (match[0],)).fetchone()[0])
                        obj = normalize(values, config, existing)
                        obj['id'] = match[0]
                    elif db.execute('SELECT 1 FROM merged WHERE id=?', (obj['id'],)).fetchone():
                        raise SourceError('catalog ID collision')
                    obj['input_sha256'] = info['sha256']
                    obj['adapter_version'] = ADAPTER
                    obj['normalization_version'] = NORMALIZATION
                    db.execute('UPDATE incoming SET id=? WHERE source_id=?', (obj['id'], obj['source_id']))
                    db.execute('INSERT OR REPLACE INTO merged VALUES (?,?)', (obj['id'], _canonical(obj)))
                removed = 0
                for oid in deletes:
                    removed += 1
                    if removed > 4096:
                        raise ValueError('delete budget exceeds 4096')
                    row = db.execute('SELECT payload FROM merged WHERE id=?', (oid,)).fetchone()
                    if row is None or json.loads(row[0]).get('import_owner') != OWNER:
                        raise ValueError('delete requires an ID owned by this adapter')
                    if db.execute('SELECT 1 FROM incoming WHERE id=?', (oid,)).fetchone():
                        raise ValueError('cannot delete incoming object')
                    db.execute('DELETE FROM merged WHERE id=?', (oid,))
                metrics['merge_normalize_seconds'] = time.perf_counter()-started-metrics['download_stage_seconds']
                manifest = {'schema': 'catalog-import/1', 'catalog_schema': 2, 'adapter': ADAPTER,
                            'normalization': NORMALIZATION, 'source': JPL_SBDB, 'endpoint': url,
                            'query': {'fields': FIELDS, 'sb-kind': 'a', 'sort': 'pdes', 'limit': limit},
                            'input': info, 'pinned_sha256': expected_sha256, 'mode': mode,
                            'received_at': received, 'built_at': utc_now(),
                            'scope': 'upsert asteroid pdes; omission preserves; explicit owned IDs delete',
                            'deleted_count': removed, 'source_epoch': None, 'frame': None, 'accuracy': None,
                            'config_sha256': hashlib.sha256(_canonical(config['display']['asteroid']).encode()).hexdigest()}
                candidate = tmp/'catalog.sqlite'
                meta = build_streaming_index(candidate, None,
                    objects=(json.loads(row[0]) for row in db.execute('SELECT payload FROM merged ORDER BY id')),
                    cell_size_ly=previous['cell_size_ly'], max_objects=previous['max_objects'], max_depth=previous['max_depth'],
                    source_signature=previous.get('source_signature'), parent_revision=expected_revision,
                    manifest=manifest, metrics=metrics)
                check = time.perf_counter()
                validate_staged(candidate, manifest)
                metrics['validate_seconds'] = time.perf_counter()-check
                publish = time.perf_counter()
                changed = meta['catalog_revision'] != expected_revision
                if changed:
                    with candidate.open('rb') as stream:
                        os.fsync(stream.fileno())
                    candidate.replace(path)
                    # Rename is the commit point. No fallible work follows it:
                    # errors must never report failure after changing active data.
                else:
                    meta = previous
                metrics['publish_seconds'] = time.perf_counter()-publish
                return {'changed': changed, 'metadata': meta, 'metrics': metrics, 'input': info}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', type=Path)
    parser.add_argument('--expected-revision', required=True)
    parser.add_argument('--url', default=ENDPOINT)
    parser.add_argument('--limit', type=int, default=400)
    parser.add_argument('--expected-sha256')
    parser.add_argument('--timeout', type=float, default=30)
    parser.add_argument('--total-timeout', type=float, default=600)
    parser.add_argument('--retries', type=int, default=2)
    parser.add_argument('--max-bytes', type=int, default=MAX_BYTES)
    parser.add_argument('--delete-id', action='append', default=[])
    args = parser.parse_args()
    try:
        result = import_sbdb(args.path, expected_revision=args.expected_revision, url=args.url,
                             limit=args.limit, expected_sha256=args.expected_sha256, deletes=args.delete_id,
                             timeout=args.timeout, total_timeout=args.total_timeout, retries=args.retries, max_bytes=args.max_bytes)
    except (ValueError, SourceError, OSError, sqlite3.Error, ijson.JSONError) as exc:
        parser.exit(1, f'Import failed; active revision preserved: {exc}\n')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
