import * as THREE from '../vendor/three.module.js';
import { makeLabel, escapeHtml, formatBp, disposeHierarchy } from '../framework/primitives.js';
import { clamp } from '../framework/algorithms.js';

// Categorical palette grouped by COG functional family, tuned for the dark
// canvas: information = cool blue/violet, cellular = teal/cyan, metabolism =
// warm yellow/orange/lime, poorly characterised = neutral slate. Within a
// family hues are spaced enough to stay distinguishable at 1 px ring width.
const COG_COLORS = {
  // information storage & processing
  J:'#60A5FA', A:'#818CF8', K:'#A78BFA', L:'#8B5CF6', B:'#64748B',
  // cellular processes & signalling
  M:'#2DD4BF', D:'#22D3EE', N:'#34D399', O:'#10B981', T:'#0EA5E9',
  U:'#38BDF8', V:'#C084FC', W:'#94A3B8', Y:'#CBD5E1', Z:'#475569',
  // metabolism (warm band, intentionally not green/blue)
  C:'#FDE047', E:'#FBBF24', F:'#F59E0B', G:'#FB923C', H:'#FDBA74',
  I:'#EAB308', P:'#A3E635', Q:'#84CC16',
  // poorly characterised
  R:'#A8A29E', S:'#78716C', X:'#D8B4FE',
};
const KIND_COLORS = {
  // 与上游 demo 的 CAT 调色板一致：无 COG 的 CDS 是暗灰，而不是亮蓝。
  amr:'#FF4D6D', vir:'#FF9F43', cds:'#4B5563', trna:'#22D3EE', rrna:'#34D399',
  ncrna:'#67E8F9', tmrna:'#5EEAD4', sorf:'#94A3B8', pseudogene:'#475569', unknown:'#334155',
};
const CATEGORY_LABELS = {
  amr:'CARD 耐药', vir:'VFDB 毒力', cds:'CDS', trna:'tRNA', rrna:'rRNA',
  tmrna:'tmRNA', ncrna:'ncRNA', sorf:'sORF', pseudogene:'假基因', unknown:'未注释',
  // COG 类别使用 demo 的具体功能名称，而不是只显示字母。
  J:'翻译/核糖体', A:'RNA 加工', K:'转录', L:'复制/修复', B:'染色质',
  M:'细胞壁/膜', D:'细胞周期/分裂', N:'细胞运动', O:'翻译后修饰/伴侣',
  T:'信号转导', U:'分泌/运输', V:'防御机制', W:'胞外结构', Y:'核结构', Z:'细胞骨架',
  C:'能量产生', E:'氨基酸代谢', F:'核苷酸代谢', G:'糖类代谢', H:'辅酶代谢',
  I:'脂类代谢', P:'无机离子转运', Q:'次级代谢产物',
  R:'仅一般功能预测', S:'功能未知', X:'可移动元件',
};

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

function ring(reference, z, color = '#3d4d75', opacity = 0.35, cx = 0, cy = 0) {
  const points = [];
  for (let i = 0; i <= 360; i++) {
    const angle = i / 360 * Math.PI * 2;
    points.push(new THREE.Vector3(cx + Math.cos(angle) * reference, cy - Math.sin(angle) * reference, z));
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

const _COMPLEMENT = { A:'T', T:'A', G:'C', C:'G', N:'N', a:'t', t:'a', g:'c', c:'g', n:'n' };
const _CODON = {
  TTT:'F',TTC:'F',TTA:'L',TTG:'L',TCT:'S',TCC:'S',TCA:'S',TCG:'S',TAT:'Y',TAC:'Y',TAA:'*',TAG:'*',TGT:'C',TGC:'C',TGA:'*',TGG:'W',
  CTT:'L',CTC:'L',CTA:'L',CTG:'L',CCT:'P',CCC:'P',CCA:'P',CCG:'P',CAT:'H',CAC:'H',CAA:'Q',CAG:'Q',CGT:'R',CGC:'R',CGA:'R',CGG:'R',
  ATT:'I',ATC:'I',ATA:'I',ATG:'M',ACT:'T',ACC:'T',ACA:'T',ACG:'T',AAT:'N',AAC:'N',AAA:'K',AAG:'K',AGT:'S',AGC:'S',AGA:'R',AGG:'R',
  GTT:'V',GTC:'V',GTA:'V',GTG:'V',GCT:'A',GCC:'A',GCA:'A',GCG:'A',GAT:'D',GAC:'D',GAA:'E',GAG:'E',GGT:'G',GGC:'G',GGA:'G',GGG:'G',
};
function revcomp(seq) {
  let out = '';
  for (let i = seq.length - 1; i >= 0; i--) out += (_COMPLEMENT[seq[i]] ?? 'N');
  return out;
}
function translate(seq) {
  const aa = [];
  for (let i = 0; i + 3 <= seq.length; i += 3) {
    let value = _CODON[seq.slice(i, i + 3)] ?? 'X';
    if (i === 0) value = 'M';
    aa.push(value);
  }
  return aa;
}
function sequenceOf(data, feature) {
  const replicon = data.replicons.find(item => item.id === feature.contig || item.name === feature.contig);
  if (!replicon?.sequence) return null;
  const raw = replicon.sequence.slice(feature.start, feature.end);
  return feature.strand === '-' ? revcomp(raw) : raw;
}
function renderSequenceHtml(seq, feature, aa) {
  const PER = 30;
  let html = '<div class="seq-scroll">';
  for (let i = 0; i < seq.length; i += PER) {
    const chunk = seq.slice(i, i + PER);
    const pos = feature.strand === '+' ? feature.start + i + 1 : feature.end - i;
    let bases = '';
    for (let j = 0; j < chunk.length; j++) {
      const b = chunk[j];
      const gi = i + j;
      const first = gi < 3, last = gi >= seq.length - 3;
      const cls = `b-${b}${first ? ' b-start' : ''}${last ? ' b-stop' : ''}`;
      if (j % 3 === 0) bases += `<span class="b3 ${cls}">`;
      bases += b;
      if (j % 3 === 2) bases += '</span>';
    }
    html += `<div class="seq-row"><span class="seq-pos">${pos.toLocaleString('en-US')}</span><span class="seq-bases">${bases}</span></div>`;
    if (aa) {
      const line = aa.slice(i / 3, i / 3 + PER / 3).join(' ');
      html += `<div class="seq-row"><span class="seq-pos"></span><span class="seq-aa">${line}</span></div>`;
    }
  }
  html += '</div>';
  return html;
}
function featureInspectHtml(feature, data) {
  const tag = CATEGORY_LABELS[feature.flag || feature.category] || feature.category || '—';
  const color = featureColor(feature);
  const seq = sequenceOf(data, feature);
  const coding = feature.kind === 'cds';
  const aa = coding && seq ? translate(seq) : null;
  const gc = seq
    ? (100 * [...seq].filter(base => base === 'G' || base === 'C').length / Math.max(1, seq.length)).toFixed(1)
    : null;
  const list = (values, label) => values?.length
    ? `<dl class="kv"><dt>${label}</dt><dd>${values.map(value => escapeHtml(value)).join(', ')}</dd></dl>` : '';
  return `<div class="gene-name">${escapeHtml(feature.gene || feature.locus || feature.id)}
      <span class="strand">· ${escapeHtml(feature.strand)}</span>
      <span class="badge" style="color:${color};border-color:${color}55;background:${color}14">${escapeHtml(tag)}</span></div>
    <p class="gene-product">${escapeHtml(feature.product || '（未注释 / unannotated）')}</p>
    <div class="gauges"><div class="gauge-stats">
      <div class="g"><span>长度</span><b>${formatBp(feature.end - feature.start)}</b></div>
      <div class="g"><span>${coding ? 'aa' : '类型'}</span><b>${aa ? aa.length : escapeHtml(feature.kind)}</b></div>
      <div class="g"><span>GC</span><b>${gc === null ? '—' : `${gc}%`}</b></div>
      <div class="g"><span>链</span><b>${escapeHtml(feature.strand)}</b></div>
    </div></div>
    <dl class="kv">
      <dt>locus_tag</dt><dd>${escapeHtml(feature.locus || '—')}</dd>
      <dt>COG</dt><dd>${escapeHtml(CATEGORY_LABELS[feature.category] || feature.category || '—')}</dd>
      <dt>复制子</dt><dd>${escapeHtml(feature.contig)}</dd>
      <dt>位置</dt><dd>${(feature.start + 1).toLocaleString('en-US')} – ${feature.end.toLocaleString('en-US')}</dd>
      <dt>protein_id</dt><dd>${escapeHtml(feature.protein_id || '—')}</dd>
      <dt>Preferred name</dt><dd>${escapeHtml(feature.preferred_name || '—')}</dd>
    </dl>
    ${list(feature.ec, 'EC')}${list(feature.kegg_ko, 'KEGG KO')}${list(feature.kegg_pathways, 'KEGG pathway')}${list(feature.pfams, 'PFAM')}${list(feature.go?.slice(0, 8), 'GO')}${list(feature.eggnog_ogs?.slice(0, 5), 'eggNOG OGs')}
    <div class="sec-label">碱基序列 · ${coding ? 'Bases + 翻译' : 'Bases'}</div>
    ${seq ? renderSequenceHtml(seq, feature, aa) : '<p class="empty">该复制子未携带序列（结果包超过载荷上限）。</p>'}
    <p class="detail-footnote">Contigs 按 draft circular layout 排列：弧长与 contig 长度成比例，布局不声明任何 contig 已闭合。</p>`;
}

function featureColor(feature) {
  if (feature.flag) return KIND_COLORS[feature.flag];
  return KIND_COLORS[feature.category] || COG_COLORS[feature.category] || KIND_COLORS.unknown;
}

/**
 * Draft layout: when the payload contains only linear contigs (a Bakta
 * annotated draft assembly), treat the assembly as ONE replicon and render a
 * shared ring of length-proportional contig arcs — the same "draft circular
 * layout" convention as the assembly view, with a user-defined minimum contig
 * threshold (default 10 kb) and contigs sorted from large to small.
 */
function createDraftView({ root, data, host, registerPickable, contigs }) {
  const sorted = contigs.slice().sort((a, b) => b.length - a.length);
  const featureById = new Map(data.features.map(feature => [feature.id, feature]));
  const radius = { plusIn: 5.25, plusOut: 6.45, minusIn: 4.05, minusOut: 5.25 };

  let thresholdKb = 10;
  let categorySelection = null;  // null = 全部；Set 为空 = 全不选
  let showGc = true, showLabels = true;
  let selected = null;
  let sidebarEl = null;
  let activeContig = null;
  let ringContigs = [], ringFeatures = 0;
  const promoted = new Set();      // 用户声明成环的 contig id
  const ringSelection = new Set(); // 圈图列表里的待成环选择
  const dynamicPickables = [];
  const layoutGroup = new THREE.Group();
  layoutGroup.name = 'draft-ring';
  root.add(layoutGroup);
  const selectionGroup = new THREE.Group();
  selectionGroup.name = 'draft-selection';
  root.add(selectionGroup);
  let selectedLabel = null, selectedLine = null;

  function addPickable(object, payload) {
    dynamicPickables.push(object);
    return registerPickable(object, payload);
  }

  function clearSelectionMarker() {
    disposeHierarchy(selectionGroup);
    selectionGroup.clear();
    selectedLabel = null;
    selectedLine = null;
  }

  function showSelectionMarker(record) {
    clearSelectionMarker();
    const matrix = new THREE.Matrix4();
    record.mesh.getMatrixAt(record.instanceId, matrix);
    const target = new THREE.Vector3().setFromMatrixPosition(matrix);
    const radial = target.clone().setZ(0).normalize();
    const labelPos = target.clone().add(radial.multiplyScalar(1.15)).add(new THREE.Vector3(0, 0.85, 0.65));
    selectedLine = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints([target, labelPos]),
      new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.65 }),
    );
    selectedLabel = makeLabel(record.feature.gene || record.feature.locus || record.feature.id, {
      color: '#ffffff', height: 0.34, fontSize: 22, align: 'center',
    });
    selectedLabel.position.copy(labelPos);
    selectionGroup.add(selectedLine, selectedLabel);
  }

  function clearSelection() {
    clearSelectionMarker();
    if (!selected) return;
    selected.mesh.setColorAt(selected.instanceId, selected.color);
    selected.mesh.instanceColor.needsUpdate = true;
    if (selected.baseMatrix) {
      selected.mesh.setMatrixAt(selected.instanceId, selected.baseMatrix);
      selected.mesh.instanceMatrix.needsUpdate = true;
      selected.baseMatrix = null;
    }
    selected = null;
    syncSidebarSelection();
  }

  function selectPayload(payload) {
    clearSelection();
    if (!payload) return;
    const record = featureById.get(payload.id)?.record;
    if (!record) return;
    selected = record;
    record.mesh.setColorAt(record.instanceId, new THREE.Color('#ffffff'));
    record.mesh.instanceColor.needsUpdate = true;
    // demo 行为：选中的基因方块沿径向弹出一段并抬高，避免只靠颜色变化。
    const matrix = new THREE.Matrix4();
    record.mesh.getMatrixAt(record.instanceId, matrix);
    record.baseMatrix = matrix.clone();
    const position = new THREE.Vector3().setFromMatrixPosition(matrix);
    const radial = position.clone().setZ(0).normalize();
    matrix.setPosition(
      position.clone().add(radial.multiplyScalar(0.45)).add(new THREE.Vector3(0, 0, 0.45)),
    );
    matrix.scale(new THREE.Vector3(1.28, 1.28, 1.28));
    record.mesh.setMatrixAt(record.instanceId, matrix);
    record.mesh.instanceMatrix.needsUpdate = true;
    showSelectionMarker(record);
    syncSidebarSelection();
  }

  function clearLayout() {
    clearSelection();
    for (const object of dynamicPickables) host.unregisterPickable(object);
    dynamicPickables.length = 0;
    disposeHierarchy(layoutGroup);
  }

  const truncText = (text, n) => {
    const value = String(text ?? '');
    return value.length > n ? `${value.slice(0, n - 1)}…` : value;
  };

  function syncSidebarSelection() {
    if (!sidebarEl) return;
    const id = selected?.feature?.id || '';
    sidebarEl.querySelectorAll('.gene-row').forEach(btn =>
      btn.classList.toggle('on', btn.dataset.id === id));
  }

  function renderRingList() {
    if (!sidebarEl) return;
    const box = sidebarEl.querySelector('[data-role="ring"]');
    if (!box) return;
    const counts = new Map();
    for (const feature of data.features) counts.set(feature.contig, (counts.get(feature.contig) || 0) + 1);
    box.innerHTML = ringContigs.map((contig, index) => `
      <label class="rep-row${activeContig === contig.id ? ' on' : ''}${promoted.has(contig.id) ? ' promoted' : ''}" data-id="${escapeHtml(contig.id)}">
        <input type="checkbox" data-ring="${escapeHtml(contig.id)}"${ringSelection.has(contig.id) ? ' checked' : ''}>
        <span class="rname"><span data-filter="${escapeHtml(contig.id)}">${escapeHtml(truncText(contig.name || contig.id, 22))}</span><span class="rlen">${formatBp(contig.length)}</span></span>
        <span class="rmeta"><span>#${index + 1}</span><span><b>${counts.get(contig.id) || 0}</b> features</span>${promoted.has(contig.id) ? '<span class="hot"><b>●</b> CIRCULAR</span>' : ''}</span>
      </label>`).join('');
    box.querySelectorAll('input[data-ring]').forEach(input => input.addEventListener('change', () => {
      if (input.checked) ringSelection.add(input.dataset.ring);
      else ringSelection.delete(input.dataset.ring);
      syncRingActions();
    }));
    // Row body click keeps the original behavior: filter the site list to this
    // contig. Only the checkbox participates in the 成环 selection.
    box.querySelectorAll('.rep-row').forEach(row => row.addEventListener('click', event => {
      if (event.target.matches('input[type="checkbox"]')) return;
      event.preventDefault();
      activeContig = activeContig === row.dataset.id ? null : row.dataset.id;
      renderRingList();
      renderSiteList();
    }));
  }

  function syncRingActions() {
    if (!sidebarEl) return;
    const promoteBtn = sidebarEl.querySelector('[data-role="promote"]');
    const restoreBtn = sidebarEl.querySelector('[data-role="restore"]');
    const hint = sidebarEl.querySelector('[data-role="ring-hint"]');
    if (promoteBtn) {
      promoteBtn.disabled = ringSelection.size === 0;
      promoteBtn.textContent = ringSelection.size ? `成环 (${ringSelection.size})` : '成环';
    }
    if (restoreBtn) restoreBtn.disabled = promoted.size === 0;
    if (hint) {
      hint.textContent = promoted.size
        ? `已声明 ${promoted.size} 个环状 replicon；未成环的 contigs 仍按 draft 环排列`
        : '勾选完整环状染色体/质粒后点「成环」；它们将各自渲染为闭合环';
    }
  }

  function promoteSelected() {
    let changed = false;
    for (const id of ringSelection) {
      if (!promoted.has(id)) {
        promoted.add(id);
        changed = true;
      }
    }
    ringSelection.clear();
    if (changed) {
      clearLayout();
      render();
      // reframe so every promoted ring clears the side panels
      host.setCamera(new THREE.Vector3(0, 6.5, 34), new THREE.Vector3(0, -1.5, 0));
    } else {
      renderRingList();
      syncRingActions();
    }
  }

  function restoreRings() {
    if (!promoted.size) return;
    promoted.clear();
    ringSelection.clear();
    clearLayout();
    render();
    host.setCamera(new THREE.Vector3(5.5, 4.8, 22.5), new THREE.Vector3(0, 0, 0));
  }

  function renderSiteList() {
    if (!sidebarEl) return;
    const box = sidebarEl.querySelector('[data-role="sites"]');
    const countEl = sidebarEl.querySelector('[data-role="site-count"]');
    if (!box || !countEl) return;
    const q = (sidebarEl.querySelector('[data-role="search"]')?.value || '').trim().toLowerCase();
    const onRing = new Set(ringContigs.map(contig => contig.id));
    let pool = data.features.filter(feature =>
      onRing.has(feature.contig) && (!activeContig || feature.contig === activeContig));
    const total = pool.length;
    if (q) {
      pool = pool.filter(feature =>
        [feature.gene, feature.locus, feature.product, feature.contig,
          CATEGORY_LABELS[feature.flag || feature.category]]
          .some(value => String(value ?? '').toLowerCase().includes(q)));
    }
    countEl.textContent = q ? `${pool.length}/${total}` : `${total}`;
    const MAX_ROWS = 220;
    const rows = pool.slice(0, MAX_ROWS);
    box.innerHTML = rows.map((feature, index) => {
      const color = featureColor(feature);
      const tag = CATEGORY_LABELS[feature.flag || feature.category] || feature.category || '—';
      return `<button class="gene-row" data-id="${escapeHtml(feature.id)}">
        <span class="idx">${String(index + 1).padStart(2, '0')}</span>
        <span class="gr-main">
          <b><span style="color:${color}">|</span> ${escapeHtml(feature.gene || feature.locus || feature.id)}</b>
          <em>${escapeHtml(truncText(feature.product || tag, 46))}</em>
        </span>
        <span class="tag" style="color:${color}">${escapeHtml(tag)}</span>
      </button>`;
    }).join('') + (pool.length > MAX_ROWS
      ? `<div class="gene-note">仅显示前 ${MAX_ROWS} 条（共 ${pool.length}）· 可用搜索缩小</div>`
      : (rows.length ? '' : '<div class="gene-note">当前范围内没有匹配的基因</div>'));
    box.querySelectorAll('.gene-row').forEach(btn => btn.addEventListener('click', () => {
      const payload = { type: 'feature', id: btn.dataset.id };
      selectPayload(payload);
      const target = payloadPosition(payload);
      if (target) host.flyTo(target.clone().multiplyScalar(1.28).setZ(6), target);
      host.onSelect(payload);
      syncSidebarSelection();
    }));
    syncSidebarSelection();
  }

  function mountSidebar(el) {
    sidebarEl = el;
    el.innerHTML = `
      <div class="blk">
        <div class="blk-head"><span class="t">圈图 · Ring</span><span class="n" data-role="ring-count"></span></div>
        <div data-role="ring" style="max-height:210px; overflow-y:auto;"></div>
        <div class="ring-actions">
          <button type="button" data-role="promote" disabled>成环</button>
          <button type="button" data-role="restore" disabled>恢复</button>
        </div>
        <div class="ring-hint" data-role="ring-hint"></div>
      </div>
      <div class="blk grow">
        <div class="blk-head"><span class="t">位点 · Sites</span><span class="n" data-role="site-count"></span></div>
        <div class="sb-search"><input data-role="search" type="search" placeholder="基因 / locus / 产物 / 类别" spellcheck="false"></div>
        <div id="gene-list" data-role="sites"></div>
      </div>
      <div class="blk">
        <div class="blk-head"><span class="t">功能分类 · COG</span><span class="n" data-role="cat-count"></span></div>
        <div class="cat-actions">
          <button type="button" data-role="cat-all">全选</button>
          <button type="button" data-role="cat-none">全不选</button>
          <button type="button" data-role="cat-reset">重置</button>
        </div>
        <div data-role="categories" class="cat-list"></div>
      </div>
      <div id="legend" class="blk">
        <div class="lg-head"><span class="t">轨道 · Tracks</span><span class="n">draft ring</span></div>
        <div class="lg-tracks">
          <div><i class="sw-plus"></i>+ 链 CDS（外环）</div>
          <div><i class="sw-minus"></i>− 链 CDS（内环）</div>
          <div><i class="sw-gc"></i>GC 含量 · 1 kb 滑窗</div>
          <div><i class="sw-skew"></i>GC skew (G−C)/(G+C)</div>
        </div>
      </div>`;
    el.querySelector('[data-role="search"]').addEventListener('input', renderSiteList);
    el.querySelector('[data-role="promote"]').addEventListener('click', promoteSelected);
    el.querySelector('[data-role="restore"]').addEventListener('click', restoreRings);
    el.querySelector('[data-role="cat-all"]').addEventListener('click', () => {
      categorySelection = null; applyCategoryVisibility(); syncCategoryChecks();
    });
    el.querySelector('[data-role="cat-none"]').addEventListener('click', () => {
      categorySelection = new Set(); applyCategoryVisibility(); syncCategoryChecks();
    });
    el.querySelector('[data-role="cat-reset"]').addEventListener('click', () => {
      categorySelection = null; applyCategoryVisibility(); syncCategoryChecks();
    });
    renderRingList();
    renderSiteList();
    renderCategoryList();
    syncRingActions();
    const ringCount = el.querySelector('[data-role="ring-count"]');
    if (ringCount) ringCount.textContent = promoted.size
      ? `${promoted.size} 成环 · ${ringContigs.length} contigs`
      : `${ringContigs.length} contigs`;
  }

  function categoryKeys() {
    return [...new Set(data.features.map(feature => feature.flag || feature.category))]
      .filter(Boolean)
      .sort();
  }

  function categoryColor(key) {
    if (key === 'amr') return KIND_COLORS.amr;
    if (key === 'vir') return KIND_COLORS.vir;
    return COG_COLORS[key] || KIND_COLORS[key] || KIND_COLORS.unknown;
  }

  function applyCategoryVisibility() {
    for (const child of layoutGroup.children) {
      if (child.isInstancedMesh) {
        child.visible = !categorySelection || categorySelection.has(child.userData.category);
      }
    }
    renderSiteList();
  }

  function syncCategoryChecks() {
    if (!sidebarEl) return;
    sidebarEl.querySelectorAll('input[data-cat]').forEach(input => {
      input.checked = !categorySelection || categorySelection.has(input.dataset.cat);
    });
  }

  function renderCategoryList() {
    if (!sidebarEl) return;
    const box = sidebarEl.querySelector('[data-role="categories"]');
    if (!box) return;
    const counts = new Map();
    for (const feature of data.features) {
      const key = feature.flag || feature.category;
      if (key) counts.set(key, (counts.get(key) || 0) + 1);
    }
    const keys = categoryKeys();
    box.innerHTML = keys.map(key => `
      <label class="cat-row">
        <input type="checkbox" data-cat="${escapeHtml(key)}"${!categorySelection || categorySelection.has(key) ? ' checked' : ''}>
        <i style="background:${categoryColor(key)}"></i>
        <span>${escapeHtml(key)} · ${escapeHtml(CATEGORY_LABELS[key] || key)}</span>
        <b>${counts.get(key) || 0}</b>
      </label>`).join('');
    box.querySelectorAll('input[data-cat]').forEach(input => input.addEventListener('change', () => {
      const checked = [...box.querySelectorAll('input[data-cat]:checked')].map(item => item.dataset.cat);
      categorySelection = checked.length === keys.length ? null : new Set(checked);
      applyCategoryVisibility();
      syncCategoryChecks();
    }));
    const count = sidebarEl.querySelector('[data-role="cat-count"]');
    if (count) count.textContent = `${keys.length} 类`;
  }

  function promotedSlots(count) {
    if (count === 1) return [{ x: 0, y: 0, scale: 1 }];
    if (count === 2) return [{ x: -9.5, y: 0, scale: 0.5 }, { x: 9.5, y: 0, scale: 0.5 }];
    if (count === 3) return [{ x: 0, y: 8.4, scale: 0.4 }, { x: -10.6, y: -6.6, scale: 0.4 }, { x: 10.6, y: -6.6, scale: 0.4 }];
    const cols = Math.ceil(Math.sqrt(count));
    const rows = Math.ceil(count / cols);
    const dx = cols > 1 ? 19 / (cols - 1) : 0;
    const dy = rows > 1 ? 15 / (rows - 1) : 0;
    return Array.from({ length: count }, (_, i) => ({
      x: cols > 1 ? -9.5 + (i % cols) * dx : 0,
      y: rows > 1 ? 7.5 - Math.floor(i / cols) * dy : 0,
      scale: 0.34,
    }));
  }

  /** Draw one ring: a shared draft ring of contigs, or one promoted closed ring. */
  function drawRing(contigs, cx, cy, scale, { closed = false, summary = false, title = '' } = {}) {
    const sr = value => value * scale;
    const labels = new THREE.Group(), gcGroup = new THREE.Group();
    labels.userData.role = 'labels';
    gcGroup.userData.role = 'gc';
    if (!showLabels) labels.visible = false;
    if (!showGc) gcGroup.visible = false;
    layoutGroup.add(labels, gcGroup);
    layoutGroup.add(
      ring(sr(3.95), .01, '#3d4d75', .35, cx, cy),
      ring(sr(6.55), .01, '#3d4d75', .35, cx, cy),
      ring(sr(7.15), -.01, '#2c3854', .25, cx, cy),
    );

    const totalBp = contigs.reduce((sum, contig) => sum + contig.length, 0);
    const gap = closed ? 0 : Math.min(0.018, (Math.PI * 2 / contigs.length) * 0.20);
    const usable = Math.PI * 2 - gap * contigs.length;
    let cursor = Math.PI / 2;
    const arcOf = new Map();
    for (const contig of contigs) {
      const arcLength = closed ? Math.PI * 2 : contig.length / totalBp * usable;
      const a0 = cursor, a1 = cursor + arcLength;
      arcOf.set(contig.id, { a0, arcLength, contig });
      cursor = a1 + gap;
      layoutGroup.add(sectorMesh(sr(6.70), sr(7.30), a0, a1, 0, '#3a4d78', cx, cy));
      if (!closed) {
        for (const boundary of [a0, a1]) {
          layoutGroup.add(sectorMesh(sr(6.58), sr(7.42), boundary - 0.004, boundary + 0.004, 0.01, '#7e8bb0', cx, cy));
        }
      }
      const mid = (a0 + a1) / 2;
      if (closed) {
        // promoted rings mirror the closed-replicon rendering: bp ticks + coordinate labels
        const step = niceStep(contig.length, contig.length > 1e6 ? 8 : 5);
        for (let position = 0; position < contig.length; position += step) {
          const angle = position / contig.length * Math.PI * 2;
          layoutGroup.add(sectorMesh(sr(6.58), sr(6.74), angle, angle + 0.0015, 0.01, '#9aabd8', cx, cy));
          const label = makeLabel(formatCoordinate(position), { color: '#a8b5d6', height: Math.max(0.14, .26 * scale), fontSize: 22, align: 'center' });
          label.position.set(cx + Math.cos(angle) * sr(7.45), cy - Math.sin(angle) * sr(7.45), .04);
          labels.add(label);
        }
        const ringTitle = makeLabel(`${contig.name || contig.id} · CIRCULAR（用户成环）`, {
          color: '#c3cdf0', height: Math.max(0.2, .34 * scale), fontSize: 24, align: 'center',
        });
        ringTitle.position.set(cx, cy + sr(1.1), .03);
        labels.add(ringTitle);
      } else if (arcLength > 0.05) {
        const label = makeLabel(`${contig.name || contig.id} · ${formatBp(contig.length)}`, {
          color: '#a8b5d6', height: 0.24, fontSize: 21, align: 'center',
        });
        label.position.set(cx + Math.cos(mid) * sr(7.75), cy - Math.sin(mid) * sr(7.75), 0.04);
        labels.add(label);
      }

      if (contig.track?.pos?.length > 1) {
        // GC 含量带（高于均值蓝、低于均值琥珀）与 GC skew 青绿色折线，与 demo 一致。
        const track = contig.track;
        const mean = track.gc.reduce((a, b) => a + b, 0) / track.gc.length;
        const gcBase = sr(3.18), gcAmp = sr(0.22);
        const skewBase = sr(2.52), skewAmp = sr(0.20);
        const positions = [], colors = [];
        const angleAt = index => a0 + track.pos[index] / contig.length * arcLength;
        const point = (index, radius) => {
          const angle = angleAt(index);
          return [cx + Math.cos(angle) * radius, cy - Math.sin(angle) * radius, 0.02];
        };
        const pushTriangle = (a, b, c, rgb) => {
          for (const vertex of [a, b, c]) {
            positions.push(...vertex);
            colors.push(...rgb);
          }
        };
        for (let i = 0; i + 1 < track.pos.length; i++) {
          const dev0 = clamp((track.gc[i] - mean) / 6, -1, 1);
          const dev1 = clamp((track.gc[i + 1] - mean) / 6, -1, 1);
          const r0i = gcBase, r0o = gcBase + dev0 * gcAmp;
          const r1i = gcBase, r1o = gcBase + dev1 * gcAmp;
          const color = (dev0 + dev1) / 2 > 0
            ? new THREE.Color('#3D7AEB')
            : new THREE.Color('#EA8C38');
          const rgb = [color.r, color.g, color.b];
          pushTriangle(point(i, r0i), point(i, r0o), point(i + 1, r1i), rgb);
          pushTriangle(point(i + 1, r1i), point(i, r0o), point(i + 1, r1o), rgb);
        }
        if (positions.length) {
          const geometry = new THREE.BufferGeometry();
          geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
          geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
          gcGroup.add(new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({
            vertexColors: true, side: THREE.DoubleSide, transparent: true,
            opacity: 0.72, depthWrite: false,
          })));
        }
        const skewPositions = track.pos.map((position, i) => {
          const angle = angleAt(i);
          const radius = skewBase + clamp(track.skew[i] * 6, -1, 1) * skewAmp;
          return new THREE.Vector3(cx + Math.cos(angle) * radius, cy - Math.sin(angle) * radius, 0.02);
        });
        gcGroup.add(new THREE.Line(
          new THREE.BufferGeometry().setFromPoints(skewPositions),
          new THREE.LineBasicMaterial({ color: '#35C9A4', transparent: true, opacity: 0.85 }),
        ));
      }
    }

    if (summary) {
      const head = makeLabel(`DRAFT CIRCULAR LAYOUT · ≥ ${thresholdKb} kb`, {
        color: '#f0b07a', height: 0.42, fontSize: 26, align: 'center',
      });
      head.position.set(cx, cy + 0.55, 0.05);
      labels.add(head);
      const summaryLabel = makeLabel(`${contigs.length} contigs · ${formatBp(totalBp)} · sorted by length`, {
        color: '#c3cdf0', height: 0.3, fontSize: 22, align: 'center',
      });
      summaryLabel.position.set(cx, cy + 0.05, 0.05);
      labels.add(summaryLabel);
      const notice = makeLabel('draft 布局 · 未声明闭合', { color: '#68779b', height: 0.26, fontSize: 20, align: 'center' });
      notice.position.set(cx, cy - 0.4, 0.05);
      labels.add(notice);
    }
    if (title) {
      const titleLabel = makeLabel(title, { color: '#f0b07a', height: 0.3, fontSize: 20, align: 'center' });
      titleLabel.position.set(cx, cy + sr(1.6), 0.05);
      labels.add(titleLabel);
    }

    const grouped = new Map();
    for (const feature of data.features) {
      const arc = arcOf.get(feature.contig);
      if (!arc) continue;
      const key = feature.flag || feature.category;
      if (!grouped.has(key)) grouped.set(key, []);
      grouped.get(key).push({ feature, arc });
    }
    const matrix = new THREE.Matrix4(), position = new THREE.Vector3();
    const tangent = new THREE.Vector3(), radial = new THREE.Vector3(), normal = new THREE.Vector3(0, 0, 1);
    for (const [category, entries] of grouped) {
      const mesh = new THREE.InstancedMesh(
        new THREE.BoxGeometry(1, 1, 1),
        new THREE.MeshStandardMaterial({ color: featureColor({ category, flag: null }), roughness: .31, metalness: .30 }),
        entries.length,
      );
      entries.forEach(({ feature, arc }, instanceId) => {
        const { a0, arcLength, contig } = arc;
        const start = a0 + feature.start / contig.length * arcLength;
        const end = a0 + feature.end / contig.length * arcLength;
        const mid = (start + end) / 2;
        const plus = feature.strand !== '-';
        const rMid = sr((plus ? radius.plusIn + radius.plusOut : radius.minusIn + radius.minusOut) / 2);
        const width = Math.max(sr(0.004), rMid * (end - start));
        const cos = Math.cos(mid), sin = Math.sin(mid);
        position.set(cx + cos * rMid, cy - sin * rMid, .18);
        tangent.set(-sin, -cos, 0);
        radial.set(cos, -sin, 0);
        matrix.makeBasis(tangent, radial, normal);
        matrix.scale(new THREE.Vector3(width, Math.max(0.12, sr(0.52)), sr(0.32)));
        matrix.setPosition(position);
        mesh.setMatrixAt(instanceId, matrix);
        mesh.setColorAt(instanceId, new THREE.Color(featureColor(feature)));
        featureById.set(feature.id, { ...feature, record: { feature, mesh, instanceId, color: new THREE.Color(featureColor(feature)) } });
      });
      mesh.instanceMatrix.needsUpdate = true;
      if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
      mesh.userData.category = category;
      mesh.visible = !categorySelection || categorySelection.has(category);
      layoutGroup.add(addPickable(mesh, { type: 'feature', id: entries[0].feature.id }));
      mesh.userData.pickFor = instanceId => {
        const feature = entries[instanceId]?.feature;
        return feature ? { type: 'feature', id: feature.id } : null;
      };
      ringFeatures += entries.length;
    }
    return arcOf;
  }

  function render() {
    const threshold = thresholdKb * 1000;
    ringContigs = sorted.filter(contig => contig.length >= threshold);
    if (!ringContigs.length) ringContigs = [sorted[0]];
    ringFeatures = 0;
    const promotedContigs = ringContigs.filter(contig => promoted.has(contig.id));
    const draftContigs = ringContigs.filter(contig => !promoted.has(contig.id));

    if (!promotedContigs.length) {
      drawRing(draftContigs, 0, 0, 1, { summary: true });
    } else {
      const slots = promotedSlots(promotedContigs.length);
      promotedContigs.forEach((contig, index) => {
        const slot = slots[index];
        drawRing([contig], slot.x, slot.y, slot.scale, { closed: true });
      });
      if (draftContigs.length) {
        const lowest = slots.reduce((min, slot) => Math.min(min, slot.y), 0);
        drawRing(draftContigs, 0, lowest - 10.5, 0.28, { title: `DRAFT · ${draftContigs.length} contigs（未成环）` });
      }
    }
    if (sidebarEl) {
      renderRingList();
      renderSiteList();
      renderCategoryList();
      const ringCount = sidebarEl.querySelector('[data-role="ring-count"]');
      if (ringCount) ringCount.textContent = promoted.size
        ? `${promoted.size} 成环 · ${ringContigs.length} contigs`
        : `${ringContigs.length} contigs`;
      syncRingActions();
    }
  }
  render();

  const matrix = new THREE.Matrix4();
  function payloadPosition(payload) {
    const record = featureById.get(payload?.id)?.record;
    if (!record) return null;
    const vector = new THREE.Vector3();
    record.mesh.getMatrixAt(record.instanceId, matrix);
    return vector.setFromMatrixPosition(matrix);
  }

  return {
    debug: () => ({
      draft: true,
      thresholdKb,
      contigs: ringContigs.length,
      promoted: [...promoted],
      records: ringFeatures,
    }),
    stats: () => [
      { label: '组装总长度', value: formatBp(ringContigs.reduce((sum, contig) => sum + contig.length, 0)) },
      { label: '圈图 contigs', value: `${ringContigs.length} / ${sorted.length}` },
      ...(promoted.size ? [{ label: '成环 replicons', value: promoted.size }] : []),
      { label: '注释特征', value: ringFeatures },
      { label: '功能类别', value: new Set(data.features.filter(feature => ringContigs.some(contig => contig.id === feature.contig)).map(feature => feature.flag || feature.category)).size },
      ...(Number.isFinite(data.eggnog_matched) && Number.isFinite(data.eggnog_total)
        ? [{ label: 'eggNOG 匹配', value: `${data.eggnog_matched}/${data.eggnog_total}` }] : []),
    ],
    mountSidebar,
    resetCamera: () => host.setCamera(
      promoted.size ? new THREE.Vector3(0, 6.5, 34) : new THREE.Vector3(5.5, 4.8, 22.5),
      new THREE.Vector3(0, promoted.size ? -1.5 : 0, 0),
    ),
    setOption: (key, value) => {
      if (key === 'thresholdKb') {
        thresholdKb = value;
        clearLayout();
        render();
        return;
      }
      if (key === 'category') {
        categorySelection = value === 'all' ? null : new Set([value]);
        applyCategoryVisibility();
        syncCategoryChecks();
        return;
      }
      if (key === 'gc' || key === 'labels') {
        if (key === 'gc') showGc = value;
        else showLabels = value;
        for (const child of layoutGroup.children) {
          if (child.userData.role === key) child.visible = value;
        }
      }
    },
    select: selectPayload,
    focus: payload => {
      const target = payloadPosition(payload);
      if (target) host.flyTo(target.clone().multiplyScalar(1.28).setZ(6), target);
    },
    selectionLabel: payload => {
      const feature = featureById.get(payload?.id);
      return feature?.gene || feature?.locus || feature?.id || '—';
    },
    tooltip: payload => {
      const feature = featureById.get(payload?.id);
      if (!feature) return '';
      const tag = feature.flag ? CATEGORY_LABELS[feature.flag] : CATEGORY_LABELS[feature.category] || feature.category;
      return `<div class="tt-name">${escapeHtml(feature.gene || feature.locus || feature.id)}</div>
        <div class="tt-sub">${escapeHtml(tag)} · ${escapeHtml(feature.contig)}</div>
        <div class="tt-sub">${formatBp(feature.end - feature.start)} · 双击聚焦</div>`;
    },
    inspect: payload => {
      const feature = featureById.get(payload?.id);
      return feature ? featureInspectHtml(feature, data) : '';
    },
  };
}

export const circularAnnotationView = {
  id: 'circle',
  schema: 'gvixb.annotated-genome/v1',
  title: '3D 注释圈图',
  subtitle: 'BAKTA + EGGNOG CIRCULAR MAP',
  description: '由 Bakta GFF3 提供基因坐标，eggNOG-mapper 提供 COG/EC/KEGG/PFAM 功能注释；CARD/VFDB 命中按坐标叠加。声明为 circular 的复制子按闭合圈渲染，线性 contig 仅在显式开启时使用伪环布局。',
  controls: data => {
    const hasCircular = data.replicons.some(replicon => replicon.topology === 'circular');
    const draftOnly = !hasCircular && data.replicons.length > 0;
    // 分类筛选由左侧「功能分类 · COG」复选面板承担，避免重复的「功能过滤」下拉。
    const controls = [];
    if (draftOnly) {
      const sortedLengths = data.replicons.map(replicon => replicon.length).sort((a, b) => b - a);
      controls.push({
        key: 'thresholdKb', label: '圈图 contig 阈值', type: 'range',
        min: 0, max: Math.max(10, Math.ceil(sortedLengths[0] / 1000)), step: 1, value: 10, unit: ' kb',
      });
    } else {
      controls.push({ key: 'linear', label: '显示线性 contig（伪环布局）', type: 'toggle', value: !hasCircular });
    }
    controls.push(
      { key: 'gc', label: '显示 GC / GC-skew', type: 'toggle', value: true },
      { key: 'labels', label: '显示 contig 与坐标标签', type: 'toggle', value: true },
    );
    return controls;
  },

  create({ root, data, host, registerPickable }) {
    const circular = data.replicons.filter(replicon => replicon.topology === 'circular');
    const linear = data.replicons.filter(replicon => replicon.topology === 'linear');
    if (circular.length === 0 && linear.length > 0) {
      return createDraftView({ root, data, host, registerPickable, contigs: linear });
    }
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
      group.add(ring(sr(3.95), .01, '#3d4d75', .35, cx, cy), ring(sr(6.55), .01, '#3d4d75', .35, cx, cy), ring(sr(7.15), -.01, '#2c3854', .25, cx, cy));
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
        mesh.userData.pickFor = instanceId => {
          const feature = features[instanceId];
          return feature ? { type: 'feature', id: feature.id } : null;
        };
      }
    });

    function applyCategory(value) {
      for (const [category, mesh] of categoryMeshes) mesh.visible = value === 'all' || category === value;
    }
    applyCategory('all');

    let selected = null;
    let sidebarEl = null;
    const truncText = (text, n) => {
      const value = String(text ?? '');
      return value.length > n ? `${value.slice(0, n - 1)}…` : value;
    };
    function syncSidebarSelection() {
      if (!sidebarEl) return;
      const id = selected?.feature?.id || '';
      sidebarEl.querySelectorAll('.gene-row').forEach(btn =>
        btn.classList.toggle('on', btn.dataset.id === id));
    }
    function clearSelection() {
      if (!selected) return;
      selected.mesh.setColorAt(selected.instanceId, selected.color);
      selected.mesh.instanceColor.needsUpdate = true;
      if (selected.baseMatrix) {
        selected.mesh.setMatrixAt(selected.instanceId, selected.baseMatrix);
        selected.mesh.instanceMatrix.needsUpdate = true;
        selected.baseMatrix = null;
      }
      selected = null;
      syncSidebarSelection();
    }
    function select(payload) {
      clearSelection();
      if (!payload) return;
      const record = featureById.get(payload.id)?.record;
      if (!record) return;
      selected = record;
      record.mesh.setColorAt(record.instanceId, new THREE.Color('#ffffff'));
      record.mesh.instanceColor.needsUpdate = true;
      const matrix = new THREE.Matrix4();
      record.mesh.getMatrixAt(record.instanceId, matrix);
      record.baseMatrix = matrix.clone();
      const position = new THREE.Vector3().setFromMatrixPosition(matrix);
      const radial = position.clone().setZ(0).normalize();
      matrix.setPosition(
        position.clone().add(radial.multiplyScalar(0.45)).add(new THREE.Vector3(0, 0, 0.45)),
      );
      matrix.scale(new THREE.Vector3(1.28, 1.28, 1.28));
      record.mesh.setMatrixAt(record.instanceId, matrix);
      record.mesh.instanceMatrix.needsUpdate = true;
      syncSidebarSelection();
    }
    function renderSiteList() {
      if (!sidebarEl) return;
      const box = sidebarEl.querySelector('[data-role="sites"]');
      const countEl = sidebarEl.querySelector('[data-role="site-count"]');
      if (!box || !countEl) return;
      const q = (sidebarEl.querySelector('[data-role="search"]')?.value || '').trim().toLowerCase();
      let pool = data.features.slice();
      const total = pool.length;
      if (q) {
        pool = pool.filter(feature =>
          [feature.gene, feature.locus, feature.product, feature.contig,
            CATEGORY_LABELS[feature.flag || feature.category]]
            .some(value => String(value ?? '').toLowerCase().includes(q)));
      }
      countEl.textContent = q ? `${pool.length}/${total}` : `${total}`;
      const MAX_ROWS = 220;
      const rows = pool.slice(0, MAX_ROWS);
      box.innerHTML = rows.map((feature, index) => {
        const color = featureColor(feature);
        const tag = CATEGORY_LABELS[feature.flag || feature.category] || feature.category || '—';
        return `<button class="gene-row" data-id="${escapeHtml(feature.id)}">
          <span class="idx">${String(index + 1).padStart(2, '0')}</span>
          <span class="gr-main">
            <b><span style="color:${color}">|</span> ${escapeHtml(feature.gene || feature.locus || feature.id)}</b>
            <em>${escapeHtml(truncText(feature.product || tag, 46))}</em>
          </span>
          <span class="tag" style="color:${color}">${escapeHtml(tag)}</span>
        </button>`;
      }).join('') + (pool.length > MAX_ROWS
        ? `<div class="gene-note">仅显示前 ${MAX_ROWS} 条（共 ${pool.length}）· 可用搜索缩小</div>`
        : (rows.length ? '' : '<div class="gene-note">没有匹配的基因</div>'));
      box.querySelectorAll('.gene-row').forEach(btn => btn.addEventListener('click', () => {
        const payload = { type: 'feature', id: btn.dataset.id };
        select(payload);
        const target = payloadPosition(payload);
        if (target) host.flyTo(target.clone().add(new THREE.Vector3(0, 1, 6)), target);
        host.onSelect(payload);
        syncSidebarSelection();
      }));
    }
    function mountSidebar(el) {
      sidebarEl = el;
      el.innerHTML = `
        <div class="blk">
          <div class="blk-head"><span class="t">复制子 · Replicons</span><span class="n">${ordered.length}</span></div>
          <div style="max-height:210px; overflow-y:auto;">${ordered.map((replicon, index) => `
            <div class="rep-row"><div class="rname"><span>${escapeHtml(truncText(replicon.id, 22))}</span><span class="rlen">${formatBp(replicon.length)}</span></div>
            <div class="rmeta"><span>#${index + 1}</span><span>${escapeHtml(replicon.topology)}</span></div></div>`).join('')}</div>
        </div>
        <div class="blk grow">
          <div class="blk-head"><span class="t">位点 · Sites</span><span class="n" data-role="site-count"></span></div>
          <div class="sb-search"><input data-role="search" type="search" placeholder="基因 / locus / 产物 / 类别" spellcheck="false"></div>
          <div id="gene-list" data-role="sites"></div>
        </div>`;
      el.querySelector('[data-role="search"]').addEventListener('input', renderSiteList);
      renderSiteList();
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
        { label: 'eggNOG 匹配', value: Number.isFinite(data.eggnog_matched) && Number.isFinite(data.eggnog_total) ? `${data.eggnog_matched}/${data.eggnog_total}` : '—' },
      ],
      mountSidebar,
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
        return feature ? featureInspectHtml(feature, data) : '';
      },
    };
  },
};
