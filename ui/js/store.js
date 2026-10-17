// Persistence. Every storage touch is try/catch wrapped (private mode, blocked storage).
const HKEY = 'ftc.history.v1';
const MAX = 10;

export function loadHistory() {
  try {
    const a = JSON.parse(localStorage.getItem(HKEY) || '[]');
    return Array.isArray(a) ? a.filter((x) => x && x.resp && typeof x.ts === 'number').slice(0, MAX) : [];
  } catch { return []; }
}
function saveHistory(list) { try { localStorage.setItem(HKEY, JSON.stringify(list)); } catch { /* ignore */ } }

const keyOf = (r) => [r.brand, r.model_family, r.error_code].map((s) => String(s || '').toLowerCase()).join('|');

export function addHistory(resp) {
  const list = loadHistory().filter((x) => keyOf(x.resp) !== keyOf(resp));
  list.unshift({ ts: Date.now(), resp });
  saveHistory(list.slice(0, MAX));
  return loadHistory();
}
export function clearHistory() { try { localStorage.removeItem(HKEY); } catch { /* ignore */ } }

export function resultKey(r) {
  return 'ftc.ticks.' + [r.brand, r.model_family, r.error_code, r.fault_name, r.source_reference].map((s) => String(s || '')).join('|');
}
export function loadTicks(r) {
  try { const a = JSON.parse(sessionStorage.getItem(resultKey(r)) || '[]'); return new Set(Array.isArray(a) ? a : []); }
  catch { return new Set(); }
}
export function saveTicks(r, set) {
  try { sessionStorage.setItem(resultKey(r), JSON.stringify([...set])); } catch { /* ignore */ }
}

export function getTheme() { try { return localStorage.getItem('ftc.theme') || 'auto'; } catch { return 'auto'; } }
export function setTheme(t) { try { localStorage.setItem('ftc.theme', t); } catch { /* ignore */ } }
