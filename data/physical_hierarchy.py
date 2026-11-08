"""Coordinate placement metadata, never a solver or a catalog-position fallback."""
from copy import deepcopy

VERSION = 'physical-hierarchy/1'
REVISION = 'hierarchy1-ssb1'
MAX_SECTORS, MAX_SYSTEMS, MAX_BODIES = 128, 512, 4096


def attach_hierarchy(frame):
    """Add the existing SSB solar coordinate chart without changing any vector.

    Sector/system origins are coordinate anchors, not additional celestial bodies.
    All source coordinates/epoch/uncertainties remain in positions/1 unchanged.
    """
    if len(frame['objects']) > MAX_BODIES:
        raise ValueError('physical hierarchy body limit exceeded')
    sector = frame['sector']
    system = sector + ':ssb'
    frame['hierarchy'] = {
        'version': VERSION, 'revision': frame['revision'],
        'reference_system': frame['coordinates']['reference_system'],
        'origin': frame['coordinates']['origin'], 'unit': frame['coordinates']['unit'],
        'time_scale': frame['coordinates']['time_scale'],
        'jd_tdb': frame['jd_tdb'], 'evaluated_at': frame['evaluated_at'],
        'sectors': [{'id': sector, 'origin_km': [0, 0, 0]}],
        'systems': [{'id': system, 'sector_id': sector, 'offset_km': [0, 0, 0]}],
        'bodies': [{'id': row['id'], 'system_id': system if row['position'] is not None else None,
                    'offset_km': deepcopy(row['position'])} for row in frame['objects']],
    }
    return frame
