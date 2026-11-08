import { readFileSync } from 'node:fs';
import { expect, test } from 'vitest';
import { readBinaryCatalog } from '../src/data/readBinaryCatalog.js';

const fixture = JSON.parse(readFileSync('../tests/fixtures/binary_catalog.json', 'utf8'));
const binary = version => Uint8Array.from(Buffer.from(fixture[version], 'base64')).buffer;
const mutate = edit => { const buffer = binary('v2'); edit(new DataView(buffer), buffer); return buffer; };

test('Python encoder and JS reader agree on both versions and Unicode strings', () => {
  const v1 = readBinaryCatalog(binary('v1')), v2 = readBinaryCatalog(binary('v2'));
  expect(v1.count).toBe(3); expect(v2.count).toBe(3);
  expect([...v1.positions]).toEqual([...v2.positions]);
  expect(v2.objects.map(o => o.id)).toEqual(fixture.objects.map(o => o.id));
  expect(v2.objects.map(o => o.name)).toEqual(fixture.objects.map(o => o.name));
  expect(v2.objects[0].color).toBe('#aabbcc');
  expect(v2.objects[1].color).toBe('#11223344');
  expect(v2.objects[1].parent).toBe('host');
  expect(v2.objects[1].period_days).toBe(365);
  expect(v2.objects[2].has_jet).toBe(true);
  expect(v2.objects[2].latin).toBeUndefined();
});

test('headers, versions, table offsets, alignment and section sizes are validated', () => {
  for (const bytes of [new ArrayBuffer(0), new ArrayBuffer(7), binary('v1').slice(0, 8),
    binary('v2').slice(0, 8), binary('v2').slice(0, 24), binary('v1').slice(0, -1)])
    expect(() => readBinaryCatalog(bytes)).toThrow();
  const badMagic = binary('v2'); new DataView(badMagic).setUint32(0, 0);
  expect(() => readBinaryCatalog(badMagic)).toThrow(/magic/);
  const version = binary('v2'); new DataView(version).setUint32(4, 99, true);
  expect(() => readBinaryCatalog(version)).toThrow(/version/);
  const offset = binary('v1'); new DataView(offset).setBigUint64(12, 0n, true);
  expect(() => readBinaryCatalog(offset)).toThrow(/offset/);
  for (const edit of [
    v => v.setUint32(16, 0, true), v => v.setUint32(12, 0, true),
    v => v.setBigUint64(20, 0n, true), v => v.setBigUint64(20, 100000n, true),
    v => v.setBigUint64(20, 173n, true),
    v => v.setBigUint64(28, v.getBigUint64(20, true) - 4n, true),
    v => v.setBigUint64(28, v.getBigUint64(20, true), true),
    v => v.setUint32(8, 10000, true),
  ]) expect(() => readBinaryCatalog(mutate(edit))).toThrow();
});

test('invalid parent indices and string ranges fail instead of yielding broken scene objects', () => {
  for (const parent of [-2, 3, 10000]) {
    const buffer = binary('v2'), parsed = readBinaryCatalog(buffer);
    new DataView(buffer).setInt32(parsed.sectionOffsets.parents, parent, true);
    expect(() => readBinaryCatalog(buffer)).toThrow(/parent/i);
  }
  const buffer = binary('v2'), parsed = readBinaryCatalog(buffer);
  new DataView(buffer).setUint32(parsed.sectionOffsets.id_lengths, 100000, true);
  expect(() => readBinaryCatalog(buffer)).toThrow(/range/);
});

test('overlapping string references take the safe fallback without corrupting UTF-8', () => {
  const buffer = binary('v2'), parsed = readBinaryCatalog(buffer), view = new DataView(buffer);
  const nameOffset = view.getUint32(parsed.sectionOffsets.name_offsets, true);
  const nameLength = view.getUint32(parsed.sectionOffsets.name_lengths, true);
  view.setUint32(parsed.sectionOffsets.latin_offsets, nameOffset, true);
  view.setUint32(parsed.sectionOffsets.latin_lengths, nameLength, true);
  expect(readBinaryCatalog(buffer).objects[0].latin).toBe('Звезда 🌟');
});

test('empty catalog decodes without assuming a first string', () => {
  const buffer = binary('v2'); new DataView(buffer).setUint32(8, 0, true);
  expect(readBinaryCatalog(buffer).objects).toEqual([]);
});
