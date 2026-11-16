import * as THREE from '../lib/three.module.js';
import { cylinderBetween, makeLabel, escapeHtml, formatBp, PALETTE } from '../framework/primitives.js';

function bezierPoint(p0, p1, p2, p3, t) {
  const u = 1 - t;
  return p0.clone().multiplyScalar(u * u * u)
    .add(p1.clone().multiplyScalar(3 * u * u * t))
    .add(p2.clone().multiplyScalar(3 * u * t * t))
    .add(p3.clone().multiplyScalar(t * t * t));
}

/** A translucent 3D ribbon; endpoint coordinates remain exact genomic data. */
function makeRibbon(source, target, reverse, identity) {
  const lift = 2.0 + (reverse ? 0.45 : 0);
  const dy = target.y - source.y;
  const p1 = source.clone().add(new THREE.Vector3(0, dy * 0.42, lift));
  const p2 = target.clone().add(new THREE.Vector3(0, -dy * 0.42, lift));
  const positions = [], indices = [], centers = [];
  const segments = 36;
  const halfWidth = 0.12 + Math.max(0, identity - 80) / 20 * 0.10;
  for (let i = 0; i <= segments; i++) {
    const t = i / segments;
    const point = bezierPoint(source, p1, p2, target, t);
    const before = bezierPoint(source, p1, p2, target, Math.max(0, t - 0.01));
    const after = bezierPoint(source, p1, p2, target, Math.min(1, t + 0.01));
    const tangent = after.sub(before).normalize();
    const side = new THREE.Vector3(-tangent.y, tangent.x, 0).normalize().multiplyScalar(halfWidth);
    positions.push(point.x + side.x, point.y + side.y, point.z + side.z);
    positions.push(point.x - side.x, point.y - side.y, point.z - side.z);
    centers.push(point);
    if (i < segments) {
      const a = i * 2, b = a + 1, c = a + 2, d = a + 3;
      indices.push(a, b, c, b, d, c);
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geometry.setIndex(indices);
  geometry.computeVertexNormals();
  const color = reverse ? '#ff8a3d' : '#53e6ff';
  const material = new THREE.MeshStandardMaterial({
    color, emissive: new THREE.Color(color).multiplyScalar(0.13),
    transparent: true, opacity: 0.34, side: THREE.DoubleSide,
    depthWrite: false, roughness: 0.48, metalness: 0.08,
  });
  const mesh = new THREE.Mesh(geometry, material);
  const line = new THREE.Line(
    new THREE.BufferGeometry().setFromPoints(centers),
    new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.50 }),
  );
  return { mesh, line };
}

export const syntenyView = {
  id: 'synteny',
  dockLabel: 'Synteny',
  title: '3D 序列共线性',
  subtitle: 'COMPARATIVE GENOME SYNTENY',
  dataUrl: './data/framework/synteny.json',
  description: '平行基因组轨道上的同源区块比较。曲线连接真实输入坐标，橙色表示反向/倒位匹配；所有基因组使用共同的 bp 水平尺度。',
  controls: [
    { key: 'identity', label: '最低序列一致性', type: 'range', min: 80, max: 100, step: 1, value: 80, unit: '%' },
    { key: 'inversions', label: '显示反向匹配', type: 'toggle', value: true },
    { key: 'labels', label: '显示区块标签', type: 'toggle', value: true },
  ],

  create({ root, data, host, registerPickable }) {
    if (!Array.isArray(data.genomes) || !Array.isArray(data.blocks) || !Array.isArray(data.links)) {
      throw new Error('共线性数据需要 genomes、blocks 和 links 数组');
    }
    const genomes = data.genomes;
    const genomeIndex = new Map(genomes.map((genome, i) => [genome.id, i]));
    const blockById = new Map(data.blocks.map(block => [block.id, block]));
    const maxLength = Math.max(...genomes.map(genome => genome.length));
    const WIDTH = 22;
    const TRACK_GAP = 4.4;
    const yOf = genomeId => (genomeIndex.get(genomeId) - (genomes.length - 1) / 2) * TRACK_GAP;
    const xOf = (bp, genomeId) => {
      const genome = genomes[genomeIndex.get(genomeId)];
      return (bp - genome.length / 2) / maxLength * WIDTH;
    };
    const trackGroup = new THREE.Group(), blockGroup = new THREE.Group(), linkGroup = new THREE.Group();
    const labelGroup = new THREE.Group();
    root.add(linkGroup, trackGroup, blockGroup, labelGroup);

    const blockMeshes = new Map();
    const connected = new Map(data.blocks.map(block => [block.id, 0]));
    for (const link of data.links) {
      connected.set(link.source, (connected.get(link.source) || 0) + 1);
      connected.set(link.target, (connected.get(link.target) || 0) + 1);
    }

    genomes.forEach((genome, index) => {
      const color = genome.color || PALETTE[index % PALETTE.length];
      const y = yOf(genome.id);
      const material = new THREE.MeshStandardMaterial({ color: '#27344e', roughness: 0.5, metalness: 0.3 });
      const trackWidth = WIDTH * genome.length / maxLength;
      const backbone = cylinderBetween(new THREE.Vector3(-trackWidth / 2, y, 0), new THREE.Vector3(trackWidth / 2, y, 0), 0.10, material, 12);
      trackGroup.add(backbone);
      const label = makeLabel(genome.label || genome.id, { color, height: 0.36, fontSize: 27, align: 'left' });
      label.position.set(-trackWidth / 2, y + 0.88, 0.3);
      trackGroup.add(label);
      const length = makeLabel(formatBp(genome.length), { color: '#68779b', height: 0.27, fontSize: 22, align: 'center' });
      length.position.set(trackWidth / 2 - 0.5, y + 0.88, 0.3);
      trackGroup.add(length);
    });

    for (const block of data.blocks) {
      if (!genomeIndex.has(block.genome)) throw new Error(`区块 ${block.id} 引用了未知基因组 ${block.genome}`);
      const gi = genomeIndex.get(block.genome), genome = genomes[gi];
      const color = genome.color || PALETTE[gi % PALETTE.length];
      const width = Math.max(0.16, (block.end - block.start) / maxLength * WIDTH);
      const geometry = new THREE.BoxGeometry(width, 0.48, 0.38);
      const material = new THREE.MeshStandardMaterial({
        color, roughness: 0.30, metalness: 0.32,
        emissive: new THREE.Color(color).multiplyScalar(0.12),
      });
      const mesh = new THREE.Mesh(geometry, material);
      mesh.position.set(xOf((block.start + block.end) / 2, genome.id), yOf(block.genome), 0.25);
      blockGroup.add(registerPickable(mesh, { type: 'block', id: block.id }));
      blockMeshes.set(block.id, mesh);
      const label = makeLabel(block.label || block.id, { color: '#a8b5d6', height: 0.25, fontSize: 22, align: 'center' });
      label.position.copy(mesh.position).add(new THREE.Vector3(0, 0.48, 0.18));
      labelGroup.add(label);
    }

    const linkObjects = [];
    data.links.forEach((link, index) => {
      const sourceBlock = blockById.get(link.source), targetBlock = blockById.get(link.target);
      if (!sourceBlock || !targetBlock) throw new Error(`连接 ${link.id} 引用了未知区块`);
      const source = blockMeshes.get(link.source).position.clone();
      const target = blockMeshes.get(link.target).position.clone();
      source.z = target.z = 0.38;
      const reverse = link.orientation === 'reverse' || sourceBlock.strand !== targetBlock.strand;
      const identity = Number(link.identity ?? 100);
      const { mesh, line } = makeRibbon(source, target, reverse, identity);
      linkGroup.add(registerPickable(mesh, { type: 'link', index }), line);
      linkObjects.push({ mesh, line, link, reverse, identity });
    });

    const legend = makeLabel('FORWARD / CYAN     ·     REVERSE / AMBER     ·     RIBBON WIDTH = IDENTITY', {
      color: '#68779b', height: 0.28, fontSize: 22, align: 'center',
    });
    legend.position.set(0, Math.min(...genomes.map(genome => yOf(genome.id))) - 1.2, 0);
    root.add(legend);

    let selected = null;
    function clearSelection() {
      if (!selected) return;
      selected.object.material.color.copy(selected.color);
      if (selected.object.material.emissive) selected.object.material.emissive.copy(selected.emissive);
      selected.object.material.opacity = selected.opacity;
      selected = null;
    }
    function select(payload) {
      clearSelection();
      if (!payload) return;
      const object = payload.type === 'block' ? blockMeshes.get(payload.id) : linkObjects[payload.index]?.mesh;
      if (!object) return;
      selected = {
        object, color: object.material.color.clone(), opacity: object.material.opacity,
        emissive: object.material.emissive?.clone(),
      };
      object.material.color.set('#ffffff');
      if (object.material.emissive) object.material.emissive.set('#53e6ff').multiplyScalar(0.4);
      object.material.opacity = Math.max(0.75, object.material.opacity);
    }

    function payloadPosition(payload) {
      if (payload?.type === 'block') return blockMeshes.get(payload.id)?.position;
      if (payload?.type === 'link') {
        const item = linkObjects[payload.index];
        if (item) return blockMeshes.get(item.link.source).position.clone().lerp(blockMeshes.get(item.link.target).position, 0.5);
      }
      return null;
    }

    return {
      stats: () => [
        { label: '比较基因组', value: genomes.length },
        { label: '同源区块', value: data.blocks.length },
        { label: '同源连接', value: data.links.length },
        { label: '反向连接', value: data.links.filter(link => link.orientation === 'reverse').length },
      ],
      resetCamera: () => host.setCamera(new THREE.Vector3(0, 1.2, 28.5), new THREE.Vector3(0, 0, 0.5)),
      setOption: (key, value) => {
        if (key === 'labels') labelGroup.visible = value;
        if (key === 'identity' || key === 'inversions') {
          if (key === 'identity') root.userData.identity = Number(value);
          if (key === 'inversions') root.userData.inversions = value;
          const identity = Number(root.userData.identity ?? 80);
          const showInversions = root.userData.inversions ?? true;
          for (const item of linkObjects) {
            item.mesh.visible = item.line.visible = item.identity >= identity && (showInversions || !item.reverse);
          }
        }
      },
      select,
      focus: payload => {
        const position = payloadPosition(payload);
        if (position) host.flyTo(position.clone().add(new THREE.Vector3(0, 1.0, 7.5)), position);
      },
      selectionLabel: payload => {
        if (payload?.type === 'block') return blockById.get(payload.id)?.label || payload.id;
        if (payload?.type === 'link') return data.links[payload.index]?.id || 'Synteny link';
        return '—';
      },
      tooltip: payload => {
        if (payload?.type === 'block') {
          const block = blockById.get(payload.id);
          return `<div class="tt-name">${escapeHtml(block.label || block.id)}</div>
            <div class="tt-sub">${escapeHtml(block.genome)} · ${formatBp(block.start)}–${formatBp(block.end)}</div>
            <div class="tt-sub">${connected.get(block.id) || 0} 条同源连接</div>`;
        }
        if (payload?.type === 'link') {
          const link = data.links[payload.index];
          return `<div class="tt-name">${escapeHtml(link.id)}</div>
            <div class="tt-sub">identity ${link.identity}% · ${link.orientation === 'reverse' ? '反向匹配' : '同向匹配'}</div>`;
        }
        return '';
      },
      inspect: payload => {
        if (payload?.type === 'block') {
          const block = blockById.get(payload.id);
          return `<div class="detail-title">${escapeHtml(block.label || block.id)}</div>
            <p class="detail-subtitle">同源区块 · ${escapeHtml(block.genome)}</p>
            <div class="metric-grid">
              <div><span>起点</span><b>${block.start.toLocaleString()}</b></div>
              <div><span>终点</span><b>${block.end.toLocaleString()}</b></div>
              <div><span>长度</span><b>${formatBp(block.end - block.start)}</b></div>
              <div><span>连接数</span><b>${connected.get(block.id) || 0}</b></div>
            </div>
            <dl class="kv"><dt>方向</dt><dd>${escapeHtml(block.strand || '+')}</dd><dt>区块 ID</dt><dd>${escapeHtml(block.id)}</dd></dl>`;
        }
        if (payload?.type === 'link') {
          const link = data.links[payload.index];
          const source = blockById.get(link.source), target = blockById.get(link.target);
          return `<div class="detail-title">${escapeHtml(link.id)}</div>
            <p class="detail-subtitle">${escapeHtml(source.label || source.id)} ↔ ${escapeHtml(target.label || target.id)}</p>
            <div class="metric-grid">
              <div><span>Identity</span><b>${link.identity}%</b></div>
              <div><span>方向</span><b>${link.orientation === 'reverse' ? 'REVERSE' : 'FORWARD'}</b></div>
            </div>
            <dl class="kv">
              <dt>源坐标</dt><dd>${escapeHtml(source.genome)}:${source.start.toLocaleString()}–${source.end.toLocaleString()}</dd>
              <dt>目标坐标</dt><dd>${escapeHtml(target.genome)}:${target.start.toLocaleString()}–${target.end.toLocaleString()}</dd>
            </dl>
            <p class="detail-footnote">曲线高度只是空间布局；identity、方向和端点坐标才携带比较基因组学信息。</p>`;
        }
        return '';
      },
    };
  },
};
