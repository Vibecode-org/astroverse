/** Bounded snapshot cards. Never promote coordinates/1 to simulation positions. */
export class SnapshotChanged extends Error {}
export class SectorStore {
  constructor({ fetcher = (...args) => fetch(...args), maxBytes = 4 * 1024 * 1024, maxObjects = 4096 } = {}) {
    this.fetcher = fetcher;
    this.maxBytes = maxBytes;
    this.maxObjects = maxObjects;
    this.generation = 0;
    this.snapshot = null;
    this.entries = new Map();
    this.bytes = 0;
  }
  clear() { this.generation++; this.entries.clear(); this.bytes = 0; this.snapshot = null; }
  check(signal, generation) {
    if (signal?.aborted) throw new DOMException('cancelled', 'AbortError');
    if (generation !== this.generation) throw new SnapshotChanged('Каталог обновлён');
  }
  async json(path, signal, generation = this.generation) {
    this.check(signal, generation);
    const response = await this.fetcher(path, { signal });
    this.check(signal, generation);
    if (response.status === 409) { this.clear(); throw new SnapshotChanged('Каталог обновлён'); }
    if (!response.ok) throw new Error(`Каталог: HTTP ${response.status}`);
    const data = await response.json();
    this.check(signal, generation);
    return { data, response };
  }
  async locate(id, signal) {
    const generation = this.generation;
    const suffix = this.snapshot ? `?snapshot=${encodeURIComponent(this.snapshot)}` : '';
    const { data } = await this.json(`/api/spatial/v1/objects/${encodeURIComponent(id)}/sector${suffix}`, signal, generation);
    this.check(signal, generation);
    if (this.snapshot && this.snapshot !== data.snapshot) { this.clear(); throw new SnapshotChanged(); }
    this.snapshot = data.snapshot;
    return data;
  }
  async load(sid, signal) {
    const generation = this.generation;
    this.check(signal, generation);
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
      this.check(signal, generation);
      if (response.status === 409) { this.clear(); throw new SnapshotChanged('Каталог обновлён'); }
      if (!response.ok && response.status !== 304) throw new Error(`Сектор: HTTP ${response.status}`);
      const snapshot = response.headers.get('X-Catalog-Snapshot');
      if (!snapshot || (this.snapshot && this.snapshot !== snapshot)) { this.clear(); throw new SnapshotChanged(); }
      this.snapshot = snapshot;
      if (response.status === 304 && !old) throw new Error('304 без сохранённой страницы');
      const text = response.status === 304 ? old.text : await response.text();
      this.check(signal, generation);
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
    const current = this.entries.get(sid);
    if (current) { this.entries.delete(sid); this.bytes -= current.bytes; }
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
        const generation = this.generation;
        const located = await this.locate(id, signal);
        this.check(signal, generation);
        // Cards may belong to arbitrarily large families. Retain one bounded
        // page, not the whole family or a growing serialized-page cache.
        let after = null;
        do {
          const params = new URLSearchParams({limit:String(Math.min(512, this.maxObjects)), snapshot:this.snapshot});
          if (after !== null) params.set('after', after);
          const response = await this.fetcher(`/api/spatial/v1/sectors/${encodeURIComponent(located.sector.id)}?${params}`, {signal});
          this.check(signal, generation);
          if (response.status === 409) { this.clear(); throw new SnapshotChanged('Каталог обновлён'); }
          if (!response.ok) throw new Error(`Сектор: HTTP ${response.status}`);
          if (response.headers.get('X-Catalog-Snapshot') !== this.snapshot) { this.clear(); throw new SnapshotChanged(); }
          const text = await response.text();
          this.check(signal, generation);
          if (text.length * 2 + 256 > this.maxBytes) throw new Error('Страница превышает лимит клиента');
          const data = JSON.parse(text);
          if (data.version !== 'spatial/1' || !Array.isArray(data.objects)
              || data.objects.length > Math.min(512, this.maxObjects)) throw new Error('Некорректная страница сектора');
          if (data.next_after !== null && (typeof data.next_after !== 'string'
              || !data.objects.length || after !== null && data.next_after <= after)) throw new Error('Неверное продолжение сектора');
          const card = data.objects.find(row => row.object.id === id);
          if (card) return card;
          after = data.next_after;
        } while (after !== null);
        throw new Error('Объект отсутствует в указанном секторе');
      } catch (error) {
        if (!(error instanceof SnapshotChanged) || attempt === 1) throw error;
      }
    }
  }
}
