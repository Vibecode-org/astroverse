"""Bounded family closure and local sector updates for incremental patches.

Publication, global revisions and compatibility representations are coordinated
by incremental_catalog; these functions only inspect or update the admitted
family/base-cell region on the caller's SQLite connection.
"""

import hashlib
import json
import math

from data.coordinates import coordinate_contract
from data.incremental_index import (MAX_AFFECTED_OBJECTS, MAX_AFFECTED_BYTES,
                                    MAX_AFFECTED_CELLS, family_location)
from data.sectors import ResultLimitExceeded, SCHEMA_VERSION, MAX_BOUND_LY, _canonical


def _region(db, changes, removed, meta):
    """Indexed family closure, final graph validation and bounded cell expansion.

    A target parent brings its old family into the closure. Consequently every
    path affected by a changed edge, including its descendants, is validated.
    Complete old/new base cells are the deterministic split/merge boundary.
    """
    roots, cells, region, payload_bytes = set(), set(), {}, 0

    def include(row):
        nonlocal payload_bytes
        oid, size, ordinal, root = row
        if oid in region:
            return
        payload_bytes += size
        if len(region) >= MAX_AFFECTED_OBJECTS or payload_bytes > MAX_AFFECTED_BYTES:
            raise ResultLimitExceeded('affected region exceeds 65536 objects or 64 MiB; full rebuild required')
        payload = db.execute('SELECT payload FROM objects WHERE id=?', (oid,)).fetchone()[0]
        region[oid] = (json.loads(payload), payload, ordinal, root)

    def add_root(root):
        if root in roots:
            return
        roots.add(root)
        row = db.execute('SELECT base_sid FROM family_index WHERE root=?', (root,)).fetchone()
        if row is None:
            raise ValueError('incremental family index is inconsistent; rebuild required')
        cells.add(row[0])
        for row in db.execute('SELECT id,length(CAST(payload AS BLOB)),ordinal,root_id FROM objects WHERE root_id=?', (root,)):
            include(row)

    targets = set(changes) | removed | {obj.get('parent') for obj, _ in changes.values()} - {None}
    for oid in targets:
        row = db.execute('SELECT root_id FROM objects WHERE id=?', (oid,)).fetchone()
        if row:
            add_root(row[0])
    final = {oid: row[0] for oid, row in region.items() if oid not in removed}
    final.update((oid, obj) for oid, (obj, _) in changes.items())
    resolved = {}
    for oid in final:
        chain, seen, current = [], set(), oid
        while current not in resolved:
            if current in seen:
                raise ValueError('parent cycle')
            if current not in final:
                raise ValueError('unknown parent')
            seen.add(current)
            chain.append(current)
            parent = final[current].get('parent')
            if parent is None:
                resolved[current] = current
                break
            current = parent
        root = resolved[current]
        for member in chain:
            if final[member]['scale'] != final[root]['scale']:
                raise ValueError('cross-scale parent family')
            resolved[member] = root
    for root in set(resolved.values()):
        cells.add(family_location(final[root], meta['cell_size_ly'])[0])
    if len(cells) > MAX_AFFECTED_CELLS:
        raise ResultLimitExceeded('affected region exceeds 4096 base cells; full rebuild required')
    # Include unchanged sibling families: merging only touched leaves would
    # depend on patch history and disagree with the canonical full builder.
    for sid in sorted(cells):
        for row in db.execute('''SELECT o.id,length(CAST(o.payload AS BLOB)),o.ordinal,o.root_id
                FROM family_index f JOIN objects o ON o.root_id=f.root
                WHERE f.base_sid=?''', (sid,)):
            include(row)
    final = {oid: row[0] for oid, row in region.items() if oid not in removed}
    final.update((oid, obj) for oid, (obj, _) in changes.items())
    # Enforce the bound on the final region too (an all-new patch has no old rows).
    affected_bytes = payload_bytes + sum(max(0, len(payload.encode()) -
        (len(region[oid][1].encode()) if oid in region else 0)) for oid, (_, payload) in changes.items())
    if len(set(region) | set(final)) > MAX_AFFECTED_OBJECTS or affected_bytes > MAX_AFFECTED_BYTES:
        raise ResultLimitExceeded('affected region exceeds 65536 objects or 64 MiB; full rebuild required')
    for oid, row in region.items():
        if oid not in resolved and oid not in removed:
            resolved[oid] = row[3]
    return region, final, resolved, cells, affected_bytes


def _update_region(db, changes, removed, meta, region, final, resolved, cells):
    db.execute('BEGIN')
    db.execute('PRAGMA defer_foreign_keys=ON')
    old_sectors = {}
    for sid in sorted(cells):
        # Sector IDs encode base cells; use indexed ranges, never LIKE whose
        # case-insensitive default can force a complete sectors-table scan.
        for old_sid, revision in db.execute('''SELECT id,revision FROM sectors
                WHERE id=? OR (id>=? AND id<?)''', (sid, sid + '/', sid + '0')):
            old_sectors[old_sid] = revision
    for sid in old_sectors:
        db.execute('DELETE FROM sector_bounds WHERE sector_rowid=(SELECT rowid FROM sectors WHERE id=?)', (sid,))
        db.execute('DELETE FROM sectors WHERE id=?', (sid,))
    for oid in removed:
        db.execute('DELETE FROM object_links WHERE id=?', (oid,))
        db.execute('DELETE FROM objects WHERE id=?', (oid,))
    for root in {row[3] for row in region.values()}:
        db.execute('DELETE FROM family_index WHERE root=?', (root,))

    families = {}
    for oid, root in resolved.items():
        if oid in final:
            families.setdefault(root, []).append(oid)
    groups = {}
    for root, members in families.items():
        obj = final[root]
        sid, frame, xyz = family_location(obj, meta['cell_size_ly'])
        family = root, members, xyz
        groups.setdefault((sid, obj['scale'], frame), []).append(family)
        db.execute('INSERT INTO family_index VALUES (?,?,?,?,?,?,?,?)',
                   (root, sid, obj['scale'], frame, *(xyz or [None] * 3), len(members)))

    next_ordinal = db.execute('SELECT ordinal FROM objects ORDER BY ordinal DESC LIMIT 1').fetchone()
    next_ordinal = next_ordinal[0] + 1 if next_ordinal else 0
    new_ordinals = {}
    # Preserve original ordering for existing IDs; append new IDs sorted, as
    # the previous patch writer did. Physical IDs never depend on an ordinal.
    for oid in sorted(changes):
        if oid not in region:
            new_ordinals[oid] = next_ordinal
            next_ordinal += 1
    new_sectors = {}

    def leaf(sid, scale, frame, lower, side, units, depth):
        bounds = None
        if lower is not None:
            bounds = [min(lower[a], *(u[2][a] for u in units)) for a in range(3)] + [
                max(lower[a] + side, *(u[2][a] for u in units)) for a in range(3)]
            if any(not math.isfinite(v) or abs(v) > MAX_BOUND_LY for v in bounds):
                raise ValueError('sector bounds exceed R-tree coordinate range')
        ids = sorted(oid for _, members, _ in units for oid in members)
        digest = hashlib.sha256(_canonical([SCHEMA_VERSION, coordinate_contract(), sid, bounds]).encode())
        for oid in ids:
            digest.update(b'\n')
            digest.update((changes[oid][1] if oid in changes else region[oid][1]).encode())
        revision = digest.hexdigest()
        row = db.execute('INSERT INTO sectors VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                         (sid, scale, frame, *(bounds or [None] * 6), len(ids), len(units), depth, revision))
        if bounds is not None:
            db.execute('INSERT INTO sector_bounds VALUES (?,?,?,?,?,?,?)',
                       (row.lastrowid, bounds[0], bounds[3], bounds[1], bounds[4], bounds[2], bounds[5]))
        new_sectors[sid] = revision
        for oid in ids:
            obj = final[oid]
            root = resolved[oid]
            if oid in changes:
                payload = changes[oid][1]
                search = '\n'.join(str(obj.get(f) or '') for f in
                                   ('name', 'latin', 'description', 'facts', 'mythology', 'history')).lower()
                ordinal = region[oid][2] if oid in region else new_ordinals[oid]
                db.execute('''INSERT INTO objects VALUES (?,?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET sector_id=excluded.sector_id,
                    root_id=excluded.root_id,payload=excluded.payload,kind=excluded.kind,
                    scale=excluded.scale,search_blob=excluded.search_blob''',
                           (oid, sid, root, payload, ordinal, obj['kind'], obj['scale'], search))
                db.execute('INSERT OR REPLACE INTO object_links VALUES (?,?)', (oid, obj.get('parent')))
            elif region[oid][3] != root or db.execute('SELECT sector_id FROM objects WHERE id=?', (oid,)).fetchone()[0] != sid:
                db.execute('UPDATE objects SET sector_id=?,root_id=? WHERE id=?', (sid, root, oid))

    def partition(sid, scale, frame, lower, side, units, depth):
        n = sum(len(u[1]) for u in units)
        if lower is None or n <= meta['max_objects'] or len(units) == 1 or depth >= meta['max_depth']:
            leaf(sid, scale, frame, lower, side, units, depth)
            return
        half = side / 2
        middle = [v + half for v in lower]
        children = {}
        for unit in units:
            octant = sum((unit[2][a] >= middle[a]) << a for a in range(3))
            children.setdefault(octant, []).append(unit)
        for octant, child in sorted(children.items()):
            child_lower = [lower[a] + (half if octant & (1 << a) else 0) for a in range(3)]
            partition(f'{sid}/{octant}', scale, frame, child_lower, half, child, depth + 1)

    for (sid, scale, frame), units in sorted(groups.items()):
        lower = None if frame in ('system', 'unlocated') else [
            int(v) * meta['cell_size_ly'] for v in sid.split(':')[2:]]
        partition(sid, scale, frame, lower, meta['cell_size_ly'], units, 0)
    return old_sectors, new_sectors
