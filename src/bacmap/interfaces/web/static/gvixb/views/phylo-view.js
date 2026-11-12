import * as THREE from '../vendor/three.module.js';
import { parseNewick, layoutPhylogenyRadial3D, forceLayout3D, clamp } from '../framework/algorithms.js';
import { makeLabel, groupColors, escapeHtml, metadataRows, makeDustField, makeDotTexture, makeDotSprite } from '../framework/primitives.js';

const backOut = t => { const s = 1.70158; const x = t - 1; return 1 + (s + 1) * x * x * x + s * x * x; };

export const phyloView = {
  id: 'phylo',
  dockLabel: 'Phylo',
  title: '3D 进化树',
  subtitle: 'PHYLOGENETIC ATLAS',
  dataUrl: './data/framework/phylogeny.json',
  description: 'Newick 系统发育树的力导向三维呈现，与 MST 视图同一视觉语言：谱系按分支长度自然聚簇并各向同性扩散。连线长度近似分支长度比例，布局仅用于显示；精确分支长度与累计根距在 tooltip 和详情面板中给出。',
  controls: [
    { key: 'labels', label: '显示样本标签', type: 'toggle', value: true },
    { key: 'branchLabels', label: '显示分支长度', type: 'toggle', value: false },
  ],

  create({ root, data, host, registerPickable }) {
    if (!data.newick) throw new Error('进化树数据需要 newick 字段');
    const tree = layoutPhylogenyRadial3D(parseNewick(data.newick));
    const metadata = data.metadata || {};
    const colors = groupColors(tree.leaves.map(node => metadata[node.name]?.group || '未分组'));

    // --- Atmosphere: deep-space presentation, decorative only. ---
    host.scene.fog = new THREE.FogExp2(0x05070d, 0.012);
    host.setBloom?.({ strength: 0.48, radius: 0.4, threshold: 0.5 });
    host.setAutoRotate(true, 0.5);
    host.raycaster.params.Line.threshold = 0.3;
    const dust = makeDustField({ count: 650, radius: 58, color: 0x9fb2e8 });
    root.add(dust);
    const dotTexture = makeDotTexture();

    const nodeGroup = new THREE.Group(), branchGroup = new THREE.Group();
    const labelGroup = new THREE.Group(), branchLabelGroup = new THREE.Group(), legendGroup = new THREE.Group();
    root.add(branchGroup, nodeGroup, labelGroup, branchLabelGroup, legendGroup);

    // --- Force-directed diffusion, the same mechanism as the MST view. ---
    // Spring rest lengths track branch lengths linearly, relative to the
    // tree's median branch: clades with short internal branches condense into
    // tight knots while long backbone links stretch apart — an isotropic,
    // radiating cloud. Display-only: exact values live in tooltips/inspector.
    const lengths = tree.links.map(link => link.target.branchLength).sort((a, b) => a - b);
    const medianBranch = lengths[Math.floor(lengths.length / 2)] || 0;
    const springEdges = tree.links.map(link => ({
      source: link.source.id,
      target: link.target.id,
      // Power > 1 exaggerates the short/long contrast so clades condense into
      // knots while the backbone stretches them apart (display-only).
      distance: medianBranch > 0 ? Math.pow(link.target.branchLength / medianBranch, 1.5) * 6 : 6,
    }));
    const layout = forceLayout3D(tree.nodes, springEdges, { repulsion: 0.8, springStiffness: 0.2 });
    const maxGen = Math.max(...tree.nodes.map(node => {
      node.gen = node.parent ? node.parent.gen + 1 : 0;
      return node.gen;
    }));
    for (const node of tree.nodes) {
      node.position = new THREE.Vector3(layout[node.id].x, layout[node.id].y, layout[node.id].z);
      node.group = metadata[node.name]?.group || null;
    }
    const crowded = tree.leafCount > 40;

    // Growth choreography: hairlines extend from parent to child, waves keyed
    // to topological generation so the tree unfolds from the root outward.
    const segments = [];
    const branchDelay = gen => 0.1 + (gen / Math.max(1, maxGen)) * 1.35;

    for (const link of tree.links) {
      const parent = link.source, child = link.target;
      const payload = { type: 'node', id: child.id };
      const color = child.group ? colors.get(child.group) : '#6d8bff';
      const material = new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0 });
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array([
        parent.position.x, parent.position.y, parent.position.z,
        parent.position.x, parent.position.y, parent.position.z,
      ]), 3));
      const line = new THREE.Line(geometry, material);
      const delta = child.position.clone().sub(parent.position);
      const length = Math.max(0.0001, delta.length());
      segments.push({
        geometry,
        start: parent.position,
        dir: delta.clone().divideScalar(length),
        length,
        material,
        delay: branchDelay(child.gen),
        dur: 0.45,
        targetOpacity: crowded
          ? (child.children.length ? 0.34 : 0.5)
          : (child.children.length ? 0.6 : 0.8),
      });
      branchGroup.add(registerPickable(line, payload));

      if (child.branchLength > 0 && !crowded) {
        const label = makeLabel(child.branchLength.toFixed(3), { color: '#7e8bb0', height: 0.24, fontSize: 23, align: 'center' });
        label.position.copy(parent.position).lerp(child.position, 0.62).add(new THREE.Vector3(0, 0.24, 0));
        label.material.opacity = 0;
        branchLabelGroup.add(label);
      }
    }

    const nodeDots = new Map();
    const nodePops = [];
    for (const node of tree.nodes) {
      const isLeaf = node.children.length === 0;
      const color = node.group ? colors.get(node.group) : (isLeaf ? '#7e8bb0' : '#52617f');
      const size = isLeaf ? (crowded ? 0.42 : 0.56) : (crowded ? 0.16 : 0.2);
      const dotColor = new THREE.Color(color);
      if (isLeaf) dotColor.lerp(new THREE.Color('#ffffff'), 0.25);
      const dot = makeDotSprite({ color: dotColor, size, texture: dotTexture });
      dot.position.copy(node.position);
      dot.userData.dotSize = size;
      dot.scale.setScalar(0.001);
      nodeGroup.add(registerPickable(dot, { type: 'node', id: node.id }));
      nodeDots.set(node.id, dot);
      nodePops.push({ dot, delay: branchDelay(node.gen) + 0.4 });

      if (isLeaf) {
        const meta = metadata[node.name] || {};
        const outward = node.position.lengthSq() > 0.000001
          ? node.position.clone().normalize().multiplyScalar(0.32) : new THREE.Vector3(0.32, 0, 0);
        const label = makeLabel(node.name, { color, height: crowded ? 0.24 : 0.38, fontSize: crowded ? 22 : 28 });
        label.position.copy(node.position).add(outward).add(new THREE.Vector3(0, crowded ? 0.12 : 0.17, 0));
        label.material.opacity = 0;
        labelGroup.add(label);
        if (meta.st && !crowded) {
          const st = makeLabel(meta.st, { color: '#68779b', height: 0.26, fontSize: 23 });
          st.position.copy(node.position).add(outward).add(new THREE.Vector3(0, -0.24, 0));
          st.material.opacity = 0;
          labelGroup.add(st);
        }
      }
    }

    // Reading rule stays explicit: layout is display-only, exact numbers live
    // in tooltips and the inspector.
    const legend = makeLabel('EDGE LENGTH ≈ BRANCH LENGTH (PERCEPTUAL)    ·    LAYOUT IS DISPLAY-ONLY — EXACT VALUES IN TOOLTIP / INSPECTOR', {
      color: '#68779b', height: 0.26, fontSize: 20, align: 'center',
    });
    legend.position.set(0, Math.min(...tree.nodes.map(node => node.position.y)) - 1.4, 0);
    legend.material.opacity = 0;
    legendGroup.add(legend);
    branchLabelGroup.visible = false;

    // --- Intro timeline: branches radiate from the root, labels surface. ---
    const LABEL_T0 = 1.65, LABEL_DUR = 0.5, LEGEND_T0 = 1.95, LEGEND_DUR = 0.5;
    const INTRO_END = 2.65;
    let elapsed = 0, introDone = false;

    let selected = null;
    let selectedColor = null;
    function select(payload) {
      if (selected) {
        selected.material.color.copy(selectedColor);
        if (introDone) selected.scale.setScalar(selected.userData.dotSize);
      }
      selected = payload?.type === 'node' ? nodeDots.get(payload.id) : null;
      if (selected) {
        selectedColor = selected.material.color.clone();
        selected.material.color.set('#ffffff');
        if (introDone) selected.scale.setScalar(selected.userData.dotSize * 1.65);
      }
    }

    function getNode(payload) { return payload?.type === 'node' ? tree.nodes[payload.id] : null; }

    return {
      stats: () => {
        const rows = [
          { label: '叶节点 / Taxa', value: tree.leafCount },
          { label: '内节点', value: tree.nodes.length - tree.leafCount },
          { label: '最大根距', value: tree.maxDepth.toFixed(3) },
          { label: '队列', value: `${data.cohort || 'tree'} / ${data.group || '—'}` },
        ];
        if (data.n_snp_sites !== null && data.n_snp_sites !== undefined) rows.push({ label: '核心 SNP 位点', value: data.n_snp_sites });
        if (data.n_loci) rows.push({ label: 'cgMLST 位点', value: data.n_loci });
        return rows;
      },
      resetCamera: () => {
        const spread = crowded ? 1.24 : 1;
        host.setCamera(new THREE.Vector3(9.5 * spread, 6.2 * spread, 22.5 * spread), new THREE.Vector3(0, 0, 0));
      },
      setOption: (key, value) => {
        if (key === 'labels') labelGroup.visible = value;
        if (key === 'branchLabels') branchLabelGroup.visible = value;
      },
      update: dt => {
        dust.rotation.y += dt * 0.008;
        if (introDone) return;
        elapsed += dt;
        for (const segment of segments) {
          const t = clamp((elapsed - segment.delay) / segment.dur, 0, 1);
          const eased = t * t * (3 - 2 * t);
          const attribute = segment.geometry.getAttribute('position');
          attribute.setXYZ(1,
            segment.start.x + segment.dir.x * segment.length * eased,
            segment.start.y + segment.dir.y * segment.length * eased,
            segment.start.z + segment.dir.z * segment.length * eased);
          attribute.needsUpdate = true;
          segment.material.opacity = clamp(t * 1.6, 0, 1) * segment.targetOpacity;
        }
        nodePops.forEach(({ dot, delay }) => {
          const t = clamp((elapsed - delay) / 0.4, 0, 1);
          dot.scale.setScalar(Math.max(0.001, dot.userData.dotSize * backOut(t)));
        });
        const labelT = clamp((elapsed - LABEL_T0) / LABEL_DUR, 0, 1);
        labelGroup.children.forEach(label => { label.material.opacity = labelT; });
        branchLabelGroup.children.forEach(label => { label.material.opacity = labelT; });
        const legendT = clamp((elapsed - LEGEND_T0) / LEGEND_DUR, 0, 1);
        legendGroup.children.forEach(label => { label.material.opacity = legendT; });
        if (elapsed >= INTRO_END) {
          introDone = true;
          nodePops.forEach(({ dot }) => dot.scale.setScalar(dot.userData.dotSize));
          if (selected) selected.scale.setScalar(selected.userData.dotSize * 1.65);
        }
      },
      select,
      focus: payload => {
        const node = getNode(payload);
        if (node) host.flyTo(node.position.clone().add(new THREE.Vector3(0, 1.2, 7.5)), node.position);
      },
      selectionLabel: payload => getNode(payload)?.name || (getNode(payload)?.children.length ? '祖先节点' : '未命名'),
      tooltip: payload => {
        const node = getNode(payload);
        if (!node) return '';
        const meta = metadata[node.name] || {};
        return `<div class="tt-name">${escapeHtml(node.name || '内部节点')}</div>
          <div class="tt-sub">${node.children.length ? `${node.leafCount} 个后代叶节点` : `${escapeHtml(meta.st || '样本')} · ${escapeHtml(meta.group || '未分组')}`}</div>
          <div class="tt-sub">根距 ${node.depth.toFixed(4)} · 双击聚焦</div>`;
      },
      inspect: payload => {
        const node = getNode(payload);
        if (!node) return '';
        const meta = metadata[node.name] || {};
        const title = node.name || `内部节点 ${node.id}`;
        return `<div class="detail-title">${escapeHtml(title)}</div>
          <p class="detail-subtitle">${node.children.length ? `包含 ${node.leafCount} 个叶节点的祖先分支` : '终端样本 / Operational taxonomic unit'}</p>
          <div class="metric-grid">
            <div><span>分支长度</span><b>${node.branchLength.toFixed(4)}</b></div>
            <div><span>累计根距</span><b>${node.depth.toFixed(4)}</b></div>
            <div><span>后代叶节点</span><b>${node.leafCount}</b></div>
            <div><span>层级</span><b>${node.children.length ? 'NODE' : 'LEAF'}</b></div>
          </div>
          <dl class="kv">${metadataRows(meta, [
            ['group', '谱系分组'], ['st', '序列型'], ['host', '宿主'], ['year', '采样年份'], ['amr', '耐药标记数'],
          ])}</dl>
          <p class="detail-footnote">分支长度与拓扑直接来自输入 Newick；力导向布局仅用于显示，连线长度按分支长度相对全树中位数线性缩放，精确数值以本面板为准。纵深与光效不承载生物学含义。示例中的距离和元数据均为模拟值，不构成真实进化结论。</p>`;
      },
    };
  },
};
