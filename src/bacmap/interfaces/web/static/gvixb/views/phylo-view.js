import * as THREE from '../vendor/three.module.js';
import { parseNewick, layoutPhylogeny } from '../framework/algorithms.js';
import { cylinderBetween, lineFromPoints, makeLabel, groupColors, escapeHtml, metadataRows } from '../framework/primitives.js';

export const phyloView = {
  id: 'phylo',
  dockLabel: 'Phylo',
  title: '3D 进化树',
  subtitle: 'PHYLOGENETIC ATLAS',
  dataUrl: './data/framework/phylogeny.json',
  description: 'Newick 系统发育树的三维系统树图。水平方向严格表示累计分支长度，纵向表示叶节点顺序；立体材质不引入额外的生物学维度。',
  controls: [
    { key: 'labels', label: '显示样本标签', type: 'toggle', value: true },
    { key: 'branchLabels', label: '显示分支长度', type: 'toggle', value: false },
  ],

  create({ root, data, host, registerPickable }) {
    if (!data.newick) throw new Error('进化树数据需要 newick 字段');
    const tree = layoutPhylogeny(parseNewick(data.newick));
    const metadata = data.metadata || {};
    const colors = groupColors(tree.leaves.map(node => metadata[node.name]?.group || '未分组'));
    const nodeGroup = new THREE.Group(), branchGroup = new THREE.Group();
    const labelGroup = new THREE.Group(), branchLabelGroup = new THREE.Group(), axisGroup = new THREE.Group();
    root.add(branchGroup, nodeGroup, labelGroup, branchLabelGroup, axisGroup);

    const X0 = -8.5, WIDTH = 17;
    const xOf = depth => X0 + (depth / Math.max(0.000001, tree.maxDepth)) * WIDTH;
    for (const node of tree.nodes) {
      node.position = new THREE.Vector3(xOf(node.depth), node.y, 0);
      node.group = metadata[node.name]?.group || null;
    }

    const nodeMeshes = new Map();
    for (const link of tree.links) {
      const parent = link.source, child = link.target;
      const payload = { type: 'node', id: child.id };
      const color = child.group ? colors.get(child.group) : '#6d8bff';
      const material = new THREE.MeshStandardMaterial({
        color, roughness: 0.42, metalness: 0.28,
        emissive: new THREE.Color(color).multiplyScalar(0.10),
      });
      const elbow = new THREE.Vector3(parent.position.x, child.position.y, 0);
      if (Math.abs(parent.position.y - child.position.y) > 0.001) {
        const vertical = cylinderBetween(parent.position, elbow, 0.042, material, 8);
        branchGroup.add(registerPickable(vertical, payload));
      }
      const horizontal = cylinderBetween(elbow, child.position, child.children.length ? 0.052 : 0.065, material, 10);
      branchGroup.add(registerPickable(horizontal, payload));

      if (child.branchLength > 0) {
        const label = makeLabel(child.branchLength.toFixed(3), { color: '#7e8bb0', height: 0.25, fontSize: 24, align: 'center' });
        label.position.copy(elbow).lerp(child.position, 0.5).add(new THREE.Vector3(0, 0.25, 0.15));
        branchLabelGroup.add(label);
      }
    }

    for (const node of tree.nodes) {
      const isLeaf = node.children.length === 0;
      const color = node.group ? colors.get(node.group) : (isLeaf ? '#7e8bb0' : '#52617f');
      const radius = isLeaf ? 0.18 : 0.11;
      const material = new THREE.MeshStandardMaterial({
        color, roughness: 0.3, metalness: 0.35,
        emissive: new THREE.Color(color).multiplyScalar(isLeaf ? 0.20 : 0.06),
      });
      const sphere = new THREE.Mesh(new THREE.SphereGeometry(radius, 18, 12), material);
      sphere.position.copy(node.position);
      sphere.userData.baseRadius = radius;
      nodeGroup.add(registerPickable(sphere, { type: 'node', id: node.id }));
      nodeMeshes.set(node.id, sphere);

      if (isLeaf) {
        const meta = metadata[node.name] || {};
        const label = makeLabel(node.name, { color, height: 0.38, fontSize: 28 });
        label.position.copy(node.position).add(new THREE.Vector3(0.38, 0, 0.12));
        labelGroup.add(label);
        if (meta.st) {
          const st = makeLabel(meta.st, { color: '#68779b', height: 0.26, fontSize: 23 });
          st.position.copy(node.position).add(new THREE.Vector3(0.40, -0.37, 0.10));
          labelGroup.add(st);
        }
      }
    }

    // A quantitative branch-length axis keeps the 3D presentation auditable.
    const axisY = Math.min(...tree.nodes.map(node => node.y)) - 1.05;
    axisGroup.add(lineFromPoints([
      new THREE.Vector3(X0, axisY, -0.1), new THREE.Vector3(X0 + WIDTH, axisY, -0.1),
    ], 0x52617f, 0.55));
    for (let i = 0; i <= 5; i++) {
      const depth = tree.maxDepth * i / 5;
      const x = xOf(depth);
      axisGroup.add(lineFromPoints([
        new THREE.Vector3(x, axisY - 0.10, -0.1), new THREE.Vector3(x, axisY + 0.10, -0.1),
      ], 0x7e8bb0, 0.65));
      const label = makeLabel(depth.toFixed(2), { color: '#7e8bb0', height: 0.26, fontSize: 22, align: 'center' });
      label.position.set(x, axisY - 0.36, 0);
      axisGroup.add(label);
    }
    const axisTitle = makeLabel(data.distanceLabel || '累计分支长度', { color: '#a8b5d6', height: 0.28, fontSize: 23, align: 'center' });
    axisTitle.position.set(0, axisY - 0.82, 0);
    axisGroup.add(axisTitle);
    branchLabelGroup.visible = false;

    let selected = null;
    function select(payload) {
      if (selected) {
        selected.scale.setScalar(1);
        selected.material.emissive.copy(selected.userData.originalEmissive);
      }
      selected = payload?.type === 'node' ? nodeMeshes.get(payload.id) : null;
      if (selected) {
        selected.userData.originalEmissive = selected.material.emissive.clone();
        selected.scale.setScalar(1.65);
        selected.material.emissive.set('#ffffff').multiplyScalar(0.55);
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
      resetCamera: () => host.setCamera(new THREE.Vector3(1.4, 2.3, 28), new THREE.Vector3(1.4, 0, 0)),
      setOption: (key, value) => {
        if (key === 'labels') labelGroup.visible = value;
        if (key === 'branchLabels') branchLabelGroup.visible = value;
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
          <p class="detail-footnote">分支长度与拓扑直接来自输入 Newick。示例中的距离和元数据均为模拟值，不构成真实进化结论。</p>`;
      },
    };
  },
};
