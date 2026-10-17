// Fake media devices. Used by tests/audio.test.mjs and by the browser when the
// page is opened with ?mock=1&fakemic=1 (so the real VoiceRecorder code path --
// timer, level meter, 20 s auto-stop, Blob assembly -- can be exercised without a mic).

export function makeFakeEnv({ timers, supported = ['audio/webm;codecs=opus'], denyWith } = {}) {
  let clock = 0;
  const fakeNow = () => clock;

  class FakeTrack { constructor() { this.stopped = false; } stop() { this.stopped = true; } }
  class FakeStream { constructor() { this.tracks = [new FakeTrack()]; } getTracks() { return this.tracks; } }

  class FakeMediaRecorder {
    static isTypeSupported(t) { return supported.includes(t); }
    constructor(stream, opts = {}) { this.stream = stream; this.mimeType = opts.mimeType || ''; this.state = 'inactive'; FakeMediaRecorder.last = this; }
    start() { this.state = 'recording'; this._n = 0; }
    stop() {
      if (this.state === 'inactive') return;
      this.state = 'inactive';
      if (this.ondataavailable) this.ondataavailable({ data: new Blob([new Uint8Array(2048)], { type: this.mimeType || 'audio/webm' }) });
      setTimeout(() => this.onstop && this.onstop(), 0);
    }
  }

  class FakeAnalyser {
    constructor() { this.fftSize = 1024; }
    connect() {}
    getByteTimeDomainData(buf) {
      const amp = 8 + 26 * Math.abs(Math.sin(clock / 220));
      for (let i = 0; i < buf.length; i++) buf[i] = 128 + Math.round(amp * Math.sin(i / 5));
    }
  }
  class FakeAudioContext {
    constructor() { this.closed = false; }
    resume() {}
    createMediaStreamSource() { return { connect() {} }; }
    createAnalyser() { return new FakeAnalyser(); }
    close() { this.closed = true; }
  }

  const mediaDevices = {
    getUserMedia: async () => {
      if (denyWith) { const e = new Error('denied'); e.name = denyWith; throw e; }
      return new FakeStream();
    },
  };

  const env = {
    mediaDevices, MediaRecorder: FakeMediaRecorder, AudioContext: FakeAudioContext, now: fakeNow,
  };
  if (timers) {
    // deterministic timers for tests
    env.setInterval = (f) => { timers.fn = f; return 1; };
    env.clearInterval = () => { timers.fn = null; };
  } else {
    // browser: real timers, but a clock driven by wall time
    const t0 = (globalThis.performance || Date).now();
    env.now = () => (globalThis.performance || Date).now() - t0;
    clock = 0;
    const real = globalThis.setInterval;
    env.setInterval = (f, ms) => real(() => { clock = env.now(); f(); }, ms);
    env.clearInterval = (id) => globalThis.clearInterval(id);
  }
  env.advance = (ms) => { clock += ms; };
  env.FakeMediaRecorder = FakeMediaRecorder;
  return env;
}
