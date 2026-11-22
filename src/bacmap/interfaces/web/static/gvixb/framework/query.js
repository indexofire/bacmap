/**
 * Metadata / matrix filter — pure condition evaluation for the phylo view.
 * No DOM / no THREE here. Semantics are descriptive only: a condition asks
 * "does this leaf's record/cell look like X", never infers biology.
 *
 * filter = { mode: 'all'|'any', conditions: Condition[] }
 * Condition:
 *   { source:'matrix', matrix:id, column:id, op:'pos'|'neg'|'untested' }
 *   { source:'field', field:key, op:'in'|'not_in', values:string[] }
 *   { source:'field', field:key, op:'gte'|'lte'|'between', min?, max? }
 *   { source:'field', field:key, op:'contains', text }
 *   { source:'field', field:key, op:'missing'|'present' }
 *
 * Missing/null values never satisfy any op except 'missing' (and matrix
 * 'untested' for null). In particular 'not_in' on a missing value is false:
 * "not tested" is not "not Sichuan".
 */

/**
 * Field types usable for filtering. `fields[]` is optional in the schema, so
 * declared fields are merged with types inferred from metadata records:
 * declared entries win (they carry richer types like 'text'/'date'); inferred
 * 'categorical'/'numeric' fill the gaps. Inferred dates are not offered —
 * the time brush covers them.
 * Returns Map<key, type>.
 */
export function filterFieldTypes(declaredFields, inferred = {}) {
  const map = new Map();
  for (const f of declaredFields || []) {
    if (f && typeof f.key === 'string') map.set(f.key, f.type);
  }
  for (const k of inferred.categorical || []) if (!map.has(k)) map.set(k, 'categorical');
  for (const k of inferred.numeric || []) if (!map.has(k)) map.set(k, 'numeric');
  return map;
}

const isMissing = v => v === null || v === undefined || v === '';
const asNumber = v => {
  if (isMissing(v)) return NaN;
  const n = Number(v);
  return Number.isFinite(n) ? n : NaN;
};

function evalMatrix(cond, leafName, matrices) {
  const m = matrices.find(mx => mx.id === cond.matrix);
  const col = m?.columns.findIndex(c => c.id === cond.column);
  if (!m || col < 0) return { skip: `未知矩阵列：${cond.matrix}:${cond.column}` };
  const row = m.rows?.[leafName];
  const v = row ? row[col] : null;
  if (cond.op === 'untested') return { hit: v === null || v === undefined };
  if (cond.op === 'pos') return { hit: v === 1 };
  if (cond.op === 'neg') return { hit: v === 0 };
  return { skip: `未知操作：${cond.op}` };
}

function evalField(cond, leafName, metadata, fieldTypes) {
  const type = fieldTypes.get(cond.field);
  if (type === undefined) return { skip: `未知字段：${cond.field}` };
  const v = metadata[leafName]?.[cond.field];
  switch (cond.op) {
    case 'missing': return { hit: isMissing(v) };
    case 'present': return { hit: !isMissing(v) };
    case 'in': {
      if (isMissing(v)) return { hit: false };
      const vals = Array.isArray(cond.values) ? cond.values : [];
      return { hit: vals.includes(String(v)) };
    }
    case 'not_in': {
      if (isMissing(v)) return { hit: false };   // missing ≠ "not X"
      const vals = Array.isArray(cond.values) ? cond.values : [];
      return { hit: !vals.includes(String(v)) };
    }
    case 'gte': case 'lte': case 'between': {
      const n = asNumber(v);
      if (!Number.isFinite(n)) return { hit: false };
      if (cond.op === 'gte') return { hit: n >= Number(cond.min) };
      if (cond.op === 'lte') return { hit: n <= Number(cond.max) };
      return { hit: n >= Number(cond.min) && n <= Number(cond.max) };
    }
    case 'contains': {
      if (isMissing(v)) return { hit: false };
      return { hit: String(v).toLowerCase().includes(String(cond.text || '').toLowerCase()) };
    }
    default: return { skip: `未知操作：${cond.op}` };
  }
}

/**
 * Evaluate a filter over leaves.
 * Returns { matched: Set<leafName>|null, warnings: string[] } — matched is
 * null when the filter is empty or every condition was skipped.
 */
export function evaluateFilter(filter, { leaves, metadata, matrices = [], fieldTypes }) {
  const warnings = [];
  const conds = Array.isArray(filter?.conditions) ? filter.conditions : [];
  if (!conds.length) return { matched: null, warnings };
  const mode = filter.mode === 'any' ? 'any' : 'all';
  const matched = new Set();
  let usable = 0;
  const hits = conds.map(cond => {
    if (!cond || typeof cond !== 'object') { warnings.push('无效条件'); return null; }
    // pre-validate references once so skip warnings aren't per-leaf noise
    if (cond.source === 'matrix') {
      const m = matrices.find(mx => mx.id === cond.matrix);
      if (!m || !m.columns.some(c => c.id === cond.column)) {
        warnings.push(`未知矩阵列：${cond.matrix}:${cond.column}`); return null;
      }
    } else if (cond.source === 'field') {
      if (!fieldTypes.has(cond.field)) { warnings.push(`未知字段：${cond.field}`); return null; }
    } else {
      warnings.push(`未知条件来源：${cond.source}`); return null;
    }
    usable++;
    return leaves.map(leaf =>
      (cond.source === 'matrix' ? evalMatrix(cond, leaf, matrices) : evalField(cond, leaf, metadata, fieldTypes))
        .hit === true);
  });
  if (!usable) return { matched: null, warnings };
  for (let i = 0; i < leaves.length; i++) {
    const ok = mode === 'all'
      ? hits.every(h => h === null || h[i])
      : hits.some(h => h !== null && h[i]);
    if (ok) matched.add(leaves[i]);
  }
  return { matched, warnings };
}

/** Short chip text for a condition. */
export function describeCondition(cond, { fieldLabel = k => k, matrixLabel = id => id } = {}) {
  if (!cond || typeof cond !== 'object') return '?';
  if (cond.source === 'matrix') {
    const op = { pos: '阳性', neg: '阴性', untested: '未检测' }[cond.op] || cond.op;
    return `${matrixLabel(cond.matrix)}:${cond.column} ${op}`;
  }
  const f = fieldLabel(cond.field);
  switch (cond.op) {
    case 'in': return `${f} ∈ ${(cond.values || []).join(', ')}`;
    case 'not_in': return `${f} ∉ ${(cond.values || []).join(', ')}`;
    case 'gte': return `${f} ≥ ${cond.min}`;
    case 'lte': return `${f} ≤ ${cond.max}`;
    case 'between': return `${f} ∈ [${cond.min}, ${cond.max}]`;
    case 'contains': return `${f} 含 “${cond.text || ''}”`;
    case 'missing': return `${f} 缺失`;
    case 'present': return `${f} 有值`;
    default: return `${f} ${cond.op}`;
  }
}

/** Ops offered per field type ('matrix' handled separately). */
export function conditionOptions(fieldType) {
  if (fieldType === 'matrix') return [
    { op: 'pos', label: '阳性（=1）' },
    { op: 'neg', label: '阴性（=0）' },
    { op: 'untested', label: '未检测' },
  ];
  if (fieldType === 'numeric') return [
    { op: 'gte', label: '≥' }, { op: 'lte', label: '≤' }, { op: 'between', label: '介于' },
    { op: 'missing', label: '缺失' }, { op: 'present', label: '有值' },
  ];
  if (fieldType === 'text') return [
    { op: 'contains', label: '包含' }, { op: 'in', label: '等于' },
    { op: 'missing', label: '缺失' }, { op: 'present', label: '有值' },
  ];
  // categorical (and anything else)
  return [
    { op: 'in', label: '属于' }, { op: 'not_in', label: '不属于' },
    { op: 'missing', label: '缺失' }, { op: 'present', label: '有值' },
  ];
}

/**
 * Match-table columns (right panel). Each column:
 *   { id, kind: 'field'|'matrix', key?, matrix?, column?, label, type }
 * `id` is the persisted form: 'field:<key>' or 'matrix:<mid>|<col>'.
 */

/** All columns the match table can offer: filterable + date fields, plus the
 * matrix columns referenced by conditions (not the whole matrix). */
export function tableColumnOptions({ conditions = [], fields = [], fieldTypes, matrices = [], fieldLabel = k => k }) {
  const cols = [];
  const types = fieldTypes instanceof Map ? fieldTypes : new Map(fieldTypes || []);
  const declared = new Set((fields || []).map(f => f.key));
  for (const [key, type] of types) {
    cols.push({ id: `field:${key}`, kind: 'field', key, type, label: fieldLabel(key) });
  }
  // declared date fields may be absent from fieldTypes in some callers —
  // make sure they are still offered (the table displays dates fine).
  for (const f of fields || []) {
    if (!types.has(f.key)) cols.push({ id: `field:${f.key}`, kind: 'field', key: f.key, type: f.type || 'text', label: f.label || f.key });
  }
  for (const cond of conditions) {
    if (cond?.source !== 'matrix') continue;
    const m = matrices.find(mx => mx.id === cond.matrix);
    if (!m || !m.columns.some(c => c.id === cond.column)) continue;
    const id = `matrix:${cond.matrix}|${cond.column}`;
    if (!cols.some(c => c.id === id)) {
      cols.push({ id, kind: 'matrix', matrix: cond.matrix, column: cond.column, type: 'matrix', label: `${m.label || m.id}:${cond.column}` });
    }
  }
  return cols;
}

/** Default visible columns: fields/columns referenced by the conditions,
 * then the current colour field, then declared primary fields of the
 * time/place/source roles — deduplicated, capped at `max`. */
export function defaultTableColumns({ conditions = [], colorField = null, fields = [], fieldLabel = k => k, max = 6 }) {
  const cols = [];
  const push = col => { if (col && !cols.some(c => c.id === col.id) && cols.length < max) cols.push(col); };
  for (const cond of conditions) {
    if (!cond || typeof cond !== 'object') continue;
    if (cond.source === 'matrix') push({ id: `matrix:${cond.matrix}|${cond.column}`, kind: 'matrix', matrix: cond.matrix, column: cond.column, type: 'matrix' });
    else if (cond.source === 'field') push({ id: `field:${cond.field}`, kind: 'field', key: cond.field });
  }
  if (colorField) push({ id: `field:${colorField}`, kind: 'field', key: colorField });
  for (const f of fields || []) {
    if (f.primary && ['time', 'place', 'source'].includes(f.role)) {
      push({ id: `field:${f.key}`, kind: 'field', key: f.key, type: f.type, label: f.label });
    }
  }
  return cols;
}

const isMissingCell = v => v === null || v === undefined || v === '';

/**
 * Cell comparator: missing always last (regardless of direction), numeric
 * compare for 'numeric' columns, lexicographic for everything else (ISO-ish
 * dates compare correctly as strings; 'zh' locale for Chinese values).
 */
export function compareCellValues(a, b, type) {
  const ma = isMissingCell(a), mb = isMissingCell(b);
  if (ma || mb) return ma === mb ? 0 : (ma ? 1 : -1);
  if (type === 'numeric') {
    const na = Number(a), nb = Number(b);
    if (Number.isFinite(na) && Number.isFinite(nb) && na !== nb) return na - nb;
  }
  return String(a).localeCompare(String(b), 'zh');
}

/** Sort comparator over leaf records for one column + direction. `valueOf`
 * returns the raw cell for a leaf record. Missing stays last either way. */
export function makeRowComparator(column, dir = 1, valueOf) {
  return (ra, rb) => {
    const va = valueOf(column, ra), vb = valueOf(column, rb);
    const ma = isMissingCell(va), mb = isMissingCell(vb);
    if (ma || mb) return ma === mb ? 0 : (ma ? 1 : -1);
    return compareCellValues(va, vb, column.type) * dir;
  };
}

/**
 * MST sample records — one filterable record per real sample.
 * If a node carries `members` with per-member `meta` objects, each member is
 * a record (values = member.meta; the node's own aggregated "|"-joined meta
 * is NOT used — it is a display string, not data). Otherwise the node itself
 * is one record (values = node record).
 * Returns [{ key, id, nodeIndex, values, memberIndex|null }].
 */
export function mstSampleRecords(isolates) {
  const records = [];
  isolates.forEach((iso, i) => {
    const withMeta = Array.isArray(iso.members)
      && iso.members.some(m => m && typeof m.meta === 'object' && Object.keys(m.meta).length);
    if (withMeta) {
      iso.members.forEach((m, mi) => {
        records.push({ key: `${i}:${mi}`, id: String(m?.id ?? ''), nodeIndex: i, values: m?.meta || {}, memberIndex: mi });
      });
    } else {
      records.push({ key: `n${i}`, id: String(iso.id), nodeIndex: i, values: iso.record || {}, memberIndex: null });
    }
  });
  return records;
}

/** Set of node indices that have ≥1 matched sample record. */
export function matchedNodeSet(matched, records) {
  if (!matched) return null;
  const set = new Set();
  for (const r of records) if (matched.has(r.key)) set.add(r.nodeIndex);
  return set;
}
