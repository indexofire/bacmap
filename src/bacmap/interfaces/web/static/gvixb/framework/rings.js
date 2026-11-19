/**
 * Data rings — pure geometry/selection helpers for views that draw annulus
 * cells around a radial tree. No DOM / no THREE here; the view converts the
 * returned cell list into a single BufferGeometry.
 */

const TAU = Math.PI * 2;

/**
 * Angular sectors for leaves placed on a circle.
 * `positions` maps leaf → {x, y} (flat layout plane coords).
 * Each leaf's sector spans halfway to its angular neighbours; where the gap
 * between two consecutive leaves exceeds 3× the median gap (the layout's big
 * angular gap), the facing sides are capped at the median gap so cells do not
 * stretch into empty space.
 * Returns sectors in INPUT order: [{ leaf, theta, a0, a1 }] with a0 <= a1 and
 * both in [0, 2π); sectors may share boundaries but never overlap.
 */
export function leafSectors(leaves, positions) {
  const entries = leaves.map((leaf, i) => {
    const p = positions instanceof Map ? positions.get(leaf)
      : Array.isArray(positions) ? positions[i] : positions[leaf];
    const theta = Math.atan2(p.y, p.x);
    return { leaf, theta: theta + (theta < 0 ? TAU : 0) };
  });
  const sorted = [...entries].sort((a, b) => a.theta - b.theta);
  const n = sorted.length;
  if (!n) return [];
  // gaps between consecutive angles (incl. wrap)
  const gaps = sorted.map((e, i) => {
    const next = sorted[(i + 1) % n];
    return (next.theta - e.theta + TAU) % TAU || TAU;
  });
  const sortedGaps = [...gaps].sort((a, b) => a - b);
  const median = n % 2 ? sortedGaps[(n - 1) / 2] : (sortedGaps[n / 2 - 1] + sortedGaps[n / 2]) / 2;
  // side width allowed to each side of a gap: half the gap normally, but a
  // suspiciously large gap (> 3× median = the layout's angular break) only
  // grants each leaf the median gap so cells don't stretch into empty space
  const sideOf = gap => (gap > median * 3 ? median : gap / 2);
  const sectors = new Array(n);
  for (let i = 0; i < n; i++) {
    const prevGap = gaps[(i - 1 + n) % n];
    const w0 = sideOf(prevGap);
    const w1 = sideOf(gaps[i]);
    sectors[i] = {
      leaf: sorted[i].leaf,
      theta: sorted[i].theta,
      a0: (sorted[i].theta - w0 + TAU) % TAU,
      a1: (sorted[i].theta + w1) % TAU,
      w0, w1,
      span: w0 + w1,
      gapAfter: gaps[i],
    };
  }
  // restore input order
  const byLeaf = new Map(sectors.map(s => [s.leaf, s]));
  return entries.map(e => byLeaf.get(e.leaf));
}

/** Per-column presence stats. Prevalence ignores nulls (untested). */
export function matrixColumnStats(matrix, leafNames) {
  return matrix.columns.map((column, ci) => {
    let carriers = 0, tested = 0, nulls = 0;
    for (const name of leafNames) {
      const value = matrix.rows?.[name]?.[ci];
      if (value === null || value === undefined) { nulls++; continue; }
      tested++;
      if (value === 1) carriers++;
    }
    return {
      id: column.id, group: column.group || null, index: ci,
      carriers, tested, nulls,
      prevalence: tested ? carriers / tested : 0,
    };
  });
}

/**
 * Column selection. Precedence: exclude > include > filters.
 * sort: 'group' (group order then prevalence desc), 'prev', 'name'.
 */
export function selectColumns(matrix, stats, { sort = 'group', minPrev = 0, maxCols = 30, include = [], exclude = [] } = {}) {
  const inc = new Set(include), exc = new Set(exclude);
  let cols = stats.filter(s => !exc.has(s.id) && (inc.has(s.id) || s.prevalence * 100 >= minPrev));
  const cmp = {
    group: (a, b) => String(a.group || '').localeCompare(String(b.group || '')) || b.prevalence - a.prevalence || a.id.localeCompare(b.id),
    prev: (a, b) => b.prevalence - a.prevalence || a.id.localeCompare(b.id),
    name: (a, b) => a.id.localeCompare(b.id),
  }[sort] || ((a, b) => a.index - b.index);
  cols = [...cols].sort(cmp);
  // maxCols caps filter-selected columns; manual includes are always kept
  const forced = cols.filter(c => inc.has(c.id));
  const kept = new Set([...forced, ...cols.filter(c => !inc.has(c.id)).slice(0, maxCols)]);
  return cols.filter(c => kept.has(c)).map(s => ({ id: s.id, group: s.group, index: s.index }));
}

/**
 * Radial layout of visible columns.
 * rings: [{ id, columns: [{id, group}] }] in draw order (innermost first).
 * Returns { w, rings: [{ id, columns: [{id, group, r0, r1}] }], outerRadius }.
 * Gaps: 0.25·w between columns, 2·w between column groups, 4·w between rings.
 */
export function ringLayout({ rings, R0, Rtree }) {
  const total = rings.reduce((acc, ring) => acc + ring.columns.length, 0);
  if (!total) return { w: 0, rings: rings.map(r => ({ ...r, columns: [] })), outerRadius: R0 };
  const available = 0.45 * Rtree;
  const w = Math.min(0.28, Math.max(0.06, available / total));
  let r = R0;
  const out = rings.map(ring => {
    const columns = [];
    let prevGroup = null, first = true;
    for (const col of ring.columns) {
      if (!first) r += (col.group !== prevGroup ? 2 : 0.25) * w;
      r += w / 2;
      columns.push({ id: col.id, group: col.group ?? null, r0: r - w / 2, r1: r + w / 2, mid: r });
      r += w / 2;
      prevGroup = col.group ?? null;
      first = false;
    }
    r += 4 * w;   // inter-ring gap
    return { id: ring.id, columns };
  });
  return { w, rings: out, outerRadius: r - 4 * w + w * 0.25 };
}

/**
 * Triangle cells for every leaf × visible column.
 * sectors: from leafSectors (has a0/theta; span preserved through wrap).
 * colors(leaf, ringId, columnId) → [r,g,b,a] 0..1 or null to skip the cell.
 * Returns { positions: number[], cells: [{ring, column, leaf, v0}] } —
 * v0 = first vertex index; 6 vertices (2 tris) per cell.
 * y: flat baseline plane height for all ring vertices.
 */
export function buildRingCells({ sectors, layout, colors, y = 0 }) {
  const SEGS = 4;   // angular subdivisions per cell — smooth enough at ring radii
  const VERTS = SEGS * 6;
  let totalCols = 0;
  for (const ring of layout.rings) totalCols += ring.columns.length;
  const nCells = sectors.length * totalCols;
  const positions = new Float32Array(nCells * VERTS * 3);
  const vertexColors = new Float32Array(nCells * VERTS * 4);
  const cells = new Array(nCells);
  let ci = 0, pi = 0, vi = 0;
  for (const sector of sectors) {
    // unwrap a0..a1 around theta so wrapped sectors stay contiguous
    const span = sector.span;
    const a0 = sector.theta - (sector.w0 ?? span / 2);
    for (const ring of layout.rings) {
      for (const col of ring.columns) {
        const rgba = colors(sector.leaf, ring.id, col.id) || ZERO_RGBA;
        const v0 = pi / 3;
        // angular quad strip → SEGS × 2 triangles, written directly
        for (let s = 0; s < SEGS; s++) {
          const an0 = a0 + (span * s) / SEGS;
          const an1 = a0 + (span * (s + 1)) / SEGS;
          const c0 = Math.cos(an0) * col.r0, s0 = Math.sin(an0) * col.r0;
          const C0 = Math.cos(an0) * col.r1, S0 = Math.sin(an0) * col.r1;
          const c1 = Math.cos(an1) * col.r0, s1 = Math.sin(an1) * col.r0;
          const C1 = Math.cos(an1) * col.r1, S1 = Math.sin(an1) * col.r1;
          positions[pi++] = c0; positions[pi++] = y; positions[pi++] = s0;
          positions[pi++] = C1; positions[pi++] = y; positions[pi++] = S1;
          positions[pi++] = c1; positions[pi++] = y; positions[pi++] = s1;
          positions[pi++] = c0; positions[pi++] = y; positions[pi++] = s0;
          positions[pi++] = C0; positions[pi++] = y; positions[pi++] = S0;
          positions[pi++] = C1; positions[pi++] = y; positions[pi++] = S1;
          for (let k = 0; k < 6; k++) {
            vertexColors[vi++] = rgba[0]; vertexColors[vi++] = rgba[1];
            vertexColors[vi++] = rgba[2]; vertexColors[vi++] = rgba[3];
          }
        }
        cells[ci++] = { ring: ring.id, column: col.id, leaf: sector.leaf, v0 };
      }
    }
  }
  return { positions, vertexColors, cells, verticesPerCell: VERTS };
}
const ZERO_RGBA = [0, 0, 0, 0];
