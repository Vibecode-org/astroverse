"""Bounded-memory JSON -> SQLite builder. Graph, partitions and strings live on disk.

Publishes the same schema/revisions/binary bytes as the reference list builder.
Atomic full publication; this is not a concurrent live incremental writer.
"""
from contextlib import closing
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import tempfile

import ijson

from data.catalog import validate_catalog
from data.coordinates import coordinate_contract, snapshot_coordinates
from data.sectors import SCHEMA_SQL, SCHEMA_VERSION, MAX_BOUND_LY, physical_position, _canonical
from data.streaming_binary import write_representations


BUILDER_VERSION = 'streaming/1'


def iter_catalog(source):
    with Path(source).open('rb') as stream:
        # ijson.items('item') alone accepts a top-level object as an empty list.
        while byte := stream.read(1):
            if byte not in b' \r\n\t':
                break
        if byte != b'[':
            raise ValueError('catalog must be a JSON array')
        stream.seek(0)
        try:
            for obj in ijson.items(stream,'item',use_float=True):
                if isinstance(obj,dict) and obj.get('ra') == 24 and not isinstance(obj.get('ra'),bool):
                    obj['ra'] = 0.0
                # Validate local fields using the existing contract. Graph checks
                # are separate SQL operations after all objects have arrived.
                local = dict(obj) if isinstance(obj,dict) else obj
                if isinstance(local,dict):
                    local.pop('parent',None)
                validate_catalog([local])
                if obj.get('parent') is not None and (not isinstance(obj['parent'],str) or obj['parent']==obj['id']):
                    raise ValueError('invalid parent')
                snapshot_coordinates(obj)
                yield obj
        except ijson.JSONError as exc:
            raise ValueError('invalid catalog JSON') from exc


def build_streaming_index(path, source, *, cell_size_ly=32.0, max_objects=4096,
                          max_depth=16, source_signature=None, objects=None, previous_path=None, parent_revision=None):
    if (isinstance(cell_size_ly,bool) or not isinstance(cell_size_ly,(int,float))
            or not math.isfinite(cell_size_ly) or not 0<cell_size_ly<=MAX_BOUND_LY
            or type(max_objects) is not int or max_objects<1
            or type(max_depth) is not int or not 0<=max_depth<=32
            or cell_size_ly/(1<<max_depth)==0):
        raise ValueError('invalid partition configuration')
    cell_size_ly = float(cell_size_ly)
    path = Path(path)
    source = Path(source) if source is not None else None
    if source is not None and path.resolve()==source.resolve():
        raise ValueError('source and destination must differ')
    with tempfile.TemporaryDirectory(dir=path.parent,prefix=f'.{path.name}.') as tmp:
        temporary = Path(tmp)/'index.sqlite'
        with closing(sqlite3.connect(temporary)) as db:
            db.executescript(SCHEMA_SQL)
            # Bound page caches and use disk-backed temporary sort/graph tables.
            db.executescript('''PRAGMA cache_size=-8192; PRAGMA temp_store=FILE;
                CREATE TABLE input (id TEXT PRIMARY KEY, payload TEXT, ordinal INTEGER UNIQUE,
                                    parent TEXT, scale TEXT, kind TEXT, root TEXT);
                CREATE INDEX input_parent ON input(parent);
                CREATE INDEX input_root ON input(root,id);
                CREATE TABLE families (root TEXT PRIMARY KEY,sid TEXT,scale TEXT,frame TEXT,
                                       x REAL,y REAL,z REAL,n INTEGER);
                CREATE INDEX family_sector ON families(sid);
            ''')
            digest = hashlib.sha256(_canonical([SCHEMA_VERSION,coordinate_contract(),
                                               cell_size_ly,max_objects,max_depth]).encode())
            reused_sectors = 0
            if previous_path is not None:
                previous_uri = Path(previous_path).resolve().as_uri() + '?mode=ro'
                db.execute('ATTACH DATABASE ? AS previous', (previous_uri,))
            count = 0
            try:
                for ordinal,obj in enumerate(iter_catalog(source) if objects is None else objects):
                    payload = _canonical(obj)
                    digest.update(payload.encode()); digest.update(b'\n')
                    db.execute('INSERT INTO input VALUES (?,?,?,?,?,?,NULL)',
                               (obj['id'],payload,ordinal,obj.get('parent'),obj['scale'],obj['kind']))
                    count += 1
            except sqlite3.IntegrityError as exc:
                raise ValueError('duplicate catalog ID') from exc
            if db.execute('SELECT 1 FROM input i LEFT JOIN input p ON p.id=i.parent WHERE i.parent IS NOT NULL AND p.id IS NULL LIMIT 1').fetchone():
                raise ValueError('unknown parent')
            db.execute('''WITH RECURSIVE tree(id,root) AS (
                SELECT id,id FROM input WHERE parent IS NULL
                UNION ALL SELECT i.id,t.root FROM input i JOIN tree t ON i.parent=t.id
            ) UPDATE input SET root=(SELECT root FROM tree WHERE tree.id=input.id)''')
            if db.execute('SELECT 1 FROM input WHERE root IS NULL LIMIT 1').fetchone():
                raise ValueError('parent cycle')
            if db.execute('SELECT 1 FROM input i JOIN input r ON r.id=i.root WHERE i.scale<>r.scale LIMIT 1').fetchone():
                raise ValueError('cross-scale parent family')
            roots = db.execute('''SELECT r.id,r.payload,count(*) FROM input r JOIN input i ON i.root=r.id
                                  WHERE r.parent IS NULL GROUP BY r.id''')
            for root,payload,n in roots:
                obj = json.loads(payload); scale = obj['scale']
                position = physical_position(obj) if scale!='solar' else None
                if scale=='solar':
                    sid,frame,xyz = 'solar:system','system',[None]*3
                elif position is None:
                    sid,frame,xyz = f'{scale}:unlocated','unlocated',[None]*3
                else:
                    frame,*xyz = position
                    ratios = [v/cell_size_ly for v in xyz]
                    if any(not math.isfinite(v) or abs(v)>2**52 for v in ratios):
                        raise ValueError('cell_size_ly too small for coordinates')
                    sid = f'{scale}:{frame}:'+':'.join(str(math.floor(v)) for v in ratios)
                db.execute('INSERT INTO families VALUES (?,?,?,?,?,?,?,?)',(root,sid,scale,frame,*xyz,n))

            def leaf(sid,scale,frame,lower,side,depth,n,systems):
                bounds = None
                if lower is not None:
                    extremes = db.execute('SELECT min(x),min(y),min(z),max(x),max(y),max(z) FROM families WHERE sid=?',(sid,)).fetchone()
                    bounds = [min(lower[a],extremes[a]) for a in range(3)] + [max(lower[a]+side,extremes[a+3]) for a in range(3)]
                    if any(not math.isfinite(v) or abs(v)>MAX_BOUND_LY for v in bounds):
                        raise ValueError('sector bounds exceed R-tree coordinate range')
                sector_digest = hashlib.sha256(_canonical([SCHEMA_VERSION,coordinate_contract(),sid,bounds]).encode())
                query = 'SELECT i.* FROM families f JOIN input i ON i.root=f.root WHERE f.sid=? ORDER BY i.id'
                for row in db.execute(query,(sid,)):
                    sector_digest.update(b'\n'); sector_digest.update(row[1].encode())
                inserted = db.execute('INSERT INTO sectors VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                                     (sid,scale,frame,*(bounds or [None]*6),n,systems,depth,sector_digest.hexdigest()))
                if bounds is not None:
                    db.execute('INSERT INTO sector_bounds VALUES (?,?,?,?,?,?,?)',
                               (inserted.lastrowid,bounds[0],bounds[3],bounds[1],bounds[4],bounds[2],bounds[5]))
                nonlocal reused_sectors
                if previous_path is not None:
                    old = db.execute('SELECT revision FROM previous.sectors WHERE id=?',(sid,)).fetchone()
                    if old and old[0] == sector_digest.hexdigest():
                        db.execute('''INSERT INTO objects SELECT p.id,p.sector_id,p.root_id,p.payload,
                            i.ordinal,p.kind,p.scale,p.search_blob FROM previous.objects p
                            JOIN input i ON i.id=p.id WHERE p.sector_id=?''',(sid,))
                        reused_sectors += 1
                        return
                for oid,payload,ordinal,parent,scale,kind,root in db.execute(query,(sid,)):
                    obj = json.loads(payload)
                    search = '\n'.join(str(obj.get(f) or '') for f in ('name','latin','description','facts','mythology','history')).lower()
                    db.execute('INSERT INTO objects VALUES (?,?,?,?,?,?,?,?)',(oid,sid,root,payload,ordinal,kind,scale,search))

            def partition(sid,scale,frame,lower,side,depth):
                n,systems = db.execute('SELECT sum(n),count(*) FROM families WHERE sid=?',(sid,)).fetchone()
                if lower is None or n<=max_objects or systems==1 or depth>=max_depth:
                    leaf(sid,scale,frame,lower,side,depth,n,systems)
                    return
                half = side/2
                middle = [v+half for v in lower]
                db.execute('''UPDATE families SET sid=sid||'/'||((x>=?)+2*(y>=?)+4*(z>=?)) WHERE sid=?''',(*middle,sid))
                for octant in range(8):
                    child = f'{sid}/{octant}'
                    if db.execute('SELECT 1 FROM families WHERE sid=? LIMIT 1',(child,)).fetchone():
                        partition(child,scale,frame,[lower[a]+(half if octant&(1<<a) else 0) for a in range(3)],half,depth+1)

            # Materialize only cell IDs in an SQL cursor, never a Python list.
            # An independent table avoids invalidating iteration during splits.
            db.execute('CREATE TABLE cells AS SELECT DISTINCT sid,scale,frame FROM families')
            for sid,scale,frame in db.execute('SELECT * FROM cells ORDER BY sid'):
                lower = None if frame in ('system','unlocated') else [int(v)*cell_size_ly for v in sid.split(':')[2:]]
                partition(sid,scale,frame,lower,cell_size_ly,0)
            write_representations(db)
            metadata = {'schema_version':SCHEMA_VERSION,'unit':'ly','cell_size_ly':cell_size_ly,
                        'max_objects':max_objects,'max_depth':max_depth,'object_count':count,
                        'catalog_revision':digest.hexdigest(),'coordinates':coordinate_contract(),
                        'source_signature':source_signature,'builder':BUILDER_VERSION,'reused_sectors':reused_sectors}
            if parent_revision is not None:
                metadata['parent_revision'] = parent_revision
            db.executemany('INSERT INTO metadata VALUES (?,?)',((k,json.dumps(v)) for k,v in metadata.items()))
            db.executescript('DROP TABLE cells; DROP TABLE families; DROP TABLE input;')
            db.commit()
            if previous_path is not None:
                db.execute('DETACH DATABASE previous')
            db.execute('VACUUM')
        temporary.replace(path)
    return metadata
