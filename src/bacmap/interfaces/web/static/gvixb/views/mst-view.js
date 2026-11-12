import * as THREE from '../vendor/three.module.js';
import { minimumSpanningTree, forceLayout3D, clamp } from '../framework/algorithms.js';
import { makeLabel, groupColors, escapeHtml, makeDustField, makeDotTexture, makeDotSprite } from '../framework/primitives.js';

const distanceColor = distance => {
  const t = clamp(distance / 7, 0, 1);
  const cold = new THREE.Color('#53e6ff'), warm = new THREE.Color('#ff8a3d');
  return cold.lerp(warm, t);
};

const backOut = t => { const s = 1.70158; const x = t - 1; return 1 + (s + 1) * x * x * x + s * x * x; };

const lineBetween = (a, b, material) =>
  new THREE.Line(new THREE.BufferGeometry().setFromPoints([a.clone(), b.clone()]), material);

export const mstView = {
  id: 'mst',
  dockLabel: 'MST',
  title: '3D 最小生成树',
  subtitle: 'MLST MINIMUM SPANNING TREE',
  dataUrl: './data/framework/mst.json',
  description: '忠实渲染当前运行中 gmlst visual mst 已生成的节点、边和等位距离。样本为平面圆点、连接为细线；三维力导向布局仅用于显示，纵深不承载生物学含义，边与节点颜色、大小所编码的变量与数据契约一致。',
  controls: [
    { key: 'labels', label: '显示样本标签', type: 'toggle', value: true },
    { key: 'distances', label: '显示等位距离', type: 'toggle', value: true },
  ],

  create({ root, data, host, registerPickable }) {
    const precomputed = Array.isArray(data.nodes) && Array.isArray(data.edges);
    if (!precomputed && (!Array.isArray(data.isolates) || data.isolates.length < 2)) throw new Error('MST 数据至少需要两个节点');
    const isolates = precomputed
      ? data.nodes.map(node => ({ id: node.label || node.id, count: 1, group: '', profile: null }))
      : data.isolates;
    let edges;
    if (precomputed) {
      const indices = new Map(data.nodes.map((node, index) => [String(node.id), index]));
      edges = data.edges.map(edge => ({
        source: indices.get(String(edge.source)), target: indices.get(String(edge.target)),
        distance: Number(edge.weight),
      }));
      if (edges.some(edge => edge.source === undefined || edge.target === undefined || !Number.isFinite(edge.distance))) {
        throw new Error('gmlst MST 边引用或权重无效');
      }
    } else {
      edges = minimumSpanningTree(isolates);
    }
    const positions = forceLayout3D(isolates, edges).map(p => new THREE.Vector3(p.x, p.y, p.z));
    const colors = groupColors(isolates.map(isolate => isolate.group || '未分组'));

    // --- Atmosphere: deep-space presentation, decorative only. ---
    host.scene.fog = new THREE.FogExp2(0x05070d, 0.012);
    host.setBloom?.({ strength: 0.38, radius: 0.4, threshold: 0.5 });
    host.setAutoRotate(true, 0.5);
    host.raycaster.params.Line.threshold = 0.3;
    const dust = makeDustField({ count: 650, radius: 58, color: 0x9fb2e8 });
    root.add(dust);
    const dotTexture = makeDotTexture();

    const edgeGroup = new THREE.Group(), nodeGroup = new THREE.Group();
    const labelGroup = new THREE.Group(), distanceGroup = new THREE.Group();
    root.add(edgeGroup, nodeGroup, labelGroup, distanceGroup);

    const degree = isolates.map(() => 0);
    const edgeLines = [], edgeMaterials = [];
    edges.forEach((edge, index) => {
      degree[edge.source]++;
      degree[edge.target]++;
      const color = distanceColor(edge.distance);
      const material = new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0 });
      const line = lineBetween(positions[edge.source], positions[edge.target], material);
      edgeGroup.add(registerPickable(line, { type: 'edge', index }));
      edgeLines.push(line);
      edgeMaterials.push(material);
      const label = makeLabel(`Δ ${edge.distance}`, { color: color.clone().lerp(new THREE.Color('#ffffff'), 0.3).getStyle(), height: 0.26, fontSize: 21, align: 'center' });
      label.position.copy(positions[edge.source]).lerp(positions[edge.target], 0.5).add(new THREE.Vector3(0, 0.28, 0.2));
      label.material.opacity = 0;
      distanceGroup.add(label);
    });

    const nodeDots = [];
    isolates.forEach((isolate, index) => {
      const color = new THREE.Color(colors.get(isolate.group || '未分组'));
      const size = 0.78 + Math.sqrt(Math.max(1, isolate.count || 1)) * 0.19;
      const dot = makeDotSprite({ color: color.clone().lerp(new THREE.Color('#ffffff'), 0.3), size, texture: dotTexture });
      dot.position.copy(positions[index]);
      dot.userData.baseColor = color.clone();
      dot.scale.setScalar(0.001);
      nodeGroup.add(registerPickable(dot, { type: 'node', index }));
      nodeDots.push(dot);
      const label = makeLabel(isolate.id, { color: color.clone().lerp(new THREE.Color('#ffffff'), 0.3).getStyle(), height: 0.32, fontSize: 26, align: 'center' });
      label.position.copy(positions[index]).add(new THREE.Vector3(0, size * 0.62 + 0.22, 0.14));
      label.material.opacity = 0;
      labelGroup.add(label);
    });

    // Subtle scale legend: dot size encodes count, line hue encodes allele distance.
    const legend = makeLabel('LINE  Δ 0–7 ALLELES    ·    DOT SIZE ENCODES ISOLATE COUNT    ·    3D LAYOUT IS DISPLAY-ONLY', {
      color: '#68779b', height: 0.26, fontSize: 20, align: 'center',
    });
    legend.position.set(0, Math.min(...positions.map(p => p.y)) - 1.4, 0);
    legend.material.opacity = 0;
    root.add(legend);

    // --- Intro choreography: dots condense in, links ignite, labels surface. ---
    const nodeDelay = i => 0.15 + (i / Math.max(1, isolates.length)) * 0.85;
    const edgeDelay = i => 0.55 + (i / Math.max(1, edges.length)) * 0.95;
    const NODE_DUR = 0.5, EDGE_DUR = 0.55, LABEL_T0 = 1.55, LABEL_DUR = 0.5;
    const INTRO_END = 1.55 + 0.5 + 0.2;
    let elapsed = 0, introDone = false;

    let selected = null;
    function clearSelection() {
      if (!selected) return;
      if (selected.kind === 'node') {
        selected.object.material.color.copy(selected.color);
        if (introDone) selected.object.scale.setScalar(selected.object.userData.dotSize);
      } else {
        selected.object.material.color.copy(selected.color);
        selected.object.material.opacity = 0.85;
      }
      selected = null;
    }
    function select(payload) {
      clearSelection();
      if (!payload) return;
      const kind = payload.type;
      const object = kind === 'node' ? nodeDots[payload.index] : edgeLines[payload.index];
      if (!object) return;
      selected = { object, kind, color: object.material.color.clone() };
      object.material.color.set('#ffffff');
      if (kind === 'node') {
        object.material.opacity = 1;
        if (introDone) object.scale.setScalar(object.userData.dotSize * 1.4);
      } else {
        object.material.opacity = 1;
      }
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
        { label: 'MLST 位点', value: data.n_loci || isolates[0]?.profile?.length || 0 },
        { label: '拓扑来源', value: precomputed ? 'gmlst MST' : 'Kruskal' },
      ],
      resetCamera: () => {
        const distance = isolates.length <= 3 ? 34 : 27;
        host.setCamera(new THREE.Vector3(distance * 0.36, distance * 0.26, distance * 0.9), new THREE.Vector3(0, 0.2, 0));
      },
      setOption: (key, value) => {
        if (key === 'labels') labelGroup.visible = value;
        if (key === 'distances') distanceGroup.visible = value;
      },
      update: dt => {
        dust.rotation.y += dt * 0.008;
        if (introDone) return;
        elapsed += dt;
        nodeDots.forEach((dot, i) => {
          const t = clamp((elapsed - nodeDelay(i)) / NODE_DUR, 0, 1);
          dot.scale.setScalar(Math.max(0.001, dot.userData.dotSize * backOut(t)));
        });
        edgeMaterials.forEach((material, i) => {
          const t = clamp((elapsed - edgeDelay(i)) / EDGE_DUR, 0, 1);
          material.opacity = t * 0.85;
        });
        const labelT = clamp((elapsed - LABEL_T0) / LABEL_DUR, 0, 1);
        labelGroup.children.forEach(label => { label.material.opacity = labelT; });
        distanceGroup.children.forEach(label => { label.material.opacity = labelT; });
        legend.material.opacity = labelT;
        if (elapsed >= INTRO_END) {
          introDone = true;
          nodeDots.forEach(dot => dot.scale.setScalar(dot.userData.dotSize));
          edgeMaterials.forEach(material => { material.opacity = 0.85; });
          if (selected?.kind === 'node') selected.object.scale.setScalar(selected.object.userData.dotSize * 1.4);
        }
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
          const alleles = Array.isArray(isolate.profile) ? isolate.profile : [];
          const loci = data.loci || alleles.map((_, i) => `locus_${i + 1}`);
          const profile = alleles.map((allele, i) => `<div class="allele"><span>${escapeHtml(loci[i])}</span><b>${escapeHtml(allele)}</b></div>`).join('');
          const profileSection = alleles.length
            ? `<div class="sec-label">等位基因谱</div><div class="allele-grid">${profile}</div>`
            : `<dl class="kv"><dt>Scheme</dt><dd>${escapeHtml(data.scheme || '—')}</dd><dt>位点数</dt><dd>${data.n_loci || '—'}</dd></dl>`;
          return `<div class="detail-title">${escapeHtml(isolate.id)}</div>
            <p class="detail-subtitle">${escapeHtml(isolate.st || 'cgMLST 样本')} · ${escapeHtml(isolate.group || data.group || '未分组')}</p>
            <div class="metric-grid">
              <div><span>聚合样本</span><b>${isolate.count || 1}</b></div>
              <div><span>MST 节点度</span><b>${degree[payload.index]}</b></div>
              <div><span>耐药标记</span><b>${isolate.amr ?? '—'}</b></div>
              <div><span>宿主</span><b>${escapeHtml(isolate.host || '—')}</b></div>
            </div>${profileSection}
            <p class="detail-footnote">${precomputed ? '节点与边直接来自 gmlst visual mst；三维力导向布局仅用于显示，纵深不承载生物学含义。' : '边由完整两两等位距离图上的 Kruskal 最小生成树产生；三维力导向布局仅用于显示，纵深不承载生物学含义。'}</p>`;
        }
        if (payload?.type === 'edge') {
          const edge = edges[payload.index];
          const a = isolates[edge.source], b = isolates[edge.target];
          const hasProfiles = Array.isArray(a.profile) && Array.isArray(b.profile);
          const loci = data.loci || (hasProfiles ? a.profile.map((_, i) => `locus_${i + 1}`) : []);
          const differences = hasProfiles ? a.profile.map((allele, i) => ({ allele, other: b.profile[i], locus: loci[i] }))
            .filter(item => String(item.allele) !== String(item.other)) : [];
          const differenceSection = hasProfiles
            ? `<div class="sec-label">差异位点</div><div class="difference-list">${differences.map(d => `<div><span>${escapeHtml(d.locus)}</span><b>${escapeHtml(d.allele)} → ${escapeHtml(d.other)}</b></div>`).join('') || '<p>无差异位点</p>'}</div>`
            : '<p class="detail-footnote">当前 MST 载荷不包含逐位点等位谱；此处只显示 gmlst 输出的边权，不反推差异位点。</p>';
          return `<div class="detail-title">Δ ${edge.distance} <span class="muted">alleles</span></div>
            <p class="detail-subtitle">${escapeHtml(a.id)} ↔ ${escapeHtml(b.id)}</p>
            <dl class="kv"><dt>源节点</dt><dd>${escapeHtml(a.st || a.id)}</dd><dt>目标节点</dt><dd>${escapeHtml(b.st || b.id)}</dd></dl>
            ${differenceSection}
            <p class="detail-footnote">Δ 是等位基因距离，不是核苷酸差异数。</p>`;
        }
        return '';
      },
    };
  },
};
