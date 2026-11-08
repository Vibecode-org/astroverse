"""Byte-identical legacy encoders with disk string interning and section spools."""
from contextlib import ExitStack
import json
import struct
import tempfile

from data.catalog import (BINARY_MAGIC, BINARY_HEADER_FORMAT, BINARY_HEADER_SIZE,
                          BINARY_V2_SECTIONS, BINARY_V2_FIXED_HEADER_FORMAT,
                          BINARY_V2_FIXED_HEADER_SIZE, KIND_CODES, SCALE_CODES,
                          _render_position, _f32, _color_to_uint32)


def write_representations(db):
    count = db.execute('SELECT count(*) FROM input').fetchone()[0]
    db.execute('CREATE TABLE strings (text TEXT PRIMARY KEY, offset INTEGER, size INTEGER)')
    with ExitStack() as stack:
        sections = [stack.enter_context(tempfile.TemporaryFile()) for _ in BINARY_V2_SECTIONS]
        v1flags = stack.enter_context(tempfile.TemporaryFile())
        string_size = 0

        def intern(text):
            nonlocal string_size
            if not text:
                return 0, 0
            row = db.execute('SELECT offset,size FROM strings WHERE text=?', (text,)).fetchone()
            if row:
                return tuple(row)
            encoded = text.encode('utf-8')
            result = string_size, len(encoded)
            db.execute('INSERT INTO strings VALUES (?,?,?)', (text, *result))
            sections[-1].write(encoded)
            string_size += len(encoded)
            return result

        rows = db.execute('SELECT i.payload,p.ordinal FROM input i LEFT JOIN input p ON p.id=i.parent ORDER BY i.ordinal')
        for payload, parent in rows:
            obj = json.loads(payload)
            has_parent = int(obj.get('parent') is not None)
            values = [struct.pack('<3f', *_render_position(obj)), struct.pack('<f', _f32(obj.get('radius'))),
                      struct.pack('<I', _color_to_uint32(obj.get('color'))),
                      struct.pack('<B', KIND_CODES.get(obj['kind'],255)),
                      struct.pack('<B', has_parent | (2 if obj.get('has_jet') else 0)),
                      struct.pack('<i', parent if parent is not None else -1),
                      struct.pack('<B', SCALE_CODES.get(obj['scale'],255))]
            values.extend(struct.pack('<f',_f32(obj.get(field))) for field in
                          ('radius_km','radius_earth','au','period_days','temperature_k'))
            for field in ('id','name','latin'):
                values.extend(struct.pack('<I', value) for value in intern(obj.get(field) or ''))
            for section, value in zip(sections,values):
                section.write(value)
            v1flags.write(bytes([has_parent]))

        def publish(name, header, parts, padded):
            size = len(header) + sum(part.tell() + ((-part.tell()) % 4 if padded and i<len(parts)-1 else 0)
                                     for i,part in enumerate(parts))
            cursor = db.execute('INSERT INTO representations VALUES (?,zeroblob(?))',(name,size))
            with db.blobopen('representations','data',cursor.lastrowid) as blob:
                blob.write(header)
                for i,part in enumerate(parts):
                    length = part.tell()
                    part.seek(0)
                    while chunk := part.read(65536):
                        blob.write(chunk)
                    if padded and i<len(parts)-1:
                        blob.write(bytes((-length)%4))
                    part.seek(length)

        v1parts = [*sections[:4],v1flags,sections[5]]
        publish('v1',struct.pack(BINARY_HEADER_FORMAT,BINARY_MAGIC,1,count,BINARY_HEADER_SIZE),v1parts,False)
        n = len(sections)
        header_size = BINARY_V2_FIXED_HEADER_SIZE+8*n
        offset = header_size
        offsets = []
        for i,part in enumerate(sections):
            offsets.append(offset)
            offset += part.tell() + ((-part.tell())%4 if i<n-1 else 0)
        header = struct.pack(BINARY_V2_FIXED_HEADER_FORMAT,BINARY_MAGIC,2,count,header_size,n)
        header += struct.pack(f'<{n}Q',*offsets)
        publish('v2',header,sections,True)
    db.execute('DROP TABLE strings')
