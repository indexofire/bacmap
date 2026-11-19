/**
 * Epidemiological helpers for the phylogeny view: ISO-precision date
 * intervals, compressed-triangle pairwise distance access, single-linkage
 * threshold clusters and member summaries. Everything here is pure — no DOM,
 * no THREE — and computes nothing the host did not already provide:
 * clustering is connectivity over host-supplied distances at a user-chosen
 * threshold, never an inference.
 */

const DAY = 86400000;

/**
 * 'YYYY' | 'YYYY-MM' | 'YYYY-MM-DD' → { start, end, precision } where
 * start/end are UTC day numbers. Returns null for invalid input
 * (non-string, other formats, impossible month/day like 2024-02-30).
 */
export function parseDateInterval(text) {
  if (typeof text !== 'string') return null;
  const match = /^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?$/.exec(text.trim());
  if (!match) return null;
  const year = Number(match[1]);
  const month = match[2] === undefined ? 1 : Number(match[2]);
  const day = match[3] === undefined ? 1 : Number(match[3]);
  if (month < 1 || month > 12) return null;
  const lastDay = new Date(Date.UTC(year, month, 0)).getUTCDate();
  if (day < 1 || day > lastDay) return null;
  const start = Math.floor(Date.UTC(year, month - 1, day) / DAY);
  let precision = 'day', endMonth = month - 1, endDay = day;
  if (match[2] === undefined) { precision = 'year'; endMonth = 11; endDay = 31; }
  else if (match[3] === undefined) { precision = 'month'; endDay = lastDay; }
  const end = Math.floor(Date.UTC(year, endMonth, endDay) / DAY);
  return { start, end, precision };
}

/** UTC day number → 'YYYY-MM-DD'. */
export function formatDay(day) {
  const d = new Date(day * DAY);
  const mm = String(d.getUTCMonth() + 1).padStart(2, '0');
  const dd = String(d.getUTCDate()).padStart(2, '0');
  return `${d.getUTCFullYear()}-${mm}-${dd}`;
}

/**
 * distances = { samples: string[], values: (number|null)[] } compressed
 * upper triangle, i<j row-major. Index i in samples maps pair (i,j), i<j,
 * to offset i*n - i*(i+1)/2 + (j-i-1).
 */
export function distanceIndex(distances) {
  const samples = (distances?.samples || []).map(String);
  const values = distances?.values || [];
  const n = samples.length;
  const index = new Map(samples.map((name, i) => [name, i]));
  const get = (a, b) => {
    let i = index.get(a), j = index.get(b);
    if (i === undefined || j === undefined) return null;
    if (i === j) return 0;
    if (i > j) [i, j] = [j, i];
    const v = values[i * n - (i * (i + 1)) / 2 + (j - i - 1)];
    return Number.isFinite(v) ? v : null;
  };
  return { samples, index, get, n };
}

/**
 * Single-linkage connected components over pairs with a finite value
 * <= threshold. Only components of size >= 2 are reported. Cluster order:
 * size desc, then smallest member index in samples; members in samples order.
 */
export function thresholdClusters(dist, threshold) {
  const n = dist.n;
  const parent = Array.from({ length: n }, (_, i) => i);
  const find = x => { while (parent[x] !== x) { parent[x] = parent[parent[x]]; x = parent[x]; } return x; };
  const union = (a, b) => { const ra = find(a), rb = find(b); if (ra !== rb) parent[rb] = ra; };
  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      const v = dist.get(dist.samples[i], dist.samples[j]);
      if (v !== null && v <= threshold) union(i, j);
    }
  }
  const comps = new Map();
  for (let i = 0; i < n; i++) {
    const r = find(i);
    if (!comps.has(r)) comps.set(r, []);
    comps.get(r).push(i);
  }
  const groups = [...comps.values()]
    .filter(members => members.length >= 2)
    .sort((a, b) => b.length - a.length || a[0] - b[0]);
  const clusterOf = new Map();
  const clusters = groups.map((members, ci) => {
    const names = members.map(i => dist.samples[i]);
    for (const name of names) clusterOf.set(name, ci);
    return names;
  });
  return { clusters, clusterOf };
}

/** k nearest samples by distance; nulls excluded; ties by samples order. */
export function nearestSamples(dist, name, k) {
  const out = [];
  for (const other of dist.samples) {
    if (other === name) continue;
    const value = dist.get(name, other);
    if (value !== null) out.push({ name: other, value });
  }
  out.sort((a, b) => a.value - b.value || dist.index.get(a.name) - dist.index.get(b.name));
  return out.slice(0, k);
}

/**
 * Does `leafNames` form one branch of the tree's unrooted bipartitions?
 * True iff the leaf set (or its complement) equals the descendant-leaf set of
 * some non-root node — a root-independent check. Singletons and the full
 * leaf set always return true. `tree` = a layout result ({ root, leaves }).
 */
export function isTreeSplit(tree, leafNames) {
  const all = new Set(tree.leaves.map(leaf => leaf.name));
  const wanted = new Set([...leafNames].filter(name => all.has(name)));
  if (wanted.size <= 1 || wanted.size >= all.size) return true;
  const complement = new Set([...all].filter(name => !wanted.has(name)));
  const matches = set => {
    let found = false;
    (function walk(node) {
      if (found) return;
      if (node !== tree.root) {
        const under = new Set();
        (function collect(n) {
          if (!n.children.length) under.add(n.name);
          n.children.forEach(collect);
        })(node);
        if (under.size === set.size && [...set].every(name => under.has(name))) { found = true; return; }
      }
      node.children.forEach(walk);
    })(tree.root);
    return found;
  };
  return matches(wanted) || matches(complement);
}

/**
 * Summarise one group of metadata records.
 * fieldsByRole = { time: key|null, place: key|null, source: key|null }.
 * Records may carry ISO-precision dates; timeStart/timeEnd are formatted
 * day strings spanning all member intervals (null when none parse).
 */
export function summarizeMembers(records, fieldsByRole = {}) {
  const top = key => {
    if (!key) return [];
    const counts = new Map();
    for (const record of records) {
      const v = record?.[key];
      if (v === undefined || v === null || v === '') continue;
      const s = String(v);
      counts.set(s, (counts.get(s) || 0) + 1);
    }
    return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, 3);
  };
  let timeStart = null, timeEnd = null, missingTime = 0;
  for (const record of records) {
    const interval = fieldsByRole.time ? parseDateInterval(record?.[fieldsByRole.time]) : null;
    if (!interval) { missingTime++; continue; }
    if (timeStart === null || interval.start < timeStart) timeStart = interval.start;
    if (timeEnd === null || interval.end > timeEnd) timeEnd = interval.end;
  }
  return {
    timeStart: timeStart === null ? null : formatDay(timeStart),
    timeEnd: timeEnd === null ? null : formatDay(timeEnd),
    places: top(fieldsByRole.place),
    sources: top(fieldsByRole.source),
    missingTime,
  };
}
