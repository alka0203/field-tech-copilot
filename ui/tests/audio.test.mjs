// Run: node --experimental-default-type=module --test ui/tests/audio.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { pickMimeType, extForMime, rmsLevel, formatElapsed, micSupport, micErrorMessage, VoiceRecorder, MAX_MS } from '../js/audio.js';
import { makeFakeEnv } from '../js/fakes.js';

test('pickMimeType prefers webm/opus, falls back to mp4 (Safari), else empty', () => {
  assert.equal(pickMimeType({ isTypeSupported: () => true }), 'audio/webm;codecs=opus');
  assert.equal(pickMimeType({ isTypeSupported: (t) => t === 'audio/mp4' }), 'audio/mp4');
  assert.equal(pickMimeType({ isTypeSupported: () => false }), '');
  assert.equal(pickMimeType({ isTypeSupported: () => { throw new Error('x'); } }), '');
  assert.equal(pickMimeType(undefined === 1 ? null : { }), '');
  assert.equal(pickMimeType(null), '');
});

test('extForMime', () => {
  assert.equal(extForMime('audio/webm;codecs=opus'), 'webm');
  assert.equal(extForMime('audio/mp4'), 'm4a');
  assert.equal(extForMime('audio/ogg;codecs=opus'), 'ogg');
  assert.equal(extForMime(''), 'webm');
});

test('rmsLevel: silence 0, loud clipped to 1, empty safe', () => {
  assert.equal(rmsLevel(new Uint8Array(512).fill(128)), 0);
  assert.equal(rmsLevel(Uint8Array.from({ length: 512 }, (_, i) => (i % 2 ? 255 : 0))), 1);
  assert.equal(rmsLevel(new Uint8Array(0)), 0);
  const mid = rmsLevel(Uint8Array.from({ length: 512 }, (_, i) => 128 + (i % 2 ? 10 : -10)));
  assert.ok(mid > 0 && mid < 1);
});

test('formatElapsed', () => {
  assert.equal(formatElapsed(0), '0:00');
  assert.equal(formatElapsed(7400), '0:07');
  assert.equal(formatElapsed(20000), '0:20');
  assert.equal(formatElapsed(65000), '1:05');
  assert.equal(formatElapsed(-5), '0:00');
});

test('micSupport: insecure context, no mediaDevices, no MediaRecorder, ok', () => {
  assert.equal(micSupport({ isSecureContext: false, navigator: {} }).reason, 'insecure');
  assert.match(micSupport({ isSecureContext: false, navigator: {} }).message, /https or localhost/);
  assert.equal(micSupport({ isSecureContext: true, navigator: {} }).reason, 'nomedia');
  assert.equal(micSupport({ isSecureContext: true, navigator: { mediaDevices: { getUserMedia() {} } } }).reason, 'norecorder');
  assert.equal(micSupport({ isSecureContext: true, MediaRecorder: class {}, navigator: { mediaDevices: { getUserMedia() {} } } }).ok, true);
});

test('micErrorMessage maps DOMException names', () => {
  assert.equal(micErrorMessage({ name: 'NotAllowedError' }).reason, 'denied');
  assert.equal(micErrorMessage({ name: 'NotFoundError' }).reason, 'nomic');
  assert.equal(micErrorMessage({ name: 'NotReadableError' }).reason, 'busy');
  assert.equal(micErrorMessage(new Error('?')).reason, 'unknown');
});

test('recorder: ticks, level meter, manual stop yields blob and releases device', async () => {
  const timers = {};
  const env = makeFakeEnv({ timers });
  const ticks = [];
  const rec = new VoiceRecorder({ env, onTick: (ms, lvl) => ticks.push([ms, lvl]) });
  await rec.start();
  assert.equal(rec.active, true);
  assert.equal(rec.mimeType, 'audio/webm;codecs=opus');
  for (let i = 0; i < 20; i++) { env.advance(100); timers.fn(); }
  assert.equal(ticks.length, 20);
  assert.ok(ticks.some(([, l]) => l > 0), 'meter saw signal');
  const res = await rec.stop();
  assert.equal(res.tooShort, false);
  assert.ok(res.blob.size > 0);
  assert.equal(res.durationMs, 2000);
  assert.equal(rec.active, false);
  assert.equal(timers.fn, null, 'interval cleared');
});

test('recorder: tooShort flag for accidental taps', async () => {
  const timers = {}; const env = makeFakeEnv({ timers });
  const rec = new VoiceRecorder({ env });
  await rec.start(); env.advance(200); timers.fn();
  assert.equal((await rec.stop()).tooShort, true);
});

test('recorder: auto-stops at 20 s exactly once and reports auto', async () => {
  const timers = {}; const env = makeFakeEnv({ timers });
  let auto = null, n = 0;
  const rec = new VoiceRecorder({ env, onAutoStop: (r) => { auto = r; n++; } });
  await rec.start();
  env.advance(MAX_MS - 100); timers.fn();
  assert.equal(auto, null);
  env.advance(150); timers.fn();
  timers.fn && timers.fn(); // a late extra tick must not double-stop
  await new Promise((r) => setTimeout(r, 20));
  assert.equal(n, 1);
  assert.equal(auto.auto, true);
  assert.ok(auto.durationMs >= MAX_MS && auto.durationMs <= MAX_MS + 500);
  assert.equal(rec.active, false);
});

test('recorder: stop is idempotent; cancel releases the mic without a result', async () => {
  const timers = {}; const env = makeFakeEnv({ timers });
  const rec = new VoiceRecorder({ env });
  await rec.start(); env.advance(1000);
  const [a, b] = await Promise.all([rec.stop(), rec.stop()]);
  assert.strictEqual(a, b);

  const t2 = {}; const env2 = makeFakeEnv({ timers: t2 });
  const rec2 = new VoiceRecorder({ env: env2 });
  await rec2.start();
  const stream = rec2._stream;
  rec2.cancel();
  assert.equal(rec2.active, false);
  assert.ok(stream.tracks.every((t) => t.stopped));
});

test('recorder: permission denied surfaces the DOMException name', async () => {
  const env = makeFakeEnv({ timers: {}, denyWith: 'NotAllowedError' });
  const rec = new VoiceRecorder({ env });
  await assert.rejects(rec.start(), (e) => e.name === 'NotAllowedError');
  assert.equal(rec.active, false);
});

test('recorder: Safari path picks audio/mp4 and still works without AudioContext (no meter)', async () => {
  const timers = {};
  const env = makeFakeEnv({ timers, supported: ['audio/mp4'] });
  env.AudioContext = undefined;
  const rec = new VoiceRecorder({ env, onTick: () => {} });
  await rec.start();
  assert.equal(rec.mimeType, 'audio/mp4');
  env.advance(1500); timers.fn();
  const r = await rec.stop();
  assert.equal(r.mimeType, 'audio/mp4');
});
