// Pure, renderer-independent algorithms shared by visualization plugins.
// Keeping these functions free of THREE makes them straightforward to unit test.

/** Parse a rooted Newick string, including branch lengths and quoted labels. */
export function parseNewick(source) {
  const s = String(source || '').trim();
  if (!s) throw new Error('Newick 数据为空');
  let i = 0;

  const skip = () => { while (i < s.length && /\s/.test(s[i])) i++; };
  const fail = (message) => { throw new Error(`Newick 解析失败（字符 ${i + 1}）：${message}`); };

  function parseLabel() {
    skip();
    if (s[i] === "'" || s[i] === '"') {
      const quote = s[i++];
      let out = '';
      while (i < s.length) {
        const ch = s[i++];
        if (ch === quote) {
          if (s[i] === quote) { out += quote; i++; continue; }
          return out;
        }
        out += ch;
      }
      fail('引号未闭合');
    }
    const start = i;
    while (i < s.length && !/[\s(),:;]/.test(s[i])) i++;
    return s.slice(start, i);
  }

  function parseNode() {
    skip();
    const node = { name: '', length: 0, children: [] };
    if (s[i] === '(') {
      i++;
      skip();
      while (true) {
        node.children.push(parseNode());
        skip();
        if (s[i] === ',') { i++; continue; }
        if (s[i] === ')') { i++; break; }
        fail('子树之间需要逗号，且括号必须闭合');
      }
    }
    node.name = parseLabel();
    skip();
    if (s[i] === ':') {
      i++;
      skip();
      const match = s.slice(i).match(/^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?/);
      if (!match) fail('分支长度不是有效数字');
      node.length = Number(match[0]);
      if (!Number.isFinite(node.length) || node.length < 0) fail('分支长度必须是非负有限数');
      i += match[0].length;
    }
    return node;
  }

  const root = parseNode();
  skip();
  if (s[i] === ';') i++;
  skip();
  if (i !== s.length) fail('根节点之后存在无法识别的内容');
  return root;
}

/**
 * Rectangular phylogram layout. X is cumulative branch length, Y is leaf order.
 * No biological value is assigned to Z; plugins may still render the plane in 3D.
 */
export function layoutPhylogeny(root) {  const nodes = [];
  const links = [];
  const leaves = [];
  let nextLeaf = 0;
  let maxDepth = 0;

  function visit(raw, parent = null) {
    const branchLength = parent ? Math.max(0, Number(raw.length) || 0) : 0;
    const node = {
      id: nodes.length,
      name: raw.name || '',
      raw,
      parent,
      children: [],
      branchLength,
      depth: (parent?.depth || 0) + branchLength,
      leafCount: 0,
      x: 0,
      y: 0,
    };
    nodes.push(node);
    if (parent) {
      parent.children.push(node);
      links.push({ source: parent, target: node });
    }
    if (raw.children?.length) {
      for (const child of raw.children) visit(child, node);
      node.leafCount = node.children.reduce((sum, child) => sum + child.leafCount, 0);
      node.y = node.children.reduce((sum, child) => sum + child.y, 0) / node.children.length;
    } else {
      node.leafIndex = nextLeaf++;
      node.leafCount = 1;
      node.y = node.leafIndex;
      leaves.push(node);
    }
    maxDepth = Math.max(maxDepth, node.depth);
    return node;
  }

  visit(root);
  const yMid = (nextLeaf - 1) / 2;
  for (const node of nodes) node.y = (node.y - yMid) * 1.18;
  return { root: nodes[0], nodes, links, leaves, maxDepth, leafCount: leaves.length };
}

/**
 * Radial phylogram layout in 3D — the FigTree radial convention extended to a
 * branching spatial structure. Radial distance from the origin (the root) is
 * strictly cumulative branch length. Directions follow botanical branching:
 * every child deviates from its parent's direction by a fixed spread angle at
 * a deterministic golden-angle azimuth, so the tree grows outward through 3D
 * space the way a force-directed network diffuses. Directions (including the
 * Z axis) carry no biological meaning — exactly like the angular placement of
 * a 2D radial tree. Branch segments rendered as straight chords follow the
 * same reading rule as 2D radial trees.
 */
export function layoutPhylogenyRadial3D(root) {
  const nodes = [], links = [], leaves = [];
  let maxDepth = 0;
  const GOLDEN = Math.PI * (1 + Math.sqrt(5));

  function visit(raw, parent = null) {
    const branchLength = parent ? Math.max(0, Number(raw.length) || 0) : 0;
    const node = {
      id: nodes.length,
      name: raw.name || '',
      raw,
      parent,
      children: [],
      branchLength,
      depth: (parent?.depth || 0) + branchLength,
      leafCount: 0,
      direction: null,
    };
    nodes.push(node);
    if (parent) {
      parent.children.push(node);
      links.push({ source: parent, target: node });
    }
    if (raw.children?.length) {
      for (const child of raw.children) visit(child, node);
      node.leafCount = node.children.reduce((sum, child) => sum + child.leafCount, 0);
    } else {
      node.leafCount = 1;
      leaves.push(node);
    }
    maxDepth = Math.max(maxDepth, node.depth);
    return node;
  }
  visit(root);

  const normalize = v => {
    const length = Math.hypot(v.x, v.y, v.z) || 1;
    return { x: v.x / length, y: v.y / length, z: v.z / length };
  };
  // Orthonormal frame around a direction: u, v perpendicular to d and to each other.
  function frame(d) {
    const up = Math.abs(d.y) > 0.92 ? { x: 1, y: 0, z: 0 } : { x: 0, y: 1, z: 0 };
    const u = normalize({
      x: up.y * d.z - up.z * d.y,
      y: up.z * d.x - up.x * d.z,
      z: up.x * d.y - up.y * d.x,
    });
    return {
      u,
      v: {
        x: d.y * u.z - d.z * u.y,
        y: d.z * u.x - d.x * u.z,
        z: d.x * u.y - d.y * u.x,
      },
    };
  }
  const spreadFor = count => (count <= 1 ? 0.34 : Math.min(0.85, 0.5 + 0.12 * count));

  function assign(node, direction) {
    node.direction = direction;
    if (!node.children.length) return;
    const { u, v } = frame(direction);
    const spread = spreadFor(node.children.length);
    node.children.forEach((child, i) => {
      const azimuth = (Math.PI * 2 * i) / node.children.length + GOLDEN * node.id;
      const cos = Math.cos(spread), sin = Math.sin(spread);
      const ca = Math.cos(azimuth), sa = Math.sin(azimuth);
      assign(child, normalize({
        x: direction.x * cos + (u.x * ca + v.x * sa) * sin,
        y: direction.y * cos + (u.y * ca + v.y * sa) * sin,
        z: direction.z * cos + (u.z * ca + v.z * sa) * sin,
      }));
    });
  }
  assign(nodes[0], normalize({ x: 0.2, y: 0.85, z: 0.5 }));

  return { root: nodes[0], nodes, links, leaves, maxDepth, leafCount: leaves.length };
}

/**
 * Classic 2D radial phylogram (FigTree "radial"): leaves are spread evenly by
 * leaf order around the circle, an internal node sits at the mean angle of its
 * children, and the distance from the centre (the root) is cumulative branch
 * length scaled so the deepest leaf reaches `radius`. Only the radius carries
 * data; angular placement follows leaf order exactly as in a 2D radial tree.
 */
export function layoutPhylogenyRadial2D(root, { radius = 10, gap = 0.06, forceCladogram = false } = {}) {
  const tree = layoutPhylogeny(root);
  const leafCount = Math.max(1, tree.leafCount);
  const sweep = Math.PI * 2 * (1 - gap);
  const start = Math.PI / 2 + (Math.PI * 2 * gap) / 2;
  // without any branch length the tree is a cladogram: fall back to
  // topological generation for the radius and flag it for the caller
  const cladogram = forceCladogram || !(tree.maxDepth > 0);
  for (const node of tree.nodes) node.gen = node.parent ? node.parent.gen + 1 : 0;
  const maxGen = Math.max(1, ...tree.nodes.map(node => node.gen));
  const scale = cladogram ? radius / maxGen : radius / tree.maxDepth;
  function place(node) {
    if (node.children.length) {
      for (const child of node.children) place(child);
      node.angle = node.children.reduce((sum, child) => sum + child.angle, 0) / node.children.length;
    } else {
      node.angle = start + (leafCount === 1 ? 0 : (node.leafIndex / leafCount) * sweep);
    }
    node.radius = (cladogram ? node.gen : node.depth) * scale;
    node.x = Math.cos(node.angle) * node.radius;
    node.y = Math.sin(node.angle) * node.radius;
  }
  place(tree.root);
  return { ...tree, radius, cladogram };
}

/**
 * Unrooted equal-angle layout (Felsenstein): every subtree receives an angular
 * wedge proportional to its leaf count and each branch is drawn along the
 * middle of its wedge with length equal to its branch length. Branches never
 * cross and the tree spreads over the whole plane instead of a ring. Without
 * branch lengths every branch gets unit length (`cladogram: true`).
 */
export function layoutPhylogenyEqualAngle(root, { radius = 10 } = {}) {
  const tree = layoutPhylogeny(root);
  const cladogram = !(tree.maxDepth > 0);
  const length = node => (cladogram ? 1 : node.branchLength);
  tree.root.x = 0;
  tree.root.y = 0;
  (function place(node, start, wedge) {
    let cursor = start;
    for (const child of node.children) {
      const share = wedge * child.leafCount / node.leafCount;
      const angle = cursor + share / 2;
      child.angle = angle;
      child.x = node.x + Math.cos(angle) * length(child);
      child.y = node.y + Math.sin(angle) * length(child);
      place(child, cursor, share);
      cursor += share;
    }
  })(tree.root, 0, Math.PI * 2);
  const extent = Math.max(1e-9, ...tree.nodes.map(node => Math.hypot(node.x, node.y)));
  for (const node of tree.nodes) {
    node.x *= radius / extent;
    node.y *= radius / extent;
  }
  return { ...tree, radius, cladogram, unitScale: radius / extent };
}

/**
 * Centre of a weighted tree: the node whose largest path distance to any other
 * node is smallest (ties → higher degree → lower index). Also returns the
 * cumulative path distance and hop count from that centre to every node.
 */
export function treeCentre(count, edges) {
  const adjacency = Array.from({ length: count }, () => []);
  for (const edge of edges) {
    const w = Math.max(0, Number(edge.distance) || 0);
    adjacency[edge.source].push([edge.target, w]);
    adjacency[edge.target].push([edge.source, w]);
  }
  const walk = start => {
    const dist = new Array(count).fill(Infinity), hops = new Array(count).fill(Infinity);
    const parent = new Array(count).fill(-1), order = [start];
    dist[start] = 0; hops[start] = 0;
    for (let k = 0; k < order.length; k++) {
      const u = order[k];
      for (const [v, w] of adjacency[u]) {
        if (dist[v] !== Infinity) continue;
        dist[v] = dist[u] + w; hops[v] = hops[u] + 1; parent[v] = u;
        order.push(v);
      }
    }
    return { dist, hops, parent, order };
  };
  let best = 0, bestEcc = Infinity;
  for (let i = 0; i < count; i++) {
    const { dist } = walk(i);
    const reachable = dist.filter(Number.isFinite);
    const ecc = Math.max(...reachable) + (count - reachable.length) * 1e9;
    const better = ecc < bestEcc - 1e-9 ||
      (Math.abs(ecc - bestEcc) <= 1e-9 && adjacency[i].length > adjacency[best].length);
    if (better) { best = i; bestEcc = ecc; }
  }
  return { centre: best, ...walk(best), adjacency };
}

/**
 * GrapeTree-style radial layout of a spanning tree around its centre: each
 * subtree receives a wedge proportional to its node count; a node sits
 * `base + distance` away from its parent along the middle of its wedge, where
 * `base = minLength × median positive distance` keeps zero-distance (identical
 * profile) neighbours apart. Disconnected nodes are placed on an outer ring.
 */
export function layoutTreeRadial(count, edges, { radius = 10, minLength = 0.35, edgeScale = 'linear' } = {}) {
  const { centre, dist, hops, parent, order } = treeCentre(count, edges);
  const children = Array.from({ length: count }, () => []);
  for (const v of order) if (parent[v] >= 0) children[parent[v]].push(v);
  const size = new Array(count).fill(1);
  for (let k = order.length - 1; k >= 0; k--) {
    const v = order[k];
    if (parent[v] >= 0) size[parent[v]] += size[v];
  }
  const weightOf = new Map();
  for (const edge of edges) {
    const w = Math.max(0, Number(edge.distance) || 0);
    weightOf.set(`${edge.source}:${edge.target}`, w);
    weightOf.set(`${edge.target}:${edge.source}`, w);
  }
  const positive = edges.map(edge => Number(edge.distance)).filter(w => w > 0).sort((a, b) => a - b);
  const base = minLength * (positive[Math.floor(positive.length / 2)] || 1);
  // display length of an edge grows with its allele distance; `edgeScale`
  // compresses large weights so long branches stay readable (cgMLST).
  // The mapping is normalized so the median positive weight keeps its
  // linear length — shorter branches get room, longer ones shrink.
  const squash = w => (edgeScale === 'log' ? Math.log2(1 + w) : edgeScale === 'sqrt' ? Math.sqrt(w) : w);
  const med = positive[Math.floor(positive.length / 2)] || 1;
  const squashUnit = squash(med) > 0 ? med / squash(med) : 1;
  const points = Array.from({ length: count }, () => ({ x: 0, y: 0 }));
  (function place(u, start, wedge) {
    let cursor = start;
    const total = children[u].reduce((s, v) => s + size[v], 0) || 1;
    for (const v of children[u]) {
      const share = wedge * size[v] / total;
      const angle = cursor + share / 2;
      const len = base + squash(weightOf.get(`${u}:${v}`)) * squashUnit;
      points[v] = { x: points[u].x + Math.cos(angle) * len, y: points[u].y + Math.sin(angle) * len };
      place(v, cursor, share);
      cursor += share;
    }
  })(centre, 0, Math.PI * 2);
  const extent = Math.max(1e-9, ...order.map(v => Math.hypot(points[v].x, points[v].y)));
  const scale = radius / extent;
  const orphans = [];
  for (let i = 0; i < count; i++) if (!Number.isFinite(dist[i])) orphans.push(i);
  orphans.forEach((v, k) => {
    const a = (k / orphans.length) * Math.PI * 2;
    points[v] = { x: Math.cos(a) * extent * 1.15, y: Math.sin(a) * extent * 1.15 };
  });
  return {
    centre, dist, hops,
    points: points.map(p => ({ x: p.x * scale, y: p.y * scale })),
  };
}

/**
 * GrapeTree-style force layout: start from the radial static layout (so every
 * branch already points outward in its own wedge) and relax it with springs
 * whose rest length follows the allele distance, short-range repulsion that
 * only untangles local crowding, and a weak anchor to the starting point.
 * Branches keep their overall direction instead of folding back on
 * themselves, while clusters gain an organic, less schematic shape.
 * After every step a node that drifted behind its parent branch is projected
 * back in front of it (parents first), so branches never fold back.
 */
export function layoutTreeForce(count, edges, { radius = 10, iterations = 220, anchor = 0.012, edgeScale = 'linear' } = {}) {
  const start = layoutTreeRadial(count, edges, { radius, edgeScale });
  const { parent, order } = treeCentre(count, edges);
  const points = start.points.map(p => ({ x: p.x, y: p.y }));
  const init = start.points;
  // rest lengths in world units: the radial layout's own edge lengths
  const rest = edges.map(edge => Math.max(1e-3, Math.hypot(
    init[edge.source].x - init[edge.target].x, init[edge.source].y - init[edge.target].y)));
  const sorted = rest.slice().sort((a, b) => a - b);
  const typical = sorted[Math.floor(sorted.length / 2)] || radius / 10;
  const cutoff = typical * 2.2, cutoff2 = cutoff * cutoff;
  const strength = typical * typical * 0.35;
  for (let iter = 0; iter < iterations; iter++) {
    const force = points.map(() => ({ x: 0, y: 0 }));
    for (let i = 0; i < count; i++) {
      for (let j = i + 1; j < count; j++) {
        let dx = points[i].x - points[j].x, dy = points[i].y - points[j].y;
        let d2 = dx * dx + dy * dy;
        if (d2 > cutoff2) continue;
        if (d2 < 1e-6) { dx = 1e-3 * (i - j); dy = 1e-3 * (i + j + 1); d2 = dx * dx + dy * dy; }
        const d = Math.sqrt(d2);
        const repel = Math.min(typical, strength / d2) * (1 - d / cutoff);
        force[i].x += (dx / d) * repel; force[i].y += (dy / d) * repel;
        force[j].x -= (dx / d) * repel; force[j].y -= (dy / d) * repel;
      }
    }
    edges.forEach((edge, e) => {
      const a = points[edge.source], b = points[edge.target];
      const dx = b.x - a.x, dy = b.y - a.y;
      const d = Math.max(1e-6, Math.hypot(dx, dy));
      const f = (d - rest[e]) * 0.25;
      force[edge.source].x += (dx / d) * f; force[edge.source].y += (dy / d) * f;
      force[edge.target].x -= (dx / d) * f; force[edge.target].y -= (dy / d) * f;
    });
    const cooling = 0.5 * (1 - iter / iterations) + 0.05;
    const cap = typical * 0.5;
    for (let i = 0; i < count; i++) {
      force[i].x += (init[i].x - points[i].x) * anchor;
      force[i].y += (init[i].y - points[i].y) * anchor;
      points[i].x += clamp(force[i].x, -cap, cap) * cooling;
      points[i].y += clamp(force[i].y, -cap, cap) * cooling;
    }
    // directional persistence (hard): keep each node ahead of its parent branch
    for (const v of order) {
      const p = parent[v];
      const g = p >= 0 ? parent[p] : -1;
      if (g < 0) continue;
      const ux = points[p].x - points[g].x, uy = points[p].y - points[g].y;
      const lu = Math.hypot(ux, uy);
      if (lu < 1e-9) continue;
      const along = ((points[v].x - points[p].x) * ux + (points[v].y - points[p].y) * uy) / lu;
      const want = typical * 0.12;
      if (along < want) {
        points[v].x += (ux / lu) * (want - along);
        points[v].y += (uy / lu) * (want - along);
      }
    }
  }
  const c = points[start.centre];
  const shifted = points.map(p => ({ x: p.x - c.x, y: p.y - c.y }));
  const extent = Math.max(1e-9, ...shifted.map(p => Math.hypot(p.x, p.y)));
  return { ...start, points: shifted.map(p => ({ x: p.x * radius / extent, y: p.y * radius / extent })) };
}

/**
 * Classify metadata fields for the colour / height pickers. A field is
 * `numeric` when every present value is a finite number and it has more than
 * two distinct values; `categorical` when it has 2..maxCategories distinct
 * values. Fields that are unique per record (IDs) are neither.
 */
export function classifyMetadataFields(records, { maxCategories = 24 } = {}) {
  const fields = new Map();
  for (const record of records) {
    for (const [key, raw] of Object.entries(record || {})) {
      if (raw === null || raw === undefined || raw === '' || typeof raw === 'object') continue;
      if (!fields.has(key)) fields.set(key, []);
      fields.get(key).push(raw);
    }
  }
  const result = [];
  for (const [key, values] of fields) {
    const distinct = new Set(values.map(String));
    const numeric = values.every(v => typeof v === 'number' ? Number.isFinite(v) : /^-?\d+(\.\d+)?$/.test(String(v).trim()));
    const idLike = distinct.size === records.length && records.length > maxCategories;
    result.push({
      key,
      present: values.length,
      distinct: distinct.size,
      numeric: numeric && distinct.size > 2,
      categorical: !idLike && distinct.size >= 2 && distinct.size <= maxCategories,
    });
  }
  return result.sort((a, b) => a.key.localeCompare(b.key));
}

/**
 * Deterministic deck height per category: the largest group takes the centre
 * deck and the rest alternate above / below it (+1, −1, +2, …), ties broken by
 * name. With a single category every node lands on height 0 (a flat disc).
 * Height encodes category membership only — never a quantity.
 */
export function groupLayers(groups, { gap = 2.4, maxSpan = 8 } = {}) {
  const counts = new Map();
  for (const group of groups) counts.set(group, (counts.get(group) || 0) + 1);
  const ordered = [...counts.entries()]
    .sort((a, b) => b[1] - a[1] || String(a[0]).localeCompare(String(b[0])))
    .map(([group]) => group);
  const step = ordered.length > 1 ? Math.min(gap, maxSpan / (ordered.length - 1)) : 0;
  const layers = new Map();
  ordered.forEach((group, i) => {
    const slot = i === 0 ? 0 : (i % 2 ? 1 : -1) * Math.ceil(i / 2);
    layers.set(group, { group, height: slot * step, count: counts.get(group), order: i });
  });
  return layers;
}

/**
 * Deck heights for tree nodes: leaves take their group's deck; an internal node
 * takes the mean height of its descendant leaves, so a pure clade sits on its
 * own deck and mixed ancestral branches climb between decks.
 */
export function treeLayerHeights(tree, leafHeight) {
  const heights = new Map(), sums = new Map();
  function visit(node) {
    if (!node.children.length) {
      const h = Number(leafHeight(node)) || 0;
      sums.set(node.id, { sum: h, count: 1 });
      heights.set(node.id, h);
      return;
    }
    let sum = 0, count = 0;
    for (const child of node.children) {
      visit(child);
      const s = sums.get(child.id);
      sum += s.sum; count += s.count;
    }
    sums.set(node.id, { sum, count });
    heights.set(node.id, count ? sum / count : 0);
  }
  visit(tree.root);
  return heights;
}

/** Hamming distance between two categorical allele profiles. */
export function profileDistance(a, b) {
  if (!Array.isArray(a) || !Array.isArray(b) || a.length !== b.length) {
    throw new Error('MLST 等位基因谱必须具有相同位点数');
  }
  let d = 0;
  for (let i = 0; i < a.length; i++) if (String(a[i]) !== String(b[i])) d++;
  return d;
}

/** Kruskal MST over the complete pairwise allele-distance graph. */
export function minimumSpanningTree(isolates) {
  if (!Array.isArray(isolates) || isolates.length < 2) return [];
  const candidates = [];
  for (let i = 0; i < isolates.length; i++) {
    for (let j = i + 1; j < isolates.length; j++) {
      candidates.push({ source: i, target: j, distance: profileDistance(isolates[i].profile, isolates[j].profile) });
    }
  }
  candidates.sort((a, b) => a.distance - b.distance ||
    String(isolates[a.source].id).localeCompare(String(isolates[b.source].id)) ||
    String(isolates[a.target].id).localeCompare(String(isolates[b.target].id)));

  const parent = isolates.map((_, i) => i);
  const rank = isolates.map(() => 0);
  const find = (x) => {
    let root = x;
    while (parent[root] !== root) root = parent[root];
    while (parent[x] !== x) { const next = parent[x]; parent[x] = root; x = next; }
    return root;
  };
  const union = (a, b) => {
    a = find(a); b = find(b);
    if (a === b) return false;
    if (rank[a] < rank[b]) [a, b] = [b, a];
    parent[b] = a;
    if (rank[a] === rank[b]) rank[a]++;
    return true;
  };

  const edges = [];
  for (const edge of candidates) {
    if (union(edge.source, edge.target)) edges.push(edge);
    if (edges.length === isolates.length - 1) break;
  }
  return edges;
}

/** Deterministic small-graph force layout, run once before rendering. */
export function forceLayout(nodes, edges, { iterations = 260, width = 18, height = 11 } = {}) {
  const points = nodes.map((_, i) => {
    const a = i * 2.399963229728653;
    const r = Math.sqrt(i + 0.5) * 1.25;
    return { x: Math.cos(a) * r, y: Math.sin(a) * r };
  });
  for (let iter = 0; iter < iterations; iter++) {
    const force = nodes.map(() => ({ x: 0, y: 0 }));
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        let dx = points[i].x - points[j].x;
        let dy = points[i].y - points[j].y;
        let d2 = dx * dx + dy * dy;
        if (d2 < 0.01) { dx = 0.01 * (i + 1); dy = 0.01 * (j + 1); d2 = dx * dx + dy * dy; }
        const d = Math.sqrt(d2);
        const repel = Math.min(1.2, 3.6 / d2);
        const fx = (dx / d) * repel, fy = (dy / d) * repel;
        force[i].x += fx; force[i].y += fy;
        force[j].x -= fx; force[j].y -= fy;
      }
    }
    for (const e of edges) {
      const a = points[e.source], b = points[e.target];
      const dx = b.x - a.x, dy = b.y - a.y;
      const d = Math.max(0.001, Math.hypot(dx, dy));
      const desired = 2.5 + e.distance * 0.28;
      const f = (d - desired) * 0.035;
      const fx = (dx / d) * f, fy = (dy / d) * f;
      force[e.source].x += fx; force[e.source].y += fy;
      force[e.target].x -= fx; force[e.target].y -= fy;
    }
    const cooling = 0.62 * (1 - iter / iterations) + 0.06;
    for (let i = 0; i < points.length; i++) {
      force[i].x -= points[i].x * 0.002;
      force[i].y -= points[i].y * 0.002;
      const cap = 0.55;
      points[i].x += Math.max(-cap, Math.min(cap, force[i].x)) * cooling;
      points[i].y += Math.max(-cap, Math.min(cap, force[i].y)) * cooling;
    }
  }

  const xs = points.map(p => p.x), ys = points.map(p => p.y);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  const scale = Math.min(width / Math.max(0.001, maxX - minX), height / Math.max(0.001, maxY - minY));
  const cx = (minX + maxX) / 2, cy = (minY + maxY) / 2;
  return points.map(p => ({ x: (p.x - cx) * scale, y: (p.y - cy) * scale, z: 0 }));
}

/**
 * Deterministic 3D force layout for network views. Positions are display-only:
 * depth carries no biological meaning, it only spreads the graph for legibility.
 * `repulsion` and `springStiffness` tune the charge/spring balance — larger,
 * community-structured graphs (e.g. phylogenies) want weaker charge and
 * stiffer springs so clades condense into knots.
 */
export function forceLayout3D(nodes, edges, { iterations = 300, radius = 9, repulsion = 3.6, springStiffness = 0.035 } = {}) {
  const count = nodes.length;
  const points = nodes.map((_, i) => {
    // Fibonacci-sphere seeding keeps the initial state deterministic and isotropic.
    const k = i + 0.5;
    const phi = Math.acos(1 - (2 * k) / count);
    const theta = Math.PI * (1 + Math.sqrt(5)) * k;
    const r = radius * 0.92 * Math.cbrt(k / count);
    return {
      x: r * Math.cos(theta) * Math.sin(phi),
      y: r * Math.sin(theta) * Math.sin(phi),
      z: r * Math.cos(phi),
    };
  });
  for (let iter = 0; iter < iterations; iter++) {
    const force = nodes.map(() => ({ x: 0, y: 0, z: 0 }));
    for (let i = 0; i < count; i++) {
      for (let j = i + 1; j < count; j++) {
        let dx = points[i].x - points[j].x;
        let dy = points[i].y - points[j].y;
        let dz = points[i].z - points[j].z;
        let d2 = dx * dx + dy * dy + dz * dz;
        if (d2 < 0.01) { dx = 0.01 * (i + 1); dy = 0.01 * (j + 1); dz = 0.011 * (i + j + 1); d2 = dx * dx + dy * dy + dz * dz; }
        const d = Math.sqrt(d2);
        const repel = Math.min(repulsion / 3, repulsion / d2);
        const fx = (dx / d) * repel, fy = (dy / d) * repel, fz = (dz / d) * repel;
        force[i].x += fx; force[i].y += fy; force[i].z += fz;
        force[j].x -= fx; force[j].y -= fy; force[j].z -= fz;
      }
    }
    for (const e of edges) {
      const a = points[e.source], b = points[e.target];
      const dx = b.x - a.x, dy = b.y - a.y, dz = b.z - a.z;
      const d = Math.max(0.001, Math.sqrt(dx * dx + dy * dy + dz * dz));
      const desired = 2.5 + e.distance * 0.28;
      const f = (d - desired) * springStiffness;
      const fx = (dx / d) * f, fy = (dy / d) * f, fz = (dz / d) * f;
      force[e.source].x += fx; force[e.source].y += fy; force[e.source].z += fz;
      force[e.target].x -= fx; force[e.target].y -= fy; force[e.target].z -= fz;
    }
    const cooling = 0.62 * (1 - iter / iterations) + 0.06;
    for (let i = 0; i < count; i++) {
      force[i].x -= points[i].x * 0.002;
      force[i].y -= points[i].y * 0.002;
      force[i].z -= points[i].z * 0.002;
      const cap = 0.55;
      points[i].x += Math.max(-cap, Math.min(cap, force[i].x)) * cooling;
      points[i].y += Math.max(-cap, Math.min(cap, force[i].y)) * cooling;
      points[i].z += Math.max(-cap, Math.min(cap, force[i].z)) * cooling;
    }
  }

  const cx = points.reduce((sum, p) => sum + p.x, 0) / count;
  const cy = points.reduce((sum, p) => sum + p.y, 0) / count;
  const cz = points.reduce((sum, p) => sum + p.z, 0) / count;
  const maxR = Math.max(0.001, ...points.map(p => Math.hypot(p.x - cx, p.y - cy, p.z - cz)));
  const scale = radius / maxR;
  return points.map(p => ({ x: (p.x - cx) * scale, y: (p.y - cy) * scale, z: (p.z - cz) * scale }));
}

export const clamp = (value, min, max) => Math.max(min, Math.min(max, value));

/** Deep copy of a raw Newick tree ({ name, length, children, support? }). */
export function cloneTree(node) {
  const copy = { name: node.name || '', length: node.length || 0, children: [] };
  if (node.support !== undefined) copy.support = node.support;
  if (node.rootSplitTwin) copy.rootSplitTwin = true;
  copy.children = (node.children || []).map(cloneTree);
  return copy;
}

/**
 * Attach parsed support values to a copy of the raw tree. With `support`
 * declared, every internal non-root node's label is split on '/' into
 * `node.support = { values, labels, raw }` and `node.name` is cleared;
 * non-numeric parts become null. Without `support`, nodes are untouched.
 * Leaves never receive support values.
 */
export function annotateSupport(raw, support) {
  const copy = cloneTree(raw);
  if (!support || !Array.isArray(support.labels) || !support.labels.length) return copy;
  (function walk(node, isRoot) {
    if (node.children.length) {
      if (!isRoot && node.name) {
        const parts = node.name.split('/');
        node.support = {
          values: parts.map(part => {
            const value = Number(part);
            return part !== '' && Number.isFinite(value) ? value : null;
          }),
          labels: support.labels,
          raw: node.name,
        };
        node.name = '';
      }
      node.children.forEach(child => walk(child, false));
    }
  })(copy, true);
  return copy;
}

/**
 * Path of child indices from the root to the node at `dfsIndex` in DFS
 * pre-order — the same order `layoutPhylogeny` uses for node ids, so a layout
 * node's `id` maps directly to a reroot path. Returns [] for the root.
 */
export function nodePath(raw, dfsIndex) {
  let cursor = -1;
  let found = null;
  (function walk(node, trail) {
    if (found) return;
    cursor += 1;
    if (cursor === dfsIndex) { found = trail; return; }
    node.children.forEach((child, i) => walk(child, [...trail, i]));
  })(raw, []);
  if (!found) throw new Error(`nodePath：DFS 序号 ${dfsIndex} 超出节点范围`);
  return found;
}

/**
 * Re-root the tree on the branch above the node reached by `path` (child
 * indices from the current root; [] — the root itself — is rejected). The new
 * root is inserted at fraction `t` along that branch: `t * L` towards the
 * target node, `(1 - t) * L` towards the rest. Edges along the path are
 * reversed and branch attributes (`length`, `support`) travel with the
 * branch, not the node. A degree-2 old root is suppressed by merging its two
 * incident branches (lengths summed; both merged halves describe the same
 * bipartition, so the non-null support is kept, preferring the path side
 * stored on the suppressed node). Both halves of the new root branch carry
 * the same support object; the far half is flagged `rootSplitTwin` so views
 * can label it once. The input is never mutated.
 */
export function rerootTree(raw, path, t = 0.5) {
  if (!Array.isArray(path) || !path.length) throw new Error('rerootTree：不能对当前根节点改根（path 为空）');
  const fraction = Number(t);
  if (!Number.isFinite(fraction) || fraction < 0 || fraction > 1) {
    throw new Error('rerootTree：t 必须是 [0,1] 内的数字');
  }
  const root = cloneTree(raw);
  // only the far half of the NEW root branch may stay flagged: clear stale
  // twin marks left over from a previous reroot
  (function clearTwins(node) { delete node.rootSplitTwin; node.children.forEach(clearTwins); })(root);

  const chain = [root];
  for (const index of path) {
    const next = chain[chain.length - 1].children[index];
    if (!next) throw new Error(`rerootTree：path ${JSON.stringify(path)} 超出树的范围`);
    chain.push(next);
  }
  const target = chain[chain.length - 1];
  const splitLength = target.length || 0;
  const splitSupport = target.support;

  // Reverse edges m_j -> m_{j+1} for j = 0..k-2 (the last edge is split, not
  // reversed): m_{j+1} adopts m_j, and the branch attributes that were stored
  // on the child move onto the new child (the old parent).
  for (let j = 0; j < chain.length - 2; j++) {
    const parent = chain[j];
    const child = chain[j + 1];
    const length = child.length;
    const support = child.support;
    child.children.push(parent);
    parent.children = parent.children.filter(node => node !== child);
    parent.length = length;
    if (support !== undefined) parent.support = support;
    else delete parent.support;
  }

  // Split the last edge: the new root sits between `target` and its old parent.
  const parent = chain[chain.length - 2];
  parent.children = parent.children.filter(node => node !== target);
  const newRoot = { name: '', length: 0, children: [target, parent] };
  target.length = splitLength * fraction;
  parent.length = splitLength * (1 - fraction);
  if (splitSupport !== undefined) parent.support = splitSupport;
  else delete parent.support;
  parent.rootSplitTwin = true;

  // Suppress a degree-2 old root: its remaining child takes over the merged
  // branch. The two merged branches describe the same bipartition, so keep
  // whichever support is non-null, preferring the path side (the attribute
  // stored on the suppressed node itself).
  const oldRoot = chain[0];
  if (oldRoot.children.length === 1) {
    const survivor = oldRoot.children[0];
    // old root's new parent: the first reversed node for longer paths,
    // otherwise the new root itself (path length 1).
    const holder = chain.length > 2 ? chain[1] : newRoot;
    survivor.length = (survivor.length || 0) + (oldRoot.length || 0);
    const informative = support => !!support?.values?.some(value => value !== null);
    if (informative(oldRoot.support) || !informative(survivor.support)) {
      if (oldRoot.support !== undefined) survivor.support = oldRoot.support;
    }
    if (oldRoot.rootSplitTwin) survivor.rootSplitTwin = true;
    holder.children = holder.children.map(node => (node === oldRoot ? survivor : node));
  }
  return newRoot;
}

/**
 * Midpoint root: place the root at the midpoint of the tree's diameter (the
 * longest patristic leaf-to-leaf path). Returns { tree, path, t } — tree is
 * the already-rerooted copy, and path/t reproduce it via `rerootTree`.
 * Endpoint ties are broken by DFS leaf order, so the result is deterministic.
 * Throws when the tree has no usable branch lengths (a pure cladogram).
 */
export function midpointRoot(raw) {
  const nodes = [];
  const adjacency = [];
  (function walk(node, parentIndex) {
    const index = nodes.length;
    nodes.push(node);
    adjacency.push([]);
    if (parentIndex >= 0) {
      const w = Math.max(0, Number(node.length) || 0);
      adjacency[parentIndex].push([index, w]);
      adjacency[index].push([parentIndex, w]);
    }
    node.children.forEach(child => walk(child, index));
  })(raw, -1);

  const totalLength = adjacency.flat().reduce((sum, [, w]) => sum + w, 0) / 2;
  if (!(totalLength > 0)) {
    throw new Error('Midpoint 根需要分支长度：该树没有可用分支长度（cladogram），无法计算根距');
  }
  const isLeaf = nodes.map(node => !node.children.length);
  // DFS leaf order = order of first appearance in `nodes` (built in DFS).
  const leafRank = new Map();
  {
    let rank = 0;
    nodes.forEach((node, i) => { if (isLeaf[i]) leafRank.set(i, rank++); });
  }

  const farthest = start => {
    const dist = new Array(nodes.length).fill(Infinity);
    const parent = new Array(nodes.length).fill(-1);
    dist[start] = 0;
    const order = [start];
    for (let k = 0; k < order.length; k++) {
      const u = order[k];
      for (const [v, w] of adjacency[u]) {
        if (dist[v] !== Infinity) continue;
        dist[v] = dist[u] + w;
        parent[v] = u;
        order.push(v);
      }
    }
    let best = -1;
    for (let i = 0; i < nodes.length; i++) {
      if (!isLeaf[i] || dist[i] === Infinity) continue;
      if (best < 0 || dist[i] > dist[best] + 1e-12
        || (Math.abs(dist[i] - dist[best]) <= 1e-12 && leafRank.get(i) < leafRank.get(best))) best = i;
    }
    return { best, dist, parent };
  };

  const a = farthest(nodes.findIndex((_, i) => isLeaf[i])).best;
  const { best: b, dist: distA, parent } = farthest(a);
  const half = distA[b] / 2;

  // Walk b -> a; the edge where the travelled distance crosses `half` holds
  // the midpoint. `bSide` is the endpoint nearer b, `aSide` nearer a.
  let bSide = b;
  let aSide = -1;
  let travelled = 0;
  while (true) {
    const up = parent[bSide];
    if (up < 0) throw new Error('Midpoint 根定位失败：直径路径未覆盖中点');
    const w = adjacency[bSide].find(([v]) => v === up)[1];
    if (travelled + w >= half - 1e-12) { aSide = up; break; }
    travelled += w;
    bSide = up;
  }
  const w = adjacency[bSide].find(([v]) => v === aSide)[1];
  const distFromBSide = Math.min(w, Math.max(0, half - travelled));

  // The reroot target is the *child* endpoint of the midpoint edge in the
  // current rooting; t measures the split position from that child.
  const aIsChild = nodes[bSide].children.includes(nodes[aSide]);
  const target = aIsChild ? nodes[aSide] : nodes[bSide];
  const tEdge = w > 0 ? (aIsChild ? w - distFromBSide : distFromBSide) / w : 0;

  // DFS child-index path to `target`.
  let path = null;
  (function walk(node, trail) {
    if (path) return;
    if (node === target) { path = trail; return; }
    node.children.forEach((child, i) => walk(child, [...trail, i]));
  })(raw, []);
  if (!path || !path.length) throw new Error('Midpoint 根定位失败：中点落在当前根上，无法表达');
  return { tree: rerootTree(raw, path, tEdge), path, t: tEdge };
}

/**
 * Replay a list of recorded reroot operations from the ORIGINAL tree.
 * Each op is { path, t, method }. Replay stops at the first invalid op and
 * reports a warning — the returned tree is the last good state.
 */
export function replayRootOps(raw, ops = []) {
  const warnings = [];
  let current = raw;
  let applied = 0;
  for (const [i, op] of (ops || []).entries()) {
    if (!op || !Array.isArray(op.path)) {
      warnings.push(`改根重放中止：第 ${i + 1} 步缺少 path`);
      break;
    }
    try {
      current = rerootTree(current, op.path, op.t ?? 0.5);
      applied += 1;
    } catch (error) {
      warnings.push(`改根重放中止于第 ${i + 1} 步（${op.method || 'user'}）：${error.message}`);
      break;
    }
  }
  return { tree: current, warnings, applied };
}
