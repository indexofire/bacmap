import * as THREE from '../vendor/three.module.js';
import {
  parseNewick, layoutPhylogenyRadial2D, layoutPhylogenyEqualAngle, treeLayerHeights,
} from '../framework/algorithms.js';
import { escapeHtml, makeDustField } from '../framework/primitives.js';
import { createConstellation, NETWORK_NEUTRAL, NETWORK_ACCENT } from '../framework/constellation.js';
import {
  metadataFieldOptions, heightModeOptions, defaultHeightMode, defaultColorField, nodeColoring, encodeHeights, MISSING, COLOR_SCHEMES,
} from '../framework/encodings.js';

const RADIUS = 10;

const leafRecords = data => {
  const tree = layoutPhylogenyRadial2D(parseNewick(data.newick));
  return tree.leaves.map(leaf => (data.metadata || {})[leaf.name] || {});
};

export const phyloView = {
  id: 'phylo',
  dockLabel: 'Phylo',
  title: '3D 进化树',
  subtitle: 'PHYLOGENETIC ATLAS',
  dataUrl: './data/framework/phylogeny.json',
  description: '渲染输入 Newick（如 IQ-TREE 的 .treefile），不推断树。平面布局可选 radial（半径 = 累计分支长度）或无根等角布局；高度可按根距、元数据类别或数值编码，均可实时切换。精确分支长度见 tooltip / 详情。',
  controls: data => {
    if (!data.newick) return [];
    const fields = metadataFieldOptions(leafRecords(data));
    const many = Object.keys(data.metadata || {}).length > 40;
    return [
      { type: 'section', label: '布局 · Layout' },
      {
        key: 'layout', label: '平面布局', type: 'select', value: 'radial',
        options: [
          { value: 'radial', label: 'Radial：半径 = 累计分支长度' },
          { value: 'cladogram', label: 'Cladogram：等距层级（忽略分支长度）' },
          { value: 'equal', label: '无根等角（equal-angle）' },
        ],
      },
      { key: 'height', label: '高度模式', type: 'select', value: 'flat', options: heightModeOptions(fields, '累计根距', { treeModes: true }).filter(o => o.value !== 'cone') },
      { key: 'elevate', label: '分支仰角展开（叠加）', type: 'toggle', value: true },
      { key: 'amp', label: '纵向展开', type: 'range', min: 0.3, max: 3, step: 0.1, value: 1.5 },
      {
        key: 'color', label: '颜色字段', type: 'select', value: defaultColorField(fields),
        options: [{ value: '', label: '不着色' }, { value: 'clade', label: '顶层 clade' }, ...fields.colorable.map(key => ({
          value: key, label: fields.numeric.includes(key) ? `${key}（数值渐变）` : key,
        }))],
      },
      {
        key: 'palette', label: '配色方案', type: 'select', value: 'auto',
        options: Object.entries(COLOR_SCHEMES).map(([value, label]) => ({ value, label })),
      },
      { type: 'section', label: '连线 · Edges' },
      { key: 'branchLabels', label: '显示分支长度', type: 'toggle', value: false },
      { key: 'supports', label: '显示支持值（内部节点名）', type: 'toggle', value: false },
      { key: 'edgeAlpha', label: '连线亮度', type: 'range', min: 0.1, max: 1, step: 0.05, value: 0.6 },
      { type: 'section', label: '节点 · Nodes' },
      { key: 'labels', label: '显示样本标签', type: 'toggle', value: !many },
      { type: 'section', label: '视图 · Scene' },
      { key: 'rotate', label: '旋转速度', type: 'range', min: 0, max: 3, step: 0.05, value: 0.45 },
      { key: 'glow', label: '光晕', type: 'range', min: 0, max: 1, step: 0.05, value: 0.2 },
      { key: 'pulses', label: '背景流光（装饰）', type: 'toggle', value: true },
    ];
  },

  create({ root, data, host, registerPickable }) {
    if (!data.newick) throw new Error('进化树数据需要 newick 字段');
    const parsed = parseNewick(data.newick);
    const trees = {
      radial: layoutPhylogenyRadial2D(parsed, { radius: RADIUS }),
      cladogram: layoutPhylogenyRadial2D(parsed, { radius: RADIUS, forceCladogram: true }),
      equal: layoutPhylogenyEqualAngle(parsed, { radius: RADIUS }),
    };
    // both layouts walk the same Newick in the same order → identical node ids
    const tree = trees.radial;
    const metadata = data.metadata || {};
    const recordOf = node => metadata[node.name] || {};
    const fields = metadataFieldOptions(tree.leaves.map(recordOf));
    const crowded = tree.leafCount > 40;
    for (const node of tree.nodes) node.gen = node.parent ? node.parent.gen + 1 : 0;
    const depthOf = node => (tree.cladogram ? node.gen : node.depth);
    const structureLabel = tree.cladogram ? '拓扑层级（无分支长度）' : '累计根距';
    // every node's top-level clade = the root child it descends from
    const topClade = new Map([[tree.root.id, 'root']]);
    tree.root.children.forEach((child, ci) => {
      const label = child.name || `clade ${ci + 1}`;
      (function walk(n) { topClade.set(n.id, label); n.children.forEach(walk); })(child);
    });

    const state = {
      layout: 'radial', height: 'flat', elevate: true, color: defaultColorField(fields),
      labels: !crowded, branchLabels: false, supports: false, pulses: true, glow: 0.2, edgeAlpha: 0.6, palette: 'auto', amp: 1.5,
    };

    host.scene.fog = new THREE.FogExp2(0x05070d, 0.014);
    host.setAutoRotate(true, 0.45);
    host.raycaster.params.Line.threshold = 0.22;
    const dust = makeDustField({ count: 260, radius: 60, color: 0x9a8f7a, size: 1.6, opacity: 0.3 });
    root.add(dust);

    let constellation = null, sidebarEl = null, constellationHost = null, encoded = null, cladeKey = new Map();
    function build() {
      constellation?.dispose();
      const flat = trees[state.layout];
      const leaves = tree.leaves;
      const leafIndex = new Map(leaves.map((leaf, i) => [leaf.id, i]));

      // heights: tree modes (cone / canopy) run over the whole node set so
      // ancestors accumulate their own elevation; other modes encode leaves and
      // ancestors take the mean of their descendant leaves
      const allTree = () => ({
        parent: tree.nodes.map(node => (node.parent ? node.parent.id : -1)),
        order: (() => { const o = []; (function walk(n) { o.push(n.id); n.children.forEach(walk); })(tree.root); return o; })(),
        dist: tree.nodes.map(depthOf),
      });
      const treeMode = state.height === 'canopy';
      let heights;
      if (treeMode) {
        encoded = encodeHeights({
          count: tree.nodes.length, mode: state.height, valueOf: () => '',
          structure: tree.nodes.map(depthOf), structureLabel,
          tree: allTree(),
          amp: state.amp,
        });
        heights = new Map(tree.nodes.map(node => [node.id, encoded.heights[node.id]]));
      } else {
        encoded = encodeHeights({
          count: leaves.length, mode: state.height,
          valueOf: (i, field) => recordOf(leaves[i])[field],
          structure: leaves.map(depthOf), structureLabel,
          amp: state.amp,
        });
        if (state.height === 'structure') {
          const max = Math.max(1e-12, ...tree.nodes.map(depthOf));
          heights = new Map(tree.nodes.map(node => [node.id, (4 - (depthOf(node) / max) * 8) * state.amp]));
        } else {
          heights = treeLayerHeights(tree, leaf => encoded.heights[leafIndex.get(leaf.id)]);
        }
      }
      // 仰角展开叠加：全节点锥形位移加在任意高度编码之上
      if (state.elevate) {
        const coneH = encodeHeights({
          count: tree.nodes.length, mode: 'cone', valueOf: () => '',
          structure: tree.nodes.map(depthOf), structureLabel,
          tree: allTree(), amp: state.amp,
        });
        for (const node of tree.nodes) heights.set(node.id, heights.get(node.id) + coneH.heights[node.id]);
        encoded = { ...encoded, axis: encoded.axis || coneH.axis, note: `${encoded.note} 叠加分支仰角展开。` };
      }

      // colour: leaves by field; an ancestor inherits a category only when
      // every descendant leaf shares it
      const colour = nodeColoring(leaves.map(leaf => (state.color === 'clade' ? topClade.get(leaf.id) : (state.color ? recordOf(leaf)[state.color] : ''))), NETWORK_NEUTRAL, { scheme: state.palette });
      cladeKey = new Map();
      (function visit(node) {
        if (!node.children.length) { cladeKey.set(node.id, colour.keys[leafIndex.get(node.id)]); return; }
        node.children.forEach(visit);
        const keys = new Set(node.children.map(child => cladeKey.get(child.id)));
        cladeKey.set(node.id, keys.size === 1 && !keys.has(null) ? [...keys][0] : null);
      })(tree.root);
      const sameField = encoded.decks && encoded.decks.field === state.color;
      if (sameField) for (const [key, layer] of encoded.decks.layers) layer.color = colour.layers.get(key)?.color || NETWORK_NEUTRAL;
      const layers = sameField ? encoded.decks.layers : colour.layers;

      const nodes = tree.nodes.map(node => {
        const isLeaf = !node.children.length, isRoot = node === tree.root;
        const key = cladeKey.get(node.id);
        const base = key ? (layers.get(key)?.color || NETWORK_NEUTRAL) : NETWORK_NEUTRAL;
        return {
          position: new THREE.Vector3(flat.nodes[node.id].x, heights.get(node.id), flat.nodes[node.id].y),
          color: isRoot ? NETWORK_ACCENT
            : isLeaf ? base : new THREE.Color(base).lerp(new THREE.Color('#1a1d26'), 0.35).getStyle(),
          size: isRoot ? 0.9 : isLeaf ? (crowded ? 0.42 : 0.56) : (crowded ? 0.09 : 0.12),
          layer: key,
          hub: isRoot,
          label: isRoot ? 'root' : (isLeaf ? node.name : (state.supports ? node.name : '')),
          payload: { type: 'node', id: node.id },
        };
      });
      constellation = createConstellation({
        root, host, registerPickable, layers, nodes,
        edges: tree.links.map(link => ({
          source: link.source.id, target: link.target.id,
          label: link.target.branchLength > 0 && !crowded ? link.target.branchLength.toFixed(3) : '',
          payload: { type: 'node', id: link.target.id },
        })),
        decks: !!sameField && layers.size > 1,
        heightAxis: state.height === 'structure'
          ? { ...encoded.axis, ticks: encoded.axis.ticks.map((tick, k) => ({ ...tick, text: ((k / 2) * Math.max(...tree.nodes.map(depthOf))).toFixed(tree.cladogram ? 0 : 3) })) }
          : encoded.axis,
        legendTitle: state.color ? `颜色 · ${state.color}` : '颜色 · 未着色',
        legendNote: `${encoded.note}${state.color ? ' 点击行可隐藏 / 显示该类别。' : ''}`,
        showLabels: state.labels, showEdgeLabels: state.branchLabels, pulsesOn: state.pulses, glow: state.glow, edgeAlpha: state.edgeAlpha,
        sidebarNote: `${state.layout === 'cladogram'
          ? '平面：Cladogram 等距层级（忽略分支长度，每代一环）。'
          : state.layout === 'radial'
            ? (tree.cladogram ? 'Newick 未提供分支长度：半径按拓扑层级（cladogram）排布。' : '平面：到中心的距离 = 累计分支长度。')
            : '平面：无根等角布局，分支长度沿各自扇区方向绘制（角度不表示数值）。'} 流光仅为装饰。`,
      });
      if (constellationHost) constellation.mountSidebar(constellationHost);
    }
    build();

    const getNode = payload => (payload?.type === 'node' ? tree.nodes[payload.id] : null);
    const calloutFor = node => {
      if (node === tree.root) return { title: 'root', subtitle: `${tree.leafCount} taxa · max depth ${tree.maxDepth.toFixed(3)}` };
      if (node.children.length) return { title: node.name || `node ${node.id}`, subtitle: `${node.leafCount} leaves · depth ${node.depth.toFixed(4)}` };
      const meta = recordOf(node);
      const tag = state.color ? (meta[state.color] ?? MISSING) : 'leaf';
      return { title: node.name, subtitle: `${meta.st || 'leaf'} · ${tag} · depth ${node.depth.toFixed(4)}` };
    };
    const recordRows = record => Object.entries(record)
      .filter(([, value]) => value !== null && typeof value !== 'object')
      .map(([key, value]) => `<dt>${escapeHtml(key)}</dt><dd>${escapeHtml(value)}</dd>`).join('');

    return {
      debug: () => ({ state: { ...state }, fields, leaves: tree.leafCount, ...constellation.debug() }),
      stats: () => {
        const rows = [
          { label: '叶节点 / Taxa', value: tree.leafCount },
          { label: '内节点', value: tree.nodes.length - tree.leafCount },
          { label: '最大根距', value: tree.maxDepth.toFixed(3) },
          { label: '元数据字段', value: fields.categorical.length + fields.numeric.length },
        ];
        if (data.n_snp_sites !== null && data.n_snp_sites !== undefined) rows.push({ label: '核心 SNP 位点', value: data.n_snp_sites });
        if (data.n_loci) rows.push({ label: 'cgMLST 位点', value: data.n_loci });
        return rows;
      },
      resetCamera: () => {
        const d = RADIUS * 2.7;
        host.setCamera(new THREE.Vector3(d * 0.3, d * 0.36, d * 0.88), new THREE.Vector3(0, 0, 0));
      },
      setOption: (key, value) => {
        if (key === 'labels') { state.labels = !!value; constellation.setLabels(value); }
        if (key === 'branchLabels') { state.branchLabels = !!value; constellation.setEdgeLabels(value); }
        if (key === 'pulses') { state.pulses = !!value; constellation.setPulses(value); }
        if (key === 'rotate') host.setAutoRotate(Number(value) > 0, Number(value));
        if (key === 'glow') { state.glow = Number(value); constellation.setGlow(state.glow); }
        if (key === 'edgeAlpha') { state.edgeAlpha = Number(value); constellation.setEdgeAlpha(state.edgeAlpha); }
        if (key === 'layout' || key === 'height' || key === 'color' || key === 'palette' || key === 'supports') { state[key] = String(value); build(); }
        if (key === 'elevate') { state.elevate = !!value; build(); }
        if (key === 'amp') { state.amp = Number(value); build(); }
      },
      update: dt => {
        dust.rotation.y += dt * 0.006;
        constellation.update(dt);
      },
      select: payload => {
        const node = getNode(payload);
        if (node) constellation.selectNode(node.id, calloutFor(node));
        else constellation.clearSelection();
      },
      hover: payload => constellation.hoverNode(getNode(payload)?.id ?? -1),
      mountSidebar: el => {
        sidebarEl = el;
        el.innerHTML = `
          <div class="blk mst-search-blk">
            <input class="mst-search" type="search" placeholder="搜索叶节点 / 元数据…" aria-label="搜索叶节点">
            <div class="mst-search-results"></div>
          </div>
          <div data-role="constellation-side"></div>`;
        constellationHost = el.querySelector('[data-role="constellation-side"]');
        constellation.mountSidebar(constellationHost);
        const input = el.querySelector('.mst-search');
        const out = el.querySelector('.mst-search-results');
        const rank = (leaf, q) => {
          const name = (leaf.name || '').toLowerCase();
          const rec = recordOf(leaf);
          const metaHit = Object.entries(rec).find(([, v]) => String(v).toLowerCase().includes(q));
          if (name === q) return [0, ''];
          if (name.startsWith(q)) return [1, ''];
          if (metaHit && String(metaHit[1]).toLowerCase() === q) return [2, `${metaHit[0]}=${metaHit[1]}`];
          if (name.includes(q)) return [3, ''];
          if (metaHit) return [4, `${metaHit[0]}=${metaHit[1]}`];
          return [9, ''];
        };
        input.addEventListener('input', () => {
          const q = input.value.trim().toLowerCase();
          if (q.length < 2) { out.innerHTML = ''; return; }
          const hits = tree.leaves.map(leaf => ({ leaf, r: rank(leaf, q) }))
            .filter(hit => hit.r[0] < 9)
            .sort((a, b) => a.r[0] - b.r[0])
            .slice(0, 12);
          out.innerHTML = hits.length
            ? hits.map(hit => `<button class="mst-hit" data-node="${hit.leaf.id}">
                <b>${escapeHtml(hit.leaf.name || `leaf ${hit.leaf.id}`)}</b>
                <span>${escapeHtml(recordOf(hit.leaf).st || 'leaf')}${hit.r[1] ? ` · ${escapeHtml(hit.r[1])}` : ''}</span>
              </button>`).join('')
            : '<p class="gene-note">无匹配叶节点</p>';
        });
        out.addEventListener('click', event => {
          const btn = event.target.closest('[data-node]');
          if (!btn) return;
          const id = Number(btn.dataset.node);
          const node = tree.nodes[id];
          if (!node) return;
          constellation.selectNode(node.id, calloutFor(node));
          const position = constellation.nodePosition(node.id);
          if (position) host.flyTo(position.clone().add(new THREE.Vector3(0, 3.2, 7.5)), position);
        });
      },
      focus: payload => {
        const node = getNode(payload);
        if (!node) return;
        const position = constellation.nodePosition(node.id);
        host.flyTo(position.clone().add(new THREE.Vector3(0, 3.2, 7.5)), position);
      },
      selectionLabel: payload => getNode(payload)?.name || (getNode(payload)?.children.length ? '祖先节点' : '未命名'),
      tooltip: payload => {
        const node = getNode(payload);
        if (!node) return '';
        const meta = recordOf(node);
        const tag = state.color && !node.children.length ? ` · ${state.color}: ${meta[state.color] ?? MISSING}` : '';
        return `<div class="tt-name">${escapeHtml(node.name || (node === tree.root ? 'root' : '内部节点'))}</div>
          <div class="tt-sub">${node.children.length ? `${node.leafCount} 个后代叶节点` : `${escapeHtml(meta.st || '样本')}${escapeHtml(tag)}`}</div>
          <div class="tt-sub">分支 ${node.branchLength.toFixed(4)} · 根距 ${node.depth.toFixed(4)} · 双击聚焦</div>`;
      },
      inspect: payload => {
        const node = getNode(payload);
        if (!node) return '';
        const title = node.name || (node === tree.root ? 'root' : `内部节点 ${node.id}`);
        const clade = cladeKey.get(node.id);
        return `<div class="detail-title">${escapeHtml(title)}</div>
          <p class="detail-subtitle">${node.children.length ? `包含 ${node.leafCount} 个叶节点的祖先分支` : '终端样本 / Operational taxonomic unit'}</p>
          <div class="metric-grid">
            <div><span>分支长度</span><b>${node.branchLength.toFixed(4)}</b></div>
            <div><span>累计根距</span><b>${node.depth.toFixed(4)}</b></div>
            <div><span>后代叶节点</span><b>${node.leafCount}</b></div>
            <div><span>${escapeHtml(state.color || '类别')}</span><b>${escapeHtml(clade || '跨类别')}</b></div>
            <div><span>顶层 clade</span><b>${escapeHtml(topClade.get(node.id) || '—')}</b></div>
            ${node.children.length ? `<div><span>支持值</span><b>${escapeHtml(node.name || '—')}</b></div>` : ''}
          </div>
          ${node.children.length ? '' : `<details class="insp-sec" open><summary>元数据</summary><dl class="kv">${recordRows(recordOf(node)) || '<dt>—</dt><dd>宿主未提供</dd>'}</dl></details>`}
          <p class="detail-footnote">拓扑与分支长度直接来自输入 Newick。${escapeHtml(encoded.note)} 内部节点：后代全属同一类别时归入该类别，高度取后代叶节点的平均值（结构距离模式下取自身根距）。光效不承载生物学含义。</p>`;
      },
    };
  },
};
