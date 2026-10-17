// Tiny DOM helper. Text is ALWAYS inserted as text nodes; innerHTML is banned.
export function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue;
    if (k === 'innerHTML' || k === 'outerHTML') throw new Error('innerHTML is not allowed');
    if (k === 'class') el.className = v;
    else if (k === 'text') el.textContent = v;
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (v === true) el.setAttribute(k, '');
    else el.setAttribute(k, String(v));
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid == null || kid === false) continue;
    el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

export const $ = (id) => document.getElementById(id);

export function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); }

export function announce(msg, assertive = false) {
  const el = $(assertive ? 'alertLive' : 'announce');
  el.textContent = '';
  // re-set on next tick so identical messages are re-announced
  setTimeout(() => { el.textContent = msg; }, 30);
}

let toastTimer;
export function toast(msg) {
  const t = $('toast');
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, 2600);
  announce(msg);
}

export const BRANDS = { carrier: 'Carrier', daikin: 'Daikin', mitsubishi: 'Mitsubishi' };
// Mirrors sources.yaml + HANDOFF.md (kept inline so the UI works offline).
export const FAMILIES = {
  carrier: ['40MAQ', '38MAQB', '25HCE'],
  daikin: ['FTXS', 'FTKF', 'FTKX', 'CTX', 'RXS', 'RMXS', 'VRV', 'Skyair'],
  mitsubishi: ['MSZ', 'MSZ-FH', 'MSZ-GE', 'MUZ', 'MXZ', 'PUZ'],
};
export function brandName(b) {
  const k = String(b || '').toLowerCase().trim();
  return BRANDS[k] || (k ? k.charAt(0).toUpperCase() + k.slice(1) : '');
}

export function timeAgo(ts) {
  const s = Math.max(0, (Date.now() - ts) / 1000);
  if (s < 60) return 'just now';
  if (s < 3600) return Math.floor(s / 60) + ' min ago';
  if (s < 86400) return Math.floor(s / 3600) + ' h ago';
  return Math.floor(s / 86400) + ' d ago';
}
