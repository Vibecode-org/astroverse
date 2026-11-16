"""Persistent, indexed family/parent information for bounded administrative patches."""
import math

from data.sectors import physical_position

INCREMENTAL_SCHEMA = 1
MAX_AFFECTED_OBJECTS = 65536
MAX_AFFECTED_BYTES = 64 * 1024 * 1024
MAX_AFFECTED_CELLS = 4096


def family_location(obj, cell_size):
    scale = obj['scale']
    position = physical_position(obj) if scale != 'solar' else None
    if scale == 'solar':
        return 'solar:system', 'system', None
    if position is None:
        return f'{scale}:unlocated', 'unlocated', None
    frame, *xyz = position
    ratios = [v / cell_size for v in xyz]
    if any(not math.isfinite(v) or abs(v) > 2**52 for v in ratios):
        raise ValueError('cell_size_ly too small for coordinates')
    return f'{scale}:{frame}:' + ':'.join(str(math.floor(v)) for v in ratios), frame, xyz


def install_incremental_index(db):
    """Full-builder-only setup; never invoked as a hidden patch migration."""
    db.executescript('''
        CREATE TABLE object_links (id TEXT PRIMARY KEY, parent TEXT);
        CREATE INDEX object_parent ON object_links(parent, id);
        CREATE INDEX object_root ON objects(root_id, id);
        CREATE TABLE family_index (
            root TEXT PRIMARY KEY, base_sid TEXT NOT NULL, scale TEXT NOT NULL,
            frame TEXT NOT NULL, x REAL, y REAL, z REAL, n INTEGER NOT NULL);
        CREATE INDEX family_cell ON family_index(base_sid, root);
    ''')
    # JSON's parent value remains in the original payload. The extra column is
    # only an indexed graph edge, not a second scientific interpretation.
    import json
    for oid, payload in db.execute('SELECT id,payload FROM objects'):
        db.execute('INSERT INTO object_links VALUES (?,?)', (oid, json.loads(payload).get('parent')))
    for root, sid, scale, n, payload in db.execute('''
            SELECT o.root_id, o.sector_id, o.scale, count(*), r.payload
            FROM objects o JOIN objects r ON r.id=o.root_id GROUP BY o.root_id'''):
        obj = json.loads(payload)
        position = physical_position(obj) if scale != 'solar' else None
        frame = 'system' if scale == 'solar' else position[0] if position else 'unlocated'
        xyz = position[1:] if position else [None] * 3
        db.execute('INSERT INTO family_index VALUES (?,?,?,?,?,?,?,?)',
                   (root, sid.split('/')[0], scale, frame, *xyz, n))
