import * as THREE from '../vendor/three.module.js';
import { forceLayout, forceLayout3D, layoutTreeRadial, layoutTreeForce, treeCentre, clamp } from '../framework/algorithms.js';
import { escapeHtml, makeDustField } from '../framework/primitives.js';
import { createConstellation, NETWORK_NEUTRAL } from '../framework/constellation.js';
import {
  metadataFieldOptions, heightModeOptions, defaultHeightMode, defaultColorField, nodeColoring, encodeHeights, MISSING, COLOR_SCHEMES,
} from '../framework/encodings.js';
import {
  evaluateFilter, filterFieldTypes, mstSampleRecords, matchedNodeSet,
  tableColumnOptions, defaultTableColumns,
} from '../framework/query.js';
import { createFilterUi } from '../framework/filter-ui.js';
import { createMatchTable } from '../framework/match-table.js';

const STRUCTURE_LABEL = '到中心节点的等位距离';
const RESERVED = new Set(['id', 'label', 'count', 'member_count', 'members', 'profile', 'profile_key', 'meta', 'meta_breakdown']);
const distanceColor = distance => new THREE.Color('#f5e6c8').lerp(new THREE.Color('#ff4d2e'), clamp(distance / 7, 0, 1)).getStyle();

/** gmlst-native nodes carry `meta`; contract extensions may sit on the node. */
const stOf = record => record.st ?? record.ST ?? '';

function nodeRecord(node) {
  const record = {};
  for (const [key, value] of Object.entries(node)) {
    if (!RESERVED.has(key) && (typeof value === 'string' || typeof value === 'number')) record[key] = value;
  }
  if (node.meta && typeof node.meta === 'object') Object.assign(record, node.meta);
  return record;
}

function readGraph(data) {
  if (!Array.isArray(data.nodes) || !Array.isArray(data.edges)) {
    throw new Error('MST 数据需要宿主 / gmlst 预先计算的 nodes 与 edges；gvixb 不在前端计算 MST');
  }
  const indices = new Map(data.nodes.map((node, index) => [String(node.id), index]));
  const edges = data.edges.map(edge => ({
    source: indices.get(String(edge.source)), target: indices.get(String(edge.target)),
    distance: Number(edge.weight),
    loci: Array.isArray(edge.mismatch_loci) ? edge.mismatch_loci : null,
  }));
  if (edges.some(edge => edge.source === undefined || edge.target === undefined || !Number.isFinite(edge.distance))) {
    throw new Error('MST 边引用或权重无效');
  }
  const isolates = data.nodes.map(node => ({
    id: String(node.label ?? node.id),
    count: Number(node.member_count ?? node.count) || 1,
    members: Array.isArray(node.members)
      ? node.members.map(m => (m && typeof m === 'object' ? { id: String(m.id ?? ''), meta: m.meta || {} } : { id: String(m), meta: {} }))
      : null,
    breakdown: node.meta_breakdown && typeof node.meta_breakdown === 'object' ? node.meta_breakdown : null,
    profile: Array.isArray(node.profile) ? node.profile : null,
    record: nodeRecord(node),
  }));
  return { isolates, edges };
}

export const mstView = {
  id: 'mst',
  schema: 'gvixb.mst/v1',
  dockLabel: 'MST',
  title: '3D 最小生成树',
  subtitle: 'MLST MINIMUM SPANNING TREE',
  dataUrl: './data/framework/mst.json',
  description: '只渲染宿主 / gmlst 已计算的 MST 节点、边和等位距离；gvixb 不计算拓扑。平面布局可选树形力导向（GrapeTree 式）、径向静态或自由力导向，高度可按结构距离、元数据类别或数值编码，三者都可实时切换。',
  controls: data => {
    const { isolates, edges } = readGraph(data);
    const fields = metadataFieldOptions(isolates.map(isolate => isolate.record));
    const many = isolates.length > 60;
    const maxDist = Math.max(1, ...edges.map(edge => edge.distance));
    return [
      { type: 'section', label: '布局 · Layout' },
      {
        key: 'layout', label: '平面布局', type: 'select', value: 'free3d',
        options: [
          { value: 'force', label: '树形力导向（GrapeTree 式，分支不反折）' },
          { value: 'radial', label: '径向静态（GrapeTree static）' },
          { value: 'free', label: '自由力导向（分支可能反折）' },
          { value: 'free3d', label: '立体力导向（3D 全展开）' },
        ],
      },
      { key: 'height', label: '高度模式', type: 'select', value: 'flat', options: heightModeOptions(fields, STRUCTURE_LABEL, { treeModes: true }).filter(o => o.value !== 'cone') },
      { key: 'elevate', label: '分支仰角展开（叠加）', type: 'toggle', value: true },
      { key: 'amp', label: '纵向展开', type: 'range', min: 0.3, max: 3, step: 0.1, value: 0.7 },
      {
        key: 'color', label: '颜色字段', type: 'select', value: defaultColorField(fields),
        options: [{ value: '', label: '不着色' }, ...fields.colorable.map(key => ({
          value: key, label: fields.numeric.includes(key) ? `${key}（数值渐变）` : key,
        }))],
      },
      {
        key: 'palette', label: '配色方案', type: 'select', value: 'auto',
        options: Object.entries(COLOR_SCHEMES).map(([value, label]) => ({ value, label })),
      },
      { type: 'section', label: '连线 · Edges' },
      {
        key: 'edgeColor', label: '连线颜色', type: 'select', value: 'group',
        options: [{ value: 'group', label: '按端点颜色' }, { value: 'distance', label: '按等位距离' }],
      },
      {
        key: 'edgeScale', label: '连线长度缩放', type: 'select', value: 'linear',
        options: [
          { value: 'linear', label: '线性（长度 ∝ 等位距离）' },
          { value: 'sqrt', label: '平方根（压缩长边）' },
          { value: 'log', label: '对数 log2(1+Δ)（适合 cgMLST）' },
        ],
      },
      {
        key: 'edgeMax', label: '实线上限（Δ=4 显示虚线，超过隐藏）', type: 'range',
        min: 0, max: maxDist, step: Math.max(1, Math.round(maxDist / 200)), value: 3,
      },
      { key: 'edgeAlpha', label: '连线亮度', type: 'range', min: 0.05, max: 1, step: 0.05, value: 0.15 },
      { key: 'pulseSpeed', label: '流光速度', type: 'range', min: 0, max: 3, step: 0.1, value: 1 },
      { key: 'pulseCount', label: '流光数量', type: 'range', min: 0, max: 32, step: 1, value: 12 },
      { key: 'distances', label: '显示等位距离', type: 'toggle', value: !many },
      { type: 'section', label: '节点 · Nodes' },
      { key: 'nodeSize', label: '节点大小', type: 'range', min: 0.3, max: 3, step: 0.05, value: 1 },
      { key: 'labels', label: '显示样本标签', type: 'toggle', value: !many },
      { type: 'section', label: '视图 · Scene' },
      { key: 'rotate', label: '旋转速度', type: 'range', min: 0, max: 3, step: 0.05, value: 0.45 },
      { key: 'glow', label: '光晕', type: 'range', min: 0, max: 1, step: 0.05, value: 0.2 },
      { key: 'pulses', label: '背景流光（装饰）', type: 'toggle', value: true },
    ];
  },

  create({ root, data, host, registerPickable }) {
    const { isolates, edges } = readGraph(data);
    if (isolates.length < 1) throw new Error('MST 数据没有节点');
    const fields = metadataFieldOptions(isolates.map(isolate => isolate.record));
    const centre = treeCentre(isolates.length, edges);
    const degree = isolates.map(() => 0);
    edges.forEach(edge => { degree[edge.source]++; degree[edge.target]++; });
    const many = isolates.length > 60;

    const state = {
      layout: 'free3d', height: 'flat', elevate: true, color: defaultColorField(fields),
      edgeColor: 'group', labels: !many, distances: !many, pulses: true, glow: 0.2, edgeAlpha: 0.15, nodeSize: 1,
      edgeMax: 3, edgeScale: 'linear', palette: 'auto', amp: 0.7, pulseSpeed: 1, pulseCount: 12,
    };
    const layouts = new Map();
    const radius = clamp(Math.sqrt(isolates.length) * 1.6, 8, 14);
    function planar(kind) {
      const key = `${kind}:${state.edgeScale}`;
      if (!layouts.has(key)) {
        layouts.set(key, kind === 'free3d'
          ? forceLayout3D(isolates, edges, { radius, iterations: isolates.length > 1500 ? 160 : 300 })
          : kind === 'free'
            ? forceLayout(isolates, edges, { width: radius * 2, height: radius * 2 })
          : kind === 'force'
            ? layoutTreeForce(isolates.length, edges, { radius, edgeScale: state.edgeScale }).points
            : layoutTreeRadial(isolates.length, edges, { radius, edgeScale: state.edgeScale }).points);
      }
      return layouts.get(key);
    }

    host.scene.fog = new THREE.FogExp2(0x05070d, 0.014);
    host.setAutoRotate(true, 0.45);
    host.raycaster.params.Line.threshold = 0.25;
    const dust = makeDustField({ count: 260, radius: 60, color: 0x9a8f7a, size: 1.6, opacity: 0.3 });
    root.add(dust);

    let constellation = null, nodes = [], sidebarEl = null, constellationHost = null, encoded = null;
    function build() {
      constellation?.dispose();
      const flat = planar(state.layout);
      const valueOf = (i, field) => isolates[i].record[field];
      encoded = encodeHeights({
        count: isolates.length, mode: state.height, valueOf,
        structure: centre.dist, structureLabel: STRUCTURE_LABEL,
        tree: { parent: centre.parent, order: centre.order, dist: centre.dist },
        amp: state.amp,
      });
      // 仰角展开是叠加量而非高度模式：可与任意高度编码共存
      if (state.elevate) {
        const coneH = encodeHeights({
          count: isolates.length, mode: 'cone', valueOf,
          structure: centre.dist, structureLabel: STRUCTURE_LABEL,
          tree: { parent: centre.parent, order: centre.order, dist: centre.dist },
          amp: state.amp, weights: isolates.map(isolate => isolate.count),
        });
        for (let i = 0; i < isolates.length; i++) encoded.heights[i] += coneH.heights[i];
        encoded = { ...encoded, axis: encoded.axis || coneH.axis, note: `${encoded.note} 叠加分支仰角展开。` };
      }
      const colour = nodeColoring(isolates.map((_, i) => (state.color ? valueOf(i, state.color) : '')), NETWORK_NEUTRAL, { scheme: state.palette });
      const sameField = encoded.decks && encoded.decks.field === state.color;
      if (sameField) for (const [key, layer] of encoded.decks.layers) layer.color = colour.layers.get(key)?.color || NETWORK_NEUTRAL;
      const layers = sameField ? encoded.decks.layers : colour.layers;

      // GrapeTree convention: dot *area* is proportional to member count, i.e.
      // diameter ∝ √count; the "节点大小" control multiplies every dot uniformly
      const sizeOf = count => 0.46 * Math.sqrt(Math.max(1, count));
      nodes = isolates.map((isolate, index) => ({
        position: new THREE.Vector3(flat[index].x, (flat[index].z || 0) * state.amp + encoded.heights[index], flat[index].y),
        color: layers.get(colour.keys[index])?.color || NETWORK_NEUTRAL,
        size: sizeOf(isolate.count),
        layer: colour.keys[index],
        hub: index === centre.centre,
        label: isolate.id,
        payload: { type: 'node', index },
      }));
      constellation = createConstellation({
        root, host, registerPickable, layers, nodes,
        edges: edges.map((edge, index) => ({
          source: edge.source, target: edge.target, distance: edge.distance, label: `${edge.distance}`, payload: { type: 'edge', index },
        })),
        decks: !!sameField && layers.size > 1,
        heightAxis: encoded.axis,
        legendTitle: state.color ? `颜色 · ${state.color}` : '颜色 · 未着色',
        legendNote: `${encoded.note}${state.color ? ' 点击行可隐藏 / 显示该类别。' : ''}`,
        showLabels: state.labels, showEdgeLabels: state.distances, pulsesOn: state.pulses, glow: state.glow, edgeAlpha: state.edgeAlpha,
        sizeScale: state.nodeSize, pulseSpeed: state.pulseSpeed, pulseCount: state.pulseCount,
        dashedEdgePredicate: edge => edge.distance === 4,
        sidebarNote: 'MST 拓扑与 Δ 来自宿主 / gmlst；Δ 为等位基因距离（不是核苷酸差异数）。连线与流光不表示方向或传播。',
      });
      applyEdgeColor();
      constellation.setEdgeFilter(edge => edge.distance <= Math.max(4, state.edgeMax));
      if (constellationHost) constellation.mountSidebar(constellationHost);
      applyFilter();   // re-apply emphasis/pulse on the rebuilt constellation
    }
    function applyEdgeColor() {
      constellation.recolorEdges(state.edgeColor === 'distance'
        ? (_, i) => distanceColor(edges[i].distance)
        : edge => [nodes[edge.source].color, nodes[edge.target].color]);
    }

    // ---- sample records + metadata filter (shared components) ----
    const records = mstSampleRecords(isolates);
    const sampleMeta = Object.fromEntries(records.map(r => [r.key, r.values]));
    const sampleFields = metadataFieldOptions(records.map(r => r.values));
    const filterTypes = filterFieldTypes([], sampleFields);
    const nodeRecordCount = i => records.reduce((n, r) => n + (r.nodeIndex === i ? 1 : 0), 0);
    const nodeMatchedCount = i => !filterMatched ? 0
      : records.reduce((n, r) => n + (r.nodeIndex === i && filterMatched.has(r.key) ? 1 : 0), 0);
    const fltValueCounts = new Map();
    const valueCounts = key => {
      if (!fltValueCounts.has(key)) {
        const m = new Map();
        for (const r of records) {
          const v = r.values[key];
          if (v === undefined || v === null || v === '') continue;
          m.set(String(v), (m.get(String(v)) || 0) + 1);
        }
        fltValueCounts.set(key, m);
      }
      return fltValueCounts.get(key);
    };

    const filterState = {
      mode: 'all',
      conditions: [],
      dim: 0.45,
      pulse: typeof window === 'undefined'
        || !window.matchMedia?.('(prefers-reduced-motion: reduce)').matches,
    };
    const tableState = { columns: null, sort: null, collapsed: false, colPickerOpen: false, colSearch: '' };
    let filterMatched = null, filterWarnings = [];
    let filterUi = null, matchTable = null, panelEl = null;
    let selectedIndex = -1;

    function applyEmphasis() {
      const nodeSet = matchedNodeSet(filterMatched, records);
      constellation?.setEmphasis(!filterMatched ? null : i => nodeSet.has(i));
      filterUi?.updateResult();
      matchTable?.updateDim();
    }

    function applyFilter() {
      const out = evaluateFilter(filterState, {
        leaves: records.map(r => r.key), metadata: sampleMeta, matrices: [], fieldTypes: filterTypes,
      });
      filterMatched = out.matched;
      filterWarnings = out.warnings;
      const nodeSet = matchedNodeSet(filterMatched, records);
      constellation?.setMatchPulse(nodeSet ? [...nodeSet] : null, { pulse: filterState.pulse });
      constellation?.setDimOpacity?.(filterState.dim);
      applyEmphasis();
      matchTable?.render();
    }

    function focusMatched() {
      const nodeSet = matchedNodeSet(filterMatched, records);
      if (!nodeSet?.size || !constellation) return;
      const pts = [...nodeSet].map(i => constellation.nodePosition(i)).filter(Boolean);
      if (!pts.length) return;
      const c = new THREE.Vector3();
      for (const pt of pts) c.add(pt);
      c.divideScalar(pts.length);
      let r = 1;
      for (const pt of pts) r = Math.max(r, pt.distanceTo(c));
      const dir = host.camera.position.clone().sub(host.controls.target).normalize();
      host.flyTo(c.clone().add(dir.multiplyScalar(Math.max(r * 2.6, 8))), c);
    }

    const flyToNode = index => {
      const position = constellation.nodePosition(index);
      if (position) host.centerOn?.(position);
    };

    const colorFallback = (key, r) => r.memberIndex !== null
      && key === state.color
      && (r.values[key] === undefined || r.values[key] === null || r.values[key] === '');
    const tableCellValue = (col, r) => {
      const v = colorFallback(col.key, r) ? isolates[r.nodeIndex].record[col.key] : r.values[col.key];
      return v === undefined || v === '' ? null : v;
    };
    const tableCellText = (col, r) => {
      const v = tableCellValue(col, r);
      return v === null || v === undefined ? '—' : String(v);
    };
    const tableColumns = () => {
      const options = tableColumnOptions({
        conditions: filterState.conditions, fields: [],
        fieldTypes: filterTypes, matrices: [], fieldLabel: key => key,
      });
      const byId = new Map(options.map(c => [c.id, c]));
      const current = tableState.columns
        ? tableState.columns.map(id => byId.get(id)).filter(Boolean)
        : defaultTableColumns({
            conditions: filterState.conditions,
            colorField: state.color || null,
            fields: [], fieldLabel: key => key,
          }).map(c => byId.get(c.id) || { ...c, label: c.label || c.key || c.id });
      return { options, current };
    };

    function createPanel(el) {
      matchTable = createMatchTable({
        el,
        adapter: {
          state: tableState,
          active: () => !!filterMatched,
          rows: () => records.filter(r => filterMatched?.has(r.key)),
          rowKey: r => r.key,
          leadingCols: [
            { id: 'sample', label: '样本', value: r => r.id },
            { id: 'node', label: '节点', value: r => isolates[r.nodeIndex].id },
          ],
          columns: tableColumns,
          cellValue: tableCellValue,
          cellText: tableCellText,
          cellClass: (col, r) => colorFallback(col.key, r) ? 'mp-node' : '',
          title: k => `匹配表 · ${k} 株`,
          isDimmed: () => false,
          isSelected: r => r.nodeIndex === selectedIndex,
          activate: r => { host.select?.({ type: 'node', index: r.nodeIndex }); flyToNode(r.nodeIndex); },
          notify: () => host.notifyStateChange?.(),
        },
      });
      matchTable.render();
    }

    function createFilterBlock(el) {
      filterUi = createFilterUi({
        el,
        adapter: {
          state: filterState,
          available: filterTypes.size > 0,
          fieldTypes: filterTypes,
          matrices: [],
          fieldLabel: key => key,
          matrixLabel: id => id,
          valueCounts,
          apply: applyFilter,
          onDim: dim => constellation?.setDimOpacity?.(dim),
          context: () => {
            const nodeSet = matchedNodeSet(filterMatched, records);
            const distCounts = filterMatched && state.color ? (() => {
              const m = new Map();
              for (const r of records) {
                if (!filterMatched.has(r.key)) continue;
                const v = colorFallback(state.color, r)
                  ? (isolates[r.nodeIndex].record[state.color] ?? MISSING)
                  : (r.values[state.color] ?? MISSING);
                m.set(String(v), (m.get(String(v)) || 0) + 1);
              }
              return [...m.entries()].sort((a, b) => b[1] - a[1]).slice(0, 5);
            })() : [];
            return {
              matched: filterMatched,
              k: filterMatched ? filterMatched.size : 0,
              n: records.length,
              extras: filterMatched ? [`涉及 ${nodeSet.size} 个节点`] : [],
              distCounts,
              matchRows: filterMatched
                ? records.filter(r => filterMatched.has(r.key))
                    .map(r => ({ key: r.key, label: r.id === isolates[r.nodeIndex].id ? r.id : `${r.id} · ${isolates[r.nodeIndex].id}` }))
                : [],
              warnings: filterWarnings,
            };
          },
          selectRow: key => {
            const r = records.find(x => x.key === key);
            if (!r) return;
            host.select?.({ type: 'node', index: r.nodeIndex });
            const position = constellation.nodePosition(r.nodeIndex);
            if (position) host.flyTo(position.clone().add(new THREE.Vector3(0, 3.2, 7.5)), position);
          },
          focus: focusMatched,
          notify: () => host.notifyStateChange?.(),
        },
      });
      filterUi.render();
    }

    build();

    const calloutFor = payload => {
      if (payload?.type === 'node') {
        const isolate = isolates[payload.index];
        const tag = state.color ? (isolate.record[state.color] ?? MISSING) : `degree ${degree[payload.index]}`;
        return { title: isolate.id, subtitle: `${stOf(isolate.record) || 'MST node'} · ${tag} · Δ中心 ${centre.dist[payload.index]}` };
      }
      const edge = edges[payload.index];
      return { title: `Δ ${edge.distance} alleles`, subtitle: `${isolates[edge.source].id} ↔ ${isolates[edge.target].id}` };
    };
    const select = payload => {
      selectedIndex = payload?.type === 'node' ? payload.index : -1;
      if (payload?.type === 'node') constellation.selectNode(payload.index, calloutFor(payload));
      else if (payload?.type === 'edge') constellation.selectEdge(payload.index, calloutFor(payload));
      else constellation.clearSelection();
      if (payload?.type === 'node') {
        matchTable?.highlight(records.filter(r => r.nodeIndex === payload.index).map(r => r.key));
      }
    };
    const payloadPosition = payload => {
      if (payload?.type === 'node') return constellation.nodePosition(payload.index);
      if (payload?.type === 'edge') return constellation.edgeMidpoint(payload.index);
      return null;
    };
    const recordRows = (record, skip) => Object.entries(record)
      .filter(([key]) => !skip || !skip.has(key))
      .map(([key, value]) => `<dt>${escapeHtml(key)}</dt><dd>${escapeHtml(value)}</dd>`).join('');

    // aggregated nodes: per-field member composition from gmlst meta_breakdown
    const breakdownSection = breakdown => {
      if (!breakdown) return '';
      const fields = Object.keys(breakdown)
        .filter(field => breakdown[field] && typeof breakdown[field] === 'object')
        .sort((a, b) => Object.keys(breakdown[a]).length - Object.keys(breakdown[b]).length)
        .slice(0, 7);
      return fields.map(field => {
        const entries = Object.entries(breakdown[field])
          .filter(([, n]) => Number.isFinite(Number(n)) && n > 0)
          .sort((a, b) => b[1] - a[1]);
        if (!entries.length) return '';
        const total = entries.reduce((acc, [, n]) => acc + Number(n), 0) || 1;
        const rows = entries.slice(0, 5).map(([value, n]) => {
          const pct = Math.round(Number(n) / total * 100);
          return `<div class="comp-row"><span class="comp-name">${escapeHtml(String(value))}</span>
            <span class="comp-track"><i style="width:${pct}%"></i></span><b>${n}</b><em>${pct}%</em></div>`;
        }).join('');
        const more = entries.length > 5 ? `<div class="comp-more">…等 ${entries.length} 种取值</div>` : '';
        return `<div class="comp-field"><div class="comp-head">${escapeHtml(field)}<span>${entries.length} 种</span></div>${rows}${more}</div>`;
      }).join('');
    };

    return {
      debug: () => ({ state: { ...state }, centre: centre.centre, fields, ...constellation.debug() }),
      stats: () => [
        { label: '样本节点', value: isolates.length },
        { label: 'MST 边', value: edges.length },
        { label: 'MLST 位点', value: data.n_loci || isolates[0]?.profile?.length || 0 },
        { label: '元数据字段', value: fields.categorical.length + fields.numeric.length },
      ],
      resetCamera: () => {
        const d = radius * 2.6 + 6;
        host.setCamera(new THREE.Vector3(d * 0.32, d * 0.36, d * 0.88), new THREE.Vector3(0, 0, 0));
      },
      setOption: (key, value) => {
        if (key === 'labels') { state.labels = !!value; constellation.setLabels(value); }
        if (key === 'distances') { state.distances = !!value; constellation.setEdgeLabels(value); }
        if (key === 'pulses') { state.pulses = !!value; constellation.setPulses(value); }
        if (key === 'rotate') host.setAutoRotate(Number(value) > 0, Number(value));
        if (key === 'glow') { state.glow = Number(value); constellation.setGlow(state.glow); }
        if (key === 'edgeAlpha') { state.edgeAlpha = Number(value); constellation.setEdgeAlpha(state.edgeAlpha); }
        if (key === 'pulseSpeed') { state.pulseSpeed = Number(value); constellation.setPulseSpeed(state.pulseSpeed); }
        if (key === 'pulseCount') { state.pulseCount = Number(value); constellation.setPulseCount(state.pulseCount); }
        if (key === 'nodeSize') { state.nodeSize = Number(value); constellation.setSizeScale(state.nodeSize); }
        if (key === 'edgeColor') { state.edgeColor = value; applyEdgeColor(); }
        if (key === 'layout' || key === 'height' || key === 'color' || key === 'edgeScale' || key === 'palette') { state[key] = String(value); build(); }
        if (key === 'amp') { state.amp = Number(value); build(); }
        if (key === 'elevate') { state.elevate = !!value; build(); }
        if (key === 'edgeMax') { state.edgeMax = Number(value); constellation.setEdgeFilter(edge => edge.distance <= Math.max(4, state.edgeMax)); }
      },
      dispose: () => { constellation?.dispose(); constellation = null; },
      update: dt => {
        dust.rotation.y += dt * 0.006;
        constellation.update(dt);
      },
      select,
      hover: payload => constellation.hoverNode(payload?.type === 'node' ? payload.index : -1),
      mountSidebar: el => {
        sidebarEl = el;
        el.innerHTML = `
          <div class="blk" data-role="filter-blk"></div>
          <div class="blk mst-search-blk">
            <input class="mst-search" type="search" placeholder="搜索样本 / ST / 克隆群…" aria-label="搜索节点">
            <div class="mst-search-results"></div>
          </div>
          <div data-role="constellation-side"></div>`;
        constellationHost = el.querySelector('[data-role="constellation-side"]');
        constellation.mountSidebar(constellationHost);
        createFilterBlock(el.querySelector('[data-role="filter-blk"]'));
        const input = el.querySelector('.mst-search');
        const out = el.querySelector('.mst-search-results');
        const rank = (iso, q) => {
          const id = iso.id.toLowerCase();
          const st = stOf(iso.record).toLowerCase();
          const cc = String(iso.record.clonal_complex ?? '').toLowerCase();
          const memberHit = iso.members?.find(m => m.id.toLowerCase().includes(q));
          if (id === q) return [0, ''];
          if (id.startsWith(q)) return [1, ''];
          if (st === q) return [2, ''];
          if (id.includes(q)) return [3, ''];
          if (cc.includes(q)) return [4, ''];
          if (memberHit) return [5, `含样本 ${memberHit.id}`];
          return [9, ''];
        };
        input.addEventListener('input', () => {
          const q = input.value.trim().toLowerCase();
          if (q.length < 2) { out.innerHTML = ''; return; }
          const hits = isolates.map((iso, i) => ({ i, r: rank(iso, q) }))
            .filter(hit => hit.r[0] < 9)
            .map(hit => ({ i: hit.i, rank: hit.r[0], via: hit.r[1] }))
            .sort((a, b) => a.rank - b.rank)
            .slice(0, 12);
          out.innerHTML = hits.length
            ? hits.map(hit => `<button class="mst-hit" data-node="${hit.i}">
                <b>${escapeHtml(isolates[hit.i].id)}</b>
                <span>${escapeHtml(stOf(isolates[hit.i].record) || '—')} · ${isolates[hit.i].count} 样本${hit.via ? ` · ${escapeHtml(hit.via)}` : ''}</span>
              </button>`).join('')
            : '<p class="gene-note">无匹配节点</p>';
        });
        out.addEventListener('click', event => {
          const btn = event.target.closest('[data-node]');
          if (!btn) return;
          const index = Number(btn.dataset.node);
          select({ type: 'node', index });
          const position = constellation.nodePosition(index);
          if (position) host.flyTo(position.clone().add(new THREE.Vector3(0, 3.2, 7.5)), position);
        });
      },
      mountPanel: el => {
        panelEl = el;
        createPanel(el);
      },
      getState: () => ({
        filter: {
          mode: filterState.mode,
          conditions: filterState.conditions.map(c => ({ ...c, values: Array.isArray(c.values) ? [...c.values] : c.values })),
          pulse: filterState.pulse,
          dim: filterState.dim,
          table: {
            columns: tableState.columns ? [...tableState.columns] : null,
            sort: tableState.sort ? { ...tableState.sort } : null,
            collapsed: tableState.collapsed,
          },
        },
      }),
      setState: saved => {
        const warnings = [];
        if (!saved || typeof saved !== 'object') return warnings;
        const fs = saved.filter || {};
        if (fs.mode === 'all' || fs.mode === 'any') filterState.mode = fs.mode;
        if (typeof fs.pulse === 'boolean') filterState.pulse = fs.pulse;
        if (Number.isFinite(fs.dim)) filterState.dim = Math.max(0.1, Math.min(1, fs.dim));
        const ts = fs.table;
        if (ts && typeof ts === 'object') {
          if (Array.isArray(ts.columns)) {
            tableState.columns = ts.columns.filter(id => typeof id === 'string');
            if (!tableState.columns.length) tableState.columns = null;
          }
          if (ts.sort && typeof ts.sort === 'object' && typeof ts.sort.key === 'string' && [1, -1].includes(ts.sort.dir)) {
            tableState.sort = { key: ts.sort.key, dir: ts.sort.dir };
          }
          if (typeof ts.collapsed === 'boolean') tableState.collapsed = ts.collapsed;
        }
        if (Array.isArray(fs.conditions)) {
          filterState.conditions = [];
          for (const c of fs.conditions) {
            if (!c || typeof c !== 'object' || c.source === 'matrix' || typeof c.field !== 'string' || typeof c.op !== 'string') {
              warnings.push('无效筛选条件'); continue;
            }
            filterState.conditions.push({ ...c });
          }
        }
        applyFilter();
        filterUi?.render();
        return warnings;
      },
      focus: payload => {
        const position = payloadPosition(payload);
        if (position) host.flyTo(position.clone().add(new THREE.Vector3(0, 3.2, 7.5)), position);
      },
      selectionLabel: payload => {
        if (payload?.type === 'node') return isolates[payload.index].id;
        if (payload?.type === 'edge') return `Δ ${edges[payload.index].distance}`;
        return '—';
      },
      tooltip: payload => {
        if (payload?.type === 'node') {
          const isolate = isolates[payload.index];
          const tag = state.color ? `${state.color}: ${isolate.record[state.color] ?? MISSING}` : '';
          return `<div class="tt-name">${escapeHtml(isolate.id)}</div>
            <div class="tt-sub">${escapeHtml(stOf(isolate.record) || 'ST —')}${tag ? ` · ${escapeHtml(tag)}` : ''}</div>
            <div class="tt-sub">${isolate.count} 个聚合样本 · MST 度 ${degree[payload.index]} · Δ中心 ${centre.dist[payload.index]}${filterMatched && isolate.count > 1 ? ` · 匹配 ${nodeMatchedCount(payload.index)}/${nodeRecordCount(payload.index)}` : ''}</div>`;
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
          const sec = (label, inner, open = true) => inner
            ? `<details class="insp-sec"${open ? ' open' : ''}><summary>${escapeHtml(label)}</summary>${inner}</details>`
            : '';
          const alleles = isolate.profile || [];
          const loci = data.loci || alleles.map((_, i) => `locus_${i + 1}`);
          const profile = `<table class="member-table allele-table"><tr><th>位点</th><th>等位基因</th></tr>${
            alleles.map((allele, i) => `<tr><td>${escapeHtml(loci[i])}</td><td>${escapeHtml(allele)}</td></tr>`).join('')}</table>`;
          const profileSection = alleles.length
            ? sec('等位基因谱', `<div class="seq-scroll">${profile}</div>`)
            : sec('Scheme', `<dl class="kv"><dt>Scheme</dt><dd>${escapeHtml(data.scheme || '—')}</dd><dt>位点数</dt><dd>${escapeHtml(data.n_loci || '—')}</dd></dl>`);
          // for aggregated nodes the meta fields are "|"-joined strings; the
          // per-field composition below replaces them (gmlst meta_breakdown)
          const bdKeys = isolate.count > 1 && isolate.breakdown ? new Set(Object.keys(isolate.breakdown)) : null;
          const composition = bdKeys ? sec('成员构成（gmlst meta_breakdown）', breakdownSection(isolate.breakdown), false) : '';
          // per-member meta table: union of keys present across member metas
          const members = isolate.members && isolate.members.length > 1
            ? (() => {
                const freq = new Map();
                for (const m of isolate.members) for (const k of Object.keys(m.meta || {})) freq.set(k, (freq.get(k) || 0) + 1);
                const cols = [...freq.entries()].sort((a, b) => b[1] - a[1]).slice(0, 6).map(([k]) => k);
                const head = `<tr><th>样本</th>${cols.map(c => `<th>${escapeHtml(c)}</th>`).join('')}</tr>`;
                const rows = isolate.members.map(m => `<tr><td>${escapeHtml(m.id)}</td>${cols.map(c => `<td>${escapeHtml(String(m.meta?.[c] ?? '—'))}</td>`).join('')}</tr>`).join('');
                return sec(`聚合样本（相同等位谱，${isolate.members.length}）`,
                  `<div class="seq-scroll"><table class="member-table">${head}${rows}</table></div>`, false);
              })()
            : '';
          return `<div class="detail-title">${escapeHtml(isolate.id)}</div>
            <p class="detail-subtitle">${escapeHtml(stOf(isolate.record) || 'cgMLST 节点')}${state.color ? ` · ${escapeHtml(isolate.record[state.color] ?? MISSING)}` : ''}</p>
            <div class="metric-grid">
              <div><span>聚合样本</span><b>${isolate.count}</b></div>
              <div><span>MST 节点度</span><b>${degree[payload.index]}</b></div>
              <div><span>Δ 到中心</span><b>${centre.dist[payload.index]}</b></div>
              <div><span>中心节点</span><b>${payload.index === centre.centre ? '是' : '否'}</b></div>
              ${filterMatched ? `<div><span>匹配样本</span><b>${nodeMatchedCount(payload.index)} / ${nodeRecordCount(payload.index)}</b></div>` : ''}
            </div>
            ${profileSection}
            ${composition}
            ${sec('元数据', `<dl class="kv">${recordRows(isolate.record, bdKeys) || '<dt>—</dt><dd>见上方成员构成</dd>'}</dl>`, !bdKeys)}
            ${members}
            <p class="detail-footnote">节点与边直接来自宿主 / gmlst。中心节点 = 加权离心率最小的节点（仅用于布局）。平面位置只用于显示；${escapeHtml(encoded.note)}</p>`;
        }
        if (payload?.type === 'edge') {
          const edge = edges[payload.index];
          const a = isolates[edge.source], b = isolates[edge.target];
          let differenceSection = '<p class="detail-footnote">当前 MST 载荷不包含逐位点差异；此处只显示边权，不反推差异位点。</p>';
          if (edge.loci) {
            differenceSection = `<div class="sec-label">差异位点（gmlst）</div><div class="difference-list">${edge.loci.map(locus => `<div><span>${escapeHtml(locus)}</span></div>`).join('') || '<p>无差异位点</p>'}</div>`;
          } else if (a.profile && b.profile) {
            const loci = data.loci || a.profile.map((_, i) => `locus_${i + 1}`);
            const diffs = a.profile.map((allele, i) => ({ allele, other: b.profile[i], locus: loci[i] }))
              .filter(item => String(item.allele) !== String(item.other));
            differenceSection = `<div class="sec-label">差异位点</div><div class="difference-list">${diffs.map(d => `<div><span>${escapeHtml(d.locus)}</span><b>${escapeHtml(d.allele)} → ${escapeHtml(d.other)}</b></div>`).join('') || '<p>无差异位点</p>'}</div>`;
          }
          return `<div class="detail-title">Δ ${edge.distance} <span class="muted">alleles</span></div>
            <p class="detail-subtitle">${escapeHtml(a.id)} ↔ ${escapeHtml(b.id)}</p>
            <dl class="kv"><dt>源节点</dt><dd>${escapeHtml(stOf(a.record) || a.id)}</dd><dt>目标节点</dt><dd>${escapeHtml(stOf(b.record) || b.id)}</dd></dl>
            ${differenceSection}
            <p class="detail-footnote">Δ 是等位基因距离，不是核苷酸差异数。</p>`;
        }
        return '';
      },
    };
  },
};
