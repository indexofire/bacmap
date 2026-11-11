import * as THREE from '../vendor/three.module.js';
import {
  cylinderBetween, lineFromPoints, makeLabel, escapeHtml, formatBp, disposeHierarchy,
} from '../framework/primitives.js';
import { clamp } from '../framework/algorithms.js';

function formatCoordinate(position) {
  return position < 1000 ? `${position} bp` : formatBp(position);
}

function contigOptionLabel(rank, contig) {
  const id = contig.id.length > 38 ? `${contig.id.slice(0, 37)}…` : contig.id;
  return `#${String(rank + 1).padStart(2, '0')}  ${id}  ·  ${formatBp(contig.length)}`;
}

function arcGeometry(r0, r1, a0, a1, z, cx = 0, cy = 0) {
  const steps = Math.max(4, Math.ceil((a1 - a0) / 0.012));
  const positions = [], indices = [];
  for (let i = 0; i < steps; i++) {
    const t0 = a0 + (a1 - a0) * i / steps;
    const t1 = a0 + (a1 - a0) * (i + 1) / steps;
    const i0 = [cx + Math.cos(t0) * r0, cy - Math.sin(t0) * r0, z];
    const o0 = [cx + Math.cos(t0) * r1, cy - Math.sin(t0) * r1, z];
    const i1 = [cx + Math.cos(t1) * r0, cy - Math.sin(t1) * r0, z];
    const o1 = [cx + Math.cos(t1) * r1, cy - Math.sin(t1) * r1, z];
    const base = i * 4;
    positions.push(...i0, ...o0, ...i1, ...i1, ...o0, ...o1);
    indices.push(base, base + 1, base + 2, base + 3, base + 4, base + 5);
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geometry.setIndex(indices);
  geometry.computeVertexNormals();
  return geometry;
}

/** Draft assembly atlas: the bacterial-genome default is a draft circular layout. */
export const assemblyView = {
  id: 'assembly',
  title: '3D 基因组圈图',
  subtitle: 'DRAFT CIRCULAR GENOME ATLAS',
  description: '按细菌基因组常见方式，将 ≥10 kb contigs 从大到小排列成 draft 圈图；这是布局方式，不声明 contigs 已闭合。可切换到线性视图，并从全部 contig 列表选择一个 contig 居中查看。',
  controls: data => {
    const sorted = data.contigs.slice().sort((a, b) => b.length - a.length);
    const maxKb = Math.max(10, Math.ceil(sorted[0].length / 1000));
    return [
      {
        key: 'layout', label: '布局', type: 'select', value: 'circular',
        options: [
          { value: 'circular', label: 'Draft 圈图（从大到小）' },
          { value: 'linear', label: '线性单 contig 视图' },
        ],
      },
      { key: 'thresholdKb', label: '圈图 contig 阈值', type: 'range', min: 0, max: maxKb, step: 1, value: 10, unit: ' kb' },
      {
        key: 'contig', label: 'Contig 列表（线性视图居中）', type: 'select',
        value: sorted[0]?.id || '',
        options: sorted.map((contig, rank) => ({ value: contig.id, label: contigOptionLabel(rank, contig) })),
      },
      { key: 'labels', label: '显示 contig / 命中标签', type: 'toggle', value: true },
      { key: 'gc', label: '显示 GC / GC-skew 轨道', type: 'toggle', value: true },
    ];
  },

  create({ root, data, host, registerPickable }) {
    const sorted = data.contigs.slice().sort((a, b) => b.length - a.length);
    const rankById = new Map(sorted.map((contig, rank) => [contig.id, rank]));
    const features = data.features || [];
    const featureByContig = new Map(sorted.map(contig => [contig.id, []]));
    for (const feature of features) featureByContig.get(feature.contig)?.push(feature);

    const layoutGroup = new THREE.Group();
    layoutGroup.name = 'assembly-layout';
    root.add(layoutGroup);

    let dynamicPickables = [];
    let labelObjects = [], gcObjects = [];
    let contigMeshes = new Map(), featureMeshes = new Map(), arcInfo = new Map();
    let layoutKind = 'circular';
    let thresholdKb = 10;
    let selectedContigId = sorted[0]?.id || '';
    let currentRing = [];

    function addPickable(object, payload) {
      dynamicPickables.push(object);
      return registerPickable(object, payload);
    }

    function clearLayout() {
      selected = null;
      for (const object of dynamicPickables) host.unregisterPickable(object);
      dynamicPickables = [];
      labelObjects = []; gcObjects = [];
      contigMeshes = new Map(); featureMeshes = new Map(); arcInfo = new Map();
      disposeHierarchy(layoutGroup);
    }

    function arcCenterLabel(text, color = '#c3cdf0', height = 0.52) {
      const label = makeLabel(text, { color, height, fontSize: 30, align: 'center' });
      label.position.set(0, 0, 0.06);
      layoutGroup.add(label);
      labelObjects.push(label);
    }

    function renderCircular() {
      const threshold = thresholdKb * 1000;
      currentRing = sorted.filter(contig => contig.length >= threshold);
      if (!currentRing.length) currentRing = [sorted[0]];
      const totalBp = currentRing.reduce((sum, contig) => sum + contig.length, 0);
      const gapAngle = Math.min(0.018, (Math.PI * 2 / currentRing.length) * 0.20);
      const usable = Math.PI * 2 - gapAngle * currentRing.length;
      let cursor = Math.PI / 2;
      const ringRadius = 7.0;

      for (const contig of currentRing) {
        const arcLength = contig.length / totalBp * usable;
        const a0 = cursor, a1 = cursor + arcLength;
        const group = new THREE.Group();
        group.name = `contig:${contig.id}`;
        layoutGroup.add(group);

        const backbone = new THREE.Mesh(
          arcGeometry(6.70, 7.30, a0, a1, 0),
          new THREE.MeshStandardMaterial({
            color: '#3a4d78', roughness: 0.42, metalness: 0.32,
            emissive: new THREE.Color('#1d2c4d').multiplyScalar(0.24),
          }),
        );
        group.add(addPickable(backbone, { type: 'contig', id: contig.id }));
        contigMeshes.set(contig.id, backbone);
        arcInfo.set(contig.id, { start: a0, width: arcLength });

        if (contig.track?.pos?.length) {
          const gcPoints = [], skewPoints = [];
          contig.track.pos.forEach((position, index) => {
            const angle = a0 + position / contig.length * arcLength;
            gcPoints.push(new THREE.Vector3(
              Math.cos(angle) * (6.18 + clamp((contig.track.gc[index] - contig.gc) / 18, -1, 1) * 0.34),
              -Math.sin(angle) * (6.18 + clamp((contig.track.gc[index] - contig.gc) / 18, -1, 1) * 0.34),
              0.10,
            ));
            skewPoints.push(new THREE.Vector3(
              Math.cos(angle) * (5.52 + clamp(contig.track.skew[index] * 5, -1, 1) * 0.26),
              -Math.sin(angle) * (5.52 + clamp(contig.track.skew[index] * 5, -1, 1) * 0.26),
              0.09,
            ));
          });
          if (gcPoints.length > 1) {
            const gcLine = lineFromPoints(gcPoints, 0x45d69b, 0.82);
            const skewLine = lineFromPoints(skewPoints, 0x6d8bff, 0.66);
            group.add(gcLine, skewLine);
            gcObjects.push(gcLine, skewLine);
          }
        }

        for (const feature of featureByContig.get(contig.id) || []) {
          const color = feature.kind === 'amr' ? '#ff2d55' : '#ff8a3d';
          const center = (feature.start + feature.end) / 2;
          const angle = a0 + center / contig.length * arcLength;
          const radius = feature.strand === '-' ? 7.02 : 7.58;
          const width = Math.max(0.085, feature.end - feature.start) / totalBp * usable * radius;
          const material = new THREE.MeshStandardMaterial({
            color, roughness: 0.28, metalness: 0.25,
            emissive: new THREE.Color(color).multiplyScalar(0.25),
          });
          const mesh = new THREE.Mesh(new THREE.BoxGeometry(width, 0.22, 0.32), material);
          mesh.position.set(Math.cos(angle) * radius, -Math.sin(angle) * radius, 0.26);
          mesh.rotation.z = -angle - Math.PI / 2;
          group.add(addPickable(mesh, { type: 'feature', id: feature.id }));
          featureMeshes.set(feature.id, mesh);
          if (width > 0.55) {
            const featureLabel = makeLabel(feature.gene, { color, height: 0.22, fontSize: 20, align: 'center' });
            featureLabel.position.copy(mesh.position).normalize().multiplyScalar(radius + 0.35);
            featureLabel.position.z = 0.22;
            group.add(featureLabel);
            labelObjects.push(featureLabel);
          }
        }

        const mid = a0 + arcLength / 2;
        const labelRadius = 8.38 + (rankById.get(contig.id) % 2 ? 0.42 : 0);
        const shortId = contig.id.length > 22 ? `${contig.id.slice(0, 21)}…` : contig.id;
        const label = makeLabel(`${shortId} · ${formatBp(contig.length)}`, {
          color: '#9aabd8', height: 0.27, fontSize: 22, align: 'center',
        });
        label.position.set(Math.cos(mid) * labelRadius, -Math.sin(mid) * labelRadius, 0.18);
        group.add(label);
        labelObjects.push(label);

        cursor = a1 + gapAngle;
      }

      arcCenterLabel(`DRAFT CIRCULAR LAYOUT · ≥ ${formatCoordinate(threshold)}`, '#eef2ff', 0.46);
      const sublabel = makeLabel(
        `${currentRing.length} contigs · ${formatBp(totalBp)} · sorted by length`,
        { color: '#8b9cc8', height: 0.30, fontSize: 24, align: 'center' },
      );
      sublabel.position.set(0, -0.55, 0.06);
      layoutGroup.add(sublabel);
      labelObjects.push(sublabel);
    }

    function renderLinear() {
      const contig = sorted.find(item => item.id === selectedContigId) || sorted[0];
      selectedContigId = contig.id;
      const group = new THREE.Group();
      group.name = `contig:${contig.id}`;
      layoutGroup.add(group);
      currentRing = [contig];

      const width = 18, x0 = -width / 2, y = 0;
      const backboneMaterial = new THREE.MeshStandardMaterial({
        color: '#3a4d78', roughness: 0.42, metalness: 0.32,
        emissive: new THREE.Color('#1d2c4d').multiplyScalar(0.24),
      });
      const backbone = cylinderBetween(
        new THREE.Vector3(x0, y, 0), new THREE.Vector3(x0 + width, y, 0), 0.085,
        backboneMaterial, 12,
      );
      group.add(addPickable(backbone, { type: 'contig', id: contig.id }));
      contigMeshes.set(contig.id, backbone);

      if (contig.track?.pos?.length) {
        const gcPoints = [], skewPoints = [];
        contig.track.pos.forEach((position, index) => {
          const x = x0 + position / contig.length * width;
          gcPoints.push(new THREE.Vector3(
            x, y + 0.16 + clamp((contig.track.gc[index] - contig.gc) / 18, -1, 1) * 0.30, 0.12,
          ));
          skewPoints.push(new THREE.Vector3(
            x, y - 0.15 + clamp(contig.track.skew[index] * 5, -1, 1) * 0.22, 0.11,
          ));
        });
        if (gcPoints.length > 1) {
          const gcLine = lineFromPoints(gcPoints, 0x45d69b, 0.82);
          const skewLine = lineFromPoints(skewPoints, 0x6d8bff, 0.66);
          group.add(gcLine, skewLine);
          gcObjects.push(gcLine, skewLine);
        }
      }

      for (const feature of featureByContig.get(contig.id) || []) {
        const color = feature.kind === 'amr' ? '#ff2d55' : '#ff8a3d';
        const featureWidth = Math.max(0.10, (feature.end - feature.start) / contig.length * width);
        const material = new THREE.MeshStandardMaterial({
          color, roughness: 0.28, metalness: 0.25,
          emissive: new THREE.Color(color).multiplyScalar(0.25),
        });
        const mesh = new THREE.Mesh(new THREE.BoxGeometry(featureWidth, 0.30, 0.36), material);
        const center = (feature.start + feature.end) / 2;
        mesh.position.set(x0 + center / contig.length * width, y, 0.28);
        group.add(addPickable(mesh, { type: 'feature', id: feature.id }));
        featureMeshes.set(feature.id, mesh);
        if (featureWidth > 0.55) {
          const featureLabel = makeLabel(feature.gene, { color, height: 0.23, fontSize: 21, align: 'center' });
          featureLabel.position.copy(mesh.position).add(new THREE.Vector3(0, -0.38, 0.15));
          group.add(featureLabel);
          labelObjects.push(featureLabel);
        }
      }

      const title = makeLabel(`${contig.id} · ${formatBp(contig.length)} · linear contig`, {
        color: '#dfe6f8', height: 0.42, fontSize: 27, align: 'center',
      });
      title.position.set(0, 1.05, 0.04);
      group.add(title);
      labelObjects.push(title);

      const rank = rankById.get(contig.id) + 1;
      const rankLabel = makeLabel(`length rank ${rank} / ${sorted.length}`, {
        color: '#8b9cc8', height: 0.28, fontSize: 23, align: 'center',
      });
      rankLabel.position.set(0, -0.75, 0.03);
      group.add(rankLabel);
      labelObjects.push(rankLabel);

      const axisY = -1.25;
      group.add(lineFromPoints([
        new THREE.Vector3(x0, axisY, 0), new THREE.Vector3(x0 + width, axisY, 0),
      ], 0x52617f, 0.55));
      for (let i = 0; i <= 5; i++) {
        const position = contig.length * i / 5;
        const x = x0 + width * i / 5;
        group.add(lineFromPoints([
          new THREE.Vector3(x, axisY - 0.10, 0), new THREE.Vector3(x, axisY + 0.10, 0),
        ], 0x7e8bb0, 0.65));
        const label = makeLabel(formatCoordinate(position), {
          color: '#7e8bb0', height: 0.24, fontSize: 21, align: 'center',
        });
        label.position.set(x, axisY - 0.35, 0);
        group.add(label);
        labelObjects.push(label);
      }
    }

    function render() {
      clearLayout();
      if (layoutKind === 'linear') renderLinear();
      else renderCircular();
    }

    let selected = null;
    function clearSelection() {
      if (!selected) return;
      selected.material.emissive.copy(selected.emissive);
      selected = null;
    }
    function select(payload) {
      clearSelection();
      const object = payload?.type === 'contig' ? contigMeshes.get(payload.id) : featureMeshes.get(payload?.id);
      if (!object) return;
      selected = object;
      selected.emissive = object.material.emissive.clone();
      object.material.emissive.set('#ffffff').multiplyScalar(0.42);
    }

    function payloadPosition(payload) {
      if (payload?.type === 'contig' && layoutKind === 'circular') {
        const info = arcInfo.get(payload.id);
        if (info) {
          const angle = info.start + info.width / 2;
          return new THREE.Vector3(Math.cos(angle) * 7, -Math.sin(angle) * 7, 0);
        }
      }
      const object = payload?.type === 'contig' ? contigMeshes.get(payload.id) : featureMeshes.get(payload?.id);
      return object?.position || null;
    }

    render();

    return {
      stats: () => {
        const threshold = thresholdKb * 1000;
        const included = layoutKind === 'circular' ? currentRing.length : sorted.filter(item => item.length >= threshold).length;
        return [
          { label: '组装总长度', value: formatBp(data.total_bp) },
          { label: 'Contigs', value: sorted.length },
          { label: '圈图 contigs', value: layoutKind === 'circular' ? `${included} / ${sorted.length}` : `${included} eligible` },
          { label: 'CARD / VFDB 命中', value: features.length },
        ];
      },
      resetCamera: () => {
        if (layoutKind === 'circular') {
          host.controls.maxDistance = 120;
          host.setCamera(new THREE.Vector3(0, 2.0, 29), new THREE.Vector3(0, 0, 0));
        } else {
          host.controls.maxDistance = 120;
          host.setCamera(new THREE.Vector3(0, 1.4, 27), new THREE.Vector3(0, 0, 0));
        }
      },
      setOption: (key, value) => {
        if (key === 'layout') {
          layoutKind = value === 'linear' ? 'linear' : 'circular';
          render();
          host.resetCamera();
        }
        if (key === 'thresholdKb') {
          thresholdKb = Math.max(0, Number(value));
          if (layoutKind === 'circular') render();
          host.resetCamera();
        }
        if (key === 'contig') {
          selectedContigId = String(value);
          if (layoutKind === 'linear') {
            render();
            host.resetCamera();
          } else {
            const payload = { type: 'contig', id: selectedContigId };
            select(payload);
            const position = payloadPosition(payload);
            if (position) host.flyTo(position.clone().add(new THREE.Vector3(0, 1.2, 9)), position);
          }
        }
        if (key === 'labels') labelObjects.forEach(object => { object.visible = value; });
        if (key === 'gc') gcObjects.forEach(object => { object.visible = value; });
      },
      select,
      focus: payload => {
        const position = payloadPosition(payload);
        if (position) host.flyTo(position.clone().add(new THREE.Vector3(0, 1.0, 7)), position);
      },
      selectionLabel: payload => {
        if (payload?.type === 'contig') return payload.id;
        if (payload?.type === 'feature') return features.find(feature => feature.id === payload.id)?.gene || payload.id;
        return '—';
      },
      tooltip: payload => {
        if (payload?.type === 'contig') {
          const contig = sorted.find(item => item.id === payload.id);
          const rank = rankById.get(contig.id) + 1;
          return `<div class="tt-name">${escapeHtml(contig.id)}</div>
            <div class="tt-sub">#${rank} · ${formatBp(contig.length)} · GC ${contig.gc}%</div>
            <div class="tt-sub">draft contig · circular layout only</div>`;
        }
        if (payload?.type === 'feature') {
          const feature = features.find(item => item.id === payload.id);
          return `<div class="tt-name">${escapeHtml(feature.gene)}</div>
            <div class="tt-sub">${escapeHtml(feature.database)} · ${escapeHtml(feature.contig)}</div>
            <div class="tt-sub">${feature.start + 1}–${feature.end} · ${feature.strand}</div>`;
        }
        return '';
      },
      inspect: payload => {
        if (payload?.type === 'contig') {
          const contig = sorted.find(item => item.id === payload.id);
          const hits = featureByContig.get(contig.id) || [];
          const rank = rankById.get(contig.id) + 1;
          return `<div class="detail-title">${escapeHtml(contig.id)}</div>
            <p class="detail-subtitle">draft assembly contig · ${escapeHtml(contig.name)}</p>
            <div class="metric-grid"><div><span>长度</span><b>${formatBp(contig.length)}</b></div><div><span>长度排名</span><b>#${rank}</b></div><div><span>GC</span><b>${contig.gc}%</b></div><div><span>筛查命中</span><b>${hits.length}</b></div></div>
            <dl class="kv"><dt>拓扑</dt><dd>draft contig（未声明闭合）</dd><dt>GC bins</dt><dd>${contig.track.pos.length}</dd><dt>命中基因</dt><dd>${hits.map(hit => escapeHtml(hit.gene)).join(', ') || '—'}</dd></dl>
            <p class="detail-footnote">圈图是 draft contigs 的常见可视化布局，不代表该 contig 已闭合。线性视图可从左侧 contig 列表选择并居中查看。</p>`;
        }
        if (payload?.type === 'feature') {
          const feature = features.find(item => item.id === payload.id);
          return `<div class="detail-title">${escapeHtml(feature.gene)}</div>
            <p class="detail-subtitle">${feature.kind === 'amr' ? 'CARD 耐药命中' : 'VFDB 毒力命中'} · ${escapeHtml(feature.database)}</p>
            <div class="metric-grid"><div><span>Identity</span><b>${feature.identity ?? '—'}%</b></div><div><span>Coverage</span><b>${feature.coverage ?? '—'}%</b></div><div><span>长度</span><b>${formatBp(feature.end - feature.start)}</b></div><div><span>链</span><b>${escapeHtml(feature.strand)}</b></div></div>
            <dl class="kv"><dt>Contig</dt><dd>${escapeHtml(feature.contig)}</dd><dt>坐标</dt><dd>${feature.start + 1}–${feature.end}</dd><dt>产物</dt><dd>${escapeHtml(feature.product || '—')}</dd></dl>`;
        }
        return '';
      },
    };
  },
};
