/**
 * Screen-layout preferences (not analysis state): panel collapse + legend
 * collapse are persisted under one localStorage key and never enter the
 * view-state / session contract. Storage may be unavailable (private mode,
 * disabled cookies) — every access is wrapped so callers never fail.
 */
const KEY = 'gvixb:ui-panels';

const storage = override => {
  try { return override || globalThis.localStorage; } catch { return null; }
};

/** @returns {{left:boolean, right:boolean, legend:boolean}} true = collapsed */
export function readUiPrefs(storageOverride) {
  const out = { left: false, right: false, legend: false };
  try {
    const parsed = JSON.parse(storage(storageOverride)?.getItem(KEY) || '{}');
    if (parsed && typeof parsed === 'object') {
      out.left = !!parsed.left;
      out.right = !!parsed.right;
      out.legend = !!parsed.legend;
    }
  } catch { /* malformed JSON or unavailable storage → defaults */ }
  return out;
}

/** Merge `patch` into the stored prefs and persist; returns the new prefs. */
export function writeUiPrefs(patch, storageOverride) {
  const next = { ...readUiPrefs(storageOverride), ...patch };
  try { storage(storageOverride)?.setItem(KEY, JSON.stringify(next)); } catch { /* storage unavailable */ }
  return next;
}
