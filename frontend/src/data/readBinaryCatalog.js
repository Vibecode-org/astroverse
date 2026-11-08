/** Reader for the Astroverse binary catalog (v1 and v2).
 *
 * v1 (26 bytes/object) is kept for older clients: positions, sizes, colors,
 * kinds, flags and parent indices. v2 adds scale, physical radii, orbit and
 * temperature fields, plus a UTF-8 string table for id/name/latin. Both
 * versions are little-endian SoA; v2 section offsets are 4-byte aligned so the
 * typed arrays can be created directly on the fetched ArrayBuffer.
 *
 * The full specification lives in docs/BINARY_CATALOG.md.
 */

const MAGIC = "ASTV";
const VERSION_V1 = 1;
const VERSION_V2 = 2;
const V1_HEADER_SIZE = 4 + 4 + 4 + 8; // magic, version, count, offset
const V2_FIXED_HEADER_SIZE = 4 + 4 + 4 + 4 + 4; // + section table

const KIND_NAMES = [
  "star", "planet", "dwarf_planet", "moon", "asteroid", "comet",
  "black_hole", "exoplanet", "nebula", "cluster", "galaxy",
];

const SCALE_NAMES = ["solar", "local", "galaxy"];

const FLAG_HAS_JET = 0x02;

// Fixed section order. Keep in sync with data/catalog.py::BINARY_V2_SECTIONS.
const V2_SECTIONS = [
  "positions", "sizes", "colors", "kinds", "flags", "parents", "scales",
  "radius_km", "radius_earth", "au", "period_days", "temperature_k",
  "id_offsets", "id_lengths", "name_offsets", "name_lengths",
  "latin_offsets", "latin_lengths", "strings",
];

function colorFromUint32(value) {
  const r = (value >>> 24) & 0xff;
  const g = (value >>> 16) & 0xff;
  const b = (value >>> 8) & 0xff;
  const a = value & 0xff;
  if (a === 0xff) {
    return `#${r.toString(16).padStart(2, "0")}${g.toString(16).padStart(2, "0")}${b.toString(16).padStart(2, "0")}`;
  }
  return `#${r.toString(16).padStart(2, "0")}${g.toString(16).padStart(2, "0")}${b.toString(16).padStart(2, "0")}${a.toString(16).padStart(2, "0")}`;
}

function readHeader(bytes, view) {
  const magic = String.fromCharCode(bytes[0], bytes[1], bytes[2], bytes[3]);
  if (magic !== MAGIC) {
    throw new Error(`Invalid binary catalog magic: ${magic}`);
  }
  return view.getUint32(4, true);
}

function readV1(buffer) {
  if (buffer.byteLength < V1_HEADER_SIZE) throw new Error('Truncated v1 header');
  const view = new DataView(buffer);
  const count = view.getUint32(8, true);
  const offset = Number(view.getBigUint64(12, true));
  if (offset !== V1_HEADER_SIZE) {
    throw new Error(`Invalid array offset: ${offset}`);
  }
  if (buffer.byteLength !== V1_HEADER_SIZE + count * 26) {
    throw new Error('Invalid v1 catalog size');
  }

  let cursor = offset;
  const positions = new Float32Array(buffer, cursor, count * 3);
  cursor += count * 3 * 4;
  const sizes = new Float32Array(buffer, cursor, count);
  cursor += count * 4;
  const colors = new Uint32Array(buffer, cursor, count);
  cursor += count * 4;
  const kinds = new Uint8Array(buffer, cursor, count);
  cursor += count;
  const flags = new Uint8Array(buffer, cursor, count);
  cursor += count;
  // parentIndex may be unaligned; copy into a fresh aligned array.
  const parentIndices = new Int32Array(count);
  for (let i = 0; i < count; i++) {
    parentIndices[i] = view.getInt32(cursor + i * 4, true);
    if (parentIndices[i] < -1 || parentIndices[i] >= count) throw new Error('Invalid parent index');
  }

  const objects = new Array(count);
  for (let i = 0; i < count; i++) {
    const position = [positions[i * 3], positions[i * 3 + 1], positions[i * 3 + 2]];
    objects[i] = {
      _index: i,
      position,
      _binaryPosition: position,
      size: sizes[i],
      color: colorFromUint32(colors[i]),
      kind: KIND_NAMES[kinds[i]] || "star",
      flags: flags[i],
      parentIndex: parentIndices[i],
    };
  }

  return {
    version: VERSION_V1,
    count,
    positions,
    sizes,
    colors,
    kinds,
    flags,
    parentIndices,
    objects,
  };
}

/** Decode one string table with one `TextDecoder.decode` call per string.
 *  Kept as the fallback for unusual layouts (see `decodeTablesFast`). */
function decodeTable(decoder, bytes, offsets, lengths, out = new Array(offsets.length)) {
  for (let i = 0; i < offsets.length; i++) {
    const length = lengths[i];
    if (!length) {
      out[i] = "";
      continue;
    }
    const start = offsets[i];
    if (start + length > bytes.length) {
      throw new Error("Binary catalog string table offset out of range");
    }
    out[i] = decoder.decode(bytes.subarray(start, start + length));
  }
  return out;
}

/** Number of UTF-16 code units in `bytes[from, to)`.
 *  Continuation bytes (10xxxxxx) belong to the previous character; a 4-byte
 *  UTF-8 sequence becomes a surrogate pair, i.e. two code units. */
function countUnits(bytes, from, to) {
  let units = 0;
  for (let i = from; i < to; i++) {
    const byte = bytes[i];
    if ((byte & 0xc0) === 0x80) continue;
    units += (byte & 0xf8) === 0xf0 ? 2 : 1;
  }
  return units;
}

/** Decode id/name/latin tables with a single `TextDecoder` pass.
 *
 *  `TextDecoder.decode` has a fixed per-call cost: on the 100k catalog the
 *  naive path made 300k calls and spent ~135 ms. Decoding the whole string
 *  section once and slicing it by UTF-16 offsets is the same data, ~3x faster.
 *  Returns false (and leaves `out` arrays partially written) when the tables
 *  are not ascending, disjoint ranges or the bytes are not valid UTF-8, so the
 *  caller can fall back to `decodeTable`.
 */
function decodeTablesFast(bytes, decoder, tables) {
  const text = decoder.decode(bytes);
  const ordered = tables.slice().sort((a, b) => a.offsets[0] - b.offsets[0]);
  let byteCursor = 0;
  let unitCursor = 0;
  for (const { offsets, lengths, out } of ordered) {
    for (let i = 0; i < offsets.length; i++) {
      const start = offsets[i];
      const length = lengths[i];
      // Overlapping or unsorted ranges mean this is not the layout the
      // encoder produces; do not try to be clever about it.
      if (start < byteCursor) return false;
      unitCursor += countUnits(bytes, byteCursor, start);
      byteCursor = start;
      if (!length) {
        out[i] = "";
        continue;
      }
      const end = start + length;
      if (end > bytes.length) return false;
      const units = countUnits(bytes, byteCursor, end);
      out[i] = text.slice(unitCursor, unitCursor + units);
      unitCursor += units;
      byteCursor = end;
    }
  }
  // Invalid UTF-8 decodes to replacement characters and the offsets drift.
  unitCursor += countUnits(bytes, byteCursor, bytes.length);
  return unitCursor === text.length;
}

function readV2(buffer) {
  if (buffer.byteLength < V2_FIXED_HEADER_SIZE) throw new Error('Truncated v2 header');
  const bytes = new Uint8Array(buffer);
  const view = new DataView(buffer);
  const count = view.getUint32(8, true);
  const headerSize = view.getUint32(12, true);
  const sectionCount = view.getUint32(16, true);
  if (sectionCount !== V2_SECTIONS.length) {
    throw new Error(
      `Unsupported v2 section count: ${sectionCount} (expected ${V2_SECTIONS.length})`,
    );
  }
  const expectedHeader = V2_FIXED_HEADER_SIZE + 8 * sectionCount;
  if (headerSize !== expectedHeader || headerSize > buffer.byteLength) {
    throw new Error(`Invalid v2 header size: ${headerSize}`);
  }

  const offsets = new Array(sectionCount);
  for (let i = 0; i < sectionCount; i++) {
    offsets[i] = Number(view.getBigUint64(V2_FIXED_HEADER_SIZE + i * 8, true));
    if (offsets[i] < headerSize || offsets[i] > buffer.byteLength) {
      throw new Error(`Invalid v2 section offset for ${V2_SECTIONS[i]}`);
    }
    if (i < sectionCount - 1 && offsets[i] % 4 !== 0) {
      throw new Error(`Unaligned v2 section offset for ${V2_SECTIONS[i]}`);
    }
    if (i > 0 && offsets[i] < offsets[i - 1]) {
      throw new Error("v2 section offsets are not monotonic");
    }
  }
  const sectionOffset = (name) => offsets[V2_SECTIONS.indexOf(name)];
  const bytesPerObject = [12, 4, 4, 1, 1, 4, 1, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4];
  for (let i = 0; i < bytesPerObject.length; i++) {
    if (offsets[i] + count * bytesPerObject[i] > offsets[i + 1]) {
      throw new Error(`Truncated or overlapping v2 section ${V2_SECTIONS[i]}`);
    }
  }

  const positions = new Float32Array(buffer, sectionOffset("positions"), count * 3);
  const sizes = new Float32Array(buffer, sectionOffset("sizes"), count);
  const colors = new Uint32Array(buffer, sectionOffset("colors"), count);
  const kinds = new Uint8Array(buffer, sectionOffset("kinds"), count);
  const flags = new Uint8Array(buffer, sectionOffset("flags"), count);
  const parentIndices = new Int32Array(buffer, sectionOffset("parents"), count);
  const scales = new Uint8Array(buffer, sectionOffset("scales"), count);
  const radiusKm = new Float32Array(buffer, sectionOffset("radius_km"), count);
  const radiusEarth = new Float32Array(buffer, sectionOffset("radius_earth"), count);
  const au = new Float32Array(buffer, sectionOffset("au"), count);
  const periodDays = new Float32Array(buffer, sectionOffset("period_days"), count);
  const temperatureK = new Float32Array(buffer, sectionOffset("temperature_k"), count);
  const idOffsets = new Uint32Array(buffer, sectionOffset("id_offsets"), count);
  const idLengths = new Uint32Array(buffer, sectionOffset("id_lengths"), count);
  const nameOffsets = new Uint32Array(buffer, sectionOffset("name_offsets"), count);
  const nameLengths = new Uint32Array(buffer, sectionOffset("name_lengths"), count);
  const latinOffsets = new Uint32Array(buffer, sectionOffset("latin_offsets"), count);
  const latinLengths = new Uint32Array(buffer, sectionOffset("latin_lengths"), count);
  const strings = new Uint8Array(buffer, sectionOffset("strings"));

  const decoder = new TextDecoder("utf-8");
  const ids = new Array(count);
  const names = new Array(count);
  const latins = new Array(count);
  const fast = count > 0 && decodeTablesFast(strings, decoder, [
    { offsets: idOffsets, lengths: idLengths, out: ids },
    { offsets: nameOffsets, lengths: nameLengths, out: names },
    { offsets: latinOffsets, lengths: latinLengths, out: latins },
  ]);
  if (!fast) {
    decodeTable(decoder, strings, idOffsets, idLengths, ids);
    decodeTable(decoder, strings, nameOffsets, nameLengths, names);
    decodeTable(decoder, strings, latinOffsets, latinLengths, latins);
  }

  const objects = new Array(count);
  for (let i = 0; i < count; i++) {
    const position = [positions[i * 3], positions[i * 3 + 1], positions[i * 3 + 2]];
    const parentIndex = parentIndices[i];
    if (parentIndex < -1 || parentIndex >= count) throw new Error('Invalid parent index');
    objects[i] = {
      _index: i,
      id: ids[i],
      name: names[i],
      latin: latins[i] || undefined,
      kind: KIND_NAMES[kinds[i]] || "star",
      scale: SCALE_NAMES[scales[i]] || "local",
      color: colorFromUint32(colors[i]),
      parent: parentIndex >= 0 ? ids[parentIndex] : null,
      radius: sizes[i],
      radius_km: radiusKm[i] || undefined,
      radius_earth: radiusEarth[i] || undefined,
      au: au[i] || undefined,
      period_days: periodDays[i] || undefined,
      temperature_k: temperatureK[i] || undefined,
      has_jet: (flags[i] & FLAG_HAS_JET) !== 0,
      flags: flags[i],
      parentIndex,
      position,
      _binaryPosition: position,
    };
  }

  return {
    version: VERSION_V2,
    count,
    positions,
    sizes,
    colors,
    kinds,
    flags,
    parentIndices,
    scales,
    radiusKm,
    radiusEarth,
    au,
    periodDays,
    temperatureK,
    ids,
    names,
    latins,
    strings,
    sectionOffsets: Object.fromEntries(V2_SECTIONS.map((name, i) => [name, offsets[i]])),
    objects,
  };
}

export function readBinaryCatalog(buffer) {
  const bytes = new Uint8Array(buffer);
  if (bytes.length < 8) {
    throw new Error("Truncated binary catalog header");
  }
  const version = readHeader(bytes, new DataView(buffer));
  if (version === VERSION_V1) return readV1(buffer);
  if (version === VERSION_V2) return readV2(buffer);
  throw new Error(`Unsupported binary catalog version: ${version}`);
}
