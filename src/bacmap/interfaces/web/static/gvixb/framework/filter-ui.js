/**
 * Shared 筛选 · Filter sidebar block — the metadata/matrix condition editor
 * used by phylo and MST. Owns ONLY the DOM + interaction state (draft
 * condition, in-place search, IME-safe input handling); the view owns
 * evaluation, emphasis, pulse and persistence through the adapter.
 *
 * Rendering contract:
 *   render()        — full structure; call on structural changes only
 *                     (mode, add/remove/edit condition, open/close editor,
 *                     source pick, op change)
 *   updateResult()  — rewrites only the result container; safe to call on
 *                     every emphasis change (never touches editor inputs)
 * Search inputs are filtered in place by toggling `hidden` on rows, so the
 * caret and IME composition survive — do not re-render them on input.
 */
import { describeCondition, conditionOptions } from './query.js';
import { escapeHtml } from './primitives.js';

/**
 * adapter = {
 *   state: { mode, conditions, dim, pulse },   // view-owned, mutated here
 *   available: boolean,                        // hide block entirely when false
 *   fieldTypes: Map<key, type>,
 *   matrices: [{ id, label, columns: [{id}], rows }],
 *   fieldLabel(key) => string,
 *   matrixLabel(id) => string,
 *   valueCounts(fieldKey) => Map<value, count>,
 *   apply(),          // conditions/mode/pulse changed → view re-evaluates
 *   onDim(dim),       // live slider update
 *   context() => { matched: Set|null, k, n, extras: string[],
 *                  distCounts: [[value, count]], matchRows: [{ key, label }],
 *                  warnings: string[] },
 *   selectRow(key),   // match-list row click
 *   focus(),          // 聚焦匹配
 *   notify(),         // host.notifyStateChange
 * }
 */
export function createFilterUi({ el, adapter }) {
  const state = adapter.state;
  let draft = null;      // condition being built/edited
  let search = '';       // source-picker search text
  let compBound = false;

  function sources(q) {
    const rows = [];
    for (const [key, type] of adapter.fieldTypes) {
      if (type === 'date') continue;
      const label = adapter.fieldLabel(key);
      if (q && !`${key} ${label}`.toLowerCase().includes(q)) continue;
      rows.push({ kind: 'field', key, type, label, group: '元数据字段' });
    }
    for (const m of adapter.matrices || []) {
      for (const c of m.columns) {
        if (q && !c.id.toLowerCase().includes(q)) continue;
        rows.push({ kind: 'matrix', matrix: m.id, column: c.id, type: 'matrix', label: `${adapter.matrixLabel(m.id)}:${c.id}`, group: adapter.matrixLabel(m.id) });
      }
    }
    return rows;
  }

  // Live-filter rows of the currently open editor in place — never rebuilds
  // DOM, so the focused input keeps its caret and IME composition survives.
  function filterRows(blk, rowAttr, groupAttr, q) {
    const textKey = rowAttr.replace('-row', '-text').replace(/-([a-z])/g, (_, c) => c.toUpperCase());
    const rows = blk.querySelectorAll(`[data-${rowAttr}]`);
    for (const row of rows) row.hidden = !!q && !(row.dataset[textKey] || '').includes(q);
    for (const g of blk.querySelectorAll(`[data-${groupAttr}]`)) {
      g.hidden = ![...g.querySelectorAll(`[data-${rowAttr}]`)].some(r => !r.hidden);
    }
  }

  // Rewrites only the result container (counts / actions / match list) —
  // called on every emphasis change, so it must not touch the editor or
  // its inputs.
  function updateResult() {
    const res = el?.querySelector('[data-role="flt-result"]');
    if (!res) return;
    const { matched, k, n, extras = [], distCounts = [], matchRows = [], warnings = [] } = adapter.context();
    const head = el.querySelector('.blk-head .n');
    if (head) head.textContent = matched ? k : '—';
    res.innerHTML = `${matched ? `<p class="gene-note">匹配 ${k} / ${n} 株${extras.length ? ' · ' : ''}${extras.map(escapeHtml).join(' · ')}</p>
      ${distCounts.length ? `<p class="gene-note">${distCounts.map(([v, c]) => `${escapeHtml(v)} ×${c}`).join(' · ')}</p>` : ''}
      <div class="ring-actions"><button type="button" data-flt-focus>聚焦匹配</button><button type="button" data-flt-clear>清除</button></div>
      <label class="view-toggle">闪烁<input type="checkbox" data-flt-pulse ${state.pulse ? 'checked' : ''}><i></i></label>
      ${k ? `<details class="ctl-group"><summary class="ctl-sec">匹配列表</summary>
        <div class="ring-col-list">${matchRows.slice(0, 200)
          .map(r => `<div class="cat-row" data-flt-row="${escapeHtml(r.key)}"><span class="ring-col-name" role="button">${escapeHtml(r.label)}</span></div>`).join('')}
        </div>${k > 200 ? `<p class="gene-note">仅显示前 200 个（共 ${k}）</p>` : ''}</details>` : ''}` : ''}
    ${warnings.map(w => `<p class="gene-note">⚠ ${escapeHtml(w)}</p>`).join('')}`;
  }

  function render() {
    if (!el) return;
    const blk = el;
    if (!adapter.available) { blk.innerHTML = ''; return; }
    blk.innerHTML = `<div class="blk-head"><span class="t">筛选 · Filter</span><span class="n">${adapter.context().matched ? adapter.context().k : '—'}</span></div>
      <div class="ring-actions">
        <button type="button" class="${state.mode === 'all' ? 'on' : ''}" data-flt-mode="all">全部满足</button>
        <button type="button" class="${state.mode === 'any' ? 'on' : ''}" data-flt-mode="any">任一满足</button>
      </div>
      ${state.conditions.map((c, i) => `<div class="cat-row flt-chip">
        <button type="button" class="ring-col-name" data-flt-edit="${i}">${escapeHtml(describeCondition(c, { fieldLabel: adapter.fieldLabel, matrixLabel: adapter.matrixLabel }))}</button>
        <button type="button" class="ring-field-x" data-flt-rm="${i}" title="删除条件">×</button>
      </div>`).join('')}
      <div data-role="flt-editor">${draft === null
        ? '<div class="ring-actions"><button type="button" data-flt-add>添加条件</button></div>'
        : renderEditor()}</div>
      <label class="view-range"><span>未匹配节点透明度<b>${Math.round(state.dim * 100)}%</b></span><input type="range" min="0.1" max="1" step="0.05" value="${state.dim}" data-flt-dim></label>
      <div data-role="flt-result"></div>
      <p class="gene-note">按字段值或矩阵检测筛选叶节点；匹配项规律缩放，其余按上方滑块淡出。仅描述展示，不作推断。时间请用时间刷选。</p>`;
    updateResult();
    // re-apply any live searches after a structural re-render
    if (search) filterRows(blk, 'cand-row', 'cand-group', search);
    if (draft?.valSearch) filterRows(blk, 'val-row', 'val-group', draft.valSearch);
    const applySearch = t => {
      if (t.dataset.fltSearch !== undefined) { search = t.value.trim().toLowerCase(); filterRows(blk, 'cand-row', 'cand-group', search); }
      else if (t.dataset.fltValSearch !== undefined && draft) { draft.valSearch = t.value.trim().toLowerCase(); filterRows(blk, 'val-row', 'val-group', draft.valSearch); }
    };
    blk.oninput = ev => {
      if (ev.isComposing) return;
      const t = ev.target;
      if (t.dataset.fltSearch !== undefined || t.dataset.fltValSearch !== undefined) { applySearch(t); return; }
      if (t.dataset.fltMin !== undefined && draft) draft.min = t.value;
      else if (t.dataset.fltMax !== undefined && draft) draft.max = t.value;
      else if (t.dataset.fltText !== undefined && draft) draft.text = t.value;
      else if (t.dataset.fltDim !== undefined) {
        state.dim = Math.max(0.1, Math.min(1, Number(t.value)));
        t.closest('.view-range').querySelector('b').textContent = `${Math.round(state.dim * 100)}%`;
        adapter.onDim(state.dim);
        adapter.notify();
      }
    };
    // IME composition: input events during composition are ignored above;
    // apply the composed text once it commits (bound once — blk persists).
    if (!compBound) {
      compBound = true;
      blk.addEventListener('compositionend', ev => {
        const t = ev.target;
        if (t.dataset?.fltSearch !== undefined || t.dataset?.fltValSearch !== undefined) applySearch(t);
      });
    }
    blk.onchange = ev => {
      const t = ev.target;
      if (t.dataset.fltOp && draft) { draft.op = t.value; draft.values = []; render(); }
      else if (t.dataset.fltVal && draft) {
        const v = t.dataset.fltVal;
        if (t.checked) (draft.values ||= []).push(v);
        else draft.values = (draft.values || []).filter(x => x !== v);
      }
      else if (t.hasAttribute('data-flt-pulse')) {
        state.pulse = t.checked;
        adapter.apply(); adapter.notify();
      }
    };
    blk.onclick = ev => {
      const t = ev.target;
      if (t.dataset.fltMode) { state.mode = t.dataset.fltMode; adapter.apply(); render(); adapter.notify(); }
      else if (t.dataset.fltRm) { state.conditions.splice(Number(t.dataset.fltRm), 1); adapter.apply(); render(); adapter.notify(); }
      else if (t.hasAttribute('data-flt-add')) { draft = { kind: null, op: null, values: [], valSearch: '' }; search = ''; render(); }
      else if (t.dataset.fltEdit !== undefined && !draft) {
        const c = state.conditions[Number(t.dataset.fltEdit)];
        if (c) draft = c.source === 'matrix'
          ? { kind: 'matrix', matrix: c.matrix, column: c.column, type: 'matrix', op: c.op, values: [], editIndex: Number(t.dataset.fltEdit) }
          : { kind: 'field', field: c.field, type: adapter.fieldTypes.get(c.field) || 'categorical', op: c.op,
              values: Array.isArray(c.values) ? [...c.values] : [], min: c.min, max: c.max, text: c.text,
              valSearch: '', editIndex: Number(t.dataset.fltEdit) };
        render();
      }
      else if (t.dataset.fltSrc && draft) {
        const [kind, a, b] = t.dataset.fltSrc.split('|');
        if (kind === 'field') { const type = adapter.fieldTypes.get(a) || 'categorical'; draft = { kind: 'field', field: a, type, op: conditionOptions(type)[0].op, values: [], valSearch: '' }; }
        else { draft = { kind: 'matrix', matrix: a, column: b, type: 'matrix', op: 'pos', values: [] }; }
        render();
      }
      else if (t.hasAttribute('data-flt-ok') && draft) {
        const cond = draft.kind === 'matrix'
          ? { source: 'matrix', matrix: draft.matrix, column: draft.column, op: draft.op }
          : { source: 'field', field: draft.field, op: draft.op,
              values: draft.values, min: draft.min === '' || draft.min === undefined ? undefined : Number(draft.min),
              max: draft.max === '' || draft.max === undefined ? undefined : Number(draft.max), text: draft.text };
        if (Number.isInteger(draft.editIndex)) state.conditions.splice(draft.editIndex, 1, cond);
        else state.conditions.push(cond);
        draft = null; adapter.apply(); render(); adapter.notify();
      }
      else if (t.hasAttribute('data-flt-cancel')) { draft = null; render(); }
      else if (t.hasAttribute('data-flt-focus')) { adapter.focus(); }
      else if (t.hasAttribute('data-flt-clear')) { state.conditions = []; draft = null; adapter.apply(); render(); adapter.notify(); }
      else {
        const row = t.closest('[data-flt-row]');
        if (row) adapter.selectRow(row.dataset.fltRow);
      }
    };
  }

  function renderEditor() {
    if (!draft.kind) {
      // step 1: pick a source — all rows rendered, the search box filters in
      // place (keeps IME composition and the caret alive)
      const rows = sources('');
      const groups = new Map();
      for (const r of rows) { if (!groups.has(r.group)) groups.set(r.group, []); groups.get(r.group).push(r); }
      return `<input class="mst-search" type="search" placeholder="搜索字段 / 基因…" data-flt-search value="${escapeHtml(search)}">
        <div class="ring-col-list">${[...groups.entries()].map(([g, items]) =>
          `<div data-cand-group><div class="ctl-sec">${escapeHtml(g)}</div>${items.map(r =>
            `<div class="cat-row" data-cand-row data-cand-text="${escapeHtml(`${r.kind === 'field' ? `${r.key} ${r.label}` : r.column}`.toLowerCase())}"><button type="button" class="ring-col-name" data-flt-src="${escapeHtml(`${r.kind}|${r.kind === 'field' ? r.key : `${r.matrix}|${r.column}`}`)}">${escapeHtml(r.label)}</button></div>`).join('')}</div>`).join('')}
        </div>
        <div class="ring-actions"><button type="button" data-flt-cancel>取消</button></div>`;
    }
    // step 2: op + values
    const ops = conditionOptions(draft.type);
    const title = draft.kind === 'matrix' ? `${draft.matrix}:${draft.column}` : adapter.fieldLabel(draft.field);
    let valueEditor = '';
    if (draft.op === 'in' || draft.op === 'not_in') {
      const counts = adapter.valueCounts(draft.field);
      const q = draft.valSearch || '';
      const vals = [...counts.entries()].slice(0, 300);
      valueEditor = `<input class="mst-search" type="search" placeholder="搜索值…" data-flt-val-search value="${escapeHtml(q)}">
        <div class="ring-col-list">${vals.map(([v, n]) => `<label class="cat-row" data-val-row data-val-text="${escapeHtml(v.toLowerCase())}"><input type="checkbox" data-flt-val="${escapeHtml(v)}" ${draft.values?.includes(v) ? 'checked' : ''}><span class="ring-col-name">${escapeHtml(v)}</span><b>${n}</b></label>`).join('')}</div>`;
    } else if (draft.op === 'gte') {
      valueEditor = `<input class="mst-search" type="number" placeholder="最小值 ≥" data-flt-min value="${escapeHtml(draft.min ?? '')}">`;
    } else if (draft.op === 'lte') {
      valueEditor = `<input class="mst-search" type="number" placeholder="最大值 ≤" data-flt-max value="${escapeHtml(draft.max ?? '')}">`;
    } else if (draft.op === 'between') {
      valueEditor = `<input class="mst-search" type="number" placeholder="下限" data-flt-min value="${escapeHtml(draft.min ?? '')}">
        <input class="mst-search" type="number" placeholder="上限" data-flt-max value="${escapeHtml(draft.max ?? '')}" style="margin-top:4px">`;
    } else if (draft.op === 'contains') {
      valueEditor = `<input class="mst-search" type="search" placeholder="包含文本…" data-flt-text value="${escapeHtml(draft.text || '')}">`;
    }
    return `<div class="ctl-sec">${escapeHtml(title)}</div>
      <label class="view-select"><span>条件</span><select data-flt-op>
        ${ops.map(o => `<option value="${escapeHtml(o.op)}" ${draft.op === o.op ? 'selected' : ''}>${escapeHtml(o.label)}</option>`).join('')}
      </select></label>
      ${valueEditor}
      <div class="ring-actions"><button type="button" data-flt-ok>添加</button><button type="button" data-flt-cancel>取消</button></div>`;
  }

  return { render, updateResult, state };
}
