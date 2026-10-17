// Canned backend for ?mock=1. Mirrors the contract in the task brief.
// Triggers (so every UI state can be reached):
//   Type:  Carrier/40MAQ/E1 = high | Daikin/FTXS/U4 = medium | Mitsubishi/MXZ/P8 = low + note
//          any other code = 404 | code SRV = 500 | code BUSY = 503 | model containing SLOW = 6 s delay
//   Photo: file name contains blur|dark -> quality warnings, nokey -> 503, unread -> 422, lowread -> low field confidence,
//          nodata -> read OK but 404; otherwise Carrier 40MAQ E1.
//   Voice: cycles: understood Daikin U4 -> not understood (result null) -> Mitsubishi P8 (low).
import { ApiError } from './api.js';

const DB = {
  'carrier|E1': {
    brand: 'carrier', model_family: '40MAQ', error_code: 'E1',
    fault_name: 'Indoor / outdoor units communication error',
    likely_causes: ['Wiring mistake between indoor and outdoor units', 'Indoor or outdoor PCB faulty', 'Loose or corroded communication connector', 'Noise on the communication line'],
    remedy_steps: ['Switch off power and check wiring between indoor and outdoor units against the wiring diagram', 'Inspect the communication connector for corrosion or looseness; reseat it', 'Measure voltage on the communication line; compare with the manual value', 'If wiring is correct, replace the indoor PCB, then the outdoor PCB if the fault persists'],
    source_reference: '38MAQ-01SM, section 7.2 Error code table', confidence: 'high', note: null,
  },
  'daikin|U4': {
    brand: 'daikin', model_family: 'FTXS', error_code: 'U4',
    fault_name: 'Transmission error between indoor and outdoor unit',
    likely_causes: ['Disconnected or broken transmission wiring', 'Indoor unit PCB failure', 'Outdoor unit PCB failure'],
    remedy_steps: ['Check the indoor to outdoor transmission wiring for breaks or loose terminals', 'Reset the breaker, wait 10 seconds, restore power and observe', 'Replace the failed PCB if the code returns'],
    source_reference: 'Simple Self-Diagnosis by Malfunction Code, p. 4', confidence: 'medium', note: null,
  },
  'mitsubishi|P8': {
    brand: 'mitsubishi', model_family: 'MXZ', error_code: 'P8',
    fault_name: 'Outdoor pipe temperature sensor abnormal',
    likely_causes: ['Defrost cycle not completing', 'Pipe thermistor out of range'],
    remedy_steps: ['Check thermistor resistance against the table in the manual', 'Verify refrigerant charge and airflow'],
    source_reference: 'MXZ outdoor service manual (partial match)', confidence: 'low',
    note: 'Retrieved context only partly covers this model; confirm the code meaning in the manual before acting.',
  },
};

const wait = (ms, signal) => new Promise((res, rej) => {
  const t = setTimeout(res, ms);
  if (signal) {
    const abort = () => { clearTimeout(t); rej(new ApiError('abort')); };
    if (signal.aborted) abort(); else signal.addEventListener('abort', abort, { once: true });
  }
});
const http = (status, detail) => new ApiError('http', { status, detail });
const clone = (o) => JSON.parse(JSON.stringify(o));

function lookup(brand, model, code) {
  brand = String(brand || '').toLowerCase().trim(); code = String(code || '').toUpperCase().trim();
  if (code === 'SRV') throw http(500, 'mock internal error');
  if (code === 'BUSY') throw http(503, 'mock: model overloaded');
  if (!brand && !code) throw http(422, 'At least one of brand or error_code must be provided.');
  const hit = DB[`${brand}|${code}`];
  if (!hit) throw http(404, 'No relevant context found in the RAG index for these parameters.');
  const r = clone(hit);
  if (model) r.model_family = model;
  return r;
}

let voiceN = 0;

export async function handle(path, { json, form, signal }) {
  const delay = (ms) => wait(ms, signal);
  switch (path) {
    case '/health': await delay(120); return { status: 'ok' };
    case '/speech/health': await delay(100); return { engine: 'mock-whisper', model: 'tiny', loaded: true };
    case '/query': {
      await delay(String(json && json.model_family).toUpperCase().includes('SLOW') ? 6000 : 700);
      return lookup(json.brand, json.model_family, json.error_code);
    }
    case '/vision/quality': {
      await delay(400);
      const name = (form.get('image').name || '').toLowerCase();
      const q = { blur_score: 210, brightness: 0.52, glare_fraction: 0.01, width: 2048, height: 1536, usable: true };
      const warnings = [];
      if (name.includes('blur')) { q.blur_score = 18; q.usable = false; warnings.push('Image looks blurry. Hold steady and tap to focus, then retake.'); }
      if (name.includes('dark')) { q.brightness = 0.07; q.glare_fraction = 0.22; warnings.push('Image is too dark.', 'Strong glare covers part of the plate.'); }
      return { quality: q, warnings };
    }
    case '/query/image': {
      await delay(1500);
      const name = (form.get('image').name || '').toLowerCase();
      if (name.includes('nokey')) throw http(503, 'GEMINI_API_KEY not set — image mode unavailable.');
      if (name.includes('unread')) throw http(422, 'VLM could not extract brand or error code from the image.');
      const low = name.includes('lowread');
      const vision = {
        brand: 'carrier', model_family: low ? '40MAQ' : '40MAQ', error_code: low ? 'E1' : 'E1',
        field_confidence: low ? { brand: 'high', model_family: 'low', error_code: 'medium' } : { brand: 'high', model_family: 'medium', error_code: 'high' },
        image_type: 'error_display',
        quality: { blur_score: 190, brightness: 0.5, glare_fraction: 0.02, width: 2048, height: 1536, usable: true },
        warnings: low ? ['Model text was partly covered; double-check it.'] : [], preprocess: ['resize', 'autocontrast'],
      };
      if (name.includes('nodata')) { vision.brand = 'daikin'; vision.model_family = 'FTXS'; vision.error_code = 'Z9'; throw http(404, `VLM extracted brand='daikin' model='FTXS' code='Z9' but no matching context found in the RAG index.`); }
      const r = lookup(vision.brand, vision.model_family, vision.error_code);
      r.vlm_confidence = low ? 'medium' : 'high';
      if (low) { r.confidence = 'medium'; }
      return { ...r, vision };
    }
    case '/vision/analyze': await delay(800); return { vision: {}, raw: {} };
    case '/transcribe': await delay(800); return { transcript: 'daikin ftxs u4', language: 'en', engine: 'mock', duration_s: 3.1 };
    case '/query/voice': {
      await delay(1600);
      const n = voiceN++ % 3;
      if (n === 0) return { transcript: 'Daikin FTXS showing error U4', parsed: { brand: 'daikin', model_family: 'FTXS', error_code: 'U4', question: '' }, result: lookup('daikin', 'FTXS', 'U4'), note: null };
      if (n === 1) return { transcript: 'uh the thing on the roof is blinking', parsed: { brand: '', model_family: '', error_code: '', question: 'why is it blinking' }, result: null, note: 'I could not make out a brand or an error code. Please repeat, speaking slowly.' };
      return { transcript: 'Mitsubishi MXZ error P eight', parsed: { brand: 'mitsubishi', model_family: 'MXZ', error_code: 'P8', question: '' }, result: lookup('mitsubishi', 'MXZ', 'P8'), note: null };
    }
    default: throw http(404, 'mock: unknown endpoint ' + path);
  }
}
