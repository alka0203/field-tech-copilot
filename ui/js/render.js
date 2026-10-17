// Pure DOM builders. Server / transcript text only ever goes through textContent / text nodes.
import { h, brandName, BRANDS, FAMILIES, timeAgo, toast } from './util.js';
import { loadTicks, saveTicks } from './store.js';

// ---------- confidence ----------
export function normConf(v) {
  if (typeof v === 'number' && isFinite(v)) return v >= 0.8 ? 'high' : v >= 0.5 ? 'medium' : 'low';
  const s = String(v || '').toLowerCase().trim();
  return ['high', 'medium', 'low'].includes(s) ? s : null;
}
const CONF = {
  high: ['✓', 'High'], medium: ['◐', 'Medium'], low: ['⚠', 'Low'],
  manual: ['✎', 'Set by you'], missing: ['?', 'Not found'],
};
export function confChip(level) {
  const [icon, label] = CONF[level] || CONF.missing;
  return h('span', { class: `conf conf-${CONF[level] ? level : 'missing'}` },
    h('span', { 'aria-hidden': 'true', text: icon }), h('span', { class: 'sr-only', text: 'confidence ' }), label);
}

// ---------- loading / error / no data ----------
export function renderLoading(label, detail, onCancel) {
  const t0 = Date.now();
  const elapsed = h('span', { class: 'muted small', text: '0 s' });
  const timer = setInterval(() => { elapsed.textContent = Math.floor((Date.now() - t0) / 1000) + ' s'; }, 1000);
  const node = h('section', { class: 'card', 'aria-busy': 'true', 'aria-label': label },
    h('div', { class: 'loading-head' }, h('div', { class: 'spinner', 'aria-hidden': 'true' }),
      h('div', null, h('strong', { text: label }), h('br'), elapsed)),
    detail ? h('p', { class: 'muted small', text: detail }) : null,
    h('div', { class: 'skel' }), h('div', { class: 'skel' }), h('div', { class: 'skel' }),
    h('button', { class: 'btn', type: 'button', onclick: onCancel }, 'Cancel'));
  return { node, stop: () => clearInterval(timer) };
}

export function renderError(info, { onRetry, onType } = {}) {
  const heading = h('h2', { tabindex: '-1', text: info.title });
  const node = h('section', { class: 'card err' }, heading,
    info.body ? h('p', { text: info.body }) : null,
    info.detail ? h('details', null, h('summary', { text: 'Technical detail' }), h('p', { class: 'mono small', text: info.detail })) : null,
    h('div', { class: 'row' },
      info.retry && onRetry ? h('button', { class: 'btn btn-primary', type: 'button', onclick: onRetry }, 'Try again') : null,
      onType ? h('button', { class: info.fallbackType ? 'btn btn-primary' : 'btn', type: 'button', onclick: onType }, 'Use Type instead') : null));
  node.focusTarget = heading;
  return node;
}

export function renderNoData(fields, info, { onCorrect, onType } = {}) {
  const what = [brandName(fields.brand), fields.model_family, fields.error_code && `code ${fields.error_code}`].filter(Boolean).join(' · ');
  const heading = h('h2', { tabindex: '-1', text: 'No data for this in the indexed manuals' });
  const node = h('section', { class: 'card nodata' }, heading,
    h('p', { text: what ? `Nothing in the indexed Carrier, Daikin or Mitsubishi manuals matched ${what}. I will not guess.` : 'Nothing in the indexed manuals matched. I will not guess.' }),
    h('ul', null,
      h('li', { text: 'Check the code on the display. Easy mix-ups: 0 and O, 1 and I, 5 and S, 8 and B.' }),
      h('li', { text: 'Try the model family exactly as printed on the nameplate, or leave it blank.' }),
      h('li', { text: 'Look the code up in the paper or PDF manual for this unit.' })),
    info && info.detail ? h('details', null, h('summary', { text: 'What the server said' }), h('p', { class: 'mono small', text: info.detail })) : null,
    h('div', { class: 'row' },
      onCorrect ? h('button', { class: 'btn btn-primary', type: 'button', onclick: onCorrect }, 'Correct the details') : null,
      onType ? h('button', { class: 'btn', type: 'button', onclick: onType }, 'Use Type instead') : null));
  node.focusTarget = heading;
  return node;
}

// ---------- readout ("what I read / heard") ----------
let uid = 0;
const SOURCE_TAG = { photo: 'Read from photo', voice: 'Heard', typed: 'You entered', history: 'Saved lookup' };

export function renderReadout(ctx, { onRerun } = {}) {
  const id = 'ro' + (++uid);
  const f = ctx.fields;
  const conf = ctx.conf || {};
  const fieldRow = (label, key, value) => {
    const sensed = ctx.source === 'photo' || ctx.source === 'voice';
    const c = ctx.corrected ? 'manual' : (value ? (normConf(conf[key]) || null) : (sensed ? 'missing' : null));
    return h('div', null, h('dt', { text: label }),
      h('dd', value ? { class: 'mono' } : { class: 'none' }, value ? (key === 'brand' ? brandName(value) : value) : (ctx.source === 'photo' || ctx.source === 'voice' ? 'not found' : 'not set')),
      c ? confChip(value ? c : 'missing') : h('span'));
  };

  const editor = buildEditor(id, f, (vals) => onRerun && onRerun(vals), () => { editor.hidden = true; editBtn.hidden = false; editBtn.focus(); });
  editor.hidden = true;
  const editBtn = h('button', { class: 'btn btn-sm', type: 'button', 'aria-expanded': 'false', 'aria-controls': id + '-edit', onclick: () => open() }, 'Correct this');
  const open = () => { editor.hidden = false; editBtn.hidden = true; editBtn.setAttribute('aria-expanded', 'true'); editor.querySelector('select').focus(); };

  const label = SOURCE_TAG[ctx.source] || 'Details';
  const node = h('section', { class: 'card', 'aria-labelledby': id + '-h' },
    h('div', { class: 'card-head' }, h('span', { class: 'tag', text: label }),
      h('h2', { id: id + '-h', text: ctx.corrected ? 'Corrected details' : ({ photo: 'Is this right?', voice: 'Is this right?', typed: 'Your lookup', history: 'Details' }[ctx.source] || 'Details') }),
      ctx.imageType && ctx.imageType !== 'other' ? h('span', { class: 'muted small', text: `(${String(ctx.imageType).replace('_', ' ')})` }) : null),
    h('div', { class: 'read-top' },
      ctx.thumbUrl ? h('img', { class: 'read-thumb', src: ctx.thumbUrl, alt: 'The photo you took' }) : null,
      h('div', null,
        ctx.transcript ? h('blockquote', { class: 'heard' }, h('span', { class: 'sr-only', text: 'Transcript: ' }), '“' + ctx.transcript + '”') : null,
        ctx.question ? h('p', { class: 'muted small', text: 'Question heard: ' + ctx.question }) : null)),
    h('dl', { class: 'fields' }, fieldRow('Brand', 'brand', f.brand), fieldRow('Model', 'model_family', f.model_family), fieldRow('Code', 'error_code', f.error_code)),
    ...(ctx.warnings || []).map((w) => h('p', { class: 'mini-warn', text: w })),
    ctx.vlmConfidence ? h('p', { class: 'muted small' }, 'Overall reading confidence: ', confChip(normConf(ctx.vlmConfidence) || 'missing')) : null,
    editBtn, editor);
  node.openEditor = open;
  return node;
}

function buildEditor(id, f, onSubmit, onCancel) {
  const bId = id + '-b', mId = id + '-m', cId = id + '-c', dl = id + '-dl';
  const sel = h('select', { id: bId, name: 'brand' }, h('option', { value: '', text: 'Select brand' }),
    ...Object.entries(BRANDS).map(([v, n]) => h('option', { value: v, text: n })));
  const cur = String(f.brand || '').toLowerCase();
  if (cur && !BRANDS[cur]) sel.append(h('option', { value: cur, text: brandName(cur) }));
  sel.value = cur;
  const datalist = h('datalist', { id: dl });
  const fill = () => {
    while (datalist.firstChild) datalist.removeChild(datalist.firstChild);
    const fams = sel.value ? FAMILIES[sel.value] || [] : Object.values(FAMILIES).flat();
    for (const x of fams) datalist.append(h('option', { value: x }));
  };
  sel.addEventListener('change', fill); fill();
  const model = h('input', { id: mId, type: 'text', list: dl, autocomplete: 'off', autocapitalize: 'characters', spellcheck: 'false' });
  model.value = f.model_family || '';
  const code = h('input', { id: cId, type: 'text', class: 'mono', autocomplete: 'off', autocapitalize: 'characters', spellcheck: 'false' });
  code.value = f.error_code || '';
  const err = h('p', { class: 'field-err', role: 'alert', hidden: true });
  const form = h('form', { id: id + '-edit', class: 'edit-form', novalidate: true,
    onsubmit: (e) => {
      e.preventDefault();
      if (!sel.value && !code.value.trim()) { err.textContent = 'Enter at least a brand or an error code.'; err.hidden = false; return; }
      err.hidden = true;
      onSubmit({ brand: sel.value, model_family: model.value.trim(), error_code: code.value.trim().toUpperCase() });
    } },
    h('div', { class: 'field' }, h('label', { for: bId, text: 'Brand' }), sel),
    h('div', { class: 'field' }, h('label', { for: mId }, 'Model family ', h('span', { class: 'opt', text: 'optional' })), model, datalist),
    h('div', { class: 'field' }, h('label', { for: cId, text: 'Error code' }), code),
    err,
    h('div', { class: 'row', style: 'margin-top:12px' },
      h('button', { class: 'btn btn-primary', type: 'submit' }, 'Look up again'),
      h('button', { class: 'btn', type: 'button', onclick: onCancel }, 'Cancel')));
  return form;
}

// ---------- result ----------
// The index may only know an opaque chunk id instead of a manual title; say so rather than pretending.
export function sourceLabel(ref) {
  const r = String(ref || '').trim();
  if (!r) return { text: 'not stated', opaque: true };
  if (/^[0-9a-f]{10,}$/i.test(r)) return { text: `indexed excerpt ${r.slice(0, 8)}\u2026 (manual title not recorded)`, opaque: true };
  return { text: r, opaque: false };
}

const BADGE = {
  high: ['✓', 'High confidence'], medium: ['◐', 'Medium confidence'], low: ['⚠', 'Low confidence'],
};

export function summaryText(r, ticks = new Set()) {
  const L = [];
  L.push(`${brandName(r.brand)} ${r.model_family || ''} – code ${r.error_code || '?'}`.replace(/\s+/g, ' '));
  L.push(`Fault: ${r.fault_name}`);
  L.push(`Confidence: ${(r.confidence || 'unknown').toUpperCase()}`);
  if (r.likely_causes.length) { L.push('', 'Likely causes:'); r.likely_causes.forEach((c, i) => L.push(`${i + 1}. ${c}`)); }
  if (r.remedy_steps.length) { L.push('', 'Remedy steps:'); r.remedy_steps.forEach((c, i) => L.push(`${i + 1}. [${ticks.has('r' + i) ? 'x' : ' '}] ${c}`)); }
  if (r.source_reference) L.push('', `Source: ${sourceLabel(r.source_reference).text}`);
  if (r.confidence === 'low' || r.note) L.push('', 'VERIFY AGAINST THE MANUAL' + (r.note ? ': ' + r.note : ''));
  return L.join('\n');
}

export async function copyText(text) {
  try { if (navigator.clipboard && window.isSecureContext) { await navigator.clipboard.writeText(text); return true; } } catch { /* fall through */ }
  try {
    const ta = h('textarea', { 'aria-hidden': 'true', style: 'position:fixed;opacity:0;top:0' });
    ta.value = text; document.body.append(ta); ta.select();
    const ok = document.execCommand('copy'); ta.remove(); return ok;
  } catch { return false; }
}

// -- speech synthesis --
let speakToken = 0;
export function stopSpeech() { speakToken++; try { window.speechSynthesis && window.speechSynthesis.cancel(); } catch { /* ignore */ } }

function speechChunks(r) {
  const c = [`${brandName(r.brand)} ${r.model_family || ''} code ${r.error_code || ''}. ${r.fault_name}.`, `Confidence ${r.confidence || 'unknown'}.`];
  if (r.confidence === 'low' || r.note) c.push('Verify against the manual before acting.');
  if (r.likely_causes.length) { c.push('Likely causes.'); r.likely_causes.forEach((x, i) => c.push(`${i + 1}. ${x}.`)); }
  if (r.remedy_steps.length) { c.push('Remedy steps.'); r.remedy_steps.forEach((x, i) => c.push(`Step ${i + 1}. ${x}.`)); }
  return c;
}

function speakButton(r) {
  const supported = 'speechSynthesis' in window && typeof SpeechSynthesisUtterance === 'function';
  if (!supported) return null;
  const btn = h('button', { class: 'btn', type: 'button', 'aria-pressed': 'false' }, 'Read aloud');
  const reset = () => { btn.setAttribute('aria-pressed', 'false'); btn.textContent = 'Read aloud'; };
  btn.addEventListener('click', () => {
    if (btn.getAttribute('aria-pressed') === 'true') { stopSpeech(); reset(); return; }
    stopSpeech();
    const my = speakToken;
    const chunks = speechChunks(r);
    btn.setAttribute('aria-pressed', 'true'); btn.textContent = 'Stop reading';
    chunks.forEach((t, i) => {
      const u = new SpeechSynthesisUtterance(t);
      u.rate = 0.95;
      if (i === chunks.length - 1) { u.onend = () => { if (my === speakToken) reset(); }; }
      u.onerror = () => { if (my === speakToken) reset(); };
      window.speechSynthesis.speak(u);
    });
  });
  return btn;
}

function checklist(items, prefix, ticks, r, onChange) {
  return h('ol', { class: 'check' }, ...items.map((text, i) => {
    const id = `${prefix}${i}`;
    const cb = h('input', { type: 'checkbox', id: 'cb-' + id });
    cb.checked = ticks.has(id);
    cb.addEventListener('change', () => { cb.checked ? ticks.add(id) : ticks.delete(id); saveTicks(r, ticks); onChange(); });
    return h('li', null, h('label', { for: 'cb-' + id }, cb, h('span', { class: 'num', 'aria-hidden': 'true', text: String(i + 1) }), h('span', { class: 'txt', text })));
  }));
}

export function renderResult(r, ctx = {}) {
  const ticks = loadTicks(r);
  const heading = h('h2', { tabindex: '-1', id: 'resultH', text: r.fault_name });
  const [bIcon, bText] = BADGE[r.confidence] || ['?', 'Confidence unknown'];
  const verify = r.confidence === 'low' || r.note || !BADGE[r.confidence];
  const prog = h('span', { class: 'progress' });
  const upd = () => {
    const total = r.remedy_steps.length;
    const done = r.remedy_steps.filter((_, i) => ticks.has('r' + i)).length;
    prog.textContent = total ? `${done} of ${total} done` : '';
  };
  const shareSupported = typeof navigator.share === 'function';

  const node = h('section', { class: 'card result', 'aria-labelledby': 'resultH' },
    h('div', { class: 'result-meta' }, h('span', { class: 'tag', text: 'Answer' }),
      r.brand || r.model_family ? h('span', { class: 'plate', text: [brandName(r.brand), r.model_family].filter(Boolean).join(' ') }) : null,
      r.error_code ? h('span', { class: 'plate', text: 'Code ' + r.error_code }) : null),
    heading,
    h('div', null, h('span', { class: `badge badge-${BADGE[r.confidence] ? r.confidence : 'low'}` }, h('span', { 'aria-hidden': 'true', text: bIcon }), bText)),
    ctx.source === 'history' && ctx.savedAt ? h('p', { class: 'stale', text: `Saved copy from ${timeAgo(ctx.savedAt)}. Use "Correct this" above to run it fresh.` }) : null,
    verify ? h('div', { class: 'verify', role: 'note' }, h('span', { class: 'ico', 'aria-hidden': 'true', text: '⚠' }),
      h('div', null, h('strong', { text: 'Verify against the manual' }),
        h('span', { text: r.note ? r.note : 'This answer is not high confidence. Check it against the service manual before acting.' }),
        r.source_reference && !sourceLabel(r.source_reference).opaque ? h('span', { class: 'small' }, h('br'), 'Look in: ', h('b', { class: 'mono', text: r.source_reference })) : null)) : null,
    r.likely_causes.length ? h('div', null, h('div', { class: 'sec-head' }, h('h3', { text: 'Likely causes' })), checklist(r.likely_causes, 'c', ticks, r, upd)) : null,
    r.remedy_steps.length ? h('div', null, h('div', { class: 'sec-head' }, h('h3', { text: 'Remedy steps' }), prog), checklist(r.remedy_steps, 'r', ticks, r, upd))
      : h('p', { class: 'mini-warn', text: 'No remedy steps were found in the retrieved manual text. Check the manual for the fix.' }),
    h('p', { class: 'source' }, h('span', { class: 'muted', text: 'Source manual' }), h('b', { text: sourceLabel(r.source_reference).text })),
    h('div', { class: 'row' },
      speakButton(r),
      h('button', { class: 'btn', type: 'button', onclick: async () => { toast((await copyText(summaryText(r, ticks))) ? 'Summary copied' : 'Copy failed. Select the text manually.'); } }, 'Copy'),
      shareSupported ? h('button', { class: 'btn', type: 'button', onclick: async () => {
        try { await navigator.share({ title: `${brandName(r.brand)} ${r.error_code} – ${r.fault_name}`, text: summaryText(r, ticks) }); }
        catch (e) { if (e && e.name === 'AbortError') return; toast((await copyText(summaryText(r, ticks))) ? 'Share unavailable. Summary copied.' : 'Share failed.'); }
      } }, 'Share') : null));
  upd();
  node.focusTarget = heading;
  return node;
}

// ---------- history ----------
export function renderHistoryItem(entry, onOpen) {
  const r = entry.resp;
  return h('li', null, h('button', { class: 'hist-item', type: 'button', onclick: () => onOpen(entry) },
    h('span', { class: 't', text: [brandName(r.brand), r.model_family, r.error_code].filter(Boolean).join(' · ') }),
    h('span', { class: 'when', text: timeAgo(entry.ts) }),
    h('span', { class: 'f', text: r.fault_name }),
    ));
}
