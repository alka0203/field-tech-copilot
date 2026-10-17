import { $, h, clear, announce, toast, FAMILIES, brandName } from './util.js';
import { api, ApiError, MOCK, FAKE_MIC, prepareImage, describeError } from './api.js';
import { VoiceRecorder, micSupport, micErrorMessage, formatElapsed, MAX_MS } from './audio.js';
import { makeFakeEnv } from './fakes.js';
import { addHistory, loadHistory, clearHistory, getTheme, setTheme } from './store.js';
import { renderReadout, renderResult, renderLoading, renderError, renderNoData, renderHistoryItem, normConf, stopSpeech } from './render.js';

const S = { job: null, readout: null, photo: null, rec: null, recMode: null };
const HOLD_MS = 450; // press longer than this = hold-to-talk; shorter = tap-to-toggle

// ---------------------------------------------------------------- panels / regions
const PANELS = { type: 'typePanel', photo: 'photoPanel', voice: 'voicePanel' };
function showPanel(name) {
  for (const [k, id] of Object.entries(PANELS)) $(id).hidden = k !== name;
  $('btnType').classList.toggle('on', name === 'type');
  $('btnPhoto').classList.toggle('on', name === 'photo');
  updateHome();
}
function updateHome() {
  const open = Object.values(PANELS).some((id) => !$(id).hidden);
  $('home').hidden = open || $('readout').childElementCount > 0 || $('output').childElementCount > 0;
}
function setReadout(node) { const el = $('readout'); clear(el); if (node) el.append(node); S.readout = node; updateHome(); }
function setOutput(node) { const el = $('output'); clear(el); if (node) el.append(node); updateHome(); }
function focusOn(node, scrollTo) {
  const target = node && node.focusTarget;
  if (scrollTo) scrollTo.scrollIntoView({ block: 'start' });
  if (target) target.focus({ preventScroll: true });
}

// ---------------------------------------------------------------- jobs (cancel / timeouts live in api.js)
function beginJob(label, detail) {
  abortJob();
  const ctrl = new AbortController();
  const job = { ctrl, signal: ctrl.signal, replaced: false, cancelled: false };
  const { node, stop } = renderLoading(label, detail, () => { job.cancelled = true; ctrl.abort(); });
  job.stop = stop; S.job = job;
  setOutput(node);
  announce(label + '. Please wait.');
  return job;
}
function finishJob(job) { job.stop(); if (S.job === job) S.job = null; }
function abortJob() { const j = S.job; if (j) { j.replaced = true; j.ctrl.abort(); j.stop(); S.job = null; } }

function resetForNewInput() {
  stopSpeech(); abortJob(); cancelRecording();
  setReadout(null); setOutput(null);
  if (S.photo) { URL.revokeObjectURL(S.photo.url); S.photo = null; }
}

// ---------------------------------------------------------------- results
function normalizeResp(r) {
  const arr = (x) => (Array.isArray(x) ? x.map((v) => String(v)).filter((v) => v.trim()) : []);
  const str = (x) => (x == null ? '' : String(x));
  return {
    brand: str(r.brand), model_family: str(r.model_family), error_code: str(r.error_code),
    fault_name: str(r.fault_name).trim(), likely_causes: arr(r.likely_causes), remedy_steps: arr(r.remedy_steps),
    source_reference: str(r.source_reference), confidence: str(r.confidence).toLowerCase(),
    note: r.note ? str(r.note) : null, vlm_confidence: r.vlm_confidence || null,
  };
}

function showReadout(ctx) {
  const node = renderReadout(ctx, {
    onRerun: (vals) => lookup(vals, { source: ctx.source === 'history' ? 'typed' : ctx.source, corrected: true, thumbUrl: ctx.thumbUrl, transcript: ctx.transcript, question: ctx.question }),
  });
  setReadout(node);
  return node;
}

function presentResult(raw, ctx) {
  const r = normalizeResp(raw);
  if (!r.fault_name && !r.likely_causes.length && !r.remedy_steps.length) {
    // Backend returned an empty shell: treat as "no data", never render a blank/made-up answer.
    showNoData(ctx, {});
    return;
  }
  if (ctx.source !== 'history') renderHistory(addHistory(r));
  const node = renderResult(r, ctx);
  setOutput(node);
  focusOn(node, $('readout').firstChild || node);
  announce(`Result: ${r.fault_name}. ${r.confidence || 'unknown'} confidence.` + (r.confidence === 'low' || r.note ? ' Verify against the manual.' : ''));
}

function showNoData(ctx, info) {
  const node = renderNoData(ctx.fields || {}, info, {
    onCorrect: () => { if (S.readout && S.readout.openEditor) S.readout.openEditor(); },
    onType: () => openType(ctx.fields),
  });
  setOutput(node); focusOn(node, $('readout').firstChild || node);
  announce('No data for this in the indexed manuals.', true);
}

function fail(e, kind, ctx, retry, job) {
  if (job) { if (job.replaced) return; finishJob(job); }
  if (e instanceof ApiError && e.kind === 'abort') {
    const node = renderError({ title: 'Cancelled', body: 'Nothing was sent or the request was stopped.', retry: !!retry }, { onRetry: retry, onType: () => openType(ctx && ctx.fields) });
    setOutput(node); announce('Cancelled'); return;
  }
  const info = describeError(e, kind);
  if (info.nodata) { showNoData(ctx || {}, info); return; }
  const node = renderError(info, { onRetry: retry, onType: () => openType(ctx && ctx.fields) });
  setOutput(node); focusOn(node, node);
  announce(info.title + '. ' + info.body, true);
}

const cleanFields = (f) => ({ brand: String(f.brand || ''), model_family: String(f.model_family || ''), error_code: String(f.error_code || '') });

async function lookup(fields, base) {
  fields = cleanFields(fields);
  abortJob(); stopSpeech();
  const ctx = { ...base, fields };
  showReadout(ctx);
  const job = beginJob('Looking up the manuals', 'Searching the service manuals for this code.');
  try {
    const resp = await api.query(fields, job.signal);
    if (job.replaced) return;
    finishJob(job);
    presentResult(resp, ctx);
  } catch (e) { fail(e, 'query', ctx, () => lookup(fields, base), job); }
}

// ---------------------------------------------------------------- TYPE
function fillFamilies() {
  const dl = $('families'); clear(dl);
  const b = $('fBrand').value;
  for (const f of b ? FAMILIES[b] || [] : Object.values(FAMILIES).flat()) dl.append(h('option', { value: f }));
}
function openType(prefill) {
  abortJob(); cancelRecording();
  if (prefill) {
    const b = String(prefill.brand || '').toLowerCase();
    $('fBrand').value = [...$('fBrand').options].some((o) => o.value === b) ? b : '';
    $('fModel').value = prefill.model_family || '';
    $('fCode').value = prefill.error_code || '';
    fillFamilies();
  }
  showPanel('type');
  $('typeErr').hidden = true;
  $('typePanel').scrollIntoView({ block: 'start' });
  (prefill && $('fBrand').value ? $('fCode') : $('fBrand')).focus({ preventScroll: true });
}
$('fBrand').addEventListener('change', fillFamilies);
$('typeClose').addEventListener('click', () => showPanel(null));
$('btnType').addEventListener('click', () => { if (!$('typePanel').hidden) { showPanel(null); return; } resetForNewInput(); openType(); });
$('typeForm').addEventListener('submit', (e) => {
  e.preventDefault();
  const f = { brand: $('fBrand').value, model_family: $('fModel').value.trim(), error_code: $('fCode').value.trim().toUpperCase() };
  const err = $('typeErr');
  if (!f.brand && !f.error_code) {
    err.textContent = 'Pick a brand or enter the error code (both is best).'; err.hidden = false;
    (f.brand ? $('fCode') : $('fBrand')).focus(); announce(err.textContent, true); return;
  }
  err.hidden = true;
  showPanel(null);
  lookup(f, { source: 'typed' });
});

// ---------------------------------------------------------------- PHOTO
const cam = $('fileCam'), lib = $('fileLib');
function openCamera() { cam.value = ''; cam.click(); }
$('btnPhoto').addEventListener('click', () => { cancelRecording(); openCamera(); });
$('photoRetake').addEventListener('click', openCamera);
$('photoLib').addEventListener('click', () => { lib.value = ''; lib.click(); });
$('photoClose').addEventListener('click', () => { resetForNewInput(); showPanel(null); });
$('photoUse').addEventListener('click', () => sendPhoto());
for (const inp of [cam, lib]) inp.addEventListener('change', () => { const f = inp.files && inp.files[0]; if (f) handlePhoto(f); });

const isImage = (f) => (f.type && f.type.startsWith('image/')) || /\.(jpe?g|png|webp|heic|heif|gif|bmp)$/i.test(f.name || '');

function photoUi({ status, warnings, actions = false, allowUse = true }) {
  $('photoStatus').textContent = warnings && warnings.length ? '' : (status || '');
  $('photoStatus').hidden = !$('photoStatus').textContent;
  const w = $('photoWarn'), list = $('photoWarnList'); clear(list);
  w.hidden = !(warnings && warnings.length);
  for (const t of warnings || []) list.append(h('li', { text: t }));
  $('photoActions').hidden = !actions;
  $('photoUse').hidden = !allowUse;
}

async function handlePhoto(file) {
  resetForNewInput();
  if (!isImage(file)) {
    showPanel('photo'); $('photoPreview').hidden = true;
    photoUi({ status: 'That file is not a photo. Choose a JPEG or PNG image.', actions: true, allowUse: false });
    return;
  }
  S.photo = { file, url: URL.createObjectURL(file), prepared: null };
  const prev = $('photoPreview'); prev.src = S.photo.url; prev.hidden = false;
  showPanel('photo');
  photoUi({ status: 'Checking photo quality' });
  $('photoPanel').scrollIntoView({ block: 'start' });
  const job = beginJob('Checking the photo', 'Quick check for blur, darkness and glare before sending.');
  let q = null;
  try {
    S.photo.prepared = await prepareImage(file);
    try { q = await api.visionQuality(S.photo.prepared, job.signal); }
    catch (e) {
      if (e instanceof ApiError && e.kind === 'abort') throw e;
      if (e instanceof ApiError && e.status === 422) { // server cannot decode the file at all
        if (job.replaced) return;
        finishJob(job); setOutput(null);
        photoUi({ status: 'That file could not be read as an image. Retake the photo or choose another.', actions: true, allowUse: false });
        announce('That file could not be read as an image.', true);
        return;
      }
      q = null; /* quality service unavailable: skip the check */
    }
    if (job.replaced) return;
    finishJob(job);
  } catch (e) {
    if (job.replaced) return;
    finishJob(job); setOutput(null);
    photoUi({ status: 'Check cancelled. Retake the photo or send it as is.', actions: true });
    return;
  }
  const warnings = (q && q.warnings) || [];
  const unusable = q && q.quality && q.quality.usable === false;
  if (warnings.length || unusable) {
    setOutput(null);
    photoUi({ warnings: warnings.length ? warnings : ['The photo may be too poor to read.'], actions: true });
    announce('Photo quality warning. ' + (warnings[0] || 'Retake or use anyway.'), true);
    $('photoRetake').focus({ preventScroll: true });
    return;
  }
  await sendPhoto();
}

async function sendPhoto() {
  if (!S.photo) return;
  const photo = S.photo;
  photoUi({ status: 'Sending photo' });
  const job = beginJob('Reading the photo', 'Finding brand, model and code, then searching the manuals. Can take up to a minute on a weak signal.');
  const base = { source: 'photo', thumbUrl: photo.url, fields: {} };
  try {
    const resp = await api.queryImage(photo.prepared || photo.file, job.signal);
    if (job.replaced) return;
    finishJob(job);
    const v = resp.vision && typeof resp.vision === 'object' ? resp.vision : null;
    const fields = cleanFields({ brand: (v && v.brand) || resp.brand, model_family: (v && v.model_family) || resp.model_family, error_code: (v && v.error_code) || resp.error_code });
    const fc = (v && v.field_confidence) || {};
    const fallback = normConf(resp.vlm_confidence);
    const conf = { brand: normConf(fc.brand) || fallback, model_family: normConf(fc.model_family) || fallback, error_code: normConf(fc.error_code) || fallback };
    const ctx = { source: 'photo', thumbUrl: photo.url, fields, conf, warnings: (v && v.warnings) || [], imageType: v && v.image_type, vlmConfidence: v ? null : resp.vlm_confidence };
    showPanel(null);
    const node = showReadout(ctx);
    if (v && v.image_type === 'unreadable') node.openEditor();
    presentResult(resp, ctx);
  } catch (e) {
    if (job.replaced) return;
    // keep the photo panel so the technician can Retake; 404 gets an open editor so they can type what the plate says
    const info = e instanceof ApiError && e.kind === 'http' ? describeError(e, 'image') : null;
    if (info && info.nodata) { showPanel(null); const node = showReadout(base); fail(e, 'image', base, null, job); node.openEditor(); return; }
    photoUi({ status: '', actions: true, allowUse: false });
    fail(e, 'image', base, () => sendPhoto(), job);
  }
}

// drag and drop (desktop)
let dragDepth = 0;
const hasFiles = (e) => e.dataTransfer && [...(e.dataTransfer.types || [])].includes('Files');
window.addEventListener('dragenter', (e) => { if (!hasFiles(e)) return; dragDepth++; $('dropzone').hidden = false; });
window.addEventListener('dragleave', (e) => { if (!hasFiles(e)) return; if (--dragDepth <= 0) { dragDepth = 0; $('dropzone').hidden = true; } });
window.addEventListener('dragover', (e) => { if (hasFiles(e)) e.preventDefault(); });
window.addEventListener('drop', (e) => {
  if (!hasFiles(e)) return;
  e.preventDefault(); dragDepth = 0; $('dropzone').hidden = true;
  const f = [...e.dataTransfer.files].find(isImage) || e.dataTransfer.files[0];
  if (f) handlePhoto(f);
});

// ---------------------------------------------------------------- VOICE
const vBtn = $('btnVoice');

function voiceUi(state) { // 'idle' | 'live' | 'msg'
  $('voiceLive').hidden = state !== 'live';
  $('voiceMsg').hidden = state !== 'msg';
  $('voicePanel').classList.toggle('recording', state === 'live');
  const live = state === 'live';
  vBtn.setAttribute('aria-pressed', String(live));
  $('voiceLabel').textContent = live ? 'Stop' : 'Voice';
  $('voiceHelp').textContent = live ? 'release or tap' : 'hold or tap';
}
function voiceMessage(text, soft = false) {
  voiceUi('msg'); $('voiceMsgText').textContent = text; showPanel('voice');
  $('voicePanel').scrollIntoView({ block: 'start' });
  announce(text, !soft);
}
$('voiceToType').addEventListener('click', () => { voiceUi('idle'); openType(); });
$('voiceClose').addEventListener('click', () => { cancelRecording(); showPanel(null); });

function cancelRecording() {
  if (S.rec) { S.rec.cancel(); S.rec = null; }
  S.attempt = (S.attempt || 0) + 1; // invalidates a start() still waiting on the permission prompt
  S.recStarting = false;
  voiceUi('idle');
}

async function beginRecording() {
  if (S.rec || S.recStarting) return false;
  const sup = FAKE_MIC ? { ok: true } : micSupport();
  if (!sup.ok) { resetForNewInput(); voiceMessage(sup.message); return false; }
  resetForNewInput();
  S.recStarting = true;
  const attempt = S.attempt;
  const askTimer = setTimeout(() => { if (S.recStarting && S.attempt === attempt) voiceMessage('Waiting for the microphone. Tap Allow when your browser asks. Nothing is recorded until you do.', true); }, 500);
  const rec = new VoiceRecorder({
    maxMs: MAX_MS,
    env: FAKE_MIC ? makeFakeEnv() : undefined,
    onTick: (ms, level) => {
      $('recFill').style.width = Math.round(level * 100) + '%';
      $('recTime').textContent = `${formatElapsed(ms)} / ${formatElapsed(MAX_MS)}`;
      const left = Math.ceil((MAX_MS - ms) / 1000);
      $('recState').textContent = left <= 5 ? `Listening (${left} s left)` : 'Listening';
    },
    onAutoStop: (r) => { if (S.rec === rec) { S.rec = null; voiceUi('idle'); toast('20 s limit reached. Sending.'); sendVoice(r); } },
  });
  try {
    await rec.start();
  } catch (e) {
    clearTimeout(askTimer);
    if (S.attempt !== attempt) return false; // user moved on while the prompt was open
    S.recStarting = false;
    voiceMessage(micErrorMessage(e).message);
    return false;
  }
  clearTimeout(askTimer);
  if (S.attempt !== attempt) { rec.cancel(); return false; }
  S.recStarting = false;
  S.rec = rec;
  voiceUi('live'); showPanel('voice');
  $('recTime').textContent = `0:00 / ${formatElapsed(MAX_MS)}`; $('recFill').style.width = '0';
  announce('Recording. Speak the brand, model and code.');
  return true;
}

async function stopAndSend() {
  const rec = S.rec;
  if (!rec) return;
  S.rec = null;
  const r = await rec.stop();
  voiceUi('idle');
  if (!r) return;
  if (r.tooShort) { voiceMessage('That was too short to hear. Hold the Voice button while you speak, or tap once, speak, then tap again.'); return; }
  sendVoice(r);
}

async function sendVoice(r) {
  showPanel(null);
  const job = beginJob('Listening to the recording', 'Transcribing what you said, then searching the manuals.');
  const base = { source: 'voice', fields: {} };
  try {
    const resp = await api.queryVoice(r.blob, r.mimeType, job.signal);
    if (job.replaced) return;
    finishJob(job);
    const p = resp.parsed || {};
    const fields = cleanFields(p);
    const ctx = { source: 'voice', transcript: String(resp.transcript || ''), question: p.question ? String(p.question) : '', fields };
    const node = showReadout(ctx);
    if (resp.result) {
      const res = { ...resp.result };
      if (resp.note && !res.note) res.note = String(resp.note);
      presentResult(res, ctx);
    } else {
      const msg = resp.note ? String(resp.note) : (ctx.transcript ? 'I could not find a brand or error code in what I heard.' : 'I did not hear anything.');
      const card = renderError({ title: 'I did not catch that', body: msg + ' Check the transcript above, fix the details, or record again.', retry: false }, { onType: () => openType(fields) });
      card.querySelector('.row').prepend(h('button', { class: 'btn btn-primary', type: 'button', onclick: () => beginRecording() }, 'Record again'));
      card.querySelector('.row').append(h('button', { class: 'btn', type: 'button', onclick: () => node.openEditor() }, 'Fix details'));
      setOutput(card); focusOn(card, $('readout').firstChild || card);
      announce('I did not catch that. ' + msg, true);
    }
  } catch (e) {
    fail(e, 'voice', base, null, job);
  }
}

$('recStop').addEventListener('click', stopAndSend);
$('recCancel').addEventListener('click', () => { cancelRecording(); showPanel(null); announce('Recording cancelled'); });

// Hold-to-talk AND tap-to-toggle on one button.
let pressAt = 0, pressing = false, kbHandled = false;
vBtn.addEventListener('contextmenu', (e) => e.preventDefault());
vBtn.addEventListener('pointerdown', async (e) => {
  if (e.button > 0) return;
  e.preventDefault();
  if (S.rec) { stopAndSend(); return; }          // second tap of tap-to-toggle
  pressing = true; pressAt = performance.now();
  try { vBtn.setPointerCapture(e.pointerId); } catch { /* not critical */ }
  await beginRecording();
});
const release = () => {
  if (!pressing) return;
  pressing = false;
  // Long press that started recording = hold-to-talk: releasing sends. A quick tap leaves it running (toggle mode).
  if (S.rec && performance.now() - pressAt >= HOLD_MS) stopAndSend();
};
vBtn.addEventListener('pointerup', release);
vBtn.addEventListener('pointercancel', release);
vBtn.addEventListener('keydown', (e) => {
  if (e.key !== 'Enter' && e.key !== ' ') return;
  e.preventDefault(); if (e.repeat) return;
  kbHandled = true; setTimeout(() => { kbHandled = false; }, 400);
  if (S.rec) stopAndSend(); else beginRecording();
});
vBtn.addEventListener('keyup', (e) => { if (e.key === ' ') e.preventDefault(); });
// Assistive-tech activation (VoiceOver/TalkBack) arrives as a click with detail 0 and no key event.
vBtn.addEventListener('click', (e) => { if (e.detail === 0 && !kbHandled) { if (S.rec) stopAndSend(); else beginRecording(); } });

// ---------------------------------------------------------------- history
function renderHistory(list = loadHistory()) {
  const ul = $('historyList'); clear(ul);
  for (const entry of list) ul.append(renderHistoryItem(entry, openHistory));
  $('histEmpty').hidden = list.length > 0;
  $('clearHist').hidden = list.length === 0;
}
function openHistory(entry) {
  resetForNewInput(); showPanel(null);
  const r = entry.resp;
  const ctx = { source: 'history', savedAt: entry.ts, fields: cleanFields(r) };
  showReadout(ctx);
  presentResult(r, ctx);
}
$('clearHist').addEventListener('click', () => { clearHistory(); renderHistory([]); toast('History cleared'); });

// ---------------------------------------------------------------- theme / connectivity / lifecycle
function applyTheme(t) {
  const root = document.documentElement;
  if (t === 'light' || t === 'dark') root.dataset.theme = t; else delete root.dataset.theme;
  const label = { auto: 'Auto', light: 'Light', dark: 'Dark' }[t];
  $('themeBtn').textContent = label;
  $('themeBtn').setAttribute('aria-label', `Colour theme: ${label}. Tap to change.`);
}
let theme = getTheme(); applyTheme(theme);
$('themeBtn').addEventListener('click', () => { theme = { auto: 'light', light: 'dark', dark: 'auto' }[theme] || 'auto'; setTheme(theme); applyTheme(theme); });

function setConn(state, text) { $('conn').dataset.s = state; $('connTxt').textContent = text; }
function syncOnline() { $('offlineBanner').hidden = MOCK || navigator.onLine !== false; if (navigator.onLine === false) setConn('bad', 'Offline'); }
window.addEventListener('online', () => { syncOnline(); checkHealth(); });
window.addEventListener('offline', syncOnline);

async function checkHealth() {
  if (MOCK) { setConn('ok', 'Demo data'); return; }
  try {
    await api.health();
    setConn('ok', 'Server ready');
    api.speechHealth().then((s) => { $('conn').title = `Speech: ${s.engine || '?'} ${s.model || ''}${s.loaded ? '' : ' (not loaded yet)'}`; }).catch(() => {});
  } catch { setConn('bad', navigator.onLine === false ? 'Offline' : 'Server unreachable'); }
}

window.addEventListener('pagehide', () => { stopSpeech(); cancelRecording(); });

$('mockBanner').hidden = !MOCK;
fillFamilies(); renderHistory(); syncOnline(); checkHealth(); updateHome();
if (MOCK) window.__ftc = { S, lookup }; // handy for the browser console while testing
