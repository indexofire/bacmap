import * as THREE from '../vendor/three.module.js';
import { makeLabel, escapeHtml, formatBp } from '../framework/primitives.js';
import { clamp } from '../framework/algorithms.js';

const COG_COLORS = {
  J:'#5ee0ff',A:'#8b9cff',K:'#a78bfa',L:'#7c6cf5',B:'#6b6f9a',
  M:'#2ec4b6',D:'#33b4c9',N:'#35d0a8',O:'#4ec9d8',T:'#3f9fd0',U:'#5a8fc8',
  V:'#8f6f9e',W:'#7f8ea8',Y:'#5f6f8f',Z:'#6f8f9f',
  C:'#d8d44d',E:'#b4d64d',F:'#8fd64d',G:'#62d465',H:'#a8d64d',I:'#cfd44d',
  P:'#74d6a0',Q:'#c0b44d',R:'#6b7590',S:'#55607d',X:'#8b7ba8',
};
const KIND_COLORS = {
  amr:'#ff2d55', vir:'#ff8a3d', cds:'#6d8bff', trna:'#4de8ff', rrna:'#2ee6c0',
  ncrna:'#3ee0d0', tmrna:'#3ee0d0', sorf:'#75d6c3', pseudogene:'#424d68', unknown:'#3d465c',
};
const CATEGORY_LABELS = {
  amr:'CARD 耐药', vir:'VFDB 毒力', cds:'CDS', trna:'tRNA', rrna:'rRNA',
  tmrna:'tmRNA', ncrna:'ncRNA', sorf:'sORF', pseudogene:'假基因', unknown:'未注释',
};
for (const [letter, color] of Object.entries(COG_COLORS)) CATEGORY_LABELS[letter] = `COG ${letter}`;

function sectorGeometry(r0, r1, a0, a1, z, color, cx = 0, cy = 0) {
  const steps = Math.max(2, Math.ceil((a1 - a0) / 0.012));
  const positions = [], colors = [];
  const rgb = new THREE.Color(color);
  for (let i = 0; i < steps; i++) {
    const t0 = a0 + (a1 - a0) * i / steps;
    const t1 = a0 + (a1 - a0) * (i + 1) / steps;
    const points = [
      [cx + Math.cos(t0) * r0, cy - Math.sin(t0) * r0, z],
      [cx + Math.cos(t0) * r1, cy - Math.sin(t0) * r1, z],
      [cx + Math.cos(t1) * r0, cy - Math.sin(t1) * r0, z],
      [cx + Math.cos(t1) * r1, cy - Math.sin(t1) * r1, z],
    ];
    positions.push(...points[0], ...points[1], ...points[2], ...points[2], ...points[1], ...points[3]);
    for (let j = 0; j < 6; j++) colors.push(rgb.r, rgb.g, rgb.b);
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
  return geometry;
}

function sectorMesh(r0, r1, a0, a1, z, color, cx = 0, cy = 0) {
  return new THREE.Mesh(sectorGeometry(r0, r1, a0, a1, z, color, cx, cy), new THREE.MeshBasicMaterial({
    vertexColors: true, side: THREE.DoubleSide,
  }));
}

function ring(reference, z, color = '#3d4d75', opacity = 0.35) {
  const points = [];
  for (let i = 0; i <= 360; i++) {
    const angle = i / 360 * Math.PI * 2;
    points.push(new THREE.Vector3(Math.cos(angle) * reference, -Math.sin(angle) * reference, z));
  }
  return new THREE.Line(new THREE.BufferGeometry().setFromPoints(points), new THREE.LineBasicMaterial({
    color, transparent: true, opacity,
  }));
}

function niceStep(length, target = 8) {
  const raw = length / target;
  const power = 10 ** Math.floor(Math.log10(raw));
  const candidates = [1, 2, 2.5, 5, 10].map(value => value * power);
  return candidates.reduce((best, value) => Math.abs(length / value - target) < Math.abs(length / best - target) ? value : best);
}

function layoutFor(index) {
  const layouts = [
    { x: 0, y: 0, scale: 1 },
    { x: -16, y: 7, scale: .34 },
    { x: 16, y: -6, scale: .34 },
    { x: -16, y: -7, scale: .28 },
    { x: 16, y: 7, scale: .28 },
  ];
  return layouts[Math.min(index, layouts.length - 1)];
}

function formatCoordinate(position) {
  return position < 1000 ? `${position} bp` : formatBp(position);
}

function featureColor(feature) {
  if (feature.flag) return KIND_COLORS[feature.flag];
  return KIND_COLORS[feature.category] || COG_COLORS[feature.category] || KIND_COLORS.unknown;
}

export const circularAnnotationView = {
  id: 'circle',
  title: '3D 注释圈图',
  subtitle: 'BAKTA + EGGNOG CIRCULAR MAP',
  description: '由 Bakta GFF3 提供基因坐标，eggNOG-mapper 提供 COG/EC/KEGG/PFAM 功能注释；CARD/VFDB 命中按坐标叠加。声明为 circular 的复制子按闭合圈渲染，线性 contig 仅在显式开启时使用伪环布局。',
  controls: data => {
    const hasCircular = data.replicons.some(replicon => replicon.topology === 'circular');
    const categoryKeys = [...new Set(data.features.map(feature => feature.flag || feature.category))];
    return [
      {
        key: 'category', label: '功能过滤', type: 'select', value: 'all',
        options: [{ value: 'all', label: '全部功能' }, ...categoryKeys.map(category => ({
          value: category, label: CATEGORY_LABELS[category] || category,
        }))],
      },
      { key: 'linear', label: '显示线性 contig（伪环布局）', type: 'toggle', value: !hasCircular },
      { key: 'gc', label: '显示 GC / GC-skew', type: 'toggle', value: true },
      { key: 'labels', label: '显示复制子与坐标标签', type: 'toggle', value: true },
    ];
  },

  create({ root, data, host, registerPickable }) {
    const circular = data.replicons.filter(replicon => replicon.topology === 'circular');
    const linear = data.replicons.filter(replicon => replicon.topology === 'linear');
    const includeLinearInitially = circular.length === 0;
    let showLinear = includeLinearInitially;
    const ordered = [...circular, ...linear].slice(0, 12);
    const rendered = ordered.filter(replicon => replicon.topology === 'circular' || showLinear);
    const allGroups = [];
    const featureById = new Map(data.features.map(feature => [feature.id, feature]));
    const labelGroups = [], gcGroups = [], categoryMeshes = new Map(), records = [];

    ordered.forEach((replicon, repliconIndex) => {
      const layout = layoutFor(repliconIndex);
      const scale = layout.scale * (replicon.length > 1_000_000 ? 1 : 1.55);
      const cx = layout.x, cy = layout.y;
      const sr = value => value * scale;
      const group = new THREE.Group();
      group.visible = replicon.topology === 'circular' || showLinear;
      allGroups.push(group);
      const labels = new THREE.Group(), gcGroup = new THREE.Group();
      group.add(labels, gcGroup);
      labelGroups.push(labels); gcGroups.push(gcGroup);
      root.add(group);
      const radius = { plusIn: 5.25, plusOut: 6.45, minusIn: 4.05, minusOut: 5.25 };

      const backbone = sectorMesh(sr(3.95), sr(6.55), 0, Math.PI * 2, -.025, '#111a2e', cx, cy);
      group.add(backbone);
      group.add(ring(sr(3.95), .01), ring(sr(6.55), .01), ring(sr(7.15), -.01, '#2c3854', .25));
      const midline = sectorMesh(sr(5.835), sr(5.865), 0, Math.PI * 2, 0, '#314069', cx, cy);
      group.add(midline);

      if (replicon.track?.pos?.length) {
        const mean = replicon.gc || replicon.track.gc.reduce((a, b) => a + b, 0) / replicon.track.gc.length;
        const gcPositions = [], skewPositions = [];
        replicon.track.pos.forEach((position, i) => {
          const angle = position / replicon.length * Math.PI * 2;
          const deviation = clamp((replicon.track.gc[i] - mean) / 12, -1, 1);
          gcPositions.push(new THREE.Vector3(
            cx + Math.cos(angle) * sr(3.25 + deviation * .35),
            cy - Math.sin(angle) * sr(3.25 + deviation * .35), .02,
          ));
          skewPositions.push(new THREE.Vector3(
            cx + Math.cos(angle) * sr(2.45 + clamp(replicon.track.skew[i] * 5, -1, 1) * .28),
            cy - Math.sin(angle) * sr(2.45 + clamp(replicon.track.skew[i] * 5, -1, 1) * .28), .02,
          ));
        });
        if (gcPositions.length > 1) {
          gcGroup.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(gcPositions), new THREE.LineBasicMaterial({
            color: '#45d69b', transparent: true, opacity: .85,
          })));
          gcGroup.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(skewPositions), new THREE.LineBasicMaterial({
            color: '#6d8bff', transparent: true, opacity: .65,
          })));
        }
      }

      const step = niceStep(replicon.length, replicon.length > 1e6 ? 8 : 5);
      for (let position = 0; position < replicon.length; position += step) {
        const angle = position / replicon.length * Math.PI * 2;
        const tick = sectorMesh(sr(6.58), sr(6.74), angle, angle + .0015, .01, '#9aabd8', cx, cy);
        group.add(tick);
        const label = makeLabel(formatCoordinate(position), { color: '#a8b5d6', height: .26 * scale, fontSize: 22, align: 'center' });
        label.position.set(cx + Math.cos(angle) * sr(7.45), cy - Math.sin(angle) * sr(7.45), .04);
        labels.add(label);
      }
      const title = makeLabel(
        `${replicon.name} · ${replicon.topology.toUpperCase()}`,
        { color: replicon.topology === 'circular' ? '#c3cdf0' : '#f0b07a', height: .34 * scale, fontSize: 24, align: 'center' },
      );
      title.position.set(cx, cy + sr(1.1), .03);
      labels.add(title);

      const target = data.features.filter(feature => feature.contig === replicon.id);
      const grouped = new Map();
      for (const feature of target) {
        const key = feature.flag || feature.category;
        if (!grouped.has(key)) grouped.set(key, []);
        grouped.get(key).push(feature);
      }
      for (const [category, features] of grouped) {
        const mesh = new THREE.InstancedMesh(
          new THREE.BoxGeometry(1, 1, 1),
          new THREE.MeshStandardMaterial({ color: featureColor({ category, flag: null }), roughness: .31, metalness: .30 }),
          features.length,
        );
        const matrix = new THREE.Matrix4(), position = new THREE.Vector3();
        const tangent = new THREE.Vector3(), radial = new THREE.Vector3(), normal = new THREE.Vector3(0, 0, 1);
        features.forEach((feature, instanceId) => {
          const start = feature.start / replicon.length * Math.PI * 2;
          const end = feature.end / replicon.length * Math.PI * 2;
          const mid = (start + end) / 2;
          const plus = feature.strand !== '-';
          const rMid = sr(plus ? (radius.plusIn + radius.plusOut) / 2 : (radius.minusIn + radius.minusOut) / 2);
          const width = Math.max(sr(.004), rMid * (end - start));
          const cos = Math.cos(mid), sin = Math.sin(mid);
          position.set(cx + cos * rMid, cy - sin * rMid, .18);
          tangent.set(-sin, -cos, 0);
          radial.set(cos, -sin, 0);
          matrix.makeBasis(tangent, radial, normal);
          matrix.scale(new THREE.Vector3(width, sr(.52), .32));
          matrix.setPosition(position);
          mesh.setMatrixAt(instanceId, matrix);
          const color = new THREE.Color(featureColor(feature));
          mesh.setColorAt(instanceId, color);
          const record = { feature, mesh, instanceId, color };
          records.push(record);
          featureById.set(feature.id, { ...feature, record });
        });
        mesh.instanceMatrix.needsUpdate = true;
        if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
        group.add(registerPickable(mesh, { type: 'feature', id: features[0].id }));
        categoryMeshes.set(category, mesh);
        mesh.userData.pickFor = instanceId => featureById.get(features[instanceId].id)?.record;
      }
    });

    function applyCategory(value) {
      for (const [category, mesh] of categoryMeshes) mesh.visible = value === 'all' || category === value;
    }
    applyCategory('all');

    let selected = null;
    function clearSelection() {
      if (!selected) return;
      selected.mesh.setColorAt(selected.instanceId, selected.color);
      selected.mesh.instanceColor.needsUpdate = true;
      selected = null;
    }
    function select(payload) {
      clearSelection();
      if (!payload) return;
      const record = featureById.get(payload.id)?.record;
      if (!record) return;
      selected = record;
      record.mesh.setColorAt(record.instanceId, new THREE.Color('#ffffff'));
      record.mesh.instanceColor.needsUpdate = true;
    }
    function recordFor(payload) { return featureById.get(payload?.id)?.record; }
    function payloadPosition(payload) {
      const record = recordFor(payload);
      if (!record) return null;
      const vector = new THREE.Vector3();
      record.mesh.getMatrixAt(record.instanceId, matrix);
      return vector.setFromMatrixPosition(matrix);
    }
    const matrix = new THREE.Matrix4();

    return {
      debug: () => ({
        groups: allGroups.map(group => group.children.length),
        categories: [...categoryMeshes].map(([key, mesh]) => ({ key, visible: mesh.visible })),
        records: records.length,
      }),
      stats: () => [
        { label: '闭合复制子', value: circular.length },
        { label: '线性 contig', value: linear.length },
        { label: '注释特征', value: data.features.length },
        { label: 'eggNOG 匹配', value: `${data.eggnog_matched}/${data.eggnog_total}` },
      ],
      resetCamera: () => {
        const visible = ordered.filter(replicon => replicon.topology === 'circular' || showLinear);
        const target = visible.length > 1 ? new THREE.Vector3(0, 0, 0) : new THREE.Vector3(layoutFor(0).x, layoutFor(0).y, 0);
        const distance = visible.length > 1 ? 36 : 29;
        host.setCamera(new THREE.Vector3(target.x + 1, target.y + 7, distance), target);
      },
      setOption: (key, value) => {
        if (key === 'category') applyCategory(value);
        if (key === 'linear') {
          showLinear = Boolean(value);
          allGroups.forEach((group, index) => {
            group.visible = ordered[index].topology === 'circular' || showLinear;
          });
          host.resetCamera();
        }
        if (key === 'gc') gcGroups.forEach(group => { group.visible = value; });
        if (key === 'labels') labelGroups.forEach(group => { group.visible = value; });
      },
      select,
      focus: payload => {
        const position = payloadPosition(payload);
        if (position) host.flyTo(position.clone().add(new THREE.Vector3(0, 1, 6)), position);
      },
      selectionLabel: payload => {
        const feature = featureById.get(payload?.id);
        if (!feature) return '—';
        return feature.gene || feature.locus || feature.product.slice(0, 28) || feature.id;
      },
      tooltip: payload => {
        const feature = featureById.get(payload?.id);
        if (!feature) return '';
        const tag = feature.flag ? CATEGORY_LABELS[feature.flag] : CATEGORY_LABELS[feature.category] || feature.category;
        return `<div class="tt-name">${escapeHtml(feature.gene || feature.locus || feature.id)}</div>
          <div class="tt-sub">${escapeHtml(tag)} · ${escapeHtml(feature.contig)}</div>
          <div class="tt-sub">${feature.start + 1}–${feature.end} · ${feature.strand}</div>
          <div class="tt-sub">${escapeHtml(feature.product || '—')}</div>`;
      },
      inspect: payload => {
        const feature = featureById.get(payload?.id);
        if (!feature) return '';
        const tag = feature.flag ? CATEGORY_LABELS[feature.flag] : CATEGORY_LABELS[feature.category] || feature.category;
        const list = (values, label) => values.length
          ? `<dl class="kv"><dt>${label}</dt><dd>${values.map(value => escapeHtml(value)).join(', ')}</dd></dl>` : '';
        return `<div class="detail-title">${escapeHtml(feature.gene || feature.locus || feature.id)}</div>
          <p class="detail-subtitle">${escapeHtml(tag)} · ${escapeHtml(feature.contig)}:${feature.start + 1}–${feature.end} (${feature.strand})</p>
          <div class="metric-grid"><div><span>长度</span><b>${formatBp(feature.end - feature.start)}</b></div><div><span>类别</span><b>${escapeHtml(feature.category)}</b></div><div><span>来源</span><b>${feature.eggnog_ogs.length ? 'Bakta+eggNOG' : 'Bakta'}</b></div><div><span>临床</span><b>${feature.flag ? escapeHtml(feature.clinical_gene || feature.flag) : '—'}</b></div></div>
          <dl class="kv"><dt>产物</dt><dd>${escapeHtml(feature.product || '—')}</dd><dt>locus_tag</dt><dd>${escapeHtml(feature.locus || '—')}</dd><dt>protein_id</dt><dd>${escapeHtml(feature.protein_id || '—')}</dd><dt>Preferred name</dt><dd>${escapeHtml(feature.preferred_name || '—')}</dd></dl>
          ${list(feature.ec, 'EC')}${list(feature.kegg_ko, 'KEGG KO')}${list(feature.kegg_pathways, 'KEGG pathway')}${list(feature.pfams, 'PFAM')}${list(feature.go.slice(0, 8), 'GO')}${list(feature.eggnog_ogs.slice(0, 5), 'eggNOG OGs')}`;
      },
    };
  },
};
