import * as THREE from '../lib/three.module.js';
import { minimumSpanningTree, forceLayout, clamp } from '../framework/algorithms.js';
import { cylinderBetween, makeLabel, groupColors, escapeHtml } from '../framework/primitives.js';

const distanceColor = distance => {
  const t = clamp(distance / 7, 0, 1);
  const cold = new THREE.Color('#53e6ff'), warm = new THREE.Color('#ff8a3d');
  return cold.lerp(warm, t);
};

export const mstView = {
  id: 'mst',
  dockLabel: 'MST',
  title: '3D 最小生成树',
  subtitle: 'MLST MINIMUM SPANNING TREE',
  dataUrl: './data/framework/mst.json',
  description: '根据多位点序列分型（MLST）等位基因谱计算汉明距离，再以 Kruskal 算法实时构建最小生成树。节点大小表示聚合样本数。',
  controls: [
    { key: 'labels', label: '显示样本标签', type: 'toggle', value: true },
    { key: 'distances', label: '显示等位距离', type: 'toggle', value: true },
  ],

  create({ root, data, host, registerPickable }) {
    if (!Array.isArray(data.isolates) || data.isolates.length < 2) throw new Error('MST 数据至少需要两个 isolates');
    const isolates = data.isolates;
    const edges = minimumSpanningTree(isolates);
    const positions2d = forceLayout(isolates, edges);
    const positions = positions2d.map(p => new THREE.Vector3(p.x, p.y, 0));
    const colors = groupColors(isolates.map(isolate => isolate.group || '未分组'));
    const edgeGroup = new THREE.Group(), nodeGroup = new THREE.Group();
    const labelGroup = new THREE.Group(), distanceGroup = new THREE.Group();
    root.add(edgeGroup, nodeGroup, labelGroup, distanceGroup);

    const degree = isolates.map(() => 0);
    const edgeMeshes = [], nodeMeshes = [];
    edges.forEach((edge, index) => {
      degree[edge.source]++;
      degree[edge.target]++;
      const color = distanceColor(edge.distance);
      const material = new THREE.MeshStandardMaterial({
        color, roughness: 0.38, metalness: 0.22,
        emissive: color.clone().multiplyScalar(0.16),
      });
      const mesh = cylinderBetween(positions[edge.source], positions[edge.target], 0.055 + (7 - edge.distance) * 0.006, material, 10);
      edgeGroup.add(registerPickable(mesh, { type: 'edge', index }));
      edgeMeshes.push(mesh);
      const label = makeLabel(`Δ ${edge.distance}`, { color: color.getStyle(), height: 0.30, fontSize: 24, align: 'center' });
      label.position.copy(positions[edge.source]).lerp(positions[edge.target], 0.5).add(new THREE.Vector3(0, 0.30, 0.22));
      distanceGroup.add(label);
    });

    isolates.forEach((isolate, index) => {
      const color = colors.get(isolate.group || '未分组');
      const radius = 0.30 + Math.sqrt(Math.max(1, isolate.count || 1)) * 0.085;
      const material = new THREE.MeshStandardMaterial({
        color, roughness: 0.28, metalness: 0.36,
        emissive: new THREE.Color(color).multiplyScalar(0.18),
      });
      const sphere = new THREE.Mesh(new THREE.SphereGeometry(radius, 24, 16), material);
      sphere.position.copy(positions[index]);
      sphere.userData.radius = radius;
      nodeGroup.add(registerPickable(sphere, { type: 'node', index }));
      nodeMeshes.push(sphere);
      const label = makeLabel(isolate.id, { color, height: 0.34, fontSize: 27, align: 'center' });
      label.position.copy(positions[index]).add(new THREE.Vector3(0, radius + 0.38, 0.15));
      labelGroup.add(label);
    });

    // Subtle scale legend: node size encodes count, edge hue encodes allele distance.
    const legend = makeLabel('EDGE  Δ 0–7 ALLELES    ·    NODE SIZE ENCODES ISOLATE COUNT', {
      color: '#68779b', height: 0.28, fontSize: 22, align: 'center',
    });
    legend.position.set(0, Math.min(...positions.map(p => p.y)) - 1.3, 0);
    root.add(legend);

    let selected = null;
    function clearSelection() {
      if (!selected) return;
      selected.object.material.emissive.copy(selected.emissive);
      if (selected.kind === 'node') selected.object.scale.setScalar(1);
      selected = null;
    }
    function select(payload) {
      clearSelection();
      if (!payload) return;
      const kind = payload.type;
      const object = kind === 'node' ? nodeMeshes[payload.index] : edgeMeshes[payload.index];
      if (!object) return;
      selected = { object, kind, emissive: object.material.emissive.clone() };
      object.material.emissive.set('#ffffff').multiplyScalar(0.45);
      if (kind === 'node') object.scale.setScalar(1.25);
    }

    function payloadPosition(payload) {
      if (payload?.type === 'node') return positions[payload.index];
      if (payload?.type === 'edge') {
        const edge = edges[payload.index];
        return positions[edge.source].clone().lerp(positions[edge.target], 0.5);
      }
      return null;
    }

    return {
      stats: () => [
        { label: '样本节点', value: isolates.length },
        { label: 'MST 边', value: edges.length },
        { label: 'MLST 位点', value: isolates[0].profile.length },
        { label: '算法', value: 'Kruskal' },
      ],
      resetCamera: () => host.setCamera(new THREE.Vector3(0, 2.8, 27.5), new THREE.Vector3(0, 0, 0)),
      setOption: (key, value) => {
        if (key === 'labels') labelGroup.visible = value;
        if (key === 'distances') distanceGroup.visible = value;
      },
      select,
      focus: payload => {
        const position = payloadPosition(payload);
        if (position) host.flyTo(position.clone().add(new THREE.Vector3(0, 1.1, 7)), position);
      },
      selectionLabel: payload => {
        if (payload?.type === 'node') return isolates[payload.index].id;
        if (payload?.type === 'edge') return `Δ ${edges[payload.index].distance}`;
        return '—';
      },
      tooltip: payload => {
        if (payload?.type === 'node') {
          const isolate = isolates[payload.index];
          return `<div class="tt-name">${escapeHtml(isolate.id)}</div>
            <div class="tt-sub">${escapeHtml(isolate.st || 'ST —')} · ${escapeHtml(isolate.group || '未分组')}</div>
            <div class="tt-sub">${isolate.count || 1} 个聚合样本 · MST 度 ${degree[payload.index]}</div>`;
        }
        if (payload?.type === 'edge') {
          const edge = edges[payload.index];
          return `<div class="tt-name">Δ ${edge.distance} alleles</div>
            <div class="tt-sub">${escapeHtml(isolates[edge.source].id)} ↔ ${escapeHtml(isolates[edge.target].id)}</div>`;
        }
        return '';
      },
      inspect: payload => {
        if (payload?.type === 'node') {
          const isolate = isolates[payload.index];
          const loci = data.loci || isolate.profile.map((_, i) => `locus_${i + 1}`);
          const profile = isolate.profile.map((allele, i) => `<div class="allele"><span>${escapeHtml(loci[i])}</span><b>${escapeHtml(allele)}</b></div>`).join('');
          return `<div class="detail-title">${escapeHtml(isolate.id)}</div>
            <p class="detail-subtitle">${escapeHtml(isolate.st || '未指定序列型')} · ${escapeHtml(isolate.group || '未分组')}</p>
            <div class="metric-grid">
              <div><span>聚合样本</span><b>${isolate.count || 1}</b></div>
              <div><span>MST 节点度</span><b>${degree[payload.index]}</b></div>
              <div><span>耐药标记</span><b>${isolate.amr ?? '—'}</b></div>
              <div><span>宿主</span><b>${escapeHtml(isolate.host || '—')}</b></div>
            </div>
            <div class="sec-label">七位点等位基因谱</div><div class="allele-grid">${profile}</div>
            <p class="detail-footnote">边由完整两两等位距离图上的 Kruskal 最小生成树产生；布局仅用于显示，不参与距离计算。</p>`;
        }
        if (payload?.type === 'edge') {
          const edge = edges[payload.index];
          const a = isolates[edge.source], b = isolates[edge.target];
          const loci = data.loci || a.profile.map((_, i) => `locus_${i + 1}`);
          const differences = a.profile.map((allele, i) => ({ allele, other: b.profile[i], locus: loci[i] }))
            .filter(item => String(item.allele) !== String(item.other));
          return `<div class="detail-title">Δ ${edge.distance} <span class="muted">alleles</span></div>
            <p class="detail-subtitle">${escapeHtml(a.id)} ↔ ${escapeHtml(b.id)}</p>
            <dl class="kv"><dt>源节点</dt><dd>${escapeHtml(a.st || a.id)}</dd><dt>目标节点</dt><dd>${escapeHtml(b.st || b.id)}</dd></dl>
            <div class="sec-label">差异位点</div>
            <div class="difference-list">${differences.map(d => `<div><span>${escapeHtml(d.locus)}</span><b>${escapeHtml(d.allele)} → ${escapeHtml(d.other)}</b></div>`).join('') || '<p>无差异位点</p>'}</div>
            <p class="detail-footnote">Δ 是两个七位点等位基因谱之间的汉明距离，不是核苷酸差异数。</p>`;
        }
        return '';
      },
    };
  },
};
