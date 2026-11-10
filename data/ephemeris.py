"""Offline, geometric body centers. No apparent/observer or render coordinates."""

from datetime import datetime, timezone
import hashlib
import math
from pathlib import Path
from itertools import islice

from data.source_registry import REGISTRY, KERNEL_SHA256, MODEL
from data.physical_hierarchy import attach_hierarchy, REVISION as HIERARCHY_REVISION, VERSION as HIERARCHY_VERSION

KERNEL_PATH = Path(__file__).parent / 'ephemeris' / 'de440s.bsp'
# Keep existing response order; use body-center segments 199/299, never 1/2.
TARGETS = REGISTRY.targets  # compatibility view, never an independent membership list
# Deliberately narrower than the kernel. UTC is bounded by confirmed leap data.
UTC_START = datetime.fromisoformat(MODEL['utc_interval'][0])
UTC_STOP = datetime.fromisoformat(MODEL['utc_interval'][1])
TDB_START, TDB_STOP = MODEL['tdb_jd_interval']
REVISION = 'positions1-' + REGISTRY.revision + '-' + HIERARCHY_REVISION


def contract(registry=REGISTRY):
    result = {
        'version': 'positions/1', 'representation': 'simulation_position',
        'unit': 'km', 'reference_system': 'ICRF', 'origin': 'solar_system_barycenter',
        'axes': 'right-handed equatorial XYZ, native DE440 axes; no Y/Z permutation',
        'position_type': 'geometric_center', 'corrections': 'NONE',
        'source': 'NASA/JPL DE440s', 'source_url': 'https://ssd.jpl.nasa.gov/doc/de440_de441.html',
        'kernel_sha256': KERNEL_SHA256, 'revision': REVISION,
        'source_epoch': None, 'source_epoch_status': 'time-dependent ephemeris, not a catalog epoch',
        'time_scale': 'TDB', 'input_time_scales': ['UTC', 'TDB'],
        'utc_interval': [UTC_START.isoformat(), UTC_STOP.isoformat()],
        'tdb_jd_interval': [TDB_START, TDB_STOP], 'interval_end': 'exclusive',
        'utc_source': 'Skyfield 1.53 built-in leap table; IERS Bulletin C 72, leap table expires 2027-06-28 (exclusive API bound)',
        'utc_source_url': 'https://hpiers.obspm.fr/iers/bul/bulc/Leap_Second.dat',
        'accuracy': None, 'accuracy_status': 'no per-vector physical uncertainty provided by kernel',
        'validation': {'reference': 'JPL Horizons geometric ICRF barycentric vectors',
                       'samples_per_body': 20, 'tolerance_km': 1.0,
                       'meaning': 'numerical regression tolerance, not absolute astronomical uncertainty'},
        'supported_ids': list(islice(registry.targets, 128)),
        'supported_ids_total': len(registry.targets),
        'capabilities_url': '/api/sources/v1/objects',
        'hierarchy_version': HIERARCHY_VERSION,
        'membership': 'solar:verified; all supported centers evaluated at requested time; no static root extrapolation',
    }

    first_id = next(iter(registry.targets), None)
    model = registry.model(registry.object(first_id)['model_id']) if first_id else MODEL
    result.update({key: value for key, value in model.items() if key in result})
    result['kernel_sha256'] = model['sha256']
    if model['solver'] != 'skyfield-bsp':
        result['validation'] = None
    result['revision'] = 'positions1-' + registry.revision + '-' + HIERARCHY_REVISION
    return result


def parse_utc(value, start=UTC_START, stop=UTC_STOP):
    # Require a complete timestamp with an offset. No dates, local time, now alias
    # or leap-second syntax: Python datetime cannot represent second 60.
    if 'T' not in value:
        raise ValueError('at requires an ISO 8601 UTC timestamp with timezone')
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.tzinfo is None:
            raise ValueError('timezone required')
        result = result.astimezone(timezone.utc)
    except (ValueError, OverflowError) as exc:
        raise ValueError('invalid timestamp or unsupported leap-second syntax') from exc
    if not start <= result < stop:
        raise ValueError(f'UTC date outside confirmed interval [{start.isoformat()}, {stop.isoformat()})')
    return result


class Ephemeris:
    """Memory-mapped immutable kernel, verified once. No network at runtime."""

    def __init__(self, path=KERNEL_PATH, registry=REGISTRY, provider=None):
        self.registry = registry
        self.revision = 'positions1-' + registry.revision + '-' + HIERARCHY_REVISION
        self.model = registry.model(registry.object(next(iter(registry.targets)))['model_id']) if registry.targets else MODEL
        for oid in registry.targets:
            model = registry.model(registry.object(oid)['model_id'])
            if any(model[key] != self.model[key] for key in ('solver', 'sha256', 'reference_system', 'origin', 'unit', 'utc_interval', 'tdb_jd_interval')):
                raise ValueError('incompatible models in one physical sector')
        if provider is not None:
            self.kernel, self.timescale = provider.kernel, provider.timescale
            return
        if any(self.model[key] != MODEL[key] for key in ('solver', 'sha256', 'reference_system', 'origin', 'unit', 'time_scale')):
            raise ValueError('provider asset mismatch')
        path = Path(path)
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if digest != KERNEL_SHA256:
            raise ValueError('DE440s checksum mismatch')
        from skyfield.api import Loader, load_file
        self.kernel = load_file(str(path))
        self.timescale = Loader(str(path.parent)).timescale(builtin=True)

    def close(self):
        self.kernel.close()

    def evaluate(self, *, at=None, jd_tdb=None, ids=None):
        if (at is None) == (jd_tdb is None):
            raise ValueError('provide exactly one of at (UTC) or jd_tdb (TDB)')
        if at is not None:
            utc = parse_utc(at, *(datetime.fromisoformat(value) for value in self.model['utc_interval']))
            t = self.timescale.from_datetime(utc)
            evaluated_at = utc.isoformat()
        else:
            if not math.isfinite(jd_tdb) or not self.model['tdb_jd_interval'][0] <= jd_tdb < self.model['tdb_jd_interval'][1]:
                raise ValueError('TDB Julian date outside supported interval')
            t = self.timescale.tdb_jd(jd_tdb)
            evaluated_at = None
        rows = []
        for oid in self.registry.targets if ids is None else ids:
            row = self.registry.object(oid)
            target = row['target'] if row else None
            vector = self.kernel[target].at(t).position.km.tolist() if target is not None else None
            rows.append({'id': oid, 'target': target, 'status': 'computed' if target is not None else 'unknown',
                         'position': vector, 'reason': None if target is not None else 'no_verified_ephemeris'})
        return attach_hierarchy({'version': 'positions/1', 'revision': self.revision, 'registry_revision': self.registry.revision, 'coordinates': contract(self.registry),
                'evaluated_at': evaluated_at, 'input_time_scale': 'UTC' if at is not None else 'TDB',
                'jd_tdb': float(t.tdb), 'sector': 'solar:verified', 'objects': rows})
