/** Bounded snapshot cards. Never promote coordinates/1 to simulation positions. */
export class SnapshotChanged extends Error {}
export class SectorStore {
  constructor({ fetcher = (...args) => fetch(...args), maxBytes = 4 * 1024 * 1024, maxObjects = 4096 } = {}) {
    this.fetcher = fetcher;
    this.maxBytes = maxBytes;
    this.maxObjects = maxObjects;
    this.snapshot = null;
    this.entries = new Map();
    this.bytes = 0;
  }
  clear() { this.entries.clear(); this.bytes = 0; this.snapshot = null; }
  async json(path, signal) {
    const response = await this.fetcher(path, { signal });
    if (response.status === 409) { this.clear(); throw new SnapshotChanged('Каталог обновлён'); }
    if (!response.ok) throw new Error(`Каталог: HTTP ${response.status}`);
    return { data: await response.json(), response };
  }
  async locate(id, signal) {
    const suffix = this.snapshot ? `?snapshot=${encodeURIComponent(this.snapshot)}` : '';
    const { data } = await this.json(`/api/spatial/v1/objects/${encodeURIComponent(id)}/sector${suffix}`, signal);
    if (this.snapshot && this.snapshot !== data.snapshot) { this.clear(); throw new SnapshotChanged(); }
    this.snapshot = data.snapshot;
    return data;
  }
  async load(sid, signal) {
    const cached = this.entries.get(sid);
    const rows = [];
    const pages = [];
    let after = null;
    let bytes = 0;
    do {
      const params = new URLSearchParams({ limit: '512' });
      if (after !== null) params.set('after', after);
      if (this.snapshot) params.set('snapshot', this.snapshot);
      const old = cached?.pages[pages.length];
      const response = await this.fetcher(`/api/spatial/v1/sectors/${encodeURIComponent(sid)}?${params}`, {
        signal, headers: old ? { 'If-None-Match': old.etag } : {},
      });
      if (response.status === 409) { this.clear(); throw new SnapshotChanged('Каталог обновлён'); }
      if (!response.ok && response.status !== 304) throw new Error(`Сектор: HTTP ${response.status}`);
      const snapshot = response.headers.get('X-Catalog-Snapshot');
      if (!snapshot || (this.snapshot && this.snapshot !== snapshot)) { this.clear(); throw new SnapshotChanged(); }
      this.snapshot = snapshot;
      if (response.status === 304 && !old) throw new Error('304 без сохранённой страницы');
      const text = response.status === 304 ? old.text : await response.text();
      const data = JSON.parse(text);
      bytes += text.length * 2 + 256;
      if (data.version !== 'spatial/1') throw new Error('Неподдерживаемый контракт сектора');
      if (data.objects.length === 0 && data.next_after !== null) throw new Error('Пустая страница с продолжением');
      if (bytes > this.maxBytes || rows.length + data.objects.length > this.maxObjects) throw new Error('Сектор превышает лимит клиента');
      rows.push(...data.objects);
      pages.push({ text, etag: response.headers.get('etag') });
      if (data.next_after !== null && (after !== null && data.next_after <= after)) throw new Error('Неверное продолжение сектора');
      after = data.next_after;
    } while (after !== null);
    // Cache serialized pages only; decoded cards belong to the active request.
    if (cached) { this.entries.delete(sid); this.bytes -= cached.bytes; }
    while (this.entries.size && this.bytes + bytes > this.maxBytes) {
      const key = this.entries.keys().next().value;
      this.bytes -= this.entries.get(key).bytes;
      this.entries.delete(key);
    }
    this.entries.set(sid, { pages, bytes }); this.bytes += bytes;
    return rows;
  }
  async object(id, signal) {
    for (let attempt = 0; attempt < 2; attempt++) {
      try {
        const located = await this.locate(id, signal);
        const rows = await this.load(located.sector.id, signal);
        const card = rows.find(row => row.object.id === id);
        if (!card) throw new Error('Объект отсутствует в указанном секторе');
        return card;
      } catch (error) {
        if (!(error instanceof SnapshotChanged) || attempt === 1) throw error;
      }
    }
  }
}
