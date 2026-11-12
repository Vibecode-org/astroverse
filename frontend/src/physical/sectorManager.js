import { verifiedRows, yieldPhysicalWork } from './coordinates.js';

export const frameReadyAt = new WeakMap();

export class PositionRevisionChanged extends Error {
  constructor() { super('Ревизия положений изменилась; повторите запрос'); }
}
export const S100K_LIMITS = Object.freeze({objects:200000, sectorObjects:1000, serialized:64*1024*1024, decoded:512*1024*1024, response:1024*1024});
export const SECTOR_LIMITS = Object.freeze({ concurrency:4, queue:128, objects:4096, sectorObjects:128,
  serialized:4*1024*1024, decoded:32*1024*1024, response:256*1024,
  timeout:10000, retries:1, backoff:100 });
const abortError = () => new DOMException('cancelled', 'AbortError');
const fail = message => { throw new Error(message); };
const emptyCost = () => ({objects:0, serialized:0, decoded:0});
const fields = ['reference_system','origin','unit','time_scale','corrections','representation','axes','position_type'];
const validId = id => typeof id === 'string' && id.length > 0 && id.length <= 512;
const clientIdentity = () => {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  // getRandomValues also works for an HTTP LAN origin without randomUUID.
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
  const hex = Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('');
  return [hex.slice(0,8),hex.slice(8,12),hex.slice(12,16),hex.slice(16,20),hex.slice(20)].join('-');
};
// Allowance for UTF-16 strings, property/array slots, parsed hierarchy and its
// Float64/Map copies (including the scene). Engine dependent; NOT a browser RSS cap.
export const decodedEstimate = bytes => bytes * 8 + 4096;

function validate(body, milliseconds) {
  verifiedRows(body);
  if (typeof body.revision !== 'string' || !body.revision || body.revision.length > 256
      || body.coordinates.revision !== body.revision) fail('Некорректная ревизия положений');
  if (Date.parse(body.evaluated_at) !== milliseconds) fail('Эфемерида относится к другому моменту');
  if (body.registry_revision !== undefined && (typeof body.registry_revision !== 'string'
      || !body.registry_revision || body.registry_revision.length > 256)) fail('Некорректная ревизия реестра');
  const ids = new Set(), targets = new Set();
  for (const row of body.objects) {
    if (!validId(row.id) || ids.has(row.id)) fail('Дубликат или неверный ID физического тела');
    ids.add(row.id);
    if (row.status === 'unknown' ? row.position !== null : row.status !== 'computed'
        || !Array.isArray(row.position) || row.position.length !== 3 || !row.position.every(Number.isFinite)) fail('Некорректное положение тела');
    if (row.target != null) {
      const identity = JSON.stringify([row.model_id ?? null, row.target]);
      if (targets.has(identity)) fail('Дубликат идентичности физического тела');
      targets.add(identity);
    }
  }
}

function combine(manifest, bodies, milliseconds) {
  if (bodies.length === 1) return bodies[0]; // Keep the compatible single-sector wire shape.
  const frame = {...manifest, objects:bodies.flatMap(body => body.objects)};
  delete frame.sector;
  if (bodies.some(body => body.hierarchy)) {
    if (bodies.some(body => !body.hierarchy)) fail('Несовместимая физическая иерархия');
    frame.hierarchy = {...bodies[0].hierarchy};
    for (const key of ['sectors','systems','bodies']) {
      const rows = new Map();
      for (const body of bodies) for (const row of body.hierarchy[key]) {
        if (rows.has(row.id) && JSON.stringify(rows.get(row.id)) !== JSON.stringify(row)) fail('Конфликт физических адресов');
        rows.set(row.id, row);
      }
      frame.hierarchy[key] = [...rows.values()];
    }
  }
  validate(frame, milliseconds); // Global IDs, source identities and parent closure.
  return frame;
}

// Sector payloads have already passed bounded contract/time validation. Global
// identity closure and array assembly are staged, never published piecemeal.
async function combineLarge(manifest,bodies,check,onSlice) {
  if(bodies.some(b=>b.hierarchy)) throw new Error('Large hierarchy exceeds decoder budget');
  const objects=[],ids=new Set(),targets=new Set();
  for(const body of bodies) for(let offset=0;offset<body.objects.length;){
    await yieldPhysicalWork();check();
    const start=performance.now();let count=0;
    while(offset<body.objects.length && count++<500 && performance.now()-start<2){
      const row=body.objects[offset++];
      if(ids.has(row.id))fail('Дубликат или неверный ID физического тела');ids.add(row.id);
      if(row.target!=null){const identity=JSON.stringify([row.model_id??null,row.target]);
        if(targets.has(identity))fail('Дубликат идентичности физического тела');targets.add(identity);}
      objects.push(row);
    }
    onSlice(performance.now()-start);
  }
  check();const frame={...manifest,objects};delete frame.sector;return frame;
}

/** One atomic selection, bounded workers and no partial scene publication.
 * The caller coalesces continuous clock ticks. Explicit contexts evict the old
 * set; only continuous work in the SAME context can retain it while loading.
 * No persistent cache: identical in-flight calls share work, replacements evict.
 */
export class PhysicalSectorManager {
  constructor({fetcher=(...args)=>fetch(...args), limits={}, root='/api/positions/v1/', onRequest=null}={}) {
    this.fetcher = fetcher; this.limits = {...SECTOR_LIMITS, ...limits}; this.root = root;
    this.onRequest = onRequest; // Optional diagnostic sink; no retained event history.
    for (const [key,value] of Object.entries(this.limits)) {
      if (!Number.isSafeInteger(value) || value < (key === 'retries' ? 0 : 1)) fail('Invalid sector budget');
    }
    if (this.limits.retries > 1 || this.limits.concurrency > 128 || this.limits.queue > 128
        || this.limits.objects > 200000 || this.limits.sectorObjects > 1000) fail('Invalid sector budget');
    this.generation = 0; this.resident = null; this.current = null;
    // Transport correlation only; never a source identity or a physical phase.
    this.clientId = clientIdentity();
    this.metrics = {requests:0, active:0, peakActive:0, responseBytes:0, retries:0,
      conflicts:0, evictions:0, peakQueue:0, peakPending:0, peakObjects:0, peakSerialized:0, peakDecoded:0};
  }
  cancel() {
    this.generation++;
    if (this.current) { this.current.controller.abort(); this.draining = this.current.promise.then(() => {}, () => {}); }
    this.current = null;
    if (this.resident) this.metrics.evictions++;
    this.resident = null;
  }
  inspect() {
    const state = this.current, result = {...this.metrics, clientId:this.clientId, generation:this.generation,
      queue:state?.queue || 0, pending:state?.pending || 0, residentObjects:this.resident?.cost.objects || 0};
    for (const key of ['objects','serialized','decoded']) {
      result[key] = (this.resident?.cost[key] || 0) + (state?.cost[key] || 0) + (state?.reserved[key] || 0);
    }
    return result;
  }
  admit(state, addition) {
    this.check(state);
    const current = this.inspect();
    for (const key of ['objects','serialized','decoded']) {
      if (current[key] + (addition[key] || 0) > this.limits[key]) {
        const error = new Error('Превышен бюджет физических секторов: '+key);
        error.permanent = true; throw error;
      }
    }
  }
  account(state) {
    this.check(state);
    const metrics = this.inspect();
    for (const key of ['queue','pending','objects','serialized','decoded']) {
      const peak = 'peak'+key[0].toUpperCase()+key.slice(1);
      this.metrics[peak] = Math.max(this.metrics[peak], metrics[key]);
      if (key !== 'pending' && metrics[key] > this.limits[key]) fail('Превышен бюджет физических секторов: '+key);
    }
  }
  check(state, attemptSignal) {
    if (state.controller.signal.aborted || state.generation !== this.generation || attemptSignal?.aborted) throw abortError();
  }
  load({milliseconds, neighborhood=null, anchor='earth', signal, context='', retainPrevious=false}={}) {
    context = JSON.stringify([context, neighborhood, anchor]);
    const key = JSON.stringify([milliseconds, neighborhood, anchor, context]);
    if (this.current?.key === key && this.current.signal === signal && !signal?.aborted) return this.current.promise;
    const previous = this.current;
    const drained = previous?.promise.then(() => {}, () => {}) || this.draining;
    previous?.controller.abort();
    if (!retainPrevious || this.resident?.context !== context) {
      if (this.resident) this.metrics.evictions++;
      this.resident = null;
    }
    const state = {key, context, signal, milliseconds, generation:++this.generation,
      controller:new AbortController(), cost:emptyCost(), reserved:emptyCost(), pending:0, queue:0};
    this.current = state;
    const abort = () => state.controller.abort();
    signal?.addEventListener('abort', abort, {once:true});
    if (signal?.aborted) abort();
    // Drain aborted workers before admitting the next selection, so context
    // churn cannot temporarily exceed the manager's transport concurrency.
    const select = () => { this.check(state); return this.select(state, neighborhood, anchor); };
    state.promise = (drained ? drained.then(select) : this.select(state, neighborhood, anchor)).finally(() => {
      signal?.removeEventListener('abort', abort);
      if (this.current === state) this.current = null;
    });
    return state.promise;
  }
  async request(state, url, attemptSignal, reservedObjects=0) {
    const {limits} = this;
    for (let retry=0; ; retry++) {
      this.check(state, attemptSignal);
      // Reserve before reading/decoding: all active responses and staged/old
      // frames count. Unused allowance is returned after the response is parsed.
      const reserve = {objects:reservedObjects, serialized:limits.response, decoded:decodedEstimate(limits.response)};
      this.admit(state, reserve);
      for (const key of Object.keys(reserve)) state.reserved[key] += reserve[key];
      let controller, timer, stop, headers, outcome='error', retryDelay=limits.backoff * 2**retry;
      const started = performance.now();
      try {
        this.account(state);
        controller = new AbortController();
        const stopped = new Promise((_,reject) => {
          stop = () => { controller.abort(); reject(abortError()); };
          state.controller.signal.addEventListener('abort', stop, {once:true});
          attemptSignal.addEventListener('abort', stop, {once:true});
        });
        const timeout = new Promise((_,reject) => {
          timer = setTimeout(() => { controller.abort(); reject(new Error('Timeout физических секторов')); }, limits.timeout);
        });
        this.metrics.requests++; this.metrics.active++;
        this.metrics.peakActive = Math.max(this.metrics.peakActive, this.metrics.active);
        let result;
        try {
          headers = {'X-Astroverse-Client':this.clientId,
            'X-Astroverse-Selection':`${this.clientId}.${state.generation}.${state.attempt}`,
            'X-Astroverse-Request':`${this.clientId}.${this.metrics.requests}`};
          result = await Promise.race([this.read(url, controller.signal, headers), stopped, timeout]);
        } finally { this.metrics.active--; }
        this.check(state, attemptSignal);
        const {body,bytes,status,ok} = result;
        // Kept outside the payload: tracing cannot change positions or ETags.
        outcome = status === 409 ? 'conflict' : ok ? 'ok' : 'http_error';
        this.metrics.responseBytes += bytes;
        if (status === 409) throw new PositionRevisionChanged();
        if (!ok) {
          const error = new Error(body?.detail?.message || `Эфемериды: HTTP ${status}`);
          error.transient = [502,503,504].includes(status);
          const raw = result.retryAfter;
          const delay = /^\d+$/.test(raw || '') ? Number(raw)*1000 : Date.parse(raw)-Date.now();
          if (error.transient && Number.isFinite(delay)) retryDelay=Math.max(retryDelay,Math.min(2000,delay));
          error.permanent = [400,401,403,404,413,422].includes(status); throw error;
        }
        if (!body) fail('Некорректный ответ сервера эфемерид');
        if (body.objects?.length > this.limits.sectorObjects) fail('Превышен размер физического сектора');
        const validationStart=performance.now();
        validate(body, state.milliseconds);
        this.onPhase?.({kind:"validation_cpu",ms:performance.now()-validationStart});
        if (body.objects.length > this.limits.sectorObjects) fail('Превышен размер физического сектора');
        // Transfer the reservation to decoded residency without double counting.
        this.admit(state, {objects:body.objects.length-reserve.objects,
          serialized:bytes-reserve.serialized, decoded:decodedEstimate(bytes)-reserve.decoded});
        state.cost.objects += body.objects.length;
        state.cost.serialized += bytes;
        state.cost.decoded += decodedEstimate(bytes);
        return body;
      } catch (error) {
        if (error.message === 'Timeout физических секторов') outcome='timeout';
        else if (state.controller.signal.aborted || attemptSignal.aborted || state.generation !== this.generation || error.name === 'AbortError') outcome='cancelled';
        else if (outcome === 'ok') outcome='invalid';
        this.check(state, attemptSignal);
        // Only transient gateway/unavailability or a native fetch network error.
        // Timeout is terminal; the next continuous selection can recover.
        if (!(error.transient || error.network) || retry >= limits.retries) throw error;
        this.metrics.retries++;
      } finally {
        controller?.abort(); clearTimeout(timer);
        state.controller.signal.removeEventListener('abort', stop);
        attemptSignal.removeEventListener('abort', stop);
        for (const key of Object.keys(reserve)) state.reserved[key] -= reserve[key];
        if (headers) this.onRequest?.({request:headers['X-Astroverse-Request'],
          selection:headers['X-Astroverse-Selection'],outcome,ms:performance.now()-started});
      }
      await new Promise((resolve,reject) => {
        const cleanup = () => {
          state.controller.signal.removeEventListener('abort', stop); attemptSignal.removeEventListener('abort', stop);
        };
        const stop = () => { clearTimeout(timer); cleanup(); reject(abortError()); };
        const timer = setTimeout(() => {cleanup();resolve();}, retryDelay);
        state.controller.signal.addEventListener('abort', stop, {once:true});
        attemptSignal.addEventListener('abort', stop, {once:true});
      });
    }
  }
  async read(url, signal, headers) {
    let response;
    try { response = await this.fetcher(url, {signal, headers}); }
    catch (error) { if (error instanceof TypeError) error.network = true; throw error; }
    if (signal.aborted) throw abortError();
    if (response.status === 409) { await response.body?.cancel(); return {status:409, bytes:0}; }
    let body, bytes;
    if (response.body?.getReader) {
      const reader = response.body.getReader(), chunks = []; bytes = 0;
      try {
        for (;;) {
          const part = await reader.read();
          if (signal.aborted) throw abortError();
          if (part.done) break;
          bytes += part.value.byteLength;
          if (bytes > this.limits.response) fail('Превышен размер ответа сектора');
          chunks.push(part.value);
        }
      } finally { await reader.cancel(); }
      const buffer = new Uint8Array(bytes); let offset = 0;
      for (const chunk of chunks) { buffer.set(chunk, offset); offset += chunk.length; }
      const decodeStart=performance.now();
      try { body = JSON.parse(new TextDecoder().decode(buffer)); } catch { body = null; }
      this.onPhase?.({kind:'decode_cpu',ms:performance.now()-decodeStart});
    } else {
      // Compatibility with injected test fetchers, native HTTP uses bounded reads.
      body = await response.json().catch(() => null);
      bytes = new TextEncoder().encode(JSON.stringify(body)).length;
    }
    if (bytes > this.limits.response) fail('Превышен размер ответа сектора');
    return {body, bytes, status:response.status, ok:response.ok, retryAfter:response.headers?.get?.('Retry-After')};
  }
  async select(state, neighborhood, anchor) {
    const params = new URLSearchParams({at:new Date(state.milliseconds).toISOString(), anchor});
    const area = neighborhood || {offset:[0,0,0], radius:1e13};
    ['dx','dy','dz'].forEach((key,a) => params.set(key, String(area.offset[a])));
    if(area.origin)['ox','oy','oz'].forEach((key,a)=>params.set(key,String(area.origin[a])));
    params.set('radius', String(area.radius));
    try {
      for (let attempt=0; attempt<2; attempt++) {
        state.attempt = attempt;
        const controller = new AbortController();
        try {
          const manifest = await this.request(state, this.root+'nearby?'+params, controller.signal);
          this.account(state);
          if (manifest.sectors === undefined && !neighborhood) return this.publish(state, manifest);
          if (!Array.isArray(manifest.sectors) || manifest.sectors.length > this.limits.queue
              || manifest.objects.length !== 0) fail('Некорректный manifest положений / очередь');
          if (manifest.sectors.length > 1 && !manifest.registry_revision) fail('Нет ревизии реестра многосекторной выборки');
          const ids = new Set();
          for (const sector of manifest.sectors) {
            if (!validId(sector.id) || ids.has(sector.id)) fail('Некорректный ID сектора');
            ids.add(sector.id);
            if (sector.revision !== manifest.revision) throw new PositionRevisionChanged();
          }
          // Known counts allow rejection before any sector work. Without counts,
          // each bounded response is admitted before becoming staging residency.
          if (manifest.sectors.every(s => Number.isSafeInteger(s.object_count) && s.object_count >= 0 && s.object_count <= this.limits.sectorObjects))
            this.admit(state, {objects:manifest.sectors.reduce((n,s)=>n+s.object_count,0)});
          const bodies = new Array(manifest.sectors.length); let next = 0, failure;
          state.queue = bodies.length; this.account(state);
          const worker = async () => {
            try {
              while (next < bodies.length) {
                this.check(state, controller.signal);
                const index = next++, sector = manifest.sectors[index]; state.queue--;
                const query = new URLSearchParams({at:params.get('at'), revision:manifest.revision});
                const body = await this.request(state, this.root+'sectors/'+encodeURIComponent(sector.id)+'?'+query, controller.signal, Number.isSafeInteger(sector.object_count) && sector.object_count >= 0 && sector.object_count <= this.limits.sectorObjects ? sector.object_count : 0);
                if (body.revision !== manifest.revision || body.registry_revision !== manifest.registry_revision) throw new PositionRevisionChanged();
                if (body.sector !== sector.id || body.jd_tdb !== manifest.jd_tdb
                    || body.evaluated_at !== manifest.evaluated_at
                    || fields.some(key => body.coordinates[key] !== manifest.coordinates[key])) fail('Несогласованный сектор или момент положений');
                bodies[index] = body; state.pending++; this.account(state);
              }
            } catch (error) { if (!failure) failure = error; controller.abort(); }
          };
          await Promise.all(Array.from({length:Math.min(this.limits.concurrency,bodies.length)}, worker));
          if (failure) throw failure;
          this.check(state);
          // Reserve combined arrays/identity maps while old and staging coexist.
          this.admit(state, {decoded:state.cost.objects * 512});
          state.cost.decoded += state.cost.objects * 512; this.account(state);
          const mergeStart=performance.now();
          const large=state.cost.objects>4096;
          const frame = large ? await combineLarge(manifest,bodies,()=>this.check(state),
            ms=>this.onPhase?.({kind:'merge_slice_cpu',ms})) : combine(manifest, bodies, state.milliseconds);
          this.onPhase?.({kind:large?"merge_elapsed":"merge_cpu",ms:performance.now()-mergeStart});
          return this.publish(state, frame);
        } catch (error) {
          controller.abort(); state.cost = emptyCost(); state.pending = 0; state.queue = 0;
          this.check(state);
          if (!(error instanceof PositionRevisionChanged) || attempt === 1) throw error;
          this.metrics.conflicts++;
        }
      }
    } catch (error) {
      if (this.current === state) { if (this.resident) this.metrics.evictions++; this.resident = null; }
      throw error;
    }
  }
  publish(state, frame) {
    this.check(state); this.account(state);
    if (this.resident) this.metrics.evictions++;
    this.resident = {cost:{...state.cost}, context:state.context};
    state.cost = emptyCost(); state.pending = 0; state.queue = 0;
    frameReadyAt.set(frame, performance.now());
    return frame;
  }
}
