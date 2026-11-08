"""Explicit opt-in registry of supported centers; BSP discovery never grants support."""
from copy import deepcopy
from datetime import datetime
import math
import hashlib
import json
import re
from types import MappingProxyType

KERNEL_SHA256 = 'c1c7feeab882263fc493a9d5a5b2ddd71b54826cdf65d8d17a76126b260a49f2'
MODEL = {
    'id': 'jpl-de440s', 'provider': 'NASA/JPL', 'model': 'DE440s',
    'provider_revision': 'asset-sha256-' + KERNEL_SHA256, 'revision': 'de440s-skyfield1.53-time1', 'solver': 'skyfield-bsp',
    'source': 'NASA/JPL DE440s',
    'source_url': 'https://ssd.jpl.nasa.gov/doc/de440_de441.html',
    'asset': 'data/ephemeris/de440s.bsp', 'sha256': KERNEL_SHA256,
    'axes': 'right-handed equatorial XYZ, native DE440 axes; no Y/Z permutation',
    'reference_system': 'ICRF', 'origin': 'solar_system_barycenter', 'unit': 'km',
    'identity_namespace': 'NAIF', 'time_scale': 'TDB', 'utc_interval': ['2000-01-01T00:00:00+00:00', '2027-01-01T00:00:00+00:00'],
    'tdb_jd_interval': [2451544.5, 2462502.5], 'interval_end': 'exclusive',
    'source_epoch': None, 'source_epoch_status': 'time-dependent ephemeris, not a catalog epoch',
    'accuracy': None, 'accuracy_status': 'no per-vector physical uncertainty provided by kernel',
}


class SourceRegistry:
    """Validated immutable snapshot. Paging never copies the entire registry."""
    def __init__(self, models, objects):
        if len(models) > 128 or len(objects) > 1000000:
            raise ValueError('registry capacity exceeded')
        models, objects = deepcopy(models), deepcopy(objects)
        self._models = {}
        for model in models:
            required = set(MODEL)
            if len(json.dumps(model, allow_nan=False).encode()) > 8192:
                raise ValueError('model metadata too large')
            if not isinstance(model, dict) or set(model) != required or not model['id'] or model['id'] in self._models:
                raise ValueError('invalid or duplicate model')
            if any(not isinstance(model[key], str) for key in required - {'utc_interval','tdb_jd_interval','source_epoch','accuracy'}):
                raise ValueError('invalid model metadata type')
            if not re.fullmatch('[0-9a-f]{64}', model['sha256']):
                raise ValueError('invalid asset digest')
            if any(not model[k] for k in required - {'source_epoch', 'accuracy'}):
                raise ValueError('missing model metadata')
            if model['source_epoch'] is not None or model['accuracy'] is not None:
                raise ValueError('this registry supports unknown epoch/uncertainty only')
            for key in ('utc_interval', 'tdb_jd_interval'):
                if not isinstance(model[key], list) or len(model[key]) != 2:
                    raise ValueError('invalid interval')
                if key == 'utc_interval':
                    try:
                        bounds = [datetime.fromisoformat(value) for value in model[key]]
                        if any(value.tzinfo is None for value in bounds):
                            raise ValueError('timezone required')
                    except (TypeError, ValueError) as exc:
                        raise ValueError('invalid UTC interval') from exc
                else:
                    if any(type(value) not in (int,float) or not math.isfinite(value) for value in model[key]):
                        raise ValueError('invalid TDB interval')
                    bounds = model[key]
                if bounds[0] >= bounds[1]:
                    raise ValueError('invalid interval')
            if model['interval_end'] != 'exclusive':
                raise ValueError('invalid interval end')
            self._models[model['id']] = model
        self._objects = {}
        identities = set()
        for row in objects:
            if len(json.dumps(row, allow_nan=False).encode()) > 1024:
                raise ValueError('object metadata too large')
            if not isinstance(row, dict) or set(row) != {'id', 'target', 'identity_type', 'model_id', 'name', 'kind', 'color'}:
                raise ValueError('invalid object metadata')
            if any(not isinstance(row[key],str) for key in row if key != 'target'):
                raise ValueError('invalid object metadata type')
            if (not re.fullmatch('[a-z][a-z0-9_-]{0,127}', row['id']) or row['id'] in self._objects
                    or row['model_id'] not in self._models or type(row['target']) is not int
                    or row['identity_type'] not in ('body_center', 'barycenter')
                    or row['target'] < 0 or not row['name'] or row['kind'] not in ('star', 'planet', 'moon')
                    or not re.fullmatch('#[0-9a-fA-F]{6}', row['color'])):
                raise ValueError('invalid or duplicate object')
            if (self._models[row['model_id']]['identity_namespace'] == 'NAIF'
                    and (row['target'] <= 9) != (row['identity_type'] == 'barycenter')):
                raise ValueError('NAIF center and barycenter identity mismatch')
            identity = (row['model_id'], row['target'])
            if identity in identities:
                raise ValueError('ambiguous source identity')
            identities.add(identity)
            self._objects[row['id']] = row
        self._targets = MappingProxyType({key: row['target'] for key, row in self._objects.items()})
        self._rows = tuple(self._objects.values())
        self.revision = hashlib.sha256(json.dumps([models, objects], sort_keys=True,
            separators=(',', ':'), allow_nan=False).encode()).hexdigest()

    @property
    def targets(self):
        return self._targets

    def object(self, oid):
        return deepcopy(self._objects.get(oid))

    def model(self, mid):
        return deepcopy(self._models[mid])

    def page(self, offset=0, limit=128, q=''):
        if not 0 <= offset <= 1000000 or not 1 <= limit <= 128 or len(q) > 128:
            raise ValueError('invalid registry page')
        # Bounded result allocation, even for a large future registry.
        matches = (row for row in self._rows if q.casefold() in (row['id']+' '+row['name']).casefold())
        from itertools import islice
        rows = list(islice(matches, offset, offset + limit + 1))
        more = len(rows) > limit
        rows = rows[:limit]
        mids = dict.fromkeys(row['model_id'] for row in rows)
        return {'version': 'sources/1', 'revision': self.revision, 'objects': deepcopy(rows),
                'models': [self.model(mid) for mid in mids], 'total': len(self._rows),
                'next_offset': offset + limit if more else None}


REGISTRY = SourceRegistry([MODEL], [
    {'id': oid, 'target': target, 'identity_type': 'body_center', 'model_id': MODEL['id'],
     'name': name, 'kind': kind, 'color': color}
    for oid, target, name, kind, color in [
        ('sun', 10, 'Солнце', 'star', '#ffcf70'),
        ('earth', 399, 'Земля', 'planet', '#68b4ff'),
        ('moon', 301, 'Луна', 'moon', '#d9dfec'),
        ('mercury', 199, 'Меркурий', 'planet', '#b9aea4'),
        ('venus', 299, 'Венера', 'planet', '#e9c58e'),
    ]
])
