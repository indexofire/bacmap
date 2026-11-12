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
