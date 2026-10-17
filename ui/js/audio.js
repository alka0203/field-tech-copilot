// Audio capture pipeline: mime selection, level meter, timer, 20 s auto-stop.
// Dependency-injectable (env) so it can be unit-tested in Node and driven by
// fake devices in the browser (?mock=1&fakemic=1).

export const MAX_MS = 20000;
export const MIN_MS = 600;

const CANDIDATES = [
  'audio/webm;codecs=opus',
  'audio/webm',
  'audio/mp4',            // Safari / iOS
  'audio/mp4;codecs=mp4a.40.2',
  'audio/ogg;codecs=opus',
  'audio/mpeg',
];

export function pickMimeType(MR = globalThis.MediaRecorder) {
  if (!MR || typeof MR.isTypeSupported !== 'function') return '';
  for (const t of CANDIDATES) {
    try { if (MR.isTypeSupported(t)) return t; } catch { /* keep looking */ }
  }
  return '';
}

export function extForMime(mime) {
  const m = String(mime || '').toLowerCase();
  if (m.includes('webm')) return 'webm';
  if (m.includes('mp4') || m.includes('m4a') || m.includes('aac')) return 'm4a';
  if (m.includes('ogg')) return 'ogg';
  if (m.includes('mpeg') || m.includes('mp3')) return 'mp3';
  if (m.includes('wav')) return 'wav';
  return 'webm';
}

/** RMS of an 8-bit time-domain buffer (centre 128) scaled to a friendly 0..1 meter value. */
export function rmsLevel(bytes) {
  if (!bytes || !bytes.length) return 0;
  let sum = 0;
  for (let i = 0; i < bytes.length; i++) {
    const v = (bytes[i] - 128) / 128;
    sum += v * v;
  }
  const rms = Math.sqrt(sum / bytes.length);
  return Math.min(1, rms * 3.5); // speech RMS is small; boost so the bar is useful
}

export function formatElapsed(ms) {
  const s = Math.floor(Math.max(0, ms) / 1000);
  return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
}

export function micSupport(g = globalThis) {
  if (g.isSecureContext === false) {
    return { ok: false, reason: 'insecure', message: 'The microphone only works on https or localhost. This page was opened over plain http, so the browser blocks it. Use Type or Photo, or open the https address.' };
  }
  if (!g.navigator || !g.navigator.mediaDevices || typeof g.navigator.mediaDevices.getUserMedia !== 'function') {
    return { ok: false, reason: 'nomedia', message: 'This browser cannot access a microphone. Use Type or Photo instead.' };
  }
  if (!g.MediaRecorder) {
    return { ok: false, reason: 'norecorder', message: 'This browser cannot record audio. Update it, or use Type or Photo.' };
  }
  return { ok: true };
}

export function micErrorMessage(err) {
  const n = err && err.name;
  if (n === 'NotAllowedError' || n === 'SecurityError' || n === 'PermissionDeniedError') {
    return { reason: 'denied', message: 'Microphone is blocked. Allow the microphone for this site in the browser settings, then tap Voice again. You can still use Type or Photo.' };
  }
  if (n === 'NotFoundError' || n === 'DevicesNotFoundError' || n === 'OverconstrainedError') {
    return { reason: 'nomic', message: 'No microphone was found on this device. Use Type or Photo instead.' };
  }
  if (n === 'NotReadableError' || n === 'AbortError' || n === 'TrackStartError') {
    return { reason: 'busy', message: 'The microphone is in use by another app. Close it and try again, or use Type.' };
  }
  return { reason: 'unknown', message: 'Could not start the microphone. Use Type or Photo instead.' };
}

function defaultEnv() {
  const g = globalThis;
  return {
    mediaDevices: g.navigator && g.navigator.mediaDevices,
    MediaRecorder: g.MediaRecorder,
    AudioContext: g.AudioContext || g.webkitAudioContext,
    setInterval: (f, ms) => g.setInterval(f, ms),
    clearInterval: (id) => g.clearInterval(id),
    now: () => (g.performance ? g.performance.now() : Date.now()),
  };
}

export class VoiceRecorder {
  constructor(opts = {}) {
    this.maxMs = opts.maxMs ?? MAX_MS;
    this.onTick = opts.onTick || (() => {});
    this.onAutoStop = opts.onAutoStop || (() => {});
    this.env = { ...defaultEnv(), ...(opts.env || {}) };
    this.active = false;
    this._chunks = [];
  }

  get elapsedMs() { return this.active ? this.env.now() - this._t0 : 0; }

  async start() {
    if (this.active) return;
    const env = this.env;
    const stream = await env.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    this._stream = stream;
    const mime = pickMimeType(env.MediaRecorder);
    try {
      this._mr = mime ? new env.MediaRecorder(stream, { mimeType: mime }) : new env.MediaRecorder(stream);
    } catch (e) {
      this._releaseDevice();
      throw e;
    }
    this.mimeType = this._mr.mimeType || mime || 'audio/webm';
    this._chunks = [];
    this._cancelled = false;
    this._stopP = null;
    this._mr.ondataavailable = (ev) => { if (ev.data && ev.data.size > 0) this._chunks.push(ev.data); };

    this._analyser = null;
    try {
      if (env.AudioContext) {
        this._ctx = new env.AudioContext();
        if (this._ctx.resume) this._ctx.resume();
        const src = this._ctx.createMediaStreamSource(stream);
        this._analyser = this._ctx.createAnalyser();
        this._analyser.fftSize = 1024;
        src.connect(this._analyser);
        this._buf = new Uint8Array(this._analyser.fftSize);
      }
    } catch { this._analyser = null; } // meter is a nicety; recording must still work

    this._t0 = env.now();
    this._mr.start(250);
    this.active = true;
    this._timer = env.setInterval(() => this._tick(), 60);
  }

  _tick() {
    if (!this.active) return;
    const elapsed = this.env.now() - this._t0;
    let level = 0;
    if (this._analyser) {
      try { this._analyser.getByteTimeDomainData(this._buf); level = rmsLevel(this._buf); } catch { /* ignore */ }
    }
    this.onTick(elapsed, level);
    if (elapsed >= this.maxMs && !this._stopP) {
      this.stop().then((r) => this.onAutoStop({ ...r, auto: true }));
    }
  }

  /** Stop and resolve with {blob, mimeType, durationMs}. Idempotent. */
  stop() {
    if (this._stopP) return this._stopP;
    if (!this.active) return Promise.resolve(null);
    const durationMs = this.env.now() - this._t0;
    this._stopP = new Promise((resolve) => {
      const finish = () => {
        this._releaseAll();
        const type = (this.mimeType || 'audio/webm');
        const blob = new Blob(this._chunks, { type });
        resolve({ blob, mimeType: type, durationMs: Math.min(durationMs, this.maxMs + 500), tooShort: durationMs < MIN_MS });
      };
      if (this._mr.state === 'inactive') { finish(); return; }
      this._mr.onstop = finish;
      try { this._mr.stop(); } catch { finish(); }
    });
    return this._stopP;
  }

  cancel() {
    if (!this.active) return;
    this._cancelled = true;
    try { this._mr.ondataavailable = null; this._mr.onstop = null; if (this._mr.state !== 'inactive') this._mr.stop(); } catch { /* ignore */ }
    this._releaseAll();
  }

  _releaseDevice() {
    if (this._stream) {
      for (const t of this._stream.getTracks()) { try { t.stop(); } catch { /* ignore */ } }
      this._stream = null;
    }
  }

  _releaseAll() {
    this.active = false;
    if (this._timer != null) { this.env.clearInterval(this._timer); this._timer = null; }
    this._releaseDevice();
    if (this._ctx) { try { this._ctx.close(); } catch { /* ignore */ } this._ctx = null; }
  }
}
