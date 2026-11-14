import * as THREE from '../vendor/three.module.js';
import { groupLayers, classifyMetadataFields } from './algorithms.js';
import { groupColors } from './primitives.js';

const clamp = (v, a, b) => Math.min(b, Math.max(a, v));

/**
 * Metadata-driven encodings for network views (colour category + height).
 * Every height mode maps a data value to Y, so whatever the mode, the reader
 * can always name what the vertical axis means:
 *
 *   flat              — Y = 0
 *   structure         — Y = structural distance (root depth / distance from
 *                       the MST centre); centre on top, axis shown
 *   deck:<field>      — one deck per category of <field>, decks ordered
 *                       by the category's median structural distance
 *   spread:<field>    — deck per category, spread inside the deck by the
 *                       structural distance (within-deck thickness)
 *   num:<field>       — Y = numeric value of <field>, axis shown; records
 *                       without a value sit on a separate shelf below
 */

export const MISSING = '未提供';
export const OTHER = '其他';
export const HEIGHT_SPAN = 8;
const SPREAD_SPAN = 12;

// categorical palettes picked by category count: high-contrast sets, assigned
// in descending frequency so the dominant groups get the most distinct slots
// the original warm "instrument" palette — preferred for small group counts
export const PALETTE_WARM = ['#ff7a1a', '#f5e6c8', '#ff4d2e', '#f2c14e', '#d8dde8', '#ffae42', '#e8705a', '#c9b38a'];
const PALETTE_10 = ['#ff7a1a', '#4db2ff', '#f2c14e', '#7dd87d', '#e86a92', '#b08ee8', '#5ad1c9', '#d8dde8', '#c9863f', '#8fb04e'];
const PALETTE_20 = ['#ff7a1a', '#4db2ff', '#f2c14e', '#7dd87d', '#e86a92', '#b08ee8', '#5ad1c9', '#d8dde8', '#c9863f', '#8fb04e',
  '#ffc98a', '#9ccfff', '#f7dfa0', '#b5e8b5', '#f2a8c0', '#d0bdf0', '#a5e6e0', '#9aa3b8', '#e3b98a', '#c9d69a'];
const PALETTE_32 = [...PALETTE_20,
  '#ff4d2e', '#3f8fd2', '#c9a227', '#4e9e52', '#c0436a', '#7a5fc0', '#2f9d94', '#8a94a8', '#9c5a2e', '#5f7a34',
  '#e8705a', '#6fa8d8'];
const MAX_COLOR_CATEGORIES = 32; // beyond this, the tail merges into `OTHER`

/** Selectable colour schemes; 'auto' picks by category count. */
export const COLOR_SCHEMES = {
  auto: '自动（按类别数）',
  warm: '暖色仪器（≤8 类）',
  contrast10: '高对比 10 色',
  contrast20: '高对比 20 色',
  contrast32: '高对比 32 色',
};
const pickPalette = (scheme, n) => {
  if (scheme === 'warm') return PALETTE_WARM;
  if (scheme === 'contrast10') return PALETTE_10;
  if (scheme === 'contrast20') return PALETTE_20;
  if (scheme === 'contrast32') return PALETTE_32;
  return n <= PALETTE_WARM.length ? PALETTE_WARM : n <= 10 ? PALETTE_10 : n <= 20 ? PALETTE_20 : PALETTE_32;
};
const NUMERIC_BINS = 8;
// sequential ramp for numeric fields (cool → warm)
const RAMP = ['#233f78', '#2b6ea3', '#4db2b0', '#9ccf7a', '#f2c14e', '#ff7a1a', '#ff4d2e'];
const rampColor = t => {
  const x = clamp(t, 0, 1) * (RAMP.length - 1);
  const i = Math.min(RAMP.length - 2, Math.floor(x));
  return new THREE.Color(RAMP[i]).lerp(new THREE.Color(RAMP[i + 1]), x - i).getStyle();
};

const fmt = value => (Number.isInteger(value) ? String(value) : value.toFixed(Math.abs(value) < 1 ? 3 : 1));

export function metadataFieldOptions(records) {
  const fields = classifyMetadataFields(records);
  return {
    categorical: fields.filter(field => field.categorical).map(field => field.key),
    numeric: fields.filter(field => field.numeric).map(field => field.key),
    // colour can also serve wider category fields (tail merges into OTHER)
    // and numeric fields (sequential ramp bins)
    colorable: fields.filter(field => {
      // id-like fields (one value per record) carry no group information and
      // must not be colourable — numeric or not
      const idLike = field.distinct === records.length && records.length > 48;
      return field.distinct >= 2 && !idLike && (field.numeric || field.distinct <= 48);
    }).map(field => field.key),
  };
}

/** Height-mode select options, built only from fields actually present. */
export function heightModeOptions(fields, structureLabel, { treeModes = false } = {}) {
  return [
    { value: 'flat', label: '平面（无高度）' },
    { value: 'structure', label: `结构距离：${structureLabel}` },
    ...(treeModes ? [
      { value: 'cone', label: '锥形展开（3D 分支扇区）' },
      { value: 'canopy', label: '枢纽高度（树介数）' },
    ] : []),
    ...fields.categorical.map(key => ({ value: `spread:${key}`, label: `分层 + 层内展开：${key}` })),
    ...fields.categorical.map(key => ({ value: `deck:${key}`, label: `分层：${key}` })),
    ...fields.numeric.map(key => ({ value: `num:${key}`, label: `数值：${key}` })),
  ];
}

export function defaultHeightMode(fields) {
  const key = fields.categorical.includes('group') ? 'group' : fields.categorical[0];
  return key ? `spread:${key}` : 'structure';
}

export function defaultColorField(fields) {
  return fields.categorical.includes('group') ? 'group' : (fields.categorical[0] || '');
}

/** Legend layers (colour + visibility key) for one categorical field. */
export function colorLayers(values, palette, neutral) {
  const keys = values.map(value => (value === undefined || value === null || value === '' ? MISSING : String(value)));
  const layers = groupLayers(keys);
  const colors = groupColors([...layers.keys()].filter(key => key !== MISSING), palette);
  for (const layer of layers.values()) layer.color = layer.group === MISSING ? neutral : colors.get(layer.group);
  return { keys, layers };
}

/**
 * Node colouring for one metadata field. Returns per-item `keys` and legend
 * `layers` — the same shape colorLayers() produces, so callers can swap it in.
 *
 * - categorical: palette chosen by category count (≤10 / ≤20 / ≤32), colours
 *   assigned by descending frequency; categories past the palette merge into a
 *   single `OTHER` layer (more than ~32 hues are not reliably distinguishable,
 *   so the tail is honestly lumped instead of being given false precision).
 * - numeric: `NUMERIC_BINS` equal-width bins on a cool→warm sequential ramp;
 *   the legend rows are the bin ranges.
 */
export function nodeColoring(values, neutral, { scheme = 'auto' } = {}) {
  const present = values.filter(v => v !== undefined && v !== null && v !== '');
  const numeric = present.length > 2 && present.every(v => Number.isFinite(Number(v)));

  if (numeric) {
    const nums = present.map(Number);
    const lo = Math.min(...nums), hi = Math.max(...nums), span = hi - lo || 1;
    const keys = values.map(v => {
      if (v === undefined || v === null || v === '' || !Number.isFinite(Number(v))) return MISSING;
      return String(Math.min(NUMERIC_BINS - 1, Math.floor((Number(v) - lo) / span * NUMERIC_BINS)));
    });
    const counts = new Map();
    for (const key of keys) counts.set(key, (counts.get(key) || 0) + 1);
    const layers = new Map();
    const binLabel = i => {
      const a = lo + span * i / NUMERIC_BINS, b = lo + span * (i + 1) / NUMERIC_BINS;
      return `${fmt(a)}–${fmt(b)}`;
    };
    for (const [key, count] of [...counts.entries()].sort()) {
      layers.set(key, key === MISSING
        ? { group: MISSING, height: 0, count, order: NUMERIC_BINS, color: neutral }
        : { group: binLabel(Number(key)), height: 0, count, order: Number(key), color: rampColor((Number(key) + 0.5) / NUMERIC_BINS) });
    }
    return { keys, layers, kind: 'numeric', note: `颜色 = 数值分箱（${fmt(lo)}–${fmt(hi)}，${NUMERIC_BINS} 等宽箱）。` };
  }

  const keys0 = values.map(v => (v === undefined || v === null || v === '' ? MISSING : String(v)));
  const counts = new Map();
  for (const key of keys0) if (key !== MISSING) counts.set(key, (counts.get(key) || 0) + 1);
  const ranked = [...counts.keys()].sort((a, b) => counts.get(b) - counts.get(a) || a.localeCompare(b));
  const lumped = ranked.length > MAX_COLOR_CATEGORIES;
  const keep = new Set(lumped ? ranked.slice(0, MAX_COLOR_CATEGORIES - 1) : ranked);
  const keys = keys0.map(key => (key !== MISSING && !keep.has(key) ? OTHER : key));
  const layers = groupLayers(keys);
  const palette = pickPalette(scheme, ranked.length);
  let slot = 0;
  for (const layer of layers.values()) {
    layer.color = layer.group === MISSING || layer.group === OTHER ? neutral : palette[slot++ % palette.length];
  }
  const note = lumped
    ? `颜色按类别频率分配；${ranked.length - keep.size} 个低频类别并入"${OTHER}"。`
    : '颜色按类别分配（高频类别优先取高对比色）。';
  return { keys, layers, kind: 'categorical', note };
}

/**
 * Heights for record-bearing items (leaves / MST nodes).
 * `valueOf(i, field)` reads metadata; `structure[i]` is the structural
 * distance (≥ 0). Returns per-item heights plus an axis / deck description.
 */
export function encodeHeights({ count, mode, valueOf, structure, structureLabel, tree = null, amp = 1, weights = null }) {
  const heights = new Array(count).fill(0);
  const half = HEIGHT_SPAN / 2;
  if (mode === 'flat' || !count) return { heights, axis: null, decks: null, note: '高度未编码：全部节点位于同一平面。' };

  const maxStructure = Math.max(1e-12, ...structure.filter(Number.isFinite));
  const structural = i => (Number.isFinite(structure[i]) ? structure[i] / maxStructure : 1);

  if (mode === 'structure') {
    const sHalf = half * amp;
    for (let i = 0; i < count; i++) heights[i] = sHalf - structural(i) * 2 * sHalf;
    return {
      heights, decks: null,
      axis: {
        y0: sHalf, y1: -sHalf, label: structureLabel,
        ticks: [0, 0.5, 1].map(t => ({ y: sHalf - t * 2 * sHalf, text: fmt(t * maxStructure) })),
      },
      note: `高度 = ${structureLabel}（中心在上方，越往下越远）。`,
    };
  }

  // ---- tree-derived volumetric modes (need {parent, order, dist}) ----------
  if ((mode === 'canopy' || mode === 'cone') && tree?.parent) {
    const { parent, order, dist } = tree;
    const children = Array.from({ length: count }, () => []);
    for (const v of order) if (parent[v] >= 0) children[parent[v]].push(v);
    const size = new Array(count).fill(1);
    for (let k = order.length - 1; k >= 0; k--) {
      const v = order[k];
      if (parent[v] >= 0) size[parent[v]] += size[v];
    }

    if (mode === 'canopy') {
      // tree betweenness: traffic through a node = Σ over its incident
      // branches of branchSize × (n − branchSize). Hubs float, fringe sinks.
      const bw = new Array(count).fill(0);
      for (const v of order) {
        if (parent[v] >= 0) bw[v] += size[v] * (count - size[v]);
        for (const u of children[v]) bw[v] += size[u] * (count - size[u]);
      }
      const maxBw = Math.max(1e-12, ...bw);
      const cHalf = half * amp;
      for (let i = 0; i < count; i++) heights[i] = cHalf - (bw[i] / maxBw) * 2 * cHalf;
      return {
        heights, decks: null,
        axis: {
          y0: cHalf, y1: -cHalf, label: '树介数（枢纽度）',
          ticks: [0, 0.5, 1].map(t => ({ y: cHalf - t * 2 * cHalf, text: fmt(t * maxBw) })),
        },
        note: '高度 = 树介数（经过该节点的样本路径份额）：枢纽株浮起、末梢株下沉。',
      };
    }

    // cone: every subtree owns a contiguous vertical band proportional to its
    // weight, recursively subdivided — each node gets its own elevation slice,
    // so crowded planes spread into real volume (deterministic, no jitter).
    // weights[i] defaults to 1; hosts may pass e.g. member_count so large
    // aggregates claim wider bands.
    const w = i => Math.max(1e-9, Number(weights?.[i]) || 1);
    const wsum = new Array(count).fill(0);
    for (let k = order.length - 1; k >= 0; k--) {
      const v = order[k];
      wsum[v] = w(v);
      for (const u of children[v]) wsum[v] += wsum[u];
    }
    const coneHalf = half * amp;
    const place = (v, z0, z1) => {
      const span = z1 - z0;
      const selfShare = wsum[v] > 0 ? w(v) / wsum[v] : 0;
      heights[v] = z0 + (selfShare / 2) * span;
      let cursor = z0 + selfShare * span;
      for (const u of children[v].slice().sort((a, b) => wsum[b] - wsum[a] || a - b)) {
        const share = wsum[u] / wsum[v] * span;
        place(u, cursor, cursor + share);
        cursor += share;
      }
    };
    for (const v of order) if (parent[v] < 0) place(v, -coneHalf, coneHalf);
    return {
      heights, decks: null, axis: null,
      note: '高度 = 每个子树分得的纵向区带（节点各占一层，区带宽度 ∝ 权重）；纯显示展开，避免同面遮挡，不表示数值。',
    };
  }

  const [kind, field] = [mode.slice(0, mode.indexOf(':')), mode.slice(mode.indexOf(':') + 1)];
  if (kind === 'num') {
    const values = Array.from({ length: count }, (_, i) => Number(valueOf(i, field)));
    const present = values.filter(Number.isFinite);
    const lo = Math.min(...present), hi = Math.max(...present);
    const range = hi - lo || 1;
    let missing = 0;
    values.forEach((value, i) => {
      if (Number.isFinite(value)) heights[i] = -half + ((value - lo) / range) * HEIGHT_SPAN;
      else { heights[i] = -half - 1.6; missing++; }
    });
    return {
      heights, decks: null,
      axis: {
        y0: -half, y1: half, label: field,
        ticks: [0, 0.5, 1].map(t => ({ y: -half + t * HEIGHT_SPAN, text: fmt(lo + t * range) })),
      },
      note: `高度 = ${field}（数值，线性刻度）${missing ? `；${missing} 个节点缺少该值，置于底部单独一层` : ''}。`,
    };
  }

  // deck / spread: one deck per category, optional within-deck thickness
  const keys = Array.from({ length: count }, (_, i) => {
    const value = valueOf(i, field);
    return value === undefined || value === null || value === '' ? MISSING : String(value);
  });
  const spread = kind === 'spread';
  // deck order follows structure: the category whose members sit closest to
  // the centre (median structural distance) takes the top deck. Neighbouring
  // clusters then occupy neighbouring decks and branches descend outward
  // instead of zig-zagging between alternating decks.
  const sizes = groupLayers(keys);
  const median = new Map();
  for (const key of sizes.keys()) {
    const values = keys.map((k, i) => (k === key ? structure[i] : NaN)).filter(Number.isFinite).sort((a, b) => a - b);
    median.set(key, values.length ? values[Math.floor(values.length / 2)] : Infinity);
  }
  const ordered = [...sizes.keys()].sort((a, b) => median.get(a) - median.get(b) || sizes.get(b).count - sizes.get(a).count || String(a).localeCompare(String(b)));
  const span = Math.min((ordered.length - 1) * (spread ? 3.4 : 2.6), spread ? SPREAD_SPAN : HEIGHT_SPAN);
  const step = ordered.length > 1 ? span / (ordered.length - 1) : 3.4;
  const decks = new Map(ordered.map((key, i) => [key, {
    group: key, count: sizes.get(key).count, order: i, height: span / 2 - i * step,
  }]));
  // within-deck thickness uses the RANK of the structural distance inside the
  // deck: members of one category tend to share a similar distance, so a
  // globally normalised value would collapse the deck back into a plane
  const rank = new Array(count).fill(0.5);
  if (spread) {
    const members = new Map();
    keys.forEach((key, i) => { if (!members.has(key)) members.set(key, []); members.get(key).push(i); });
    for (const list of members.values()) {
      list.sort((a, b) => (Number.isFinite(structure[a]) ? structure[a] : Infinity) - (Number.isFinite(structure[b]) ? structure[b] : Infinity) || a - b);
      list.forEach((i, k) => { rank[i] = list.length > 1 ? k / (list.length - 1) : 0.5; });
    }
  }
  const thickness = spread ? step * 0.82 : 0;
  keys.forEach((key, i) => {
    heights[i] = decks.get(key).height + (thickness ? (0.5 - rank[i]) * thickness : 0);
  });
  return {
    heights, axis: null, decks: { field, keys, layers: decks },
    note: spread
      ? `每个 ${field} 占一层，层序按该类别的中位${structureLabel}排列（近者在上）；层内按${structureLabel}名次展开（越往下越远）。高度不表示 ${field} 的数值。`
      : `每个 ${field} 占一层（层序按中位${structureLabel}，近者在上），高度只表示类别归属。`,
  };
}
