"""Immutable requested-time candidate publications, separate from snapshot catalogs.

Real support is deliberately nonselective: one unconditional five-center sector.
Synthetic affine swept envelopes are conservative candidates, never observations.
"""
from contextlib import closing, contextmanager
import hashlib
import json
import math
from pathlib import Path
import os
import sqlite3
import tempfile
import time
from threading import Lock

from data.ephemeris import contract, parse_utc
from data.source_registry import REGISTRY, MODEL
from data.publication import publication_lock, fsync_directory

MAX_SECTORS = 16
MAX_MEMBERS = 128
MAX_BYTES = 256 * 1024
EPOCH_JD = 2461041.5
SCHEMA = '''
PRAGMA journal_mode=DELETE;
CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE sectors(id TEXT PRIMARY KEY,object_count INTEGER NOT NULL);
CREATE TABLE bodies(id TEXT PRIMARY KEY,n INTEGER UNIQUE,sector_id TEXT NOT NULL,
 x REAL,y REAL,z REAL,vx REAL,vy REAL,vz REAL);
CREATE INDEX members ON bodies(sector_id,n);
CREATE TABLE envelopes(rowid INTEGER PRIMARY KEY,sector_id TEXT NOT NULL,bucket INTEGER NOT NULL);
CREATE VIRTUAL TABLE bounds USING rtree(rowid,min_x,max_x,min_y,max_y,min_z,max_z,min_t,max_t);
'''
_timescale = None
_time_lock = Lock()


def normalize_time(at=None, jd_tdb=None):
    global _timescale
    if (at is None) == (jd_tdb is None):
        raise ValueError('provide exactly one of at (UTC) or jd_tdb (TDB)')
    if at is not None:
        utc = parse_utc(at)
        with _time_lock:
            if _timescale is None:
                from skyfield.api import load
                _timescale = load.timescale(builtin=True)
            jd = float(_timescale.from_datetime(utc).tdb)
        return jd, utc.isoformat()
    if not math.isfinite(jd_tdb) or not MODEL['tdb_jd_interval'][0] <= jd_tdb < MODEL['tdb_jd_interval'][1]:
        raise ValueError('TDB Julian date outside supported interval')
    return float(jd_tdb), None


def synthetic_record(n):
    """Deterministic bounded generator: affine centers; every 128th is unknown."""
    sector = n // MAX_MEMBERS
    offset = n % MAX_MEMBERS
    known = offset != 127
    return (f'synthetic-{n:07d}', n, f'temporal:{sector:07d}',
            (0 if sector < 16 else (sector - 15) * 1_000_000) + (offset - 63.5) * 1000 if known else None,
            0 if known else None,
            (offset % 8 - 3.5) * 1000 if known else None,
            (1 if sector % 2 == 0 else -1) * 100 if known else None,
            (sector % 3 - 1) * 10 if known else None, 0 if known else None)


def _publish(path, metadata, fill, metrics=None):
    started = time.perf_counter()
    metrics = {} if metrics is None else metrics
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with publication_lock(path):
        fd, temporary = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
        os.close(fd)
        try:
            with closing(sqlite3.connect(temporary)) as db:
                db.executescript(SCHEMA)
                fill_started = time.perf_counter()
                fill(db)
                db.executemany('INSERT INTO metadata VALUES (?,?)',
                               ((key, json.dumps(value, separators=(',', ':'), allow_nan=False)) for key, value in metadata.items()))
                db.commit()
                metrics['fill_seconds'] = time.perf_counter()-fill_started
                integrity_started = time.perf_counter()
                if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('invalid temporal publication')
                metrics['integrity_seconds'] = time.perf_counter()-integrity_started
            publish_started = time.perf_counter()
            with open(temporary, 'rb') as stream:
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            fsync_directory(path.parent)
            metrics['fsync_publish_seconds'] = time.perf_counter()-publish_started
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    result = TemporalIndex(path)
    metrics['total_seconds'] = time.perf_counter()-started
    return result


def build_synthetic(path, count, *, bucket_days=365, metrics=None):
    if type(count) is not int or count < 1 or type(bucket_days) is not int or bucket_days < 1:
        raise ValueError('positive count and bucket_days required')
    specification = {'schema': 1, 'profile': 'synthetic-affine', 'count': count,
                     'bucket_days': bucket_days, 'epoch_jd': EPOCH_JD,
                     'interval': MODEL['tdb_jd_interval'], 'generator': 'affine-lattice/1'}
    revision = 'synthetic-temporal-' + hashlib.sha256(json.dumps(specification, sort_keys=True).encode()).hexdigest()
    coordinates = contract()
    coordinates.update(source='SYNTHETIC affine lattice; no measured astronomy', source_url=None,
                       kernel_sha256=None, revision=revision, supported_ids=[], supported_ids_total=count,
                       validation=None, synthetic=True, accuracy=None,
                       source_epoch=EPOCH_JD, source_epoch_status='synthetic affine model epoch JD TDB',
                       membership='bounded immutable synthetic temporal sectors')
    metadata = {**specification, 'revision': revision, 'temporal_revision': revision,
                'coordinates': coordinates, 'registry_revision': revision.rsplit('-',1)[1]}
    def fill(db):
        db.executemany('INSERT INTO bodies VALUES (?,?,?,?,?,?,?,?,?)', (synthetic_record(n) for n in range(count)))
        start, stop = specification['interval']
        buckets = math.ceil((stop - start) / bucket_days)
        envelope_id = 0
        for sector in range(math.ceil(count / MAX_MEMBERS)):
            sid = f'temporal:{sector:07d}'
            rows = db.execute('SELECT x,y,z,vx,vy,vz FROM bodies WHERE sector_id=? ORDER BY n', (sid,)).fetchall()
            db.execute('INSERT INTO sectors VALUES (?,?)', (sid, len(rows)))
            known = [row for row in rows if row[0] is not None]
            if not known:
                continue
            for bucket in range(buckets):
                lower_t = start + bucket * bucket_days
                upper_t = min(stop, lower_t + bucket_days)
                bounds = []
                for axis in range(3):
                    values = [row[axis] + row[axis + 3] * (t - EPOCH_JD)
                              for row in known for t in (lower_t, upper_t)]
                    # Rtree rounds outward again; nextafter covers Python rounding.
                    bounds.extend((math.nextafter(min(values), -math.inf), math.nextafter(max(values), math.inf)))
                envelope_id += 1
                db.execute('INSERT INTO envelopes VALUES (?,?,?)', (envelope_id, sid, bucket))
                db.execute('INSERT INTO bounds VALUES (?,?,?,?,?,?,?,?,?)',
                           (envelope_id, *bounds, bucket, bucket))
    return _publish(path, metadata, fill, metrics)


def ensure_real(path=None, registry=REGISTRY):
    revision = contract(registry)['revision']
    path = Path(path) if path else Path(tempfile.gettempdir()) / ('astroverse-temporal-real-' + registry.revision + '.sqlite')
    if path.exists():
        index = TemporalIndex(path)
        if index.metadata['revision'] != revision or index.metadata['profile'] != 'real-five':
            raise ValueError('incompatible real temporal publication')
        return index
    metadata = {'schema': 1, 'profile': 'real-five', 'count': len(registry.targets),
                'revision': revision, 'temporal_revision': 'temporal-real1-' + registry.revision,
                'registry_revision': registry.revision, 'coordinates': contract(registry),
                'interval': MODEL['tdb_jd_interval']}
    def fill(db):
        db.execute('INSERT INTO sectors VALUES (?,?)', ('solar:verified', len(registry.targets)))
        db.executemany('INSERT INTO bodies VALUES (?,?,?,?,?,?,?,?,?)',
                       ((oid, n, 'solar:verified', None, None, None, None, None, None)
                        for n, oid in enumerate(registry.targets)))
    return _publish(path, metadata, fill)


class TemporalIndex:
    def __init__(self, path):
        self.path = Path(path).resolve()
        with self.snapshot() as snapshot:
            self.metadata = snapshot.metadata

    @contextmanager
    def snapshot(self):
        with closing(sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True)) as db:
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA query_only=ON')
            db.execute('PRAGMA cache_size=-2048')
            db.execute('BEGIN')
            yield TemporalSnapshot(db)


class TemporalSnapshot:
    def __init__(self, db):
        self.db = db
        rows = db.execute('SELECT key,value FROM metadata LIMIT 33').fetchall()
        if len(rows) > 32:
            raise ValueError('temporal metadata budget exceeded')
        self.metadata = {row[0]: json.loads(row[1]) for row in rows}
        if self.metadata.get('schema') != 1 or self.metadata.get('profile') not in ('real-five', 'synthetic-affine'):
            raise ValueError('incompatible temporal publication')
        metadata = self.metadata
        lower, upper = metadata['interval']
        if (type(metadata['count']) is not int or metadata['count'] < 0
                or not all(type(v) in (int,float) and math.isfinite(v) for v in (lower,upper))
                or lower >= upper
                or any(not isinstance(metadata[k],str) or not 1 <= len(metadata[k]) <= 256 for k in ('revision','temporal_revision','registry_revision'))
                or metadata['coordinates']['revision'] != metadata['revision']
                or any(metadata['coordinates'][key] != value for key,value in
                       (('unit','km'),('reference_system','ICRF'),('origin','solar_system_barycenter'),('time_scale','TDB')))):
            raise ValueError('invalid temporal model metadata')
        if metadata['profile'] == 'synthetic-affine' and (type(metadata['bucket_days']) is not int or metadata['bucket_days'] < 1
                or type(metadata['epoch_jd']) not in (int,float) or not math.isfinite(metadata['epoch_jd'])):
            raise ValueError('invalid affine temporal metadata')
        for name in ('sectors', 'bodies', 'envelopes', 'bounds'):
            if db.execute('SELECT 1 FROM sqlite_master WHERE name=?', (name,)).fetchone() is None:
                raise ValueError('missing temporal index table')

    def candidates(self, center, radius, jd):
        start, stop = self.metadata['interval']
        if not start <= jd < stop:
            raise ValueError('outside temporal interval')
        if self.metadata['profile'] == 'real-five':
            return [{'id': 'solar:verified', 'object_count': self.metadata['count']}]
        bucket = math.floor((jd - start) / self.metadata['bucket_days'])
        x, y, z = center
        rows = self.db.execute('''SELECT e.sector_id,s.object_count FROM bounds b
            JOIN envelopes e ON e.rowid=b.rowid JOIN sectors s ON s.id=e.sector_id
            WHERE b.max_x>=? AND b.min_x<=? AND b.max_y>=? AND b.min_y<=?
            AND b.max_z>=? AND b.min_z<=? AND b.min_t<=? AND b.max_t>=? LIMIT ?''',
            (x-radius,x+radius,y-radius,y+radius,z-radius,z+radius,bucket,bucket,MAX_SECTORS+1)).fetchall()
        if len(rows) > MAX_SECTORS:
            raise OverflowError('temporal candidate budget exceeded; reduce radius')
        if any(not 0 <= row[1] <= MAX_MEMBERS for row in rows):
            raise ValueError('invalid temporal candidate member count')
        return [{'id': row[0], 'object_count': row[1]} for row in rows]

    def members(self, sid):
        info = self.db.execute('SELECT object_count FROM sectors WHERE id=?', (sid,)).fetchone()
        if info is None:
            return None
        if info[0] > MAX_MEMBERS:
            raise OverflowError('physical sector exceeds 128 centers; use individual reads')
        if info[0] < 0:
            raise ValueError('invalid temporal member budget')
        rows = self.db.execute('SELECT * FROM bodies WHERE sector_id=? ORDER BY n LIMIT ?', (sid, MAX_MEMBERS + 1)).fetchall()
        if len(rows) != info[0]:
            raise ValueError('invalid temporal membership')
        return rows

    def object(self, oid):
        return self.db.execute('SELECT * FROM bodies WHERE id=?', (oid,)).fetchone()

    def positions(self, rows, jd):
        return [{'id': row['id'], 'status': 'computed' if row['x'] is not None else 'unknown',
                 'source': 'SYNTHETIC affine lattice; no measured astronomy',
                 'position': [row[a] + row[v] * (jd-self.metadata.get('epoch_jd', EPOCH_JD)) for a,v in (('x','vx'),('y','vy'),('z','vz'))] if row['x'] is not None else None,
                 'reason': None if row['x'] is not None else 'synthetic_unknown_position'} for row in rows]
