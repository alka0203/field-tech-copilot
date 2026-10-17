// Thin fetch layer: timeouts, cancel, plain error objects. Mock mode via ?mock=1.
import { extForMime } from './audio.js';

const params = new URLSearchParams(location.search);
export const MOCK = params.has('mock');
export const FAKE_MIC = params.has('fakemic');
export const TIMEOUT_MS = 60000;

export class ApiError extends Error {
  // kind: 'http' | 'network' | 'timeout' | 'abort' | 'offline' | 'badresponse'
  constructor(kind, { status = 0, detail = '', path = '' } = {}) {
    super(`${kind} ${status} ${path}`);
    this.kind = kind; this.status = status; this.detail = detail; this.path = path;
  }
}

let mock = null;
async function getMock() { return mock || (mock = await import('./mock.js')); }

export async function request(path, { method = 'GET', json, form, signal, timeoutMs = TIMEOUT_MS } = {}) {
  if (MOCK) return (await getMock()).handle(path, { method, json, form, signal });
  if (navigator.onLine === false) throw new ApiError('offline', { path });

  const ctrl = new AbortController();
  let timedOut = false;
  const onAbort = () => ctrl.abort();
  if (signal) { if (signal.aborted) throw new ApiError('abort', { path }); signal.addEventListener('abort', onAbort, { once: true }); }
  const timer = setTimeout(() => { timedOut = true; ctrl.abort(); }, timeoutMs);

  try {
    const init = { method, signal: ctrl.signal, headers: { Accept: 'application/json' } };
    if (json !== undefined) { init.body = JSON.stringify(json); init.headers['Content-Type'] = 'application/json'; }
    if (form) init.body = form;
    let res;
    try { res = await fetch(path, init); }
    catch (e) {
      if (timedOut) throw new ApiError('timeout', { path });
      if (e && e.name === 'AbortError') throw new ApiError('abort', { path });
      throw new ApiError('network', { path });
    }
    let body = null;
    try { body = await res.json(); } catch { /* non-JSON body */ }
    if (!res.ok) {
      let detail = '';
      if (body && typeof body.detail === 'string') detail = body.detail;
      throw new ApiError('http', { status: res.status, detail, path });
    }
    if (body === null) throw new ApiError('badresponse', { status: res.status, path });
    return body;
  } finally {
    clearTimeout(timer);
    if (signal) signal.removeEventListener('abort', onAbort);
  }
}

const imgForm = (file) => { const f = new FormData(); f.append('image', file, file.name || 'photo.jpg'); return f; };

export const api = {
  health: (signal) => request('/health', { signal, timeoutMs: 6000 }),
  speechHealth: (signal) => request('/speech/health', { signal, timeoutMs: 6000 }),
  query: (body, signal) => request('/query', { method: 'POST', json: body, signal }),
  queryImage: (file, signal) => request('/query/image', { method: 'POST', form: imgForm(file), signal }),
  visionQuality: (file, signal) => request('/vision/quality', { method: 'POST', form: imgForm(file), signal, timeoutMs: 15000 }),
  queryVoice: (blob, mimeType, signal) => {
    const f = new FormData();
    f.append('audio', blob, `voice.${extForMime(mimeType)}`);
    return request('/query/voice', { method: 'POST', form: f, signal });
  },
};

/** Downscale big camera photos before upload (slow roof LTE). Falls back to the original file. */
export async function prepareImage(file, maxEdge = 2048) {
  try {
    if (!file.type.startsWith('image/') || typeof createImageBitmap !== 'function') return file;
    const bmp = await createImageBitmap(file);
    const scale = Math.min(1, maxEdge / Math.max(bmp.width, bmp.height));
    if (scale >= 1 && file.size < 3 * 1024 * 1024) { bmp.close && bmp.close(); return file; }
    const w = Math.round(bmp.width * scale), hgt = Math.round(bmp.height * scale);
    const c = document.createElement('canvas'); c.width = w; c.height = hgt;
    c.getContext('2d').drawImage(bmp, 0, 0, w, hgt);
    bmp.close && bmp.close();
    const blob = await new Promise((res) => c.toBlob(res, 'image/jpeg', 0.9));
    if (!blob || blob.size >= file.size) return file;
    return new File([blob], (file.name || 'photo').replace(/\.\w+$/, '') + '.jpg', { type: 'image/jpeg' });
  } catch { return file; }
}

/** Map any failure to plain language. `ctx` is 'query' | 'image' | 'quality' | 'voice'. */
export function describeError(e, ctx) {
  if (!(e instanceof ApiError)) return { title: 'Something went wrong', body: 'An unexpected error occurred in the app. Try again, or use Type.', retry: true };
  switch (e.kind) {
    case 'offline': return { title: 'You are offline', body: 'No connection. Lookups need the server. Check signal (try stepping outside or near a window) and retry. Recent lookups below still open.', retry: true };
    case 'network': return { title: 'Cannot reach the server', body: 'The request did not get through. Check your signal or Wi-Fi and try again.', retry: true };
    case 'timeout': return { title: 'Taking too long', body: 'No answer after 60 seconds. The connection may be weak or the server busy. Try again.', retry: true };
    case 'badresponse': return { title: 'Unexpected reply', body: 'The server sent something this app could not read. Try again.', retry: true };
    case 'abort': return { title: 'Cancelled', body: '', retry: false };
  }
  const s = e.status;
  // A bare "Not Found" comes from the static file server = this endpoint is not deployed (yet), not "no data".
  if (s === 405 && ctx !== 'query') {
    return { title: ctx === 'voice' ? 'Voice mode unavailable on the server' : 'Not available on this server', body: 'This server does not offer that feature yet. Use Type instead.', retry: false, fallbackType: true };
  }
  if (s === 404 && ctx !== 'query' && (ctx === 'voice' || ctx === 'quality' || e.detail === 'Not Found' || !e.detail)) {
    return { title: ctx === 'voice' ? 'Voice mode unavailable on the server' : 'Not available on this server', body: 'This server does not offer that feature. Use Type instead.', retry: false, fallbackType: true };
  }
  if (s === 404 || (s >= 500 && ctx !== 'voice' && /no relevant context|no context found/i.test(e.detail || ''))) return { nodata: true, title: 'No data for this in the indexed manuals', body: '', detail: e.detail };
  if (s === 422) {
    if (ctx === 'image') return { title: 'Could not read the photo', body: 'I could not find a brand or error code in that photo. Get closer, avoid glare, fill the frame with the nameplate or display, or use Type.', retry: false, fallbackType: true, detail: e.detail };
    if (ctx === 'voice') return { title: 'Could not use that recording', body: 'The recording could not be processed. Speak the brand, model and code clearly, or use Type.', retry: false, fallbackType: true, detail: e.detail };
    return { title: 'Missing information', body: 'Enter at least a brand or an error code.', retry: false, detail: e.detail };
  }
  if (s === 503) {
    if (ctx === 'image') return { title: 'Image mode unavailable on the server', body: 'The server has no vision key configured, so photos cannot be read. Use Type or Voice instead.', retry: false, fallbackType: true };
    if (ctx === 'voice') return { title: 'Voice mode unavailable on the server', body: 'The speech service is not ready. Use Type instead, or try again in a minute.', retry: true, fallbackType: true };
    return { title: 'The answer service is busy', body: 'The AI service is temporarily unavailable. Wait a moment and try again, or check the manual directly.', retry: true };
  }
  if (s === 413) return { title: 'File too large', body: 'That file is too big to upload. Take a new photo or a shorter recording.', retry: false };
  if (s === 429) return { title: 'Too many requests', body: 'The service is rate-limited right now. Wait a minute and try again.', retry: true };
  if (s >= 500) return { title: 'Server error', body: 'The server hit a problem building the answer. Try again; if it keeps failing, use the manual.', retry: true, detail: e.detail };
  return { title: 'Request failed', body: `The server answered with status ${s}. Try again.`, retry: true, detail: e.detail };
}
