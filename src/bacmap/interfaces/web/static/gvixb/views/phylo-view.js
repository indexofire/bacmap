import * as THREE from '../vendor/three.module.js';
import {
  parseNewick, annotateSupport, rerootTree, midpointRoot, nodePath, replayRootOps,
  layoutPhylogenyRadial2D, layoutPhylogenyEqualAngle, treeLayerHeights,
} from '../framework/algorithms.js';
import { escapeHtml, makeDustField, makeLabel, makePillLabel, disposeHierarchy } from '../framework/primitives.js';
import { leafSectors, matrixColumnStats, selectColumns, ringLayout, buildRingCells } from '../framework/rings.js';
import {
  evaluateFilter,
  filterFieldTypes as buildFilterFieldTypes,
  tableColumnOptions, defaultTableColumns,
} from '../framework/query.js';
import { createFilterUi } from '../framework/filter-ui.js';
import { createMatchTable } from '../framework/match-table.js';
import { createConstellation, NETWORK_NEUTRAL, NETWORK_ACCENT } from '../framework/constellation.js';
import {
  metadataFieldOptions, heightModeOptions, defaultColorField, nodeColoring, encodeHeights, MISSING, COLOR_SCHEMES,
} from '../framework/encodings.js';
import { toPhylogenyV2 } from '../contracts/phylogeny.js';
import {
  parseDateInterval, formatDay, distanceIndex, thresholdClusters,
  nearestSamples, isTreeSplit, summarizeMembers,
} from '../framework/epi.js';

const RADIUS = 10;
const CLUSTER_PALETTE = ['#00e5ff', '#ff3df2', '#c6ff00', '#ffea00', '#7c4dff', '#ff6e40', '#18ffff', '#eeff41'];

const UNIT_LABELS = {
  substitutions_per_site: '替换数 / 位点',
  snp: 'SNP 差异',
  allele_differences: '等位基因差异',
  years: '年',
  none: '',
  unknown: '分支长度',
};
const unitLabel = spec => spec?.branch_length?.label || UNIT_LABELS[spec?.branch_length?.unit] || '分支长度';

/** Parse + annotate for a normalized payload; returns null when unusable. */
const prepareRaw = v2 => {
  if (!v2?.tree?.newick) return null;
  const support = v2.tree.kind === 'mst_derived' ? null : v2.tree.support;
  return annotateSupport(parseNewick(v2.tree.newick), support);
};

const leafRecords = v2 => {
  const raw = prepareRaw(v2);
  if (!raw) return [];
  return layoutPhylogenyRadial2D(raw).leaves.map(leaf => (v2.metadata || {})[leaf.name] || {});
};

export const phyloView = {
  id: 'phylo',
  schema: 'gvixb.phylogeny/v2',
  acceptsSchemas: ['gvixb.phylogeny/v1', 'gvixb.phylogeny/v2'],
  dockLabel: 'Phylo',
  title: '3D 进化树',
  subtitle: 'PHYLOGENETIC ATLAS',
  dataUrl: './data/framework/phylogeny-v2.json',
  description: '渲染输入 Newick（如 IQ-TREE 的 .treefile），不推断树。v2 数据声明根状态、分支长度单位与支持值标签；支持值随改根映射到分支。平面布局可选 radial（半径 = 累计分支长度）或无根等角布局；高度可按根距、元数据类别或数值编码。可在侧栏对选中分支或 midpoint 改根。精确分支长度见 tooltip / 详情。',
  controls: data => {
    let v2 = null;
    try { v2 = toPhylogenyV2(data); } catch { return []; }
    const raw = prepareRaw(v2);
    if (!raw) return [];
    const fields = metadataFieldOptions(leafRecords(v2));
    const many = Object.keys(v2.metadata || {}).length > 40;
    const fieldLabel = key => (v2.fields || []).find(field => field.key === key)?.label || key;
    const supportLabel = v2.tree.kind === 'mst_derived'
      ? '显示内部节点名'
      : v2.tree.support ? '显示支持值' : '显示内部节点名';
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
      {
        key: 'height', label: '高度模式', type: 'select', value: 'flat',
        options: [
          ...heightModeOptions(fields, '累计根距', { treeModes: true, fieldLabel }).filter(o => o.value !== 'cone'),
          ...(v2.fields || []).filter(field => field.type === 'date')
            .map(field => ({ value: `time:${field.key}`, label: `时间：${field.label || field.key}` })),
        ],
      },
      { key: 'elevate', label: '分支仰角展开（叠加）', type: 'toggle', value: true },
      { key: 'amp', label: '纵向展开', type: 'range', min: 0.3, max: 3, step: 0.1, value: 1.5 },
      {
        key: 'color', label: '颜色字段', type: 'select', value: defaultColorField(fields),
        options: [{ value: '', label: '不着色' }, { value: 'clade', label: '顶层 clade' }, ...fields.colorable.map(key => ({
          value: key, label: fields.numeric.includes(key) ? `${fieldLabel(key)}（数值渐变）` : fieldLabel(key),
        }))],
      },
      {
        key: 'palette', label: '配色方案', type: 'select', value: 'auto',
        options: Object.entries(COLOR_SCHEMES).map(([value, label]) => ({ value, label })),
      },
      { type: 'section', label: '连线 · Edges' },
      { key: 'branchLabels', label: '显示分支长度', type: 'toggle', value: false },
      { key: 'supports', label: supportLabel, type: 'toggle', value: false },
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
    const v2 = toPhylogenyV2(data);
    const spec = v2.tree;
    if (!spec?.newick) throw new Error('进化树数据需要 tree.newick 字段');
    const mstDerived = spec.kind === 'mst_derived';
    const declaredSupport = mstDerived ? null : spec.support;
    const originalRaw = annotateSupport(parseNewick(spec.newick), declaredSupport);
    let currentRaw = originalRaw;
    // null → root comes from the payload; otherwise a display reroot
    let displayRoot = null;
    const rootOps = [];   // recorded reroot ops for view-state replay
    const notifyState = () => host.notifyStateChange?.();
    const effectiveRoot = () => displayRoot
      ? { status: 'rooted', method: displayRoot.method, display: true }
      : { status: spec.root?.status || 'unknown', method: spec.root?.method };
    const rooted = () => effectiveRoot().status === 'rooted';
    const branchUnit = unitLabel(spec);
    const fieldLabels = new Map((v2.fields || []).map(field => [field.key, field.label || field.key]));
    const fieldLabel = key => fieldLabels.get(key) || key;
    const supportPairs = node => (node.raw?.support
      ? node.raw.support.values.map((value, i) => `${node.raw.support.labels[i] || `support ${i + 1}`} ${value ?? '—'}`)
      : null);

    const metadata = v2.metadata || {};
    let tree = null, trees = null, topClade = null, depthOf = null, structureLabel = '';
    const recordOf = node => metadata[node.name] || {};

    function rebuildLayouts() {
      trees = {
        radial: layoutPhylogenyRadial2D(currentRaw, { radius: RADIUS }),
        cladogram: layoutPhylogenyRadial2D(currentRaw, { radius: RADIUS, forceCladogram: true }),
        equal: layoutPhylogenyEqualAngle(currentRaw, { radius: RADIUS }),
      };
      // both layouts walk the same Newick in the same order → identical node ids
      tree = trees.radial;
      for (const node of tree.nodes) node.gen = node.parent ? node.parent.gen + 1 : 0;
      depthOf = node => (tree.cladogram ? node.gen : node.depth);
      structureLabel = tree.cladogram ? '拓扑层级（无分支长度）' : '累计根距';
      // every node's top-level clade = the root child it descends from
      topClade = new Map([[tree.root.id, 'root']]);
      tree.root.children.forEach((child, ci) => {
        const label = child.name || `clade ${ci + 1}`;
        (function walk(n) { topClade.set(n.id, label); n.children.forEach(walk); })(child);
      });
    }
    rebuildLayouts();
    const fields = metadataFieldOptions(tree.leaves.map(recordOf));
    const crowded = tree.leafCount > 40;
    const hasBranchLengths = tree.maxDepth > 0;

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
    let ringsBlockEl = null;
    let selectedNode = null, rootBlockEl = null, clusterBlockEl = null, timeBlockEl = null;
    let selectedBranchLabel = '';

    // ---- phase B: distances (暴发簇) + date fields (时间刷选/时间高度) ----
    const leafNameSet = new Set(tree.leaves.map(leaf => leaf.name));
    const dist = v2.distances?.samples?.length ? distanceIndex(v2.distances) : null;
    const distCoverage = dist ? dist.samples.filter(name => leafNameSet.has(name)).length : 0;
    let maxDistance = 0;
    if (dist) for (const value of v2.distances.values || []) {
      if (Number.isFinite(value) && value > maxDistance) maxDistance = value;
    }
    const dateFields = (v2.fields || []).filter(field => field.type === 'date');
    const fieldOfRole = role => {
      const list = (v2.fields || []).filter(field => field.role === role);
      return (list.find(field => field.primary) || list[0])?.key || null;
    };
    const timeIntervals = new Map();   // field key → { intervals, minStart, maxEnd, missing }
    const timeData = key => {
      if (!timeIntervals.has(key)) {
        const intervals = new Map();
        let minStart = Infinity, maxEnd = -Infinity, missing = 0;
        for (const leaf of tree.leaves) {
          const interval = parseDateInterval(recordOf(leaf)[key]);
          if (!interval) { missing++; continue; }
          intervals.set(leaf.name, interval);
          minStart = Math.min(minStart, interval.start);
          maxEnd = Math.max(maxEnd, interval.end);
        }
        timeIntervals.set(key, intervals.size
          ? { intervals, minStart, maxEnd, missing }
          : null);
      }
      return timeIntervals.get(key);
    };
    const epi = {
      clusterOn: false, threshold: Math.min(10, maxDistance || 10),
      clusters: [], clusterOf: new Map(), focus: -1,
      timeField: null, brush: null, playTimer: null,
    };
    // default time field: primary role=time → first role=time → first date field
    if (dateFields.length) {
      const pick = fieldOfRole('time') || dateFields[0].key;
      if (timeData(pick)) {
        epi.timeField = pick;
        const td = timeData(pick);
        epi.brush = { a: td.minStart, b: td.maxEnd };
      }
    }
    // Data rings are currently hidden pending readability evaluation; all
    // state is still serialised/restored so re-enabling is a one-line flip.
    const RINGS_ENABLED = false;
    // ---- data rings (矩阵/字段环) ----
    const matrices = v2.matrices || [];
    const categoricalFields = (v2.fields || [])
      .filter(f => f.type === 'categorical' || f.type === 'text')
      .map(f => f.key);
    const ringsState = {
      matrices: Object.fromEntries(matrices.map((m, i) => [m.id, {
        on: i === 0, sort: 'group', minPrev: 0, maxCols: 30, include: [], exclude: [],
      }])),
      fieldRings: [],
      leaders: true,
      highlight: null,   // { ring, column, value } — matrix: carriers; field: category
    };
    const MATRIX_COLORS = { amr: '#ff5a5f', vf: '#ffb347', plasmid: '#5ec8ff' };
    const MATRIX_FALLBACK = ['#b78cff', '#7ef0a0', '#ff8bd1', '#ffd166', '#6ee7e7'];
    const matrixColorOf = (id, i) => MATRIX_COLORS[id] || MATRIX_FALLBACK[i % MATRIX_FALLBACK.length];
    const matrixStats = new Map();
    const statsOf = m => {
      if (!matrixStats.has(m.id)) {
        matrixStats.set(m.id, matrixColumnStats(m, tree.leaves.map(leaf => leaf.name)));
      }
      return matrixStats.get(m.id);
    };
    const leafIndex = new Map(tree.leaves.map((leaf, i) => [leaf, i]));
    const fieldColorCache = new Map();
    const fieldColors = key => {
      if (!fieldColorCache.has(key)) {
        fieldColorCache.set(key, nodeColoring(
          tree.leaves.map(leaf => recordOf(leaf)[key]), '#1c2230', { scheme: state.palette }));
      }
      return fieldColorCache.get(key);
    };
    let ringGroup = null, ringCellsMeta = null, ringColumnMeta = [], leaderLines = null;
    let lastFlat = null, lastHeights = null;
    let frameUpdateMs = 0;
    let ringEmphasis = null;   // null = all emphasised; else Set of emphasised leaf node ids

    const brushActive = () => {
      const td = epi.timeField && timeData(epi.timeField);
      return !!(td && epi.brush && (epi.brush.a > td.minStart || epi.brush.b < td.maxEnd));
    };
    const missingDates = () => (epi.timeField ? (timeData(epi.timeField)?.missing ?? 0) : 0);

    const supportText = node => {
      if (!node.raw?.support || node.raw.rootSplitTwin) return '';
      return node.raw.support.values.map(value => (value === null ? '–' : value)).join('/');
    };
    const nodeLabel = node => {
      if (node === tree.root) return 'root';
      if (!node.children.length) return node.name;
      if (!state.supports) return '';
      return declaredSupport ? supportText(node) : node.name;
    };
    const cladeNote = () => (state.color === 'clade' && !rooted()
      ? ' 顶层 clade 着色依赖已定义的根（输入未声明根或当前为无根显示），已回退为不着色。'
      : '');
    const arbitraryRootNote = () => (!rooted() ? ' 根距从任意根起算：输入未声明有根树。' : '');

    function build() {
      constellation?.dispose();
      const flat = trees[state.layout];
      const leaves = tree.leaves;
      const leafIndex = new Map(leaves.map((leaf, i) => [leaf.id, i]));
      const cladeAllowed = rooted();
      const colorMode = state.color === 'clade' && !cladeAllowed ? '' : state.color;

      // heights: tree modes (cone / canopy) run over the whole node set so
      // ancestors accumulate their own elevation; other modes encode leaves and
      // ancestors take the mean of their descendant leaves
      const allTree = () => ({
        parent: tree.nodes.map(node => (node.parent ? node.parent.id : -1)),
        order: (() => { const o = []; (function walk(n) { o.push(n.id); n.children.forEach(walk); })(tree.root); return o; })(),
        dist: tree.nodes.map(depthOf),
      });
      const treeMode = state.height === 'canopy';
      const timeKey = state.height.startsWith('time:') ? state.height.slice(5) : null;
      let heights;
      if (timeKey) {
        const td = timeData(timeKey);
        const half = 4 * state.amp;
        const span = Math.max(1, td ? td.maxEnd - td.minStart : 1);
        const leafH = leaves.map(leaf => {
          const interval = td?.intervals.get(leaf.name);
          return interval
            ? -half + (((interval.start + interval.end) / 2 - td.minStart) / span) * 2 * half
            : -half - 1;
        });
        heights = treeLayerHeights(tree, leaf => leafH[leafIndex.get(leaf.id)]);
        const fmtTick = t => (span / 365.25 > 3
          ? String(new Date(Math.round(td.minStart + t * span) * 864e5).getUTCFullYear())
          : formatDay(Math.round(td.minStart + t * span)));
        encoded = {
          heights: leafH, decks: null,
          axis: td ? {
            y0: -half, y1: half, label: `时间 · ${fieldLabel(timeKey)}`,
            ticks: [0, 0.5, 1].map(t => ({ y: -half + t * 2 * half, text: fmtTick(t) })),
          } : null,
          note: `高度 = ${fieldLabel(timeKey)}（采样时间，线性刻度，早者在下）${td?.missing ? `；${td.missing} 个叶节点无日期，置于底部下一层` : ''}。`,
        };
      } else if (treeMode) {
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
      // 仰角展开叠加：全节点锥形位移加在任意高度编码之上（时间高度下禁用，
      // 保持纵轴 = 时间的含义）
      if (state.elevate && !timeKey) {
        const coneH = encodeHeights({
          count: tree.nodes.length, mode: 'cone', valueOf: () => '',
          structure: tree.nodes.map(depthOf), structureLabel,
          tree: allTree(), amp: state.amp,
        });
        for (const node of tree.nodes) heights.set(node.id, heights.get(node.id) + coneH.heights[node.id]);
        encoded = { ...encoded, axis: encoded.axis || coneH.axis, note: `${encoded.note} 叠加分支仰角展开。` };
      }
      if (timeKey && state.elevate) {
        encoded = { ...encoded, note: `${encoded.note} 时间高度下关闭仰角叠加以保持纵轴含义。` };
      }

      // colour: leaves by field; an ancestor inherits a category only when
      // every descendant leaf shares it
      const colour = nodeColoring(leaves.map(leaf => (colorMode === 'clade' ? topClade.get(leaf.id) : (colorMode ? recordOf(leaf)[colorMode] : ''))), NETWORK_NEUTRAL, { scheme: state.palette });
      cladeKey = new Map();
      (function visit(node) {
        if (!node.children.length) { cladeKey.set(node.id, colour.keys[leafIndex.get(node.id)]); return; }
        node.children.forEach(visit);
        const keys = new Set(node.children.map(child => cladeKey.get(child.id)));
        cladeKey.set(node.id, keys.size === 1 && !keys.has(null) ? [...keys][0] : null);
      })(tree.root);
      const sameField = encoded.decks && encoded.decks.field === colorMode;
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
          label: nodeLabel(node),
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
        legendTitle: colorMode ? `颜色 · ${fieldLabel(colorMode)}` : '颜色 · 未着色',
        legendNote: `${encoded.note}${cladeNote()}${colorMode ? ' 点击行可隐藏 / 显示该类别。' : ''}`,
        showLabels: state.labels, showEdgeLabels: state.branchLabels, pulsesOn: state.pulses, glow: state.glow, edgeAlpha: state.edgeAlpha,
        sidebarNote: `${state.layout === 'cladogram'
          ? '平面：Cladogram 等距层级（忽略分支长度，每代一环）。'
          : state.layout === 'radial'
            ? (tree.cladogram ? 'Newick 未提供分支长度：半径按拓扑层级（cladogram）排布。' : `平面：到中心的距离 = 累计分支长度（${branchUnit}）。`)
            : '平面：无根等角布局，分支长度沿各自扇区方向绘制（角度不表示数值）。'}${arbitraryRootNote()}${mstDerived ? ' 由 MST 转换的树，非系统发育推断。' : ''} 流光仅为装饰。`,
      });
      if (constellationHost) constellation.mountSidebar(constellationHost);
      if (RINGS_ENABLED) {
        lastFlat = flat;
        lastHeights = heights;
        buildRings(flat, heights);
      }
      applyEpi();
      renderRingsBlock();
      applyFilter();
      filterUi?.render();
    }

    // ---- metadata / matrix filter ----
    const filterFieldTypes = buildFilterFieldTypes(v2.fields, fields);
    const filterState = {
      mode: 'all',
      conditions: [],
      dim: 0.45,
      pulse: typeof window === 'undefined'
        || !window.matchMedia?.('(prefers-reduced-motion: reduce)').matches,
    };
    let filterMatched = null;       // Set<leafName> | null
    let filterWarnings = [];
    let panelEl = null;             // right-panel match table section
    // persisted under filter.table: columns=null → defaults; sort={key,dir}
    const tableState = { columns: null, sort: null, collapsed: false, colPickerOpen: false, colSearch: '' };
    let filterUi = null;            // shared 筛选 block component
    let matchTable = null;          // shared 匹配表 panel component
    const fltValueCounts = new Map();   // field -> Map(value,count)
    const valueCounts = key => {
      if (!fltValueCounts.has(key)) {
        const m = new Map();
        for (const leaf of tree.leaves) {
          const v = recordOf(leaf)[key];
          if (v === undefined || v === null || v === '') continue;
          m.set(String(v), (m.get(String(v)) || 0) + 1);
        }
        fltValueCounts.set(key, m);
      }
      return fltValueCounts.get(key);
    };

    function applyFilter() {
      const out = evaluateFilter(filterState, {
        leaves: tree.leaves.map(leaf => leaf.name),
        metadata, matrices, fieldTypes: filterFieldTypes,
      });
      filterMatched = out.matched;
      filterWarnings = out.warnings;
      const ids = filterMatched
        ? tree.leaves.filter(leaf => filterMatched.has(leaf.name)).map(leaf => leaf.id) : null;
      constellation?.setMatchPulse(ids, { pulse: filterState.pulse });
      constellation?.setDimOpacity?.(filterState.dim);
      applyEmphasis();
      matchTable?.render();
    }

    const leafPassesFilters = leaf => {
      if (epi.focus >= 0 && !(epi.clusters[epi.focus] || []).includes(leaf.name)) return false;
      if (brushActive()) {
        const interval = timeData(epi.timeField)?.intervals.get(leaf.name);
        if (!interval || interval.start > epi.brush.b || interval.end < epi.brush.a) return false;
      }
      return !filterMatched || filterMatched.has(leaf.name);
    };

    function focusMatched() {
      if (!filterMatched?.size || !constellation) return;
      const pts = tree.leaves.filter(leaf => filterMatched.has(leaf.name))
        .map(leaf => constellation.nodePosition(leaf.id)).filter(Boolean);
      if (!pts.length) return;
      const c = new THREE.Vector3();
      for (const pt of pts) c.add(pt);
      c.divideScalar(pts.length);
      let r = 1;
      for (const pt of pts) r = Math.max(r, pt.distanceTo(c));
      const dir = host.camera.position.clone().sub(host.controls.target).normalize();
      host.flyTo(c.clone().add(dir.multiplyScalar(Math.max(r * 2.6, 8))), c);
    }

    // ---- match table (right panel, shared component) ----
    const tableCellValue = (col, leaf) => {
      if (col.kind === 'matrix') {
        const m = matrices.find(mx => mx.id === col.matrix);
        const ci = m?.columns.findIndex(c => c.id === col.column) ?? -1;
        const v = ci >= 0 ? m.rows?.[leaf.name]?.[ci] : null;
        return v === undefined ? null : v;
      }
      const v = recordOf(leaf)[col.key];
      return v === undefined || v === '' ? null : v;
    };
    const tableCellText = (col, leaf) => {
      const v = tableCellValue(col, leaf);
      if (v === null || v === undefined) return '—';
      if (col.kind === 'matrix') return v === 1 ? '阳性' : v === 0 ? '阴性' : '未检测';
      return String(v);
    };

    const tableColumns = () => {
      const options = tableColumnOptions({
        conditions: filterState.conditions, fields: v2.fields || [],
        fieldTypes: filterFieldTypes, matrices, fieldLabel,
      });
      const byId = new Map(options.map(c => [c.id, c]));
      const current = tableState.columns
        ? tableState.columns.map(id => byId.get(id)).filter(Boolean)
        : defaultTableColumns({
            conditions: filterState.conditions,
            colorField: state.color && state.color !== 'clade' ? state.color : null,
            fields: v2.fields || [], fieldLabel,
          }).map(c => byId.get(c.id) || { ...c, label: c.label || (c.kind === 'matrix' ? `${c.matrix}:${c.column}` : fieldLabel(c.key)) });
      return { options, current };
    };

    const flyToLeaf = leaf => {
      const position = constellation.nodePosition(leaf.id);
      if (position) host.centerOn?.(position);
    };

    function createPanel(el) {
      matchTable = createMatchTable({
        el,
        adapter: {
          state: tableState,
          active: () => !!filterMatched,
          rows: () => tree.leaves.filter(leaf => filterMatched?.has(leaf.name)),
          rowKey: leaf => String(leaf.id),
          leadingCols: [{ id: 'name', label: '叶名', value: leaf => leaf.name }],
          columns: tableColumns,
          cellValue: tableCellValue,
          cellText: tableCellText,
          title: k => `匹配表 · ${k} 株`,
          isDimmed: leaf => !leafPassesFilters(leaf),
          isSelected: leaf => selectedNode?.id === leaf.id,
          activate: leaf => { host.select?.({ type: 'node', id: leaf.id }); flyToLeaf(leaf); },
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
          available: matrices.length > 0 || [...filterFieldTypes.values()].some(t => t !== 'date'),
          fieldTypes: filterFieldTypes,
          matrices,
          fieldLabel,
          matrixLabel: id => matrices.find(m => m.id === id)?.label || id,
          valueCounts,
          apply: applyFilter,
          onDim: dim => constellation?.setDimOpacity?.(dim),
          context: () => {
            const comboActive = epi.focus >= 0 || brushActive();
            const combined = filterMatched && comboActive ? tree.leaves.filter(leafPassesFilters).length : null;
            const distCounts = filterMatched ? (() => {
              const m = new Map();
              for (const leaf of tree.leaves) {
                if (!filterMatched.has(leaf.name)) continue;
                const v = state.color && state.color !== 'clade' ? (recordOf(leaf)[state.color] ?? MISSING)
                  : (cladeKey.get(leaf.id) ?? MISSING);
                m.set(String(v), (m.get(String(v)) || 0) + 1);
              }
              return [...m.entries()].sort((a, b) => b[1] - a[1]).slice(0, 5);
            })() : [];
            return {
              matched: filterMatched,
              k: filterMatched ? filterMatched.size : 0,
              n: tree.leafCount,
              extras: combined !== null ? [`与时间窗/簇聚焦叠加后 ${combined} 株`] : [],
              distCounts,
              matchRows: filterMatched
                ? tree.leaves.filter(l => filterMatched.has(l.name)).map(l => ({ key: String(l.id), label: l.name }))
                : [],
              warnings: filterWarnings,
            };
          },
          selectRow: key => {
            const node = tree.nodes[Number(key)];
            if (!node) return;
            host.select?.({ type: 'node', id: node.id });
            const position = constellation.nodePosition(node.id);
            if (position) host.flyTo(position.clone().add(new THREE.Vector3(0, 3.2, 7.5)), position);
          },
          focus: focusMatched,
          notify: () => host.notifyStateChange?.(),
        },
      });
      filterUi.render();
    }

    // ---- rings geometry ----
    function disposeRings() {
      if (!ringGroup) return;
      root.remove(ringGroup);
      disposeHierarchy(ringGroup);
      ringGroup = null;
      ringCellsMeta = null;
      ringColumnMeta = [];
      leaderLines = null;
    }

    const RING_NULL_COLOR = '#3a4152';
    const RING_ZERO_COLOR = '#1c2230';

    function ringCellBase(leaf, spec, colId) {
      if (spec.matrix) {
        const row = spec.matrix.rows?.[leaf.name];
        const value = row ? row[colId] : null;
        if (value === null || value === undefined) return { rgba: rgbaOf(RING_NULL_COLOR, 0.35), tag: '未检测' };
        if (value === 1) return { rgba: rgbaOf(spec.color, 0.95), tag: '有' };
        return { rgba: rgbaOf(RING_ZERO_COLOR, 0.9), tag: '无' };
      }
      const rec = recordOf(leaf);
      const value = rec[spec.field];
      if (value === undefined || value === null || value === '') {
        return { rgba: rgbaOf(RING_NULL_COLOR, 0.35), tag: '未检测' };
      }
      const fc = spec._fColors || fieldColors(spec.field);
      const key = fc.keys[leafIndex.get(leaf)];
      const color = fc.layers.get(key)?.color || RING_ZERO_COLOR;
      return { rgba: rgbaOf(color, 0.9), tag: String(value) };
    }
    const rgbaCache = new Map();
    const rgbaOf = (hex, a) => {
      const key = `${hex}|${a}`;
      if (!rgbaCache.has(key)) {
        const c = new THREE.Color(hex);
        rgbaCache.set(key, [c.r, c.g, c.b, a]);
      }
      return rgbaCache.get(key);
    };

    const ringTimings = {};
    function buildRings(flat, heights) {
      const tStart = performance.now();
      disposeRings();
      if (state.layout === 'equal') return;
      const specs = [];
      matrices.forEach((m, mi) => {
        const cfg = ringsState.matrices[m.id];
        if (!cfg?.on) return;
        const cols = selectColumns(m, statsOf(m), cfg);
        if (cols.length) specs.push({ kind: 'matrix', id: m.id, label: m.label || m.id, matrix: m, color: matrixColorOf(m.id, mi), columns: cols });
      });
      for (const key of ringsState.fieldRings) {
        specs.push({ kind: 'field', id: `field:${key}`, label: fieldLabel(key), field: key, columns: [{ id: key, group: null }] });
      }
      if (!specs.length) return;

      const positions = new Map(tree.leaves.map(leaf => [leaf, flat.nodes[leaf.id]]));
      const t0 = performance.now();
      const sectors = leafSectors(tree.leaves, positions);
      const maxLeafR = Math.max(...tree.leaves.map(leaf => Math.hypot(flat.nodes[leaf.id].x, flat.nodes[leaf.id].y)));
      const yBase = Math.min(...tree.nodes.map(node => heights.get(node.id))) - 0.8;
      const layout = ringLayout({
        rings: specs.map(spec => ({ id: spec.id, columns: spec.columns })),
        R0: maxLeafR * 1.08, Rtree: RADIUS,
      });
      for (const spec of specs) {
        spec._colIdx = spec.matrix
          ? new Map(spec.matrix.columns.map((c, i) => [c.id, i])) : null;
        spec._fColors = spec.kind === 'field' ? fieldColors(spec.field) : null;
      }
      const t1 = performance.now();
      const specById = new Map(specs.map(spec => [spec.id, spec]));
      const colIndexOf = (spec, colId) => spec._colIdx?.get(colId) ?? 0;
      const highlighted = cell =>
        ringsState.highlight && ringsState.highlight.ring === cell.ring && ringsState.highlight.column === cell.column;
      const built = buildRingCells({
        sectors, layout, y: yBase,
        colors: (leaf, ringId, colId) => {
          const spec = specById.get(ringId);
          const base = ringCellBase(leaf, spec, colIndexOf(spec, colId));
          const cell = { ring: ringId, column: colId };
          if (highlighted(cell)) {
            // brighten the highlighted column: lerp toward white + full alpha
            const [r, g, b, a] = base.rgba;
            return [r + (1 - r) * 0.45, g + (1 - g) * 0.45, b + (1 - b) * 0.45, Math.min(1, a + 0.05)];
          }
          return base.rgba;
        },
      });

      const t2 = performance.now();
      ringGroup = new THREE.Group();
      ringGroup.name = 'data-rings';
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute('position', new THREE.BufferAttribute(built.positions, 3));
      geometry.setAttribute('color', new THREE.BufferAttribute(built.vertexColors, 4));
      const mesh = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({
        vertexColors: true, transparent: true, depthWrite: false, side: THREE.DoubleSide,
      }));
      ringGroup.add(mesh);

      // per-cell base colours + emphasis rewriting
      const byRing = new Map();
      for (const cell of built.cells) {
        const spec = specById.get(cell.ring);
        const leaf = tree.nodes[cell.leaf.id ?? cell.leaf];
        cell._leaf = leaf;
        const base = ringCellBase(leaf, spec, colIndexOf(spec, cell.column));
        const hi = ringsState.highlight && ringsState.highlight.ring === cell.ring && ringsState.highlight.column === cell.column;
        cell._base = hi
          ? [base.rgba[0] + (1 - base.rgba[0]) * 0.45, base.rgba[1] + (1 - base.rgba[1]) * 0.45, base.rgba[2] + (1 - base.rgba[2]) * 0.45, Math.min(1, base.rgba[3] + 0.05)]
          : base.rgba;
        if (!byRing.has(cell.ring)) byRing.set(cell.ring, []);
        byRing.get(cell.ring).push(cell);
      }
      ringCellsMeta = { mesh, attr: geometry.getAttribute('color'), cells: built.cells, perCell: built.verticesPerCell, specById };
      ringColumnMeta = layout.rings.flatMap(ring => ring.columns.map(col => ({ ring: ring.id, ...col })));

      // picking: triangle → cell via faceIndex
      mesh.userData.pickFor = (instanceId, hit) => {
        const v = hit.faceIndex * 3;
        // cells have constant vertex count → index by division
        const idx = Math.floor(v / built.verticesPerCell);
        const cell = built.cells[idx];
        if (!cell) return null;
        return { type: 'ring', ring: cell.ring, column: cell.column, leaf: cell._leaf.id, leafName: cell._leaf.name };
      };
      registerPickable(mesh, null);

      // leader lines: leaf position → its ring sector at R0
      if (ringsState.leaders) {
        const pts = [];
        const rTarget = layout.rings[0]?.columns[0]?.r0 || maxLeafR;
        for (const leaf of tree.leaves) {
          const p = flat.nodes[leaf.id];
          const h = heights.get(leaf.id);
          const r = Math.hypot(p.x, p.y) || 1;
          pts.push(p.x, h, p.y, p.x / r * rTarget, yBase, p.y / r * rTarget);
        }
        const lg = new THREE.BufferGeometry();
        lg.setAttribute('position', new THREE.Float32BufferAttribute(pts, 3));
        leaderLines = new THREE.LineSegments(lg, new THREE.LineBasicMaterial({
          color: '#8899aa', transparent: true, opacity: 0.18, depthWrite: false,
        }));
        ringGroup.add(leaderLines);
      }

      // column labels when few enough + group pills
      const totalCols = ringColumnMeta.length;
      if (totalCols <= 40) {
        const gapSector = sectors.reduce((best, s) => (s.gapAfter > (best?.gapAfter ?? -1) ? s : best), null);
        const gapMid = gapSector ? gapSector.theta + gapSector.gapAfter / 2 : 0;
        for (const col of ringColumnMeta) {
          const spec = specById.get(col.ring);
          const label = spec.kind === 'field' ? spec.label : col.id;
          const sprite = makeLabel(label, { color: '#c3cdf0', height: 0.3, fontSize: 20, align: 'center' });
          sprite.position.set(Math.cos(gapMid) * col.mid, yBase + 0.05, Math.sin(gapMid) * col.mid);
          ringGroup.add(sprite);
        }
        // group pills at the group's angular gap position, group mid-radius
        for (const ring of layout.rings) {
          const groups = new Map();
          for (const col of ring.columns) {
            if (!col.group) continue;
            if (!groups.has(col.group)) groups.set(col.group, []);
            groups.get(col.group).push(col.mid);
          }
          for (const [g, mids] of groups) {
            const mid = mids.reduce((a, b) => a + b, 0) / mids.length;
            const pill = makePillLabel(g, { color: '#aab3c5', height: 0.4, fontSize: 22 });
            pill.position.set(Math.cos(gapMid) * mid, yBase + 0.12, Math.sin(gapMid) * mid);
            ringGroup.add(pill);
          }
        }
      }
      root.add(ringGroup);
      const t3 = performance.now();
      Object.assign(ringTimings, {
        total: Math.round(t3 - tStart),
        sectors: Math.round(t1 - t0),
        cells: Math.round(t2 - t1),
        scene: Math.round(t3 - t2),
        cellCount: built.cells.length,
      });
    }

    function applyRingEmphasis() {
      if (!ringCellsMeta) return;
      const { attr, cells, perCell } = ringCellsMeta;
      for (const cell of cells) {
        const on = !ringEmphasis || ringEmphasis.has(cell._leaf.id);
        const a = cell._base[3] * (on ? 1 : 0.15);
        for (let k = 0; k < perCell; k++) attr.setW(cell.v0 + k, a);
      }
      attr.needsUpdate = true;
    }

    const ringColIndexOf = (spec, colId) => spec._colIdx?.get(colId) ?? 0;
    const brightenRgba = rgba => [
      rgba[0] + (1 - rgba[0]) * 0.45, rgba[1] + (1 - rgba[1]) * 0.45,
      rgba[2] + (1 - rgba[2]) * 0.45, Math.min(1, rgba[3] + 0.05)];

    function refreshRingColors() {
      if (!ringCellsMeta) return;
      const { attr, cells, perCell, specById } = ringCellsMeta;
      for (const cell of cells) {
        const spec = specById.get(cell.ring);
        const base = ringCellBase(cell._leaf, spec, ringColIndexOf(spec, cell.column));
        const hi = ringsState.highlight && ringsState.highlight.ring === cell.ring
          && ringsState.highlight.column === cell.column;
        cell._base = hi ? brightenRgba(base.rgba) : base.rgba;
        const on = !ringEmphasis || ringEmphasis.has(cell._leaf.id);
        const a = cell._base[3] * (on ? 1 : 0.15);
        for (let k = 0; k < perCell; k++) {
          attr.setXYZW(cell.v0 + k, cell._base[0], cell._base[1], cell._base[2], a);
        }
      }
      attr.needsUpdate = true;
    }

    function rebuildRings() {
      if (!lastFlat || !lastHeights) return;
      buildRings(lastFlat, lastHeights);
      applyRingEmphasis();
    }

    function ringCarrierStats() {
      const hl = ringsState.highlight;
      if (!hl) return null;
      const ok = leaf => {
        if (hl.ring.startsWith('field:')) return recordOf(leaf)[hl.column] === hl.value;
        const m = matrices.find(mx => mx.id === hl.ring);
        const row = m?.rows?.[leaf.name];
        return !!row && row[m.columns.findIndex(c => c.id === hl.column)] === 1;
      };
      let k = 0, m0 = 0;
      for (const leaf of tree.leaves) {
        if (ok(leaf)) k++;
        else if (!hl.ring.startsWith('field:')) {
          const m = matrices.find(mx => mx.id === hl.ring);
          const row = m?.rows?.[leaf.name];
          if (!row || row[m.columns.findIndex(c => c.id === hl.column)] === null
              || row[m.columns.findIndex(c => c.id === hl.column)] === undefined) m0++;
        }
      }
      // distribution over current colour field (top 5)
      const counts = new Map();
      for (const leaf of tree.leaves) {
        if (!ok(leaf)) continue;
        const v = state.color && state.color !== 'clade' ? (recordOf(leaf)[state.color] ?? MISSING) : (cladeKey.get(leaf.id) ?? MISSING);
        counts.set(String(v), (counts.get(String(v)) || 0) + 1);
      }
      const dist5 = [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 5);
      return { k, n: tree.leaves.length, p: Math.round(k / tree.leaves.length * 100), m0, dist5 };
    }

    function toggleRingHighlight(ring, column, value) {
      const hl = ringsState.highlight;
      if (hl && hl.ring === ring && hl.column === column && (value === undefined || hl.value === value)) {
        ringsState.highlight = null;
      } else {
        ringsState.highlight = { ring, column, value };
      }
      refreshRingColors();
      applyEmphasis();
    }

    function alignTopDown() {
      if (!ringCellsMeta && !lastFlat) return;
      const outerR = ringColumnMeta.length ? ringColumnMeta[ringColumnMeta.length - 1].r1
        : Math.max(...tree.leaves.map(l => Math.hypot(lastFlat.nodes[l.id].x, lastFlat.nodes[l.id].y))) * 1.08;
      const yBase = lastHeights ? Math.min(...tree.nodes.map(n => lastHeights.get(n.id))) - 0.8 : 0;
      const d = outerR * 1.3;
      host.setCamera(
        new THREE.Vector3(d * 0.03, yBase + d, 0),
        new THREE.Vector3(0, yBase, 0));
      // rotate control path so persisted state stays consistent
      if (!host.setControl?.('rotate', 0)) {
        host.setAutoRotate(false);
        host.notifyStateChange?.();
      }
    }

    build();

    const getNode = payload => (payload?.type === 'node' ? tree.nodes[payload.id] : null);
    const calloutFor = node => {
      if (node === tree.root) return { title: 'root', subtitle: `${tree.leafCount} taxa · max depth ${tree.maxDepth.toFixed(3)}` };
      if (node.children.length) return { title: node.name || `node ${node.id}`, subtitle: `${node.leafCount} leaves · depth ${node.depth.toFixed(4)}` };
      const meta = recordOf(node);
      const tag = state.color && state.color !== 'clade' ? (meta[state.color] ?? MISSING) : 'leaf';
      return { title: node.name, subtitle: `${meta.st || meta.ST || 'leaf'} · ${tag} · depth ${node.depth.toFixed(4)}` };
    };
    const clusterTag = node => {
      if (node.children.length || !epi.clusterOn) return '';
      const ci = epi.clusterOf.get(node.name);
      return ci === undefined ? '' : ` · 簇 ${ci + 1}`;
    };
    const clusterOfLeaf = leaf => (epi.clusterOn ? (epi.clusterOf.get(leaf.name) ?? null) : null);
    const distUnitLabel = v2.distances?.unit || '';
    const recordRows = record => Object.entries(record)
      .filter(([, value]) => value !== null && typeof value !== 'object')
      .map(([key, value]) => `<dt>${escapeHtml(fieldLabel(key))}</dt><dd>${escapeHtml(value)}</dd>`).join('');

    function renderRingsBlock() {
      if (!ringsBlockEl) return;
      const blk = ringsBlockEl;
      if (!RINGS_ENABLED) { blk.innerHTML = ''; return; }
      // keep expanded 列设置 details open across re-renders
      const openGroups = new Set(
        [...blk.querySelectorAll('details.ctl-group[open]')].map(d => d.dataset.det));
      if (!matrices.length && !categoricalFields.length) { blk.innerHTML = ''; return; }
      if (state.layout === 'equal') {
        blk.innerHTML = `<div class="blk-head"><span class="t">数据环 · Rings</span></div>
          <p class="gene-note">无根等角布局下叶节点不按角度排列，数据环不可用</p>`;
        return;
      }
      const hl = ringsState.highlight;
      const stats = ringCarrierStats();
      const anyOn = Object.values(ringsState.matrices).some(c => c.on) || ringsState.fieldRings.length;
      const visibleCount = Object.values(ringsState.matrices).filter(c => c.on).length + ringsState.fieldRings.length;
      blk.innerHTML = `<div class="blk-head"><span class="t">数据环 · Rings</span><span class="n">${visibleCount || '关'}</span></div>
        ${matrices.map((m) => {
          const cfg = ringsState.matrices[m.id];
          const statsM = statsOf(m);
          const sel = cfg.on ? selectColumns(m, statsM, cfg) : [];
          const hidden = m.columns.length - sel.length;
          return `<div class="ring-matrix-row">
            <label class="view-toggle">${escapeHtml(m.label || m.id)}<span class="ring-dim">${m.columns.length} 列</span><input type="checkbox" data-ring-toggle="${escapeHtml(m.id)}" ${cfg.on ? 'checked' : ''}><i></i></label>
            <details class="ctl-group" data-det="${escapeHtml(m.id)}" ${openGroups.has(m.id) ? 'open' : ''}><summary class="ctl-sec">列设置</summary>
              <label class="view-select"><span>排序</span><select data-ring-sort="${escapeHtml(m.id)}">
                <option value="group" ${cfg.sort === 'group' ? 'selected' : ''}>按分组</option>
                <option value="prev" ${cfg.sort === 'prev' ? 'selected' : ''}>按携带率</option>
                <option value="name" ${cfg.sort === 'name' ? 'selected' : ''}>按名称</option>
              </select></label>
              <label class="view-range"><span>最低携带率<b>${cfg.minPrev}%</b></span><input type="range" min="0" max="50" step="1" value="${cfg.minPrev}" data-ring-minprev="${escapeHtml(m.id)}"></label>
              <label class="view-range"><span>最大列数<b>${cfg.maxCols}</b></span><input type="range" min="5" max="200" step="1" value="${cfg.maxCols}" data-ring-maxcols="${escapeHtml(m.id)}"></label>
              <p class="gene-note" data-hidden-note="${escapeHtml(m.id)}" ${cfg.on && hidden > 0 ? '' : 'hidden'}>已隐藏 ${hidden} 列</p>
              <input class="mst-search" type="search" placeholder="搜索列…" data-ring-search="${escapeHtml(m.id)}">
              <div class="ring-col-list" data-ring-list="${escapeHtml(m.id)}">
                ${statsM.map(st => {
                  const inc = cfg.include.includes(st.id), exc = cfg.exclude.includes(st.id);
                  const shown = exc ? false : (inc ? true : sel.some(c => c.id === st.id));
                  const hlOn = hl && hl.ring === m.id && hl.column === st.id;
                  return `<div class="cat-row ring-col-item" data-colname="${escapeHtml(st.id.toLowerCase())}">
                    <input type="checkbox" data-ring-col="${escapeHtml(m.id)}|${escapeHtml(st.id)}" ${shown ? 'checked' : ''}>
                    <button type="button" class="ring-col-name ${hlOn ? 'on' : ''}" data-ring-hl="${escapeHtml(m.id)}|${escapeHtml(st.id)}" title="点击高亮携带株">${escapeHtml(st.id)}</button>
                    <b>${Math.round(st.prevalence * 100)}%</b>
                  </div>`;
                }).join('')}
              </div>
            </details>
          </div>`;
        }).join('')}
        ${categoricalFields.length ? `<label class="view-select"><span>字段环</span><select data-field-ring-add>
            <option value="">添加字段环…</option>
            ${categoricalFields.filter(k => !ringsState.fieldRings.includes(k)).map(k => `<option value="${escapeHtml(k)}">${escapeHtml(fieldLabel(k))}</option>`).join('')}
          </select></label>
          ${ringsState.fieldRings.map(k => `<div class="cat-row ring-field-row"><i style="background:${fieldColors(k).layers.get(fieldColors(k).keys[0])?.color || 'var(--accent-2)'}"></i><span>${escapeHtml(fieldLabel(k))}</span><button type="button" data-field-ring-rm="${escapeHtml(k)}" title="移除字段环">×</button></div>`).join('')}` : ''}
        ${anyOn ? `<label class="view-toggle">引线<input type="checkbox" data-ring-leaders ${ringsState.leaders ? 'checked' : ''}><i></i></label>
        <div class="ring-actions"><button type="button" data-ring-topdown>俯视对齐</button></div>` : ''}
        ${hl ? `<p class="gene-note">高亮携带株：${escapeHtml(hl.column)}
          ${stats ? `· 携带 ${stats.k} / ${stats.n}（${stats.p}%）· 未检测 ${stats.m0}` : ''}</p>
          ${stats?.dist5.length ? `<p class="gene-note">${stats.dist5.map(([v, c]) => `${escapeHtml(v)} ×${c}`).join(' · ')}</p>` : ''}
          <div class="ring-actions"><button type="button" data-ring-hl-clear>清除高亮</button></div>` : ''}`;
      blk.oninput = ev => {
        const t = ev.target;
        if (t.dataset.ringSort) { ringsState.matrices[t.dataset.ringSort].sort = t.value; rebuildRings(); renderRingsBlock(); host.notifyStateChange?.(); }
        else if (t.dataset.ringMinprev) {
          const cfg = ringsState.matrices[t.dataset.ringMinprev];
          cfg.minPrev = Number(t.value);
          t.closest('.view-range').querySelector('b').textContent = `${cfg.minPrev}%`;
          rebuildRings(); updateHiddenNote(t.dataset.ringMinprev); host.notifyStateChange?.();
        }
        else if (t.dataset.ringMaxcols) {
          const cfg = ringsState.matrices[t.dataset.ringMaxcols];
          cfg.maxCols = Number(t.value);
          t.closest('.view-range').querySelector('b').textContent = cfg.maxCols;
          rebuildRings(); updateHiddenNote(t.dataset.ringMaxcols); host.notifyStateChange?.();
        }
        else if (t.dataset.ringSearch) {
          const q = t.value.trim().toLowerCase();
          blk.querySelectorAll(`[data-ring-list="${CSS.escape(t.dataset.ringSearch)}"] .ring-col-item`)
            .forEach(item => { item.style.display = !q || item.dataset.colname.includes(q) ? '' : 'none'; });
        }
      };
      blk.onchange = ev => {
        const t = ev.target;
        if (t.dataset.ringToggle) {
          ringsState.matrices[t.dataset.ringToggle].on = t.checked;
          rebuildRings(); renderRingsBlock(); host.notifyStateChange?.();
        } else if (t.dataset.ringCol) {
          const [mid, cid] = t.dataset.ringCol.split('|');
          const cfg = ringsState.matrices[mid];
          cfg.include = cfg.include.filter(c => c !== cid);
          cfg.exclude = cfg.exclude.filter(c => c !== cid);
          if (t.checked) cfg.include.push(cid); else cfg.exclude.push(cid);
          rebuildRings(); updateHiddenNote(mid); host.notifyStateChange?.();
        } else if (t.hasAttribute('data-field-ring-add')) {
          if (t.value && ringsState.fieldRings.length < 3 && !ringsState.fieldRings.includes(t.value)) {
            ringsState.fieldRings.push(t.value);
            rebuildRings(); renderRingsBlock(); host.notifyStateChange?.();
          }
        } else if (t.hasAttribute('data-ring-leaders')) {
          ringsState.leaders = t.checked;
          rebuildRings(); host.notifyStateChange?.();
        }
      };
      blk.onclick = ev => {
        const t = ev.target;
        if (t.dataset.fieldRingRm) {
          ringsState.fieldRings = ringsState.fieldRings.filter(k => k !== t.dataset.fieldRingRm);
          rebuildRings(); renderRingsBlock(); host.notifyStateChange?.();
        } else if (t.hasAttribute('data-ring-topdown')) {
          alignTopDown();
        } else if (t.dataset.ringHl) {
          const [mid, cid] = t.dataset.ringHl.split('|');
          toggleRingHighlight(mid, cid, 1);
          renderRingsBlock(); host.notifyStateChange?.();
        } else if (t.hasAttribute('data-ring-hl-clear')) {
          ringsState.highlight = null;
          refreshRingColors(); applyEmphasis(); renderRingsBlock(); host.notifyStateChange?.();
        }
      };
    }

    function updateHiddenNote(mid) {
      const el = ringsBlockEl?.querySelector(`[data-hidden-note="${CSS.escape(mid)}"]`);
      if (!el) return;
      const m = matrices.find(mx => mx.id === mid);
      const cfg = ringsState.matrices[mid];
      const hidden = m.columns.length - (cfg.on ? selectColumns(m, statsOf(m), cfg).length : 0);
      el.hidden = !(cfg.on && hidden > 0);
      el.textContent = `已隐藏 ${hidden} 列`;
    }

    function applyEmphasis() {
      const leafOk = leafPassesFilters;
      const emphasisedIds = new Set();
      (function mark(node) {
        node.children.forEach(mark);
        if (!node.children.length) {
          if (leafOk(node)) emphasisedIds.add(node.id);
        } else if (node.children.some(child => emphasisedIds.has(child.id))) {
          emphasisedIds.add(node.id);
        }
      })(tree.root);
      const allOn = epi.focus < 0 && !brushActive() && !filterMatched;
      ringEmphasis = allOn ? null : new Set(tree.leaves.filter(leafOk).map(leaf => leaf.id));
      constellation?.setEmphasis(allOn ? null : i => emphasisedIds.has(i));
      applyRingEmphasis();
      filterUi?.updateResult();
      matchTable?.updateDim();
    }

    function applyClusters() {
      const result = epi.clusterOn && dist
        ? thresholdClusters(dist, epi.threshold)
        : { clusters: [], clusterOf: new Map() };
      epi.clusters = result.clusters;
      epi.clusterOf = result.clusterOf;
      if (epi.focus >= epi.clusters.length) epi.focus = -1;
      const colors = new Array(tree.nodes.length).fill(null);
      if (epi.clusterOn) {
        for (const leaf of tree.leaves) {
          const ci = epi.clusterOf.get(leaf.name);
          if (ci !== undefined) colors[leaf.id] = CLUSTER_PALETTE[ci % CLUSTER_PALETTE.length];
        }
      }
      constellation?.setOutlines(colors.some(Boolean) ? colors : null);
      renderClusterBlock();
      applyEmphasis();
    }
    function applyEpi() { applyClusters(); }

    const flyToNames = names => {
      const positions = tree.leaves.filter(leaf => names.includes(leaf.name))
        .map(leaf => constellation.nodePosition(leaf.id)).filter(Boolean);
      if (!positions.length) return;
      const centroid = positions.reduce((acc, pos) => acc.add(pos), new THREE.Vector3()).multiplyScalar(1 / positions.length);
      host.flyTo(centroid.clone().add(new THREE.Vector3(0, 3.2, 7.5)), centroid);
    };

    function renderClusterBlock() {
      if (!clusterBlockEl) return;
      const distLabel = v2.distances?.label || '两两距离';
      const distUnit = v2.distances?.unit === 'snp' ? 'SNP' : (v2.distances?.unit || '距离');
      const maxSlider = Math.min(Math.max(1, Math.ceil(maxDistance)), 200);
      const fieldsByRole = { time: fieldOfRole('time'), place: fieldOfRole('place'), source: fieldOfRole('source') };
      const rows = epi.clusters.slice(0, 30).map((members, ci) => {
        const records = members.map(name => metadata[name] || {});
        const sum = summarizeMembers(records, fieldsByRole);
        const split = isTreeSplit(tree, members.filter(name => leafNameSet.has(name)));
        const span = sum.timeStart ? `${sum.timeStart}→${sum.timeEnd}` : '—';
        const place = sum.places[0] ? `${sum.places[0][0]}×${sum.places[0][1]}` : '—';
        const source = sum.sources[0] ? `${sum.sources[0][0]}×${sum.sources[0][1]}` : '—';
        return `<button class="rep-row${epi.focus === ci ? ' on' : ''}" data-cluster="${ci}">
          <div class="rname"><span><i style="display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:7px;background:${CLUSTER_PALETTE[ci % CLUSTER_PALETTE.length]}"></i>簇 ${ci + 1} · ${members.length} 株</span></div>
          <div class="gene-note" style="padding:0 2px">${escapeHtml(span)} · ${escapeHtml(place)} · ${escapeHtml(source)} · 树上${split ? '构成一个分支' : '不构成单一分支'}</div>
        </button>`;
      }).join('');
      clusterBlockEl.innerHTML = `
        <div class="blk-head"><span class="t">暴发簇 · ${escapeHtml(distUnit)} 阈值</span><span class="n">${epi.clusterOn ? epi.clusters.length : '关'}</span></div>
        <div class="ring-actions">
          <button type="button" data-role="cluster-toggle">${epi.clusterOn ? '关闭聚簇' : '启用聚簇'}</button>
          <button type="button" data-role="cluster-clear" ${epi.focus >= 0 ? '' : 'disabled'}>清除聚焦</button>
        </div>
        ${epi.clusterOn ? `
        <label class="view-range"><span>阈值<b>${epi.threshold} ${escapeHtml(distUnit)}</b></span><input type="range" data-role="cluster-range" min="0" max="${maxSlider}" step="1" value="${epi.threshold}"></label>
        <div data-role="cluster-list">${rows}${epi.clusters.length > 30 ? `<p class="gene-note">还有 ${epi.clusters.length - 30} 个簇</p>` : ''}</div>` : ''}
        <p class="gene-note">距离覆盖 ${distCoverage} / ${tree.leafCount} 个叶节点（${escapeHtml(distLabel)}）。单连锁：两两距离 ≤ 阈值即相连；阈值依物种与流程而定，仅为显示分组，不是流行病学判定。</p>`;
      clusterBlockEl.querySelector('[data-role="cluster-toggle"]')?.addEventListener('click', () => {
        epi.clusterOn = !epi.clusterOn;
        if (!epi.clusterOn) epi.focus = -1;
        applyClusters();
        notifyState();
      });
      clusterBlockEl.querySelector('[data-role="cluster-clear"]')?.addEventListener('click', () => {
        epi.focus = -1;
        renderClusterBlock();
        applyEmphasis();
        notifyState();
      });
      clusterBlockEl.querySelector('[data-role="cluster-range"]')?.addEventListener('input', event => {
        epi.threshold = Number(event.target.value);
        applyClusters();
        notifyState();
      });
      clusterBlockEl.querySelectorAll('[data-cluster]').forEach(btn => btn.addEventListener('click', () => {
        const ci = Number(btn.dataset.cluster);
        if (epi.focus === ci) { epi.focus = -1; }
        else {
          epi.focus = ci;
          flyToNames(epi.clusters[ci]);
        }
        renderClusterBlock();
        applyEmphasis();
        notifyState();
      }));
    }

    function renderTimeBlock() {
      if (!timeBlockEl) return;
      const options = dateFields.map(field => `<option value="${escapeHtml(field.key)}"${field.key === epi.timeField ? ' selected' : ''}>${escapeHtml(field.label || field.key)}</option>`).join('');
      const td = epi.timeField && timeData(epi.timeField);
      if (!td) {
        timeBlockEl.innerHTML = '';
        return;
      }
      const bins = new Array(24).fill(0);
      const span = Math.max(1, td.maxEnd - td.minStart);
      for (const interval of td.intervals.values()) {
        const mid = (interval.start + interval.end) / 2;
        bins[Math.min(23, Math.floor((mid - td.minStart) / span * 24))]++;
      }
      const maxBin = Math.max(1, ...bins);
      const histogram = bins.map(count => `<i style="display:inline-block;width:${(100 / 24).toFixed(2)}%;height:${(count / maxBin * 34).toFixed(0)}px;background:${count ? '#4d9fff' : '#1a1d26'};vertical-align:bottom"></i>`).join('');
      const a = epi.brush?.a ?? td.minStart, b = epi.brush?.b ?? td.maxEnd;
      timeBlockEl.innerHTML = `
        <div class="blk-head"><span class="t">时间 · Time</span><span class="n">${escapeHtml(fieldLabel(epi.timeField))}</span></div>
        <div class="ctl-row"><select data-role="time-field">${options}</select></div>
        <div style="display:flex;align-items:flex-end;height:36px;gap:1px">${histogram}</div>
        <label class="view-range"><span>起始<b>${formatDay(a)}</b></span><input type="range" data-role="time-a" min="${td.minStart}" max="${td.maxEnd}" step="1" value="${a}"></label>
        <label class="view-range"><span>结束<b>${formatDay(b)}</b></span><input type="range" data-role="time-b" min="${td.minStart}" max="${td.maxEnd}" step="1" value="${b}"></label>
        <div class="ring-actions">
          <button type="button" data-role="time-all">全部</button>
          <button type="button" data-role="time-play">${epi.playTimer ? '⏸' : '▶ 播放'}</button>
        </div>
        <p class="gene-note">无日期的叶节点：${td.missing}（时间筛选启用时淡化）。区间取中点入箱；叶节点与窗口相交即在窗内。</p>`;
      const sync = () => {
        let [lo, hi] = [Number(timeBlockEl.querySelector('[data-role="time-a"]').value), Number(timeBlockEl.querySelector('[data-role="time-b"]').value)];
        if (lo > hi) [lo, hi] = [hi, lo];
        epi.brush = { a: lo, b: hi };
        renderTimeBlock();
        applyEmphasis();
        notifyState();
      };
      timeBlockEl.querySelector('[data-role="time-field"]')?.addEventListener('change', event => {
        epi.timeField = event.target.value;
        const next = timeData(epi.timeField);
        epi.brush = next ? { a: next.minStart, b: next.maxEnd } : null;
        stopPlay();
        renderTimeBlock();
        applyEmphasis();
        notifyState();
      });
      timeBlockEl.querySelector('[data-role="time-a"]')?.addEventListener('input', sync);
      timeBlockEl.querySelector('[data-role="time-b"]')?.addEventListener('input', sync);
      timeBlockEl.querySelector('[data-role="time-all"]')?.addEventListener('click', () => {
        epi.brush = { a: td.minStart, b: td.maxEnd };
        stopPlay();
        renderTimeBlock();
        applyEmphasis();
        notifyState();
      });
      timeBlockEl.querySelector('[data-role="time-play"]')?.addEventListener('click', () => {
        if (epi.playTimer) { stopPlay(); renderTimeBlock(); return; }
        const width = epi.brush ? epi.brush.b - epi.brush.a : span;
        const slide = Math.max(1, span - width);
        let step = 0;
        epi.brush = { a: td.minStart, b: td.minStart + width };
        epi.playTimer = setInterval(() => {
          step++;
          if (step >= 40) { stopPlay(); renderTimeBlock(); return; }
          const start = td.minStart + (slide * step) / 40;
          epi.brush = { a: Math.round(start), b: Math.round(start + width) };
          renderTimeBlock();
          applyEmphasis();
        }, 350);
        renderTimeBlock();
      });
    }
    function stopPlay() {
      if (epi.playTimer) { clearInterval(epi.playTimer); epi.playTimer = null; }
    }

    function renderRootBlock() {
      if (!rootBlockEl) return;
      const eff = effectiveRoot();
      const statusText = displayRoot
        ? (displayRoot.method === 'midpoint' ? '根：midpoint（显示用，非推断）' : `根：用户选择（分支 ${selectedBranchLabel}）`)
        : eff.status === 'rooted'
          ? `根：输入（已定义根${eff.method ? ` · ${eff.method}` : ''}）`
          : '根：输入（无根，显示用任意根）';
      const canReroot = !!selectedNode && selectedNode !== tree.root;
      const midpointOk = hasBranchLengths;
      rootBlockEl.innerHTML = `
        <div class="blk-head"><span class="t">根 · Root</span></div>
        <p class="gene-note" data-role="root-status">${escapeHtml(statusText)}</p>
        <div class="ring-actions">
          <button type="button" data-role="root-branch" ${canReroot ? '' : 'disabled'}>以选中分支为根</button>
          <button type="button" data-role="root-midpoint" ${midpointOk ? '' : 'disabled'}>Midpoint 根</button>
          <button type="button" data-role="root-restore" ${displayRoot ? '' : 'disabled'}>恢复原始根</button>
        </div>
        ${midpointOk ? '' : '<p class="gene-note">Midpoint 不可用：树没有分支长度。</p>'}
        ${canReroot ? '' : '<p class="gene-note">选中一个非根节点后可对其分支改根。</p>'}`;
      rootBlockEl.querySelector('[data-role="root-branch"]')?.addEventListener('click', () => {
        if (!selectedNode || selectedNode === tree.root) return;
        applyReroot(nodePath(currentRaw, selectedNode.id), 0.5, 'user', branchLabelOf(selectedNode));
      });
      rootBlockEl.querySelector('[data-role="root-midpoint"]')?.addEventListener('click', () => {
        try {
          const { path, t } = midpointRoot(currentRaw);
          applyReroot(path, t, 'midpoint', 'midpoint');
        } catch (error) {
          rootBlockEl.querySelector('[data-role="root-status"]').textContent = error.message;
        }
      });
      rootBlockEl.querySelector('[data-role="root-restore"]')?.addEventListener('click', () => {
        if (!displayRoot) return;
        currentRaw = originalRaw;
        displayRoot = null;
        rootOps.length = 0;
        rerender();
        notifyState();
      });
    }

    const leafNamesUnder = node => {
      const names = [];
      (function walk(n) {
        if (!n.children.length) names.push(n.name);
        n.children.forEach(walk);
      })(node);
      return names;
    };
    const branchLabelOf = node => {
      if (!node.children.length) return node.name;
      const names = leafNamesUnder(node);
      return `${node.leafCount} 叶 clade（${names[0]} … ${names[names.length - 1]}）`;
    };

    function rerender() {
      rebuildLayouts();
      selectedNode = null;
      constellation?.clearSelection?.();
      build();
      renderRootBlock();
    }

    function applyReroot(path, t, method, branchLabel) {
      currentRaw = rerootTree(currentRaw, path, t);
      displayRoot = { method };
      selectedBranchLabel = branchLabel;
      rootOps.push({ path, t, method, label: branchLabel });
      rerender();
      notifyState();
    }

    const rootFootnote = () => {
      const eff = effectiveRoot();
      if (displayRoot?.method === 'midpoint') return '当前根为 midpoint 显示根，非推断结果。';
      if (displayRoot) return '当前根为用户选择的显示根，改根不改变无根拓扑与分支长度。';
      return eff.status === 'rooted' ? '' : '输入未声明有根树：根距与顶层 clade 从任意根起算。';
    };

    return {
      getState: () => ({
        rootOps: rootOps.map(op => ({ ...op })),
        epi: {
          clustersOn: epi.clusterOn,
          threshold: epi.threshold,
          focusedCluster: epi.focus >= 0 ? epi.focus : null,
          timeField: epi.timeField,
          window: brushActive() ? [epi.brush.a, epi.brush.b] : null,
          playing: false,
        },
        rings: {
          matrices: Object.fromEntries(Object.entries(ringsState.matrices)
            .map(([k, c]) => [k, { ...c, include: [...c.include], exclude: [...c.exclude] }])),
          fieldRings: [...ringsState.fieldRings],
          leaders: ringsState.leaders,
          highlight: ringsState.highlight ? { ...ringsState.highlight } : null,
        },
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
      setState: (saved) => {
        const warnings = [];
        if (!saved || typeof saved !== 'object') return warnings;
        // 1) replay reroot ops from the original tree
        rootOps.length = 0;
        const ops = Array.isArray(saved.rootOps) ? saved.rootOps : [];
        const replay = replayRootOps(originalRaw, ops);
        currentRaw = replay.tree;
        warnings.push(...replay.warnings);
        displayRoot = replay.applied
          ? { method: ops[replay.applied - 1].method || 'user' } : null;
        selectedBranchLabel = displayRoot
          ? (ops[replay.applied - 1].label || ops[replay.applied - 1].method || 'user') : null;
        for (const op of ops.slice(0, replay.applied)) rootOps.push({ ...op });
        // 2) epi settings
        const e2 = saved.epi || {};
        if (typeof e2.clustersOn === 'boolean') epi.clusterOn = e2.clustersOn;
        if (Number.isFinite(e2.threshold)) {
          const maxSlider = Math.max(0, Math.min(Math.floor(maxDistance), 200));
          epi.threshold = Math.max(0, Math.min(maxSlider, e2.threshold));
        }
        if (e2.timeField && dateFields.some(f => f.key === e2.timeField) && timeData(e2.timeField)) {
          epi.timeField = e2.timeField;
        } else if (e2.timeField) warnings.push(`未知时间字段：${e2.timeField}`);
        if (Array.isArray(e2.window)) {
          const td = epi.timeField && timeData(epi.timeField);
          if (td) {
            epi.brush = {
              a: Math.max(td.minStart, Math.min(td.maxEnd, e2.window[0])),
              b: Math.max(td.minStart, Math.min(td.maxEnd, e2.window[1])),
            };
          }
        }
        epi.focus = Number.isInteger(e2.focusedCluster) && e2.focusedCluster >= 0
          ? e2.focusedCluster : -1;
        // 3) rings (hidden for now — state kept for forward compat, no warnings)
        const rs = saved.rings || {};
        if (rs.matrices && typeof rs.matrices === 'object') {
          for (const [mid, cfg] of Object.entries(rs.matrices)) {
            if (!ringsState.matrices[mid]) { if (RINGS_ENABLED) warnings.push(`未知矩阵环：${mid}`); continue; }
            const dst = ringsState.matrices[mid];
            if (typeof cfg.on === 'boolean') dst.on = cfg.on;
            if (['group', 'prev', 'name'].includes(cfg.sort)) dst.sort = cfg.sort;
            if (Number.isFinite(cfg.minPrev)) dst.minPrev = Math.max(0, Math.min(50, cfg.minPrev));
            if (Number.isFinite(cfg.maxCols)) dst.maxCols = Math.max(5, Math.min(200, cfg.maxCols));
            if (Array.isArray(cfg.include)) dst.include = cfg.include.filter(c => matrices.find(m => m.id === mid)?.columns.some(col => col.id === c));
            if (Array.isArray(cfg.exclude)) dst.exclude = cfg.exclude.filter(c => matrices.find(m => m.id === mid)?.columns.some(col => col.id === c));
          }
        }
        if (Array.isArray(rs.fieldRings)) {
          ringsState.fieldRings = rs.fieldRings.filter(k => categoricalFields.includes(k)).slice(0, 3);
        }
        if (typeof rs.leaders === 'boolean') ringsState.leaders = rs.leaders;
        ringsState.highlight = null;
        if (rs.highlight && typeof rs.highlight === 'object') {
          const hl = rs.highlight;
          const valid = hl.ring?.startsWith('field:')
            ? categoricalFields.includes(hl.column)
            : matrices.find(m => m.id === hl.ring)?.columns.some(c => c.id === hl.column);
          if (valid) ringsState.highlight = { ring: hl.ring, column: hl.column, value: hl.value };
          else if (RINGS_ENABLED) warnings.push(`无效环高亮：${hl.ring}/${hl.column}`);
        }
        // 4) metadata / matrix filter
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
            if (!c || typeof c !== 'object') { warnings.push('无效筛选条件'); continue; }
            if (c.source === 'matrix'
              ? !(typeof c.matrix === 'string' && typeof c.column === 'string' && ['pos', 'neg', 'untested'].includes(c.op))
              : !(typeof c.field === 'string' && typeof c.op === 'string')) {
              warnings.push('无效筛选条件'); continue;
            }
            filterState.conditions.push({ ...c });
          }
        }
        applyFilter();
        stopPlay();
        rerender();
        renderClusterBlock();
        renderTimeBlock();
        renderRingsBlock();
        filterUi?.render();
        return warnings;
      },
      debug: () => ({ state: { ...state }, fields, leaves: tree.leafCount, root: effectiveRoot(), ringTimings, updateMs: frameUpdateMs, tableMs: matchTable?.lastMs || 0, ...constellation.debug() }),
      stats: () => {
        const summary = v2.summary || {};
        const rows = [
          { label: '叶节点 / Taxa', value: tree.leafCount },
          { label: '内节点', value: tree.nodes.length - tree.leafCount },
          { label: '最大根距', value: `${tree.maxDepth.toFixed(3)} ${branchUnit}` },
          { label: '元数据字段', value: fields.categorical.length + fields.numeric.length },
        ];
        if (dist) rows.push({ label: '距离样本', value: dist.n });
        if (dateFields.length) rows.push({ label: '日期字段', value: dateFields.length });
        if (summary.n_snp_sites !== null && summary.n_snp_sites !== undefined) rows.push({ label: '核心 SNP 位点', value: summary.n_snp_sites });
        if (summary.n_loci) rows.push({ label: 'cgMLST 位点', value: summary.n_loci });
        if (summary.scheme) rows.push({ label: '分型方案', value: summary.scheme });
        if (summary.organism) rows.push({ label: '物种', value: summary.organism });
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
        const t0 = performance.now();
        constellation.update(dt);
        frameUpdateMs = frameUpdateMs * 0.9 + (performance.now() - t0) * 0.1;
      },
      dispose: () => { stopPlay(); disposeRings(); constellation?.dispose(); constellation = null; },
      select: payload => {
        if (payload?.type === 'ring') {
          // ring cell click: toggle column highlight + select the leaf
          toggleRingHighlight(payload.ring, payload.column,
            payload.ring.startsWith('field:') ? recordOf(tree.nodes[payload.leaf])[payload.column] : 1);
          const leaf = tree.nodes[payload.leaf];
          selectedNode = leaf;
          constellation.selectNode(leaf.id, calloutFor(leaf));
          renderRootBlock();
          renderRingsBlock();
          host.notifyStateChange?.();
          return;
        }
        const node = getNode(payload);
        selectedNode = node;
        if (node) constellation.selectNode(node.id, calloutFor(node));
        else constellation.clearSelection();
        renderRootBlock();
        matchTable?.highlight(node?.id ?? -1);
      },
      hover: payload => constellation.hoverNode(getNode(payload)?.id ?? -1),
      mountSidebar: el => {
        sidebarEl = el;
        el.innerHTML = `
          <div class="blk" data-role="root-blk"></div>
          <div class="blk" data-role="filter-blk"></div>
          <div class="blk" data-role="cluster-blk"></div>
          <div class="blk" data-role="time-blk"></div>
          <div class="blk" data-role="rings-blk"></div>
          <div class="blk mst-search-blk">
            <input class="mst-search" type="search" placeholder="搜索叶节点 / 元数据…" aria-label="搜索叶节点">
            <div class="mst-search-results"></div>
          </div>
          <div data-role="constellation-side"></div>`;
        rootBlockEl = el.querySelector('[data-role="root-blk"]');
        renderRootBlock();
        createFilterBlock(el.querySelector('[data-role="filter-blk"]'));
        clusterBlockEl = el.querySelector('[data-role="cluster-blk"]');
        if (dist && distCoverage >= 2) renderClusterBlock();
        timeBlockEl = el.querySelector('[data-role="time-blk"]');
        if (epi.timeField) renderTimeBlock();
        ringsBlockEl = el.querySelector('[data-role="rings-blk"]');
        renderRingsBlock();
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
                <span>${escapeHtml(recordOf(hit.leaf).st || recordOf(hit.leaf).ST || 'leaf')}${hit.r[1] ? ` · ${escapeHtml(hit.r[1])}` : ''}</span>
              </button>`).join('')
            : '<p class="gene-note">无匹配叶节点</p>';
        });
        out.addEventListener('click', event => {
          const btn = event.target.closest('[data-node]');
          if (!btn) return;
          const id = Number(btn.dataset.node);
          const node = tree.nodes[id];
          if (!node) return;
          host.select?.({ type: 'node', id: node.id });
          const position = constellation.nodePosition(node.id);
          if (position) host.flyTo(position.clone().add(new THREE.Vector3(0, 3.2, 7.5)), position);
        });
      },
      mountPanel: el => {
        panelEl = el;
        createPanel(el);
      },
      focus: payload => {
        const node = getNode(payload);
        if (!node) return;
        const position = constellation.nodePosition(node.id);
        host.flyTo(position.clone().add(new THREE.Vector3(0, 3.2, 7.5)), position);
      },
      selectionLabel: payload => {
        const node = getNode(payload);
        if (!node) return '未命名';
        if (node.name) return node.name;
        if (node.raw?.support) return `支持值 ${node.raw.support.values.map(v => v ?? '–').join('/')}`;
        return node.children.length ? '祖先节点' : '未命名';
      },
      tooltip: payload => {
        if (payload?.type === 'ring') {
          const leaf = tree.nodes[payload.leaf];
          const spec = ringCellsMeta?.specById.get(payload.ring);
          let value, group = '';
          if (spec?.matrix) {
            const idx = spec.matrix.columns.findIndex(c => c.id === payload.column);
            const row = spec.matrix.rows?.[leaf.name];
            const v = row ? row[idx] : null;
            value = v === 1 ? '有' : v === 0 ? '无' : '未检测';
            group = spec.matrix.columns[idx]?.group || '';
          } else {
            value = recordOf(leaf)[payload.column] ?? '未检测';
          }
          return `<div class="tt-name">${escapeHtml(leaf.name)} · ${escapeHtml(spec?.kind === 'field' ? spec.label : payload.column)}</div>
            <div class="tt-sub">${escapeHtml(String(value))}${group ? ` · ${escapeHtml(group)}` : ''}</div>`;
        }
        const node = getNode(payload);
        if (!node) return '';
        const meta = recordOf(node);
        const pairs = supportPairs(node);
        const tag = state.color && state.color !== 'clade' && !node.children.length ? ` · ${fieldLabel(state.color)}: ${meta[state.color] ?? MISSING}` : '';
        return `<div class="tt-name">${escapeHtml(node.name || (node === tree.root ? 'root' : (pairs ? `支持值 ${supportText(node)}` : '内部节点')))}</div>
          <div class="tt-sub">${node.children.length ? `${node.leafCount} 个后代叶节点` : `${escapeHtml(meta.st || meta.ST || '样本')}${escapeHtml(tag)}${clusterTag(node)}`}</div>
          ${pairs && !node.raw?.rootSplitTwin ? `<div class="tt-sub">${escapeHtml(pairs.join(' · '))}</div>` : ''}
          <div class="tt-sub">分支 ${node.branchLength.toFixed(4)} ${escapeHtml(branchUnit)} · 根距 ${node.depth.toFixed(4)} · 双击聚焦</div>`;
      },
      inspect: payload => {
        const node = getNode(payload);
        if (!node) return '';
        const pairs = supportPairs(node);
        const title = node.name || (node === tree.root ? 'root' : `内部节点 ${node.id}`);
        const clade = cladeKey.get(node.id);
        return `<div class="detail-title">${escapeHtml(title)}</div>
          <p class="detail-subtitle">${node.children.length ? `包含 ${node.leafCount} 个叶节点的祖先分支` : '终端样本 / Operational taxonomic unit'}</p>
          <div class="metric-grid">
            <div><span>分支长度（${escapeHtml(branchUnit)}）</span><b>${node.branchLength.toFixed(4)}</b></div>
            <div><span>累计根距</span><b>${node.depth.toFixed(4)}</b></div>
            <div><span>后代叶节点</span><b>${node.leafCount}</b></div>
            <div><span>${escapeHtml(fieldLabel(state.color) || '类别')}</span><b>${escapeHtml(clade || '跨类别')}</b></div>
            ${rooted() ? `<div><span>顶层 clade</span><b>${escapeHtml(topClade.get(node.id) || '—')}</b></div>` : ''}
            ${pairs ? `<div><span>支持值</span><b>${escapeHtml(pairs.join(' · '))}</b></div>` : ''}
          </div>
          ${node.children.length ? '' : `<details class="insp-sec" open><summary>元数据</summary><dl class="kv">${recordRows(recordOf(node)) || '<dt>—</dt><dd>宿主未提供</dd>'}</dl></details>`}
          ${!node.children.length && matrices.length ? `<details class="insp-sec"><summary>矩阵</summary>${matrices.map(m => {
            const row = m.rows?.[node.name];
            if (!row) return `<p class="detail-subtitle">${escapeHtml(m.label || m.id)}：未检测</p>`;
            const present = row.map((v, i) => v === 1 ? m.columns[i].id : null).filter(Boolean);
            const nulls = row.filter(v => v === null || v === undefined).length;
            return `<p class="detail-subtitle">${escapeHtml(m.label || m.id)}：携带 ${present.length} · 未检测 ${nulls}</p>
              <dl class="kv">${present.map(g => `<dt>${escapeHtml(g)}</dt><dd>有</dd>`).join('') || '<dt>—</dt><dd>无携带基因</dd>'}</dl>`;
          }).join('')}</details>` : ''}
          ${!node.children.length && dist ? `<details class="insp-sec" open><summary>距离 · ${escapeHtml(distUnitLabel)}</summary>
            ${clusterOfLeaf(node) !== null ? `<p class="detail-subtitle">簇 ${clusterOfLeaf(node) + 1}（阈值 ${epi.threshold} ${escapeHtml(distUnitLabel)}）</p>` : ''}
            ${epi.clusterOn ? `<p class="detail-subtitle">≤ 阈值 ${epi.threshold} 的样本：${nearestSamples(dist, node.name, dist.n).filter(r => r.value <= epi.threshold).length}</p>` : ''}
            <dl class="kv">${nearestSamples(dist, node.name, 5).map(r => `<dt>${escapeHtml(r.name)}</dt><dd>${r.value} ${escapeHtml(distUnitLabel)}</dd>`).join('') || '<dt>—</dt><dd>无距离数据</dd>'}</dl>
          </details>` : ''}
          <p class="detail-footnote">拓扑与分支长度直接来自输入 Newick（${escapeHtml(branchUnit)}）。${escapeHtml(encoded.note)} ${escapeHtml(rootFootnote())}${mstDerived ? ' 由 MST 转换的树，非系统发育推断。' : ''} 内部节点：后代全属同一类别时归入该类别，高度取后代叶节点的平均值（结构距离模式下取自身根距）。光效不承载生物学含义。</p>`;
      },
    };
  },
};
