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
export function layoutPhylogeny(root) {
  const nodes = [];
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

export const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
